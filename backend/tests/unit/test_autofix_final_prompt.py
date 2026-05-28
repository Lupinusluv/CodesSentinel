"""Unit tests for AUTOFIX_FINAL prompt builder.

零依赖：只看 prompt 字符串拼接是否符合预期。
"""

from app.agents.prompts import (
    AUTOFIX_FINAL_SYSTEM_PROMPT,
    build_autofix_final_prompt,
)


def test_system_prompt_mentions_consolidated_fix():
    """system prompt 要明确告诉 LLM 这是综合修复，不是单 issue。"""
    assert "consolidated" in AUTOFIX_FINAL_SYSTEM_PROMPT.lower()
    assert "every issue" in AUTOFIX_FINAL_SYSTEM_PROMPT.lower()


def test_system_prompt_demands_full_file_output():
    """避免 LLM 只输出 diff / patch。"""
    sp = AUTOFIX_FINAL_SYSTEM_PROMPT.lower()
    assert "complete" in sp or "entire" in sp
    assert "fenced code block" in sp


def test_user_prompt_contains_all_issue_descriptions():
    desc_block = "- SQL injection on line 5\n- Hardcoded secret on line 12"
    p = build_autofix_final_prompt(
        language="python",
        source_code="x = 1\n",
        all_issues_desc=desc_block,
        all_issues_suggestions="(no specific suggestions)",
    )
    assert "SQL injection on line 5" in p
    assert "Hardcoded secret on line 12" in p


def test_user_prompt_contains_all_suggestions_when_provided():
    sug_block = "- use parameterized query\n- read secret from env"
    p = build_autofix_final_prompt(
        language="python",
        source_code="x = 1\n",
        all_issues_desc="- d1\n- d2",
        all_issues_suggestions=sug_block,
    )
    assert "parameterized query" in p
    assert "read secret from env" in p


def test_user_prompt_falls_back_when_no_suggestions():
    p = build_autofix_final_prompt(
        language="python",
        source_code="x = 1\n",
        all_issues_desc="- d1",
        all_issues_suggestions="(no specific suggestions)",
    )
    assert "(no specific suggestions)" in p


def test_user_prompt_contains_full_source_in_fenced_block():
    src = "def foo():\n    pass\n"
    p = build_autofix_final_prompt(
        language="python",
        source_code=src,
        all_issues_desc="- d",
        all_issues_suggestions="(none)",
    )
    assert "```python" in p
    assert src in p


def test_user_prompt_language_propagated_to_fence_tag():
    p = build_autofix_final_prompt(
        language="javascript",
        source_code="const x = 1;",
        all_issues_desc="- d",
        all_issues_suggestions="(none)",
    )
    assert "```javascript" in p
