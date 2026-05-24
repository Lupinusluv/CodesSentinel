"""Git 平台 Webhook 接收端点。

GitHub 事件流程：
  1. 验证 X-Hub-Signature-256（HMAC-SHA256）
  2. 只处理 pull_request 事件，action 为 opened / synchronize / reopened
  3. 写入 Review 记录（status=pending）
  4. 入队 ARQ 任务（run_review_task）
  5. 返回 202 Accepted（GitHub 要求 10 秒内响应）

其他平台（GitLab / Gitee）接口结构相同，适配器实现后可直接接入。
"""

import json

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import get_settings
from app.core.dependencies import DBSessionDep, get_arq_pool
from app.core.logging import get_logger
from app.models.repository import Platform, Repository
from app.models.review import Review, ReviewStatus
from app.platform.adapters.github import GitHubAdapter
from app.platform.base import GitPlatformAdapter
from sqlalchemy import select

log = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# pull_request 动作白名单
_PR_ACTIONS = {"opened", "synchronize", "reopened"}


async def _enqueue_review(
    db: DBSessionDep,
    repository: Repository,
    pr_number: int,
    pr_diff: str,
    language: str,
    head_sha: str,
) -> Review:
    """创建 Review 记录并入队 ARQ 任务，返回新建的 Review。"""
    review = Review(
        repository_id=repository.id,
        pr_number=pr_number,
        status=ReviewStatus.pending,
        language=language,
        source_code=pr_diff,
        head_sha=head_sha,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)

    arq = await get_arq_pool()
    # head_sha 存在 review 里，review_task 完成后可通过 DB 读取再回调 Status Check
    await arq.enqueue_job("run_review_task", str(review.id), pr_diff, language)
    log.info(
        "review_enqueued",
        review_id=str(review.id),
        repo=repository.url,
        pr=pr_number,
        sha=head_sha[:8],
    )
    return review


# ── GitHub ────────────────────────────────────────────────────────────────────

@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    db: DBSessionDep,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict[str, str]:
    payload_bytes = await request.body()

    # ── 1. 验签 ──────────────────────────────────────────────────────────────
    settings = get_settings()
    if settings.github_webhook_secret:
        if not x_hub_signature_256:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Hub-Signature-256 header",
            )
        if not GitPlatformAdapter.verify_signature_sha256(
            payload_bytes, x_hub_signature_256, settings.github_webhook_secret
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    # ── 2. 只处理 pull_request 事件 ──────────────────────────────────────────
    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"event={x_github_event}"}

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    action: str = payload.get("action", "")
    if action not in _PR_ACTIONS:
        return {"status": "ignored", "reason": f"action={action}"}

    # ── 3. 解析仓库信息 ───────────────────────────────────────────────────────
    pr      = payload["pull_request"]
    repo    = payload["repository"]
    repo_url = repo["html_url"]
    pr_number = int(pr["number"])
    head_sha  = pr["head"]["sha"]
    # GitHub 不暴露语言字段，从仓库的 language 属性读取，默认 python
    language  = (repo.get("language") or "python").lower()

    # ── 4. 查找已注册的仓库 ───────────────────────────────────────────────────
    result = await db.execute(
        select(Repository).where(Repository.url == repo_url)
    )
    repository = result.scalar_one_or_none()
    if repository is None:
        log.warning("webhook_repo_not_registered", url=repo_url)
        return {"status": "ignored", "reason": "repository not registered"}

    # ── 5. 立刻设置 pending Status Check ─────────────────────────────────────
    adapter = GitHubAdapter()
    owner, repo_name = GitHubAdapter.parse_repo_url(repo_url)
    try:
        await adapter.set_commit_status(
            owner, repo_name, head_sha,
            state="pending",
            description="CodeSentinel review in progress…",
        )
    except Exception:
        log.warning("github_status_pending_failed", sha=head_sha[:8])

    # ── 6. 拉取 diff 并入队 ───────────────────────────────────────────────────
    try:
        pr_diff = await adapter.get_pr_diff(owner, repo_name, pr_number)
    except Exception as exc:
        log.error("github_get_diff_failed", pr=pr_number, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Failed to fetch PR diff: {exc}")

    await _enqueue_review(db, repository, pr_number, pr_diff, language, head_sha)

    return {"status": "accepted", "pr": pr_number}


# ── GitLab / Gitee（接口占位，适配器实现后接入）──────────────────────────────

@router.post("/gitlab", status_code=status.HTTP_202_ACCEPTED)
async def gitlab_webhook() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="GitLab adapter not implemented yet",
    )


@router.post("/gitee", status_code=status.HTTP_202_ACCEPTED)
async def gitee_webhook() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Gitee adapter not implemented yet",
    )
