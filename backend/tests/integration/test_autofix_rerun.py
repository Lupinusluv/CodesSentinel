"""AutoFix 重跑与聚合集成测试（需要真实 PostgreSQL）。

不发真实 LLM 请求：通过 monkeypatch 替换 compiled_autofix_graph，让图直接
为每个 IssueRef 产出一条受控的 PatchOutput。这样能验证 task 层的 DB 行为：
  - 重跑时清旧 patches、重置 issues.fixed
  - 按 (line_start, line_end) 聚合：N 个同行 issue → 1 个 patch + N 个 issue 都标记 fixed
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


# ── fixture：让 task 用 test_engine，避免 module-level singleton 跨 loop ────────

@pytest_asyncio.fixture
async def patched_task(test_engine, monkeypatch):
    """重定向 run_autofix_task 内部的 session factory 到当前 test_engine。"""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(
        "app.tasks.autofix_task.get_session_factory", lambda: factory
    )
    return factory


def _patch_graph(monkeypatch, *, syntax_valid: bool, status: PatchStatus):
    """让图直接产出每个 IssueRef 一条 patch，结果由参数控制。"""
    async def fake_ainvoke(state):
        return {
            **state,
            "patches": [
                PatchOutput(
                    issue_id=ref.issue_id,
                    original_code=state["source_code"],
                    fixed_code="# fixed\n",
                    diff="--- a\n+++ b\n",
                    syntax_valid=syntax_valid,
                    error_msg=None if syntax_valid else "fake error",
                    status=status,
                )
                for ref in state["issues"]
            ],
        }

    monkeypatch.setattr(
        "app.tasks.autofix_task.compiled_autofix_graph",
        SimpleNamespace(ainvoke=fake_ainvoke),
    )


async def _seed_review_with_issues(
    factory: async_sessionmaker,
    *,
    ranges: list[tuple[int, int, IssueSeverity]],
) -> uuid.UUID:
    """造一个 done 状态的 review + 指定 (line_start, line_end, severity) 的 issues。"""
    async with factory() as s:
        rev = Review(
            status=ReviewStatus.done,
            language="python",
            source_code="x = 1\n" * 20,
            total_issues=len(ranges),
        )
        s.add(rev)
        await s.flush()
        for ls, le, sev in ranges:
            s.add(Issue(
                review_id=rev.id,
                category=IssueCategory.security,
                severity=sev,
                line_start=ls,
                line_end=le,
                description="seeded issue",
                suggestion=None,
                fixed=False,
            ))
        await s.commit()
        return rev.id


async def _count_patches(factory: async_sessionmaker, review_id: uuid.UUID) -> int:
    async with factory() as s:
        result = await s.execute(select(Patch).where(Patch.review_id == review_id))
        return len(list(result.scalars()))


async def _fixed_count(factory: async_sessionmaker, review_id: uuid.UUID) -> int:
    async with factory() as s:
        result = await s.execute(
            select(Issue).where(Issue.review_id == review_id, Issue.fixed.is_(True))
        )
        return len(list(result.scalars()))


# ── 测试 ──────────────────────────────────────────────────────────────────────

async def test_rerun_does_not_accumulate_patches(patched_task, monkeypatch):
    """两次 Auto Fix → patches 数量等于第二次产出，不累加。"""
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph(monkeypatch, syntax_valid=True, status=PatchStatus.done)
    rid = await _seed_review_with_issues(
        patched_task,
        ranges=[
            (1, 1, IssueSeverity.warning),
            (5, 5, IssueSeverity.critical),
            (10, 10, IssueSeverity.suggestion),
        ],
    )

    await run_autofix_task({}, str(rid))
    first = await _count_patches(patched_task, rid)
    assert first == 3                   # 3 个独立行 → 3 patches

    await run_autofix_task({}, str(rid))
    second = await _count_patches(patched_task, rid)
    assert second == 3                  # 重跑仍是 3，不是 6


async def test_rerun_resets_fixed_before_running(patched_task, monkeypatch):
    """第一次成功 → fixed=True；第二次失败 → fixed 应被重置回 False。"""
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph(monkeypatch, syntax_valid=True, status=PatchStatus.done)
    rid = await _seed_review_with_issues(
        patched_task,
        ranges=[(1, 1, IssueSeverity.warning), (5, 5, IssueSeverity.warning)],
    )

    await run_autofix_task({}, str(rid))
    assert await _fixed_count(patched_task, rid) == 2

    # 切换 mock：第二轮 graph 产出失败 patch
    _patch_graph(monkeypatch, syntax_valid=False, status=PatchStatus.failed)
    await run_autofix_task({}, str(rid))
    assert await _fixed_count(patched_task, rid) == 0


async def test_same_line_issues_aggregate_to_one_patch(patched_task, monkeypatch):
    """3 个同行 issue → 1 patch + 这 3 个 issue 都 fixed=True。"""
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph(monkeypatch, syntax_valid=True, status=PatchStatus.done)
    rid = await _seed_review_with_issues(
        patched_task,
        ranges=[
            (7, 7, IssueSeverity.critical),
            (7, 7, IssueSeverity.warning),
            (7, 7, IssueSeverity.suggestion),
        ],
    )

    await run_autofix_task({}, str(rid))

    assert await _count_patches(patched_task, rid) == 1
    assert await _fixed_count(patched_task, rid) == 3   # 整组 issue 都标记


async def test_aggregation_attaches_patch_to_critical_representative(
    patched_task, monkeypatch
):
    """同行多 issue 时，patch.issue_id 必须是 severity 最高那条的 id。"""
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph(monkeypatch, syntax_valid=True, status=PatchStatus.done)
    async with patched_task() as s:
        rev = Review(
            status=ReviewStatus.done,
            language="python",
            source_code="y = 2\n" * 15,
            total_issues=2,
        )
        s.add(rev)
        await s.flush()
        warning = Issue(
            review_id=rev.id, category=IssueCategory.style,
            severity=IssueSeverity.warning,
            line_start=3, line_end=3,
            description="warning issue", fixed=False,
        )
        critical = Issue(
            review_id=rev.id, category=IssueCategory.security,
            severity=IssueSeverity.critical,
            line_start=3, line_end=3,
            description="critical issue", fixed=False,
        )
        s.add_all([warning, critical])
        await s.commit()
        crit_id = critical.id

    await run_autofix_task({}, str(rev.id))

    async with patched_task() as s:
        result = await s.execute(select(Patch).where(Patch.review_id == rev.id))
        patches = list(result.scalars())
    assert len(patches) == 1
    assert patches[0].issue_id == crit_id


async def test_no_patches_written_when_no_issues(patched_task, monkeypatch):
    """没 issues 的 review 直接返回，不会留下 patches。"""
    from app.tasks.autofix_task import run_autofix_task

    _patch_graph(monkeypatch, syntax_valid=True, status=PatchStatus.done)
    async with patched_task() as s:
        rev = Review(
            status=ReviewStatus.done,
            language="python",
            source_code="z = 3\n",
            total_issues=0,
        )
        s.add(rev)
        await s.commit()
        rid = rev.id

    await run_autofix_task({}, str(rid))
    assert await _count_patches(patched_task, rid) == 0
