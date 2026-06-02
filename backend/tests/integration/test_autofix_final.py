"""#8 FinalPatch 集成测试。

mock 整个 graph，让它产出 N 个 per-issue patch + 1 个 is_final=True 的综合 patch。
验证：
  - patches 表里 N+1 条
  - is_final=True 的 patch issue_id = global_rep_id（所有 issue 里 severity 最高那条）
  - final patch 不影响 issues.fixed 标记（仅 per-issue patch 影响）
  - GET /patches 返回时 final patch 排在最前
"""

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.autofix_agent import PatchOutput
from app.models.issue import Issue, IssueCategory, IssueSeverity
from app.models.patch import Patch, PatchStatus
from app.models.review import Review, ReviewStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def patched_task(test_engine, monkeypatch):
    factory = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr("app.tasks.autofix_task.get_session_factory", lambda: factory)
    return factory


def _patch_graph_with_final(monkeypatch):
    """让图同时产出 per-issue patches + 1 个 is_final final patch。"""

    async def fake_ainvoke(state):
        per_issue = [
            PatchOutput(
                issue_id=ref.issue_id,
                original_code=state["source_code"],
                fixed_code=f"# fixed for {ref.issue_id[:4]}\n",
                diff="d",
                syntax_valid=True,
                error_msg=None,
                status=PatchStatus.done,
                is_final=False,
            )
            for ref in state["issues"]
        ]
        final = PatchOutput(
            issue_id=state["final_rep_id"],
            original_code=state["source_code"],
            fixed_code="# consolidated fix\n",
            diff="d-final",
            syntax_valid=True,
            error_msg=None,
            status=PatchStatus.done,
            is_final=True,
        )
        return {**state, "patches": [final, *per_issue]}

    monkeypatch.setattr(
        "app.tasks.autofix_task.compiled_autofix_graph",
        SimpleNamespace(ainvoke=fake_ainvoke),
    )


def _patch_graph_final_drops_silently(monkeypatch):
    """方案 A：merge_all 失败时只返回 per-issue patches，无 final patch 入库。"""

    async def fake_ainvoke(state):
        return {
            **state,
            "patches": [
                PatchOutput(
                    issue_id=ref.issue_id,
                    original_code=state["source_code"],
                    fixed_code="# per-issue\n",
                    diff="d",
                    syntax_valid=True,
                    error_msg=None,
                    status=PatchStatus.done,
                    is_final=False,
                )
                for ref in state["issues"]
            ],
        }

    monkeypatch.setattr(
        "app.tasks.autofix_task.compiled_autofix_graph",
        SimpleNamespace(ainvoke=fake_ainvoke),
    )


async def _seed(
    factory, *, ranges: list[tuple[int, int, IssueSeverity]]
) -> tuple[uuid.UUID, dict[IssueSeverity, uuid.UUID]]:
    """返回 review_id 和 severity → issue_id 映射，便于后续断言。"""
    async with factory() as s:
        rev = Review(
            status=ReviewStatus.done,
            language="python",
            source_code="x = 1\n" * 20,
            total_issues=len(ranges),
        )
        s.add(rev)
        await s.flush()
        sev_map: dict[IssueSeverity, uuid.UUID] = {}
        for ls, le, sev in ranges:
            issue = Issue(
                review_id=rev.id,
                category=IssueCategory.security,
                severity=sev,
                line_start=ls,
                line_end=le,
                description=f"{sev.value} issue",
                fixed=False,
            )
            s.add(issue)
            await s.flush()
            # 留一个映射（若同 severity 多条则保留最后一个）
            sev_map[sev] = issue.id
        await s.commit()
        return rev.id, sev_map


# ── 主路径：成功产出 N+1 patches ───────────────────────────────────────────────


async def test_final_patch_is_written_alongside_per_issue(patched_task, monkeypatch):
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph_with_final(monkeypatch)
    rid, sev_map = await _seed(
        patched_task,
        ranges=[
            (1, 1, IssueSeverity.warning),
            (5, 5, IssueSeverity.critical),
            (9, 9, IssueSeverity.suggestion),
        ],
    )

    await run_autofix_task({}, str(rid))

    async with patched_task() as s:
        result = await s.execute(select(Patch).where(Patch.review_id == rid))
        rows = list(result.scalars())
    # 3 per-issue + 1 final
    assert len(rows) == 4
    finals = [p for p in rows if p.is_final]
    assert len(finals) == 1
    # final patch issue_id 是 critical 那条
    assert finals[0].issue_id == sev_map[IssueSeverity.critical]
    assert finals[0].fixed_code == "# consolidated fix\n"


async def test_final_patch_does_not_double_mark_issues_fixed(patched_task, monkeypatch):
    """final patch 不应触发 issues.fixed=True（避免与 per-issue 重复打）。"""
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph_with_final(monkeypatch)
    rid, _ = await _seed(
        patched_task,
        ranges=[(1, 1, IssueSeverity.warning), (5, 5, IssueSeverity.critical)],
    )

    await run_autofix_task({}, str(rid))

    # 每个 issue 都只有 per-issue patch 在 fixed=True 路径上一次
    # 这里间接验证：count(fixed=True) 应等于 issue 总数
    async with patched_task() as s:
        result = await s.execute(select(Issue).where(Issue.review_id == rid, Issue.fixed.is_(True)))
        assert len(list(result.scalars())) == 2


async def test_list_patches_api_returns_final_first(
    http_client, db_session, patched_task, monkeypatch
):
    """GET /patches 排序应让 is_final=True 排最前。"""
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph_with_final(monkeypatch)
    rid, _ = await _seed(
        patched_task,
        ranges=[(1, 1, IssueSeverity.warning), (5, 5, IssueSeverity.critical)],
    )

    await run_autofix_task({}, str(rid))

    resp = await http_client.get(f"/api/v1/reviews/{rid}/patches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3  # 2 per-issue + 1 final
    assert body["patches"][0]["is_final"] is True
    assert all(p["is_final"] is False for p in body["patches"][1:])


# ── 方案 A：失败静默降级 ───────────────────────────────────────────────────────


async def test_no_final_patch_when_merge_all_drops(patched_task, monkeypatch):
    """merge_all 失败 → 只写 per-issue patches，不写 failed final 记录。"""
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph_final_drops_silently(monkeypatch)
    rid, _ = await _seed(
        patched_task,
        ranges=[(1, 1, IssueSeverity.warning)],
    )

    await run_autofix_task({}, str(rid))

    async with patched_task() as s:
        result = await s.execute(select(Patch).where(Patch.review_id == rid))
        rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].is_final is False


async def test_api_omits_final_card_when_none_exists(
    http_client, db_session, patched_task, monkeypatch
):
    """方案 A 验证：失败时 API 返回里没有任何 is_final=True 的 patch。"""
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph_final_drops_silently(monkeypatch)
    rid, _ = await _seed(
        patched_task,
        ranges=[(1, 1, IssueSeverity.warning), (5, 5, IssueSeverity.critical)],
    )

    await run_autofix_task({}, str(rid))

    resp = await http_client.get(f"/api/v1/reviews/{rid}/patches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert all(p["is_final"] is False for p in body["patches"])
