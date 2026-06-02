"""Synthesis Agent：合并三个专项 Agent 的输出，去重，生成执行摘要。"""

import json
import re

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
        HumanMessage(
            content=build_synthesis_prompt(state["source_code"], state["language"], issues_json)
        ),
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


_SEVERITY_RANK = {"critical": 0, "warning": 1, "suggestion": 2}

# 跨类别合并的描述相似度阈值；低于此不并，避免把"同一行的 SQL 注入 + 字符串拼接低效"
# 这类真不同的问题误并（lane-bleeding）。0.6 是经验值：同义改写通常远超此值。
_DESC_JACCARD_THRESHOLD = 0.6

# 同类别相邻行的安全带：diff 行号 vs 绝对行号常差 ±1，取 ±2 留余量；不取 ≤5 以免把相邻
# 独立函数/语句的问题并掉。
_LINE_ADJACENCY = 2


def _normalize_tokens(text: str) -> set[str]:
    """归一化描述为 token 集合：转小写、按非字母数字切分、滤空。"""
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def _descriptions_similar(a: str, b: str) -> bool:
    """描述是否相似：归一化后 token Jaccard ≥ 阈值，或一方是另一方子串。"""
    na, nb = a.strip().lower(), b.strip().lower()
    if na and nb and (na in nb or nb in na):
        return True
    ta, tb = _normalize_tokens(a), _normalize_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return union > 0 and inter / union >= _DESC_JACCARD_THRESHOLD


def _lines_adjacent(a: IssueOutput, b: IssueOutput) -> bool:
    """两条 issue 行号是否相邻（|Δ|≤2）。任一为 None（whole-file）时不视为相邻。"""
    if a.line_start is None or b.line_start is None:
        return False
    return abs(a.line_start - b.line_start) <= _LINE_ADJACENCY


def _should_merge(a: IssueOutput, b: IssueOutput) -> bool:
    """判断同 file 的两条 issue 是否应合并。a 为已收录的代表，b 为新进来的候选。

    档位 1（零误并，无条件）：同 category + 相邻行 → 合并。
    档位 2（跨类别，需约束）：仅当描述相似（Jaccard 或子串）才合并；行号信息不足以跨类别
        判同，否则会把"同一行的两个真不同问题"误并。whole-file（line_start=None）的两条也
        只在描述相似时合并，异义不并。
    """
    whole_file = a.line_start is None or b.line_start is None
    if a.category == b.category:
        # 同类别有行号：相邻即并（档位 1，零误并）。
        if not whole_file:
            return _lines_adjacent(a, b)
        # 同类别但 whole-file：退化为按 file 聚合，仍要求描述相似，避免把模块级两个不同
        # 问题误并（异义不并）。
        return _descriptions_similar(a.description, b.description)
    # 跨类别（档位 2，需约束）：whole-file 仅凭描述相似；有行号时必须相邻且描述相似——行号
    # 信息不足以跨类别判同，相隔较远的两个跨类别问题即便措辞偶然相似也应各留一条。
    if whole_file:
        return _descriptions_similar(a.description, b.description)
    return _lines_adjacent(a, b) and _descriptions_similar(a.description, b.description)


def deduplicate_issues(issues: list[IssueOutput]) -> list[IssueOutput]:
    """合并语义重复的 issue，保留 severity 最高的那条，按 severity 稳定排序返回。

    收敛规格（见 docs/audit-2026-06-02-arch-test.md §3 P0①）：
    - 仅在同 file_path 内比较（None 视作同一组 ""）。
    - 档位 1：同 category + |Δline|≤2 → 无条件合并。
    - 档位 2：跨 category 或 whole-file → 仅当 description 文本相似才合并。
    - 不做区间相交（line_end 常 None / 乱填）。
    """
    # 单遍线性聚类：每条 issue 尝试并入已有代表，否则自成一组。保持代表为当前 severity 最
    # 高的一条；同时保留首次出现顺序以保证稳定排序。
    reps: list[IssueOutput] = []
    for issue in issues:
        merged = False
        for idx, rep in enumerate(reps):
            same_file = (rep.file_path or "") == (issue.file_path or "")
            if same_file and _should_merge(rep, issue):
                if _SEVERITY_RANK[issue.severity.value] < _SEVERITY_RANK[rep.severity.value]:
                    reps[idx] = issue
                merged = True
                break
        if not merged:
            reps.append(issue)

    # stable 排序：仅按 severity 排序，同 severity 内保持收录顺序（Python sort 稳定）。
    return sorted(reps, key=lambda i: _SEVERITY_RANK[i.severity.value])
