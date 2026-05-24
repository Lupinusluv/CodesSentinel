"""GitPlatformAdapter — 平台无关的 Git 操作接口。

所有与具体 Git 平台交互的代码必须通过此接口，业务逻辑不得直接调用平台 SDK。
"""

import hashlib
import hmac
from abc import ABC, abstractmethod


class GitPlatformAdapter(ABC):
    """统一的 Git 平台操作接口。

    子类实现 GitHub / GitLab / Gitee 的具体 HTTP 调用，
    调用方只依赖此抽象，保持平台无关性。
    """

    @abstractmethod
    async def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """获取 PR 的 unified diff 文本。"""

    @abstractmethod
    async def post_review_comment(
        self, owner: str, repo: str, pr_number: int, body: str
    ) -> None:
        """在 PR 下发布一条审查评论。"""

    @abstractmethod
    async def set_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,          # "pending" | "success" | "failure" | "error"
        description: str,
        context: str = "CodeSentinel",
    ) -> None:
        """设置 commit 的 Status Check（PR 页面的绿勾/红叉）。"""

    # ── 签名验证（各平台算法一致，统一实现）────────────────────────────────────

    @staticmethod
    def verify_signature_sha256(payload: bytes, signature: str, secret: str) -> bool:
        """验证 HMAC-SHA256 签名（GitHub / GitLab 格式：'sha256=<hex>'）。"""
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        received = signature.removeprefix("sha256=")
        return hmac.compare_digest(expected, received)
