"""GitHub 回写路径测试：_maybe_notify_github 状态逻辑 + _format_pr_comment 格式。

回写会写真实 GitHub PR（commit status + 评论），逻辑必须有测试背书。
GitHub HTTP 调用用 AsyncMock 替身（monkeypatch adapter 方法），不发真实请求。
"""

from unittest.mock import AsyncMock

import pytest

from app.agents.state import IssueOutput
from app.models.issue import IssueCategory, IssueSeverity
from app.models.review import Review, ReviewStatus
from app.platform.adapters.github import GitHubAdapter
from app.tasks.review_task import _format_pr_comment, _maybe_notify_github

pytestmark = pytest.mark.integration  # asyncio_mode=auto，async 测试自动识别；本文件含同步用例，不加 asyncio mark


def _issue(severity: IssueSeverity, category: IssueCategory = IssueCategory.security) -> IssueOutput:
    return IssueOutput(category=category, severity=severity, description="problem")


@pytest.fixture
def patch_github(monkeypatch):
    """替换 GitHubAdapter 的两个写操作为 AsyncMock，返回 (status_mock, comment_mock)。"""
    status_mock = AsyncMock()
    comment_mock = AsyncMock()
    monkeypatch.setattr(GitHubAdapter, "set_commit_status", status_mock)
    monkeypatch.setattr(GitHubAdapter, "post_review_comment", comment_mock)
    return status_mock, comment_mock


async def _make_review(db_session, repo, *, head_sha: str | None = "a" * 40) -> Review:
    review = Review(
        repository_id=repo.id,
        pr_number=7,
        status=ReviewStatus.done,
        language="python",
        source_code="x = 1\n",
        head_sha=head_sha,
        duration_ms=1500,
    )
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)
    return review


# ── _format_pr_comment ────────────────────────────────────────────────────────

def test_format_pr_comment_counts_by_severity():
    issues = [
        _issue(IssueSeverity.critical),
        _issue(IssueSeverity.critical),
        _issue(IssueSeverity.warning),
        _issue(IssueSeverity.suggestion),
    ]
    md = _format_pr_comment(issues, "synthesis body", 2500)
    assert "**4 issues found**" in md
    assert "2 critical" in md
    assert "1 warning" in md
    assert "1 suggestion" in md
    assert "2.5s" in md
    assert "synthesis body" in md
    assert "CodeSentinel" in md


def test_format_pr_comment_empty_uses_placeholder():
    md = _format_pr_comment([], "", 1000)
    assert "**0 issues found**" in md
    assert "No synthesis report generated" in md


# ── _maybe_notify_github 状态逻辑 ─────────────────────────────────────────────

async def test_notify_critical_sets_failure(db_session, github_repo, patch_github):
    status_mock, comment_mock = patch_github
    review = await _make_review(db_session, github_repo)

    await _maybe_notify_github(
        db_session, review, [_issue(IssueSeverity.critical), _issue(IssueSeverity.warning)], "report"
    )

    status_mock.assert_awaited_once()
    assert status_mock.call_args.args[3] == "failure"  # state 是第 4 个位置参数
    comment_mock.assert_awaited_once()  # 成功路径且有内容 → 发评论


async def test_notify_no_critical_sets_success(db_session, github_repo, patch_github):
    status_mock, comment_mock = patch_github
    review = await _make_review(db_session, github_repo)

    await _maybe_notify_github(
        db_session, review, [_issue(IssueSeverity.warning), _issue(IssueSeverity.suggestion)], "report"
    )

    assert status_mock.call_args.args[3] == "success"
    comment_mock.assert_awaited_once()


async def test_notify_no_issues_success_with_no_issues_desc(db_session, github_repo, patch_github):
    status_mock, comment_mock = patch_github
    review = await _make_review(db_session, github_repo)

    await _maybe_notify_github(db_session, review, [], "")

    assert status_mock.call_args.args[3] == "success"
    assert "No issues found" in status_mock.call_args.args[4]  # description
    comment_mock.assert_not_awaited()  # 无 issue 且无 report → 不发评论


async def test_notify_failed_sets_failure_no_comment(db_session, github_repo, patch_github):
    status_mock, comment_mock = patch_github
    review = await _make_review(db_session, github_repo)

    await _maybe_notify_github(db_session, review, [], "", failed=True)

    assert status_mock.call_args.args[3] == "failure"
    comment_mock.assert_not_awaited()  # 失败路径不发评论


async def test_notify_paste_mode_skips_github(db_session, patch_github):
    """paste 模式：head_sha=None / repository_id=None → 任何 GitHub 操作都不调用。"""
    status_mock, comment_mock = patch_github
    review = Review(status=ReviewStatus.done, language="python", source_code="x = 1\n")
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)

    await _maybe_notify_github(db_session, review, [_issue(IssueSeverity.critical)], "r")

    status_mock.assert_not_awaited()
    comment_mock.assert_not_awaited()
