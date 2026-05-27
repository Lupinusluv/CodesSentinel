"""AutoFix 后台任务（ARQ）。

由 POST /api/v1/reviews/{id}/autofix 入队，整段流程：
  1. 从 DB 读 Review（要求 status=done）+ 该 review 的所有 issues
  2. 投影为 IssueRef，构造 AutoFixState
  3. 调用 compiled_autofix_graph.ainvoke
  4. 把 patches 写入 DB；语法校验通过的 patch 对应 issue 置 issues.fixed=True

与 review_task.py 严格对称：task 负责所有 DB IO，图节点保持无副作用。
"""

import uuid

from sqlalchemy import select

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

        result = await db.execute(select(Issue).where(Issue.review_id == uid))
        db_issues = list(result.scalars())
        if not db_issues:
            log.info("autofix_no_issues", review_id=review_id)
            return

        issue_refs = [
            IssueRef(
                issue_id=str(i.id),
                line_start=i.line_start,
                line_end=i.line_end,
                description=i.description,
                suggestion=i.suggestion,
            )
            for i in db_issues
        ]

        initial: AutoFixState = {
            "review_id": review_id,
            "source_code": review.source_code,
            "language": review.language or "python",
            "issues": issue_refs,
            "patches": [],
            "error": None,
        }

        try:
            final_state = await compiled_autofix_graph.ainvoke(initial)
        except Exception:
            log.exception("autofix_graph_failed", review_id=review_id)
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
            ))
            if (
                p.status == PatchStatus.done
                and p.syntax_valid
                and p.issue_id in issue_by_id
            ):
                issue_by_id[p.issue_id].fixed = True

        await db.commit()
        log.info(
            "autofix_done",
            review_id=review_id,
            patches=len(patches),
            valid=sum(1 for p in patches if p.syntax_valid),
        )
