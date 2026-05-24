"""Unit tests for deduplicate_issues in synthesis_agent."""

from app.agents.synthesis_agent import deduplicate_issues
from app.agents.state import IssueOutput
from app.models.issue import IssueCategory, IssueSeverity


def _issue(
    category: str,
    severity: str,
    line_start: int | None = None,
    file_path: str | None = None,
    description: str = "desc",
) -> IssueOutput:
    return IssueOutput(
        category=IssueCategory(category),
        severity=IssueSeverity(severity),
        file_path=file_path,
        line_start=line_start,
        description=description,
    )


def test_no_duplicates_returns_all():
    issues = [
        _issue("security",    "critical",    line_start=1),
        _issue("performance", "warning",     line_start=5),
        _issue("style",       "suggestion",  line_start=10),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 3


def test_same_line_same_category_keeps_higher_severity():
    issues = [
        _issue("security", "warning",  line_start=3),
        _issue("security", "critical", line_start=3),  # 同行同类，severity 更高
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 1
    assert result[0].severity == IssueSeverity.critical


def test_same_line_different_category_keeps_both():
    issues = [
        _issue("security",    "critical", line_start=3),
        _issue("performance", "warning",  line_start=3),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 2


def test_paste_mode_no_file_path():
    """paste 模式 file_path=None，退化为 (line_start, category) 去重。"""
    issues = [
        _issue("security", "warning",  line_start=5, file_path=None),
        _issue("security", "critical", line_start=5, file_path=None),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 1
    assert result[0].severity == IssueSeverity.critical


def test_different_files_same_line_not_deduplicated():
    issues = [
        _issue("security", "critical", line_start=3, file_path="a.py"),
        _issue("security", "critical", line_start=3, file_path="b.py"),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 2


def test_output_sorted_by_severity():
    issues = [
        _issue("style",       "suggestion", line_start=1),
        _issue("security",    "critical",   line_start=2),
        _issue("performance", "warning",    line_start=3),
    ]
    result = deduplicate_issues(issues)
    severities = [i.severity.value for i in result]
    assert severities == ["critical", "warning", "suggestion"]


def test_empty_input():
    assert deduplicate_issues([]) == []


def test_line_start_none_not_confused_with_zero():
    """line_start=None 的 issue 不应和 line_start=0 的 issue 合并。"""
    issues = [
        _issue("security", "warning",  line_start=None),
        _issue("security", "critical", line_start=None),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 1
    assert result[0].severity == IssueSeverity.critical
