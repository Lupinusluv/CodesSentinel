"""AutoFix 后台任务（ARQ）。

由 POST /api/v1/reviews/{id}/autofix 入队，整段流程：
  1. 清掉该 review 之前的旧 patches，重置所有 issues.fixed=False（重跑场景）
  2. 从 DB 读 Review（要求 status=done）+ 该 review 的所有 issues
  3. 按 (line_start, line_end) 聚合 issues —— 同行的多个 issue 共用一个 patch
  4. 投影为 IssueRef，构造 AutoFixState
  5. 调用 compiled_autofix_graph.ainvoke
  6. 把 patches 写入 DB；语法校验通过的 patch 对应的整组 issue 都置 fixed=True

与 review_task.py 严格对称：task 负责所有 DB IO，图节点保持无副作用。
"""

import uuid
from collections import defaultdict
from typing import Iterable

from sqlalchemy import delete, select, update

from app.agents.autofix_agent import (
    AutoFixState,
    IssueRef,
    PatchOutput,
    compiled_autofix_graph,
)
from app.core.dependencies import get_session_factory
from app.core.logging import get_logger
from app.models.issue import Issue
from app.models.patch import Patch, PatchStatus
from app.models.review import Review, ReviewStatus

log = get_logger(__name__)


# critical 优先级最高，suggestion 最低；用于在同行 issue 组里挑 representative
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "suggestion": 2}


def _group_issues_by_range(
    db_issues: Iterable[Issue],
) -> tuple[list[IssueRef], dict[str, list[str]], str | None]:
    """按 (line_start, line_end) 聚合 issues。

    返回:
      issue_refs: 每个 group 一条 IssueRef，issue_id = group 内 severity 最高那条的 id
      representative_ids: rep_issue_id → 组内所有原始 issue_id（含 rep 自己）
      global_rep_id: 所有 issue 中 severity 最高那条的 id，供 final patch 作 issue_id
                     占位（patches.issue_id NOT NULL）；空输入时为 None

    None 值用 -1 占位归到同一组。description 用换行拼接，suggestion 取第一个非空。
    """
    db_issues = list(db_issues)
    groups: dict[tuple[int, int], list[Issue]] = defaultdict(list)
    for i in db_issues:
        key = (
            i.line_start if i.line_start is not None else -1,
            i.line_end if i.line_end is not None else -1,
        )
        groups[key].append(i)

    issue_refs: list[IssueRef] = []
    representative_ids: dict[str, list[str]] = {}

    for group in groups.values():
        group_sorted = sorted(
            group,
            key=lambda x: _SEVERITY_ORDER.get(
                getattr(x.severity, "value", x.severity), 99
            ),
        )
        rep = group_sorted[0]
        if len(group_sorted) == 1:
            merged_desc = rep.description
        else:
            merged_desc = "\n".join(f"- {x.description}" for x in group_sorted)
        merged_sug = next((x.suggestion for x in group_sorted if x.suggestion), None)
        issue_refs.append(
            IssueRef(
                issue_id=str(rep.id),
                line_start=rep.line_start,
                line_end=rep.line_end,
                description=merged_desc,
                suggestion=merged_sug,
            )
        )
        representative_ids[str(rep.id)] = [str(x.id) for x in group_sorted]

    if db_issues:
        global_rep = min(
            db_issues,
            key=lambda x: _SEVERITY_ORDER.get(
                getattr(x.severity, "value", x.severity), 99
            ),
        )
        global_rep_id: str | None = str(global_rep.id)
    else:
        global_rep_id = None

    return issue_refs, representative_ids, global_rep_id


async def run_autofix_task(ctx: dict, review_id: str) -> None:
    """ARQ 入口；任何异常都吞掉只记日志，避免重试风暴。"""
    try:
        uid = uuid.UUID(review_id)
    except ValueError:
        log.error("autofix_invalid_review_id", review_id=review_id)
        return

    session_factory = get_session_factory()
    async with session_factory() as db:
        review = await db.get(Review, uid)
        if review is None:
            log.error("autofix_review_not_found", review_id=review_id)
            return
        if review.status != ReviewStatus.done:
            log.warning(
                "autofix_skipped_non_done_review",
                review_id=review_id,
                status=review.status.value,
            )
            return
        if not review.source_code:
            log.warning("autofix_no_source_code", review_id=review_id)
            return

        # 清旧 patch + 重置 fixed —— 重跑时避免累加，避免上次成功标记残留
        await db.execute(delete(Patch).where(Patch.review_id == uid))
        await db.execute(
            update(Issue).where(Issue.review_id == uid).values(fixed=False)
        )

        result = await db.execute(select(Issue).where(Issue.review_id == uid))
        db_issues = list(result.scalars())
        if not db_issues:
            log.info("autofix_no_issues", review_id=review_id)
            await db.commit()
            return

        issue_refs, representative_ids, global_rep_id = _group_issues_by_range(db_issues)
        log.info(
            "autofix_grouped",
            review_id=review_id,
            total_issues=len(db_issues),
            groups=len(issue_refs),
        )

        initial: AutoFixState = {
            "review_id": review_id,
            "source_code": review.source_code,
            "language": review.language or "python",
            "issues": issue_refs,
            "patches": [],
            "error": None,
            "final_rep_id": global_rep_id,
        }

        try:
            final_state = await compiled_autofix_graph.ainvoke(initial)
        except Exception:
            log.exception("autofix_graph_failed", review_id=review_id)
            await db.commit()
            return

        patches: list[PatchOutput] = final_state.get("patches", []) or []
        issue_by_id = {str(i.id): i for i in db_issues}

        for p in patches:
            db.add(Patch(
                review_id=uid,
                issue_id=uuid.UUID(p.issue_id),
                original_code=p.original_code,
                fixed_code=p.fixed_code,
                diff=p.diff,
                syntax_valid=p.syntax_valid,
                error_msg=p.error_msg,
                status=p.status,
                is_final=p.is_final,
            ))
            # final patch 不参与 issues.fixed 标记，避免与 per-issue patch 重复打 True
            if p.is_final:
                continue
            if p.status == PatchStatus.done and p.syntax_valid:
                for member_id in representative_ids.get(p.issue_id, [p.issue_id]):
                    if member_id in issue_by_id:
                        issue_by_id[member_id].fixed = True

        await db.commit()
        log.info(
            "autofix_done",
            review_id=review_id,
            patches=len(patches),
            valid=sum(1 for p in patches if p.syntax_valid),
            final=sum(1 for p in patches if p.is_final),
        )
