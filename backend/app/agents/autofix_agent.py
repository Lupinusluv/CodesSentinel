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
from app.agents.prompts import AUTOFIX_SYSTEM_PROMPT, build_autofix_prompt
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
    """图内传递的 patch；status / diff / syntax_valid 在 validate 节点补全。"""

    issue_id: str
    original_code: str
    fixed_code: str
    diff: str = ""
    syntax_valid: bool = False
    error_msg: str | None = None
    status: PatchStatus = PatchStatus.pending


class AutoFixState(TypedDict):
    """图的共享状态。patches 由 generate 写入、validate 整段覆盖。"""

    review_id: str
    source_code: str
    language: str
    issues: list[IssueRef]
    patches: list[PatchOutput]
    error: str | None


# ── 工具 ──────────────────────────────────────────────────────────────────────

_FENCE_OPEN_RE = re.compile(r"^```[a-zA-Z0-9_+\-]*\s*\n?", re.MULTILINE)


def _extract_code(text: str) -> str:
    """剥离 LLM 输出中常见的 markdown fence，返回纯代码字符串。"""
    cleaned = text.strip()
    cleaned = _FENCE_OPEN_RE.sub("", cleaned, count=1)
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip("\n")


def _slice_source(source: str, line_start: int, line_end: int) -> str:
    """按 1-based 闭区间截取源码片段。"""
    lines = source.splitlines(keepends=True)
    if not lines:
        return ""
    start = max(1, line_start) - 1
    end = min(len(lines), line_end)
    if end <= start:
        return ""
    return "".join(lines[start:end])


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
    if issue.line_start is None or issue.line_end is None:
        return _failed_patch(issue.issue_id, reason="issue missing line range; skipped")

    original_snippet = _slice_source(source_code, issue.line_start, issue.line_end)
    if not original_snippet.strip():
        return _failed_patch(issue.issue_id, reason="line range yields empty snippet")

    messages = [
        SystemMessage(content=AUTOFIX_SYSTEM_PROMPT),
        HumanMessage(content=build_autofix_prompt(
            language=language,
            original_snippet=original_snippet,
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
            issue.issue_id, original=original_snippet, reason=f"LLM call failed: {exc}"
        )

    fixed = _extract_code(response.content or "")
    if not fixed:
        return _failed_patch(
            issue.issue_id, original=original_snippet, reason="LLM returned empty fix"
        )

    return PatchOutput(
        issue_id=issue.issue_id,
        original_code=original_snippet,
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


# ── 图编译 ────────────────────────────────────────────────────────────────────

def build_autofix_graph() -> StateGraph:
    graph = StateGraph(AutoFixState)
    graph.add_node("generate", generate_patches_node)
    graph.add_node("validate", validate_patches_node)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", END)
    return graph


compiled_autofix_graph = build_autofix_graph().compile()
