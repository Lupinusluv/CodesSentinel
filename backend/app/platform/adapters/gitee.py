"""Gitee 平台适配器（roadmap 占位，尚未实现）。

接口契约已由 GitPlatformAdapter 固定；此处仅声明骨架，所有操作抛
NotImplementedError，让"未实现"成为显式信号而非空文件。webhooks 的 /gitee
端点目前直接返回 501，不依赖本类。实现时参考 github.py。
"""

from app.platform.base import GitPlatformAdapter


class GiteeAdapter(GitPlatformAdapter):
    async def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        raise NotImplementedError("Gitee adapter not implemented yet")

    async def post_review_comment(self, owner: str, repo: str, pr_number: int, body: str) -> None:
        raise NotImplementedError("Gitee adapter not implemented yet")

    async def set_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,
        description: str,
        context: str = "CodeSentinel",
    ) -> None:
        raise NotImplementedError("Gitee adapter not implemented yet")
