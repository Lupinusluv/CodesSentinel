"""Review 主链路集成测试（需要真实 PostgreSQL）。

范围：HTTP → DB 写入 / 读取 / 状态变更。LLM 不在范围内（无 mock，不发请求），
因为本套件的目的是验证 API + ORM + DB schema 的正确性，而非 Agent 行为。
"""

import uuid

import pytest

from app.models.issue import Issue, IssueCategory, IssueSeverity
from app.models.patch import Patch, PatchStatus
from app.models.review import Review, ReviewStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ── POST /api/v1/reviews ──────────────────────────────────────────────────────


async def test_post_reviews_creates_pending_row(http_client, db_session, sample_python_code):
    resp = await http_client.post(
        "/api/v1/reviews",
        json={"source_code": sample_python_code, "language": "python"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "review_id" in data
    assert data["status"] == "pending"

    row = await db_session.get(Review, uuid.UUID(data["review_id"]))
    assert row is not None
    assert row.status == ReviewStatus.pending
    assert row.language == "python"
    assert row.source_code == sample_python_code

    # ARQ 入队被调用一次
    http_client.fake_arq.enqueue_job.assert_awaited_once()


async def test_post_reviews_rejects_empty_source(http_client):
    resp = await http_client.post(
        "/api/v1/reviews",
        json={"source_code": "  \n\t  ", "language": "python"},
    )
    assert resp.status_code == 400


async def test_post_reviews_rejects_oversized_source(http_client):
    huge = "x" * 50_001
    resp = await http_client.post(
        "/api/v1/reviews",
        json={"source_code": huge, "language": "python"},
    )
    assert resp.status_code == 400


# ── GET /api/v1/reviews/{id} ──────────────────────────────────────────────────


async def test_get_review_returns_issues_in_severity_order(http_client, db_session):
    review = Review(status=ReviewStatus.done, language="python", source_code="x = 1\n")
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)

    db_session.add_all(
        [
            Issue(
                review_id=review.id,
                category=IssueCategory.style,
                severity=IssueSeverity.suggestion,
                description="suggestion-level",
            ),
            Issue(
                review_id=review.id,
                category=IssueCategory.security,
                severity=IssueSeverity.critical,
                description="critical-level",
            ),
            Issue(
                review_id=review.id,
                category=IssueCategory.performance,
                severity=IssueSeverity.warning,
                description="warning-level",
            ),
        ]
    )
    await db_session.commit()

    resp = await http_client.get(f"/api/v1/reviews/{review.id}")
    assert resp.status_code == 200
    body = resp.json()
    severities = [i["severity"] for i in body["issues"]]
    assert severities == ["critical", "warning", "suggestion"]


async def test_get_review_404_on_missing(http_client):
    fake_id = uuid.uuid4()
    resp = await http_client.get(f"/api/v1/reviews/{fake_id}")
    assert resp.status_code == 404


async def test_get_review_400_on_bad_uuid(http_client):
    resp = await http_client.get("/api/v1/reviews/not-a-uuid")
    assert resp.status_code == 400


# ── POST /api/v1/reviews/{id}/autofix ─────────────────────────────────────────


async def test_trigger_autofix_requires_done_status(http_client, db_session):
    review = Review(status=ReviewStatus.running, language="python", source_code="x = 1\n")
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)

    resp = await http_client.post(f"/api/v1/reviews/{review.id}/autofix")
    assert resp.status_code == 409
    assert "done" in resp.json()["detail"]


async def test_trigger_autofix_enqueues_when_done(http_client, db_session):
    review = Review(status=ReviewStatus.done, language="python", source_code="x = 1\n")
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)

    # 重置 mock 计数（http_client fixture 已记录到 review 创建为 0 次）
    http_client.fake_arq.enqueue_job.reset_mock()

    resp = await http_client.post(f"/api/v1/reviews/{review.id}/autofix")
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"

    http_client.fake_arq.enqueue_job.assert_awaited_once_with("run_autofix_task", str(review.id))


async def test_trigger_autofix_rejects_review_without_source(http_client, db_session):
    review = Review(status=ReviewStatus.done, language="python", source_code=None)
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)

    resp = await http_client.post(f"/api/v1/reviews/{review.id}/autofix")
    assert resp.status_code == 409


# ── GET /api/v1/reviews/{id}/patches ──────────────────────────────────────────


async def test_list_patches_returns_existing_rows(http_client, db_session):
    review = Review(status=ReviewStatus.done, language="python", source_code="x = 1\n")
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)

    issue = Issue(
        review_id=review.id,
        category=IssueCategory.security,
        severity=IssueSeverity.critical,
        description="hardcoded credential",
    )
    db_session.add(issue)
    await db_session.commit()
    await db_session.refresh(issue)

    db_session.add(
        Patch(
            review_id=review.id,
            issue_id=issue.id,
            original_code="password = '123'\n",
            fixed_code="password = os.environ['PW']\n",
            diff="--- a\n+++ b\n@@ -1 +1 @@\n-password='123'\n+password=os.environ['PW']\n",
            syntax_valid=True,
            error_msg=None,
            status=PatchStatus.done,
        )
    )
    await db_session.commit()

    resp = await http_client.get(f"/api/v1/reviews/{review.id}/patches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["patches"][0]["status"] == "done"
    assert body["patches"][0]["syntax_valid"] is True


async def test_list_patches_empty_when_none(http_client, db_session):
    review = Review(status=ReviewStatus.done, language="python", source_code="x = 1\n")
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)

    resp = await http_client.get(f"/api/v1/reviews/{review.id}/patches")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
