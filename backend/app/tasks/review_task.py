"""审查后台任务（ARQ）。

流式协议：
  {"type": "agent_start",      "agent": "security"|"performance"|"style"|"synthesis"}
  {"type": "agent_done",       "agent": "...", "issue_count": N}
  {"type": "synthesis_token",  "content": "..."}   ← synthesis LLM 逐 token
  {"type": "done",             "issue_count": N, "duration_ms": N, "parse_failures": [...]}
  {"type": "error",            "message": "..."}
"""

import json
import time
import uuid

from app.agents.graph import compiled_graph
from app.agents.state import IssueOutput, ReviewState
from app.agents.synthesis_agent import deduplicate_issues
from app.core.dependencies import get_redis, get_session_factory
from app.core.logging import get_logger
from app.models.issue import Issue, IssueSeverity
from app.models.repository import Repository
from app.models.review import Review, ReviewStatus
from app.platform.adapters.github import GitHubAdapter
from app.rag.retriever import retrieve_context

log = get_logger(__name__)

_STREAM_CHANNEL = "review:{review_id}:stream"
_AGENT_NODES = {"security", "performance", "style"}


async def run_review_task(ctx: dict, review_id: str, source_code: str, language: str) -> None:
    """ARQ 入口：驱动 LangGraph 图，推送进度事件到 Redis Pub/Sub。"""
    channel = _STREAM_CHANNEL.format(review_id=review_id)
    session_factory = get_session_factory()
    redis = get_redis()
    started_at = time.monotonic()

    async with session_factory() as db:
        review = await db.get(Review, uuid.UUID(review_id))
        if review is None:
            log.error("review_not_found", review_id=review_id)
            return

        try:
            review.status = ReviewStatus.running
            await db.commit()

            # Webhook 模式：source_code 为空，在 Worker 内拉 diff（避免 Webhook handler 超时）
            if not source_code and review.repository_id and review.pr_number:
                source_code = await _fetch_pr_diff(db, review)

            # Webhook 模式注入 RAG 上下文，paste 模式（repository_id=None）返回 ""
            rag_context = await retrieve_context(db, source_code, review.repository_id)

            initial_state: ReviewState = {
                "source_code": source_code,
                "language": language,
                "rag_context": rag_context,
                "issues": [],
                "parse_failures": [],
                "report_text": "",
                "error": None,
            }

            final_state: ReviewState | None = None

            # astream_events 遍历图执行事件，按类型路由到 Pub/Sub 消息
            async for event in compiled_graph.astream_events(initial_state, version="v2"):
                kind: str = event["event"]
                name: str = event.get("name", "")
                tags: list[str] = event.get("tags", [])

                if kind == "on_chain_start" and name in _AGENT_NODES:
                    await redis.publish(channel, json.dumps({"type": "agent_start", "agent": name}))

                elif kind == "on_chain_end" and name in _AGENT_NODES:
                    output = event["data"].get("output") or {}
                    issue_count = len(output.get("issues", []))
                    msg = json.dumps({"type": "agent_done", "agent": name, "issue_count": issue_count})
                    await redis.publish(channel, msg)
                    # 持久化进度，供晚连接的 WS 追赶（TTL 1小时）
                    progress_key = f"review:{review_id}:progress"
                    await redis.hset(progress_key, name, issue_count)
                    await redis.expire(progress_key, 3600)

                elif kind == "on_chain_start" and name == "synthesis":
                    await redis.publish(channel, json.dumps({"type": "agent_start", "agent": "synthesis"}))

                elif kind == "on_chat_model_stream" and "synthesis" in tags:
                    token: str = event["data"]["chunk"].content
                    if token:
                        await redis.publish(channel, json.dumps({
                            "type": "synthesis_token",
                            "content": token,
                        }))

                elif kind == "on_chain_end" and not event.get("parent_ids"):
                    # 根图事件（parent_ids 为空）即图执行结束，拿最终状态。
                    # 不用硬编码 name=="LangGraph"：那是 langgraph 内部命名，升级改名会
                    # 让 final_state 恒为 None、每个审查都失败。parent_ids 为空更稳。
                    final_state = event["data"].get("output")

            if final_state is None:
                raise RuntimeError("LangGraph returned no final state")

            # 三个并行 Agent 的输出经 Reducer 合并，写 DB 前统一去重
            issues: list[IssueOutput] = deduplicate_issues(final_state.get("issues", []))
            report_text: str = final_state.get("report_text", "")
            duration_ms = int((time.monotonic() - started_at) * 1000)

            # 某个 Agent 的 JSON 解析失败 → 整类问题被吞掉，必须发信号而非静默漏报
            parse_failures: list[str] = final_state.get("parse_failures", [])
            if parse_failures:
                log.warning("agent_parse_failures", failures=parse_failures)

            review.status = ReviewStatus.done
            review.report_text = report_text
            review.total_issues = len(issues)
            review.duration_ms = duration_ms
            for issue in issues:
                db.add(Issue(
                    review_id=review.id,
                    category=issue.category,
                    severity=issue.severity,
                    file_path=issue.file_path,
                    line_start=issue.line_start,
                    line_end=issue.line_end,
                    description=issue.description,
                    suggestion=issue.suggestion,
                ))
            await db.commit()

            await redis.publish(channel, json.dumps({
                "type": "done",
                "issue_count": len(issues),
                "duration_ms": duration_ms,
                "parse_failures": parse_failures,
            }))
            log.info("review_done", review_id=review_id, issues=len(issues), ms=duration_ms)

            # P1: Webhook 模式回调 GitHub（paste 模式无 head_sha，静默跳过）
            await _maybe_notify_github(db, review, issues, report_text)

        except Exception as exc:
            log.exception("review_failed", review_id=review_id)
            try:
                review.status = ReviewStatus.failed
                review.error_message = str(exc)
                await db.commit()
            except Exception:
                pass
            await redis.publish(channel, json.dumps({"type": "error", "message": str(exc)}))
            await _maybe_notify_github(db, review, [], "", failed=True)


# ── Webhook 模式：在 Worker 内拉 PR diff ─────────────────────────────────────

async def _fetch_pr_diff(db, review: Review) -> str:
    """从 GitHub 拉取 PR diff，写入 review.source_code 供后续 Source Code Tab 展示。

    拉取失败向上抛出，由 run_review_task 的 except 块统一处理（标记 failed）。
    """
    repo: Repository | None = await db.get(Repository, review.repository_id)
    if repo is None:
        raise RuntimeError(f"Repository {review.repository_id} not found in DB")

    adapter = GitHubAdapter()
    owner, repo_name = GitHubAdapter.parse_repo_url(repo.url)
    diff = await adapter.get_pr_diff(owner, repo_name, review.pr_number)

    # 持久化到 DB，ReviewDetail 的 Source Code Tab 可直接展示
    review.source_code = diff
    await db.commit()

    log.info("pr_diff_fetched", review_id=str(review.id), chars=len(diff))
    return diff


# ── GitHub 回调 ───────────────────────────────────────────────────────────────

def _format_pr_comment(issues: list[IssueOutput], report_text: str, duration_ms: int) -> str:
    """将审查结果格式化为 GitHub PR 评论 Markdown。"""
    critical = sum(1 for i in issues if i.severity == IssueSeverity.critical)
    warnings  = sum(1 for i in issues if i.severity == IssueSeverity.warning)

    header = (
        f"## 🔍 CodeSentinel Review\n\n"
        f"**{len(issues)} issues found** "
        f"({critical} critical · {warnings} warning · "
        f"{len(issues) - critical - warnings} suggestion) "
        f"· {duration_ms / 1000:.1f}s\n\n"
    )
    body = report_text if report_text else "_No synthesis report generated._"
    return header + body + "\n\n---\n*Powered by CodeSentinel — Multi-Agent AI Code Review*"


async def _maybe_notify_github(
    db,
    review: Review,
    issues: list[IssueOutput],
    report_text: str,
    *,
    failed: bool = False,
) -> None:
    """审查完成后回调 GitHub Status Check 和 PR 评论。

    paste 模式（head_sha=None）和非 GitHub 仓库静默跳过。
    回调失败只记录警告，不向上抛出（避免污染主任务状态）。
    """
    if not review.head_sha or not review.repository_id:
        return

    try:
        repo: Repository | None = await db.get(Repository, review.repository_id)
        if repo is None or repo.platform.value != "github":
            return

        adapter = GitHubAdapter()
        owner, repo_name = GitHubAdapter.parse_repo_url(repo.url)

        # Status Check
        if failed:
            state, desc = "failure", "CodeSentinel review failed"
        else:
            critical_count = sum(1 for i in issues if i.severity == IssueSeverity.critical)
            state = "failure" if critical_count > 0 else "success"
            desc = (
                f"Found {len(issues)} issues ({critical_count} critical)"
                if issues else "No issues found"
            )
        await adapter.set_commit_status(owner, repo_name, review.head_sha, state, desc)

        # PR 评论（仅成功路径且有内容时发布）
        if not failed and review.pr_number and (issues or report_text):
            comment = _format_pr_comment(issues, report_text, review.duration_ms or 0)
            await adapter.post_review_comment(owner, repo_name, review.pr_number, comment)

    except Exception:
        log.warning("github_notify_failed", review_id=str(review.id))
