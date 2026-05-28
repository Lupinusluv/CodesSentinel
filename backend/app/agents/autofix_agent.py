"""AutoFix LangGraph 图与节点。

拓扑：START → generate → validate → END

设计约束（同 review 主图）：
  - 节点只读写 AutoFixState，不接触 DB。
  - DB 读 / 写副作用全部由 app/tasks/autofix_task.py 承担。
  - LLM 原始输出不直接信任：用 _extract_code 剥离 markdown fence，再喂给
    AST 校验；不通过的标 status=failed，但仍持久化便于面试时演示链路。
"""

import asyncio
import re
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agents.llm import get_llm
from app.agents.prompts import (
    AUTOFIX_FINAL_SYSTEM_PROMPT,
    AUTOFIX_SYSTEM_PROMPT,
    build_autofix_final_prompt,
    build_autofix_prompt,
)
from app.core.logging import get_logger
from app.models.patch import PatchStatus
from app.sandbox.executor import check_syntax
from app.sandbox.validator import make_unified_diff

log = get_logger(__name__)


# ── 结构化输出 ────────────────────────────────────────────────────────────────

class IssueRef(BaseModel):
    """task 层从 DB Issue 投影出的轻量入参。"""

    issue_id: str
    line_start: int | None = None
    line_end: int | None = None
    description: str
    suggestion: str | None = None


class PatchOutput(BaseModel):
    """图内传递的 patch；status / diff / syntax_valid 在 validate 节点补全。

    is_final=True 由 merge_all_node 产出的综合修复版标记，task 层据此
    区分写入行为（不影响 issues.fixed 标记）。
    """

    issue_id: str
    original_code: str
    fixed_code: str
    diff: str = ""
    syntax_valid: bool = False
    error_msg: str | None = None
    status: PatchStatus = PatchStatus.pending
    is_final: bool = False


class AutoFixState(TypedDict):
    """图的共享状态。patches 由 generate 写入、validate 整段覆盖。

    final_rep_id 由 task 层在调用前注入：所有 issue 中 severity 最高那条的 id，
    供 merge_all_node 产出 final patch 时作 issue_id 占位（patches.issue_id NOT NULL）。
    无 issue 时为 None，此时 merge_all_node 直接跳过。
    """

    review_id: str
    source_code: str
    language: str
    issues: list[IssueRef]
    patches: list[PatchOutput]
    error: str | None
    final_rep_id: str | None


# ── 工具 ──────────────────────────────────────────────────────────────────────

_FENCE_OPEN_RE = re.compile(r"^```[a-zA-Z0-9_+\-]*\s*\n?", re.MULTILINE)


def _extract_code(text: str) -> str:
    """剥离 LLM 输出中常见的 markdown fence，返回纯代码字符串。"""
    cleaned = text.strip()
    cleaned = _FENCE_OPEN_RE.sub("", cleaned, count=1)
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip("\n")


def _failed_patch(issue_id: str, *, original: str = "", reason: str) -> PatchOutput:
    return PatchOutput(
        issue_id=issue_id,
        original_code=original,
        fixed_code="",
        diff="",
        syntax_valid=False,
        error_msg=reason,
        status=PatchStatus.failed,
    )


# ── 节点 ──────────────────────────────────────────────────────────────────────

async def _generate_one(
    source_code: str, language: str, issue: IssueRef
) -> PatchOutput:
    if not source_code.strip():
        return _failed_patch(issue.issue_id, reason="empty source code")

    messages = [
        SystemMessage(content=AUTOFIX_SYSTEM_PROMPT),
        HumanMessage(content=build_autofix_prompt(
            language=language,
            source_code=source_code,
            line_start=issue.line_start,
            line_end=issue.line_end,
            description=issue.description,
            suggestion=issue.suggestion,
        )),
    ]
    llm = get_llm(temperature=0.0, tags=["autofix"])
    try:
        response = await llm.ainvoke(messages)
    except Exception as exc:
        log.warning("autofix_llm_error", issue_id=issue.issue_id, error=str(exc))
        return _failed_patch(
            issue.issue_id, original=source_code, reason=f"LLM call failed: {exc}"
        )

    fixed = _extract_code(response.content or "")
    if not fixed:
        return _failed_patch(
            issue.issue_id, original=source_code, reason="LLM returned empty fix"
        )

    return PatchOutput(
        issue_id=issue.issue_id,
        original_code=source_code,
        fixed_code=fixed,
        diff="",
        syntax_valid=False,
        error_msg=None,
        status=PatchStatus.pending,
    )


async def generate_patches_node(state: AutoFixState) -> dict:
    """并发为每个 issue 生成 patch。LLM 异常已在 _generate_one 内吞掉。"""
    issues = state["issues"]
    if not issues:
        return {"patches": []}
    results = await asyncio.gather(
        *[_generate_one(state["source_code"], state["language"], i) for i in issues]
    )
    log.info(
        "autofix_generate_done",
        review_id=state["review_id"],
        total=len(results),
        failed=sum(1 for p in results if p.status == PatchStatus.failed),
    )
    return {"patches": results}


async def validate_patches_node(state: AutoFixState) -> dict:
    """对未失败的 patch 做语法校验，补 diff 和最终 status。"""
    patches = state.get("patches", [])
    validated: list[PatchOutput] = []
    for p in patches:
        if p.status == PatchStatus.failed:
            validated.append(p)
            continue
        valid, err = await check_syntax(p.fixed_code, state["language"])
        diff = make_unified_diff(p.original_code, p.fixed_code)
        validated.append(p.model_copy(update={
            "diff": diff,
            "syntax_valid": valid,
            "error_msg": err,
            "status": PatchStatus.done if valid else PatchStatus.failed,
        }))
    log.info(
        "autofix_validate_done",
        review_id=state["review_id"],
        total=len(validated),
        invalid=sum(1 for p in validated if not p.syntax_valid),
    )
    return {"patches": validated}


async def merge_all_node(state: AutoFixState) -> dict:
    """generate + validate 之后再跑一次 LLM 综合所有 issue 产出 final patch。

    失败方案 A：LLM 异常 / 输出为空 / 无 issues / 无 final_rep_id → 不入库，
    静默返回原 patches。前端 filter is_final && done 自然不渲染。
    """
    issues = state["issues"]
    patches = state.get("patches", [])
    final_rep_id = state.get("final_rep_id")

    if not issues or not final_rep_id:
        return {"patches": patches}

    desc_block = "\n".join(f"- {i.description}" for i in issues)
    sug_lines = [f"- {i.suggestion}" for i in issues if i.suggestion]
    sug_block = "\n".join(sug_lines) if sug_lines else "(no specific suggestions)"

    messages = [
        SystemMessage(content=AUTOFIX_FINAL_SYSTEM_PROMPT),
        HumanMessage(content=build_autofix_final_prompt(
            language=state["language"],
            source_code=state["source_code"],
            all_issues_desc=desc_block,
            all_issues_suggestions=sug_block,
        )),
    ]

    llm = get_llm(temperature=0.0, tags=["autofix-final"])
    try:
        response = await llm.ainvoke(messages)
    except Exception as exc:
        log.warning("autofix_final_llm_error", review_id=state["review_id"], error=str(exc))
        return {"patches": patches}

    fixed = _extract_code(response.content or "")
    if not fixed:
        log.warning("autofix_final_empty_output", review_id=state["review_id"])
        return {"patches": patches}

    valid, err = await check_syntax(fixed, state["language"])
    if not valid:
        log.warning(
            "autofix_final_syntax_invalid",
            review_id=state["review_id"],
            error=err,
        )
        return {"patches": patches}

    diff = make_unified_diff(state["source_code"], fixed)
    final_patch = PatchOutput(
        issue_id=final_rep_id,
        original_code=state["source_code"],
        fixed_code=fixed,
        diff=diff,
        syntax_valid=True,
        error_msg=None,
        status=PatchStatus.done,
        is_final=True,
    )
    log.info(
        "autofix_final_done",
        review_id=state["review_id"],
        per_issue_count=len(patches),
    )
    return {"patches": [final_patch, *patches]}


# ── 图编译 ────────────────────────────────────────────────────────────────────

def build_autofix_graph() -> StateGraph:
    graph = StateGraph(AutoFixState)
    graph.add_node("generate", generate_patches_node)
    graph.add_node("validate", validate_patches_node)
    graph.add_node("merge_all", merge_all_node)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", "merge_all")
    graph.add_edge("merge_all", END)
    return graph


compiled_autofix_graph = build_autofix_graph().compile()
