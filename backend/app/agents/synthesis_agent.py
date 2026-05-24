"""Synthesis Agent：合并三个专项 Agent 的输出，去重，生成执行摘要。"""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import get_llm
from app.agents.prompts import SYNTHESIS_SYSTEM_PROMPT, build_synthesis_prompt
from app.agents.state import IssueOutput, ReviewState
from app.core.logging import get_logger

log = get_logger(__name__)


async def synthesis_node(state: ReviewState) -> dict:
    """合并所有 Agent issues，去重，调用 LLM 生成 Markdown 摘要。"""
    raw_issues = state.get("issues", [])
    deduped = deduplicate_issues(raw_issues)

    issues_json = json.dumps(
        [i.model_dump() for i in deduped],
        ensure_ascii=False,
        indent=2,
    )

    messages = [
        SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
        HumanMessage(content=build_synthesis_prompt(
            state["source_code"], state["language"], issues_json
        )),
    ]
    # 标记 "synthesis" tag，review_task 用 astream_events 过滤此 tag 推流式 token
    llm = get_llm(temperature=0.3, tags=["synthesis"])
    accumulated = ""
    async for chunk in llm.astream(messages):
        accumulated += chunk.content

    log.info("synthesis_done", raw=len(raw_issues), deduped=len(deduped))
    # 只返回 report_text，不返回 issues。
    # issues 字段带 operator.add Reducer，若此处返回 deduped，Reducer 会再次追加
    # 导致 final_state["issues"] = 原始列表 + 去重列表，数据翻倍写入 DB。
    # 去重由 review_task.py 在写 DB 前统一执行（调用 _deduplicate）。
    return {"report_text": accumulated}


def deduplicate_issues(issues: list[IssueOutput]) -> list[IssueOutput]:
    """按 (file_path, line_start, category) 去重，保留 severity 最高的那条。

    paste 模式下 file_path 为 None，退化为 (line_start, category) 去重。
    """
    _SEVERITY_RANK = {"critical": 0, "warning": 1, "suggestion": 2}

    best: dict[tuple, IssueOutput] = {}
    for issue in issues:
        key = (
            issue.file_path or "",
            issue.line_start if issue.line_start is not None else -1,
            issue.category.value,
        )
        existing = best.get(key)
        if existing is None:
            best[key] = issue
        else:
            # 保留 severity 更高（数值更小）的那条
            if _SEVERITY_RANK[issue.severity.value] < _SEVERITY_RANK[existing.severity.value]:
                best[key] = issue

    # 按 severity 排序后返回
    return sorted(best.values(), key=lambda i: _SEVERITY_RANK[i.severity.value])
