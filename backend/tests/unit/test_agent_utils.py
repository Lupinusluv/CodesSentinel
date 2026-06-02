"""Unit tests for parse_agent_json in agents.utils.

回归 B5：JSON 解析失败必须"有信号"。parse_agent_json 返回 (issues, ok) 二元组，
ok=False 时上游 Agent 才能把整类问题被吞掉的事实上报给前端。
"""

from app.agents.utils import parse_agent_json
from app.agents.state import IssueOutput
from app.models.issue import IssueCategory


def test_valid_json_array_returns_issues_and_true():
    text = (
        '[{"severity": "critical", "file_path": "a.py", "line_start": 1, '
        '"description": "SQL injection"}]'
    )
    issues, ok = parse_agent_json(text, "security", "security_agent")
    assert ok is True
    assert len(issues) == 1
    assert issues[0].category == IssueCategory.security
    assert issues[0].description == "SQL injection"


def test_empty_json_array_returns_empty_and_true():
    """空数组是合法解析结果（Agent 确实没发现问题），不是失败。"""
    issues, ok = parse_agent_json("[]", "style", "style_agent")
    assert ok is True
    assert issues == []


def test_invalid_json_returns_empty_and_false():
    issues, ok = parse_agent_json("not json at all {{{", "style", "style_agent")
    assert ok is False
    assert issues == []


def test_non_array_json_returns_empty_and_false():
    """合法 JSON 但不是数组（如对象）→ 视为失败，发信号。"""
    issues, ok = parse_agent_json('{"severity": "warning"}', "performance", "perf_agent")
    assert ok is False
    assert issues == []


def test_json_fence_wrapped_array_parses_and_true():
    text = "```json\n" '[{"severity": "warning", "description": "magic number"}]\n' "```"
    issues, ok = parse_agent_json(text, "style", "style_agent")
    assert ok is True
    assert len(issues) == 1
    assert issues[0].category == IssueCategory.style
