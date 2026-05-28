"""#6 polling race fix：trigger 接口必须在返回前同步清掉旧 patches。

否则前端 trigger 后立刻 polling 会拉到上一轮残留（全是 done），
满足 "every non-pending" 立即停止轮询，永远看不到新一轮结果。
"""

import uuid

import pytest
from sqlalchemy import select

from app.models.issue import Issue, IssueCategory, IssueSeverity
from app.models.patch import Patch, PatchStatus
from app.models.review import Review, ReviewStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _seed_done_review_with_old_patch(db_session) -> tuple[uuid.UUID, uuid.UUID]:
    """造一个 done 状态 review + 1 个旧 issue + 1 个旧 done patch。返回 (review_id, patch_id)。"""
    rev = Review(
        status=ReviewStatus.done,
        language="python",
        source_code="x = 1\n",
        total_issues=1,
    )
    db_session.add(rev)
    await db_session.flush()

    issue = Issue(
        review_id=rev.id,
        category=IssueCategory.security,
        severity=IssueSeverity.warning,
        line_start=1, line_end=1,
        description="seed",
        fixed=True,
    )
    db_session.add(issue)
    await db_session.flush()

    old_patch = Patch(
        review_id=rev.id,
        issue_id=issue.id,
        original_code="x = 1\n",
        fixed_code="x = 2\n",
        diff="diff",
        syntax_valid=True,
        error_msg=None,
        status=PatchStatus.done,
    )
    db_session.add(old_patch)
    await db_session.commit()
    return rev.id, old_patch.id


async def test_trigger_immediately_clears_old_patches(http_client, db_session):
    """POST /autofix 返回后，立即 GET /patches 应当返回 0 条。"""
    review_id, _old_patch_id = await _seed_done_review_with_old_patch(db_session)

    resp = await http_client.post(f"/api/v1/reviews/{review_id}/autofix")
    assert resp.status_code == 202

    list_resp = await http_client.get(f"/api/v1/reviews/{review_id}/patches")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] == 0
    assert body["patches"] == []

    # ARQ 入队仍然发生
    http_client.fake_arq.enqueue_job.assert_awaited()


async def test_trigger_clears_via_db_query(http_client, db_session):
    """直接查 DB 确认 patches 表里该 review 的行已被删除。"""
    review_id, _ = await _seed_done_review_with_old_patch(db_session)

    resp = await http_client.post(f"/api/v1/reviews/{review_id}/autofix")
    assert resp.status_code == 202

    # 用新 session 避免事务隔离误判
    from tests.conftest import TEST_DATABASE_URL
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine(TEST_DATABASE_URL, future=True, pool_size=2, max_overflow=0)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            result = await s.execute(select(Patch).where(Patch.review_id == review_id))
            rows = list(result.scalars())
        assert rows == []
    finally:
        await engine.dispose()


async def test_trigger_404_does_not_delete_anything(http_client, db_session):
    """review 不存在 → 404，且不应误删任何 patches。"""
    review_id, old_patch_id = await _seed_done_review_with_old_patch(db_session)

    bogus_id = uuid.uuid4()
    resp = await http_client.post(f"/api/v1/reviews/{bogus_id}/autofix")
    assert resp.status_code == 404

    # 原 patches 仍在
    list_resp = await http_client.get(f"/api/v1/reviews/{review_id}/patches")
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1
