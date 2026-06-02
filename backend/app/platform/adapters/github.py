"""GitHub 平台适配器。

使用 GitHub REST API v3，通过 httpx 异步调用。
Token 从 Settings.github_token 读取（Personal Access Token 或 GitHub App token）。
"""

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.platform.base import GitPlatformAdapter

log = get_logger(__name__)

_GITHUB_API = "https://api.github.com"
_DIFF_ACCEPT = "application/vnd.github.v3.diff"
_JSON_ACCEPT = "application/vnd.github+json"
_API_VERSION = "2022-11-28"


class GitHubAdapter(GitPlatformAdapter):
    def __init__(self, token: str | None = None) -> None:
        self._token = token or get_settings().github_token
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": _API_VERSION,
        }

    # ── 核心操作 ───────────────────────────────────────────────────────────────

    async def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """获取 PR 的 unified diff。"""
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                headers={**self._headers, "Accept": _DIFF_ACCEPT},
            )
            resp.raise_for_status()
            return resp.text

    async def post_review_comment(self, owner: str, repo: str, pr_number: int, body: str) -> None:
        """在 PR 下发布审查评论。"""
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                headers={**self._headers, "Accept": _JSON_ACCEPT},
                json={"body": body},
            )
            resp.raise_for_status()
        log.info("github_comment_posted", owner=owner, repo=repo, pr=pr_number)

    async def set_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,
        description: str,
        context: str = "CodeSentinel",
    ) -> None:
        """设置 commit Status Check。"""
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/statuses/{sha}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                headers={**self._headers, "Accept": _JSON_ACCEPT},
                json={
                    "state": state,
                    "description": description[:140],  # GitHub 限制 140 字符
                    "context": context,
                },
            )
            resp.raise_for_status()
        log.info(
            "github_status_set",
            owner=owner,
            repo=repo,
            sha=sha[:8],
            state=state,
        )

    # ── 工具方法 ───────────────────────────────────────────────────────────────

    @staticmethod
    def parse_repo_url(url: str) -> tuple[str, str]:
        """从 https://github.com/owner/repo[.git] 解析出 (owner, repo)。"""
        parts = url.rstrip("/").split("/")
        if len(parts) < 2:
            raise ValueError(f"Cannot parse GitHub URL: {url}")
        repo = parts[-1].removesuffix(".git")
        return parts[-2], repo
