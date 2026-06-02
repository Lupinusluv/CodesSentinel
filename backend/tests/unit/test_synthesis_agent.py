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
        _issue("security", "critical", line_start=1),
        _issue("performance", "warning", line_start=5),
        _issue("style", "suggestion", line_start=10),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 3


def test_same_line_same_category_keeps_higher_severity():
    issues = [
        _issue("security", "warning", line_start=3),
        _issue("security", "critical", line_start=3),  # 同行同类，severity 更高
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 1
    assert result[0].severity == IssueSeverity.critical


def test_same_line_different_category_dissimilar_keeps_both():
    """跨类别同行，但描述语义不同 → 必须保留两条（lane-bleeding 护栏）。

    旧用例（test_same_line_different_category_keeps_both）断言"无论描述如何，跨类别同行
    都保留 2 条"。收敛后的档位 2 允许跨类别在描述相似时合并，故旧用例的默认同义描述
    ("desc" vs "desc") 会被并掉。改为显式给互不相似的描述，保住"异义不并"的真实意图。
    """
    issues = [
        _issue(
            "security",
            "critical",
            line_start=3,
            description="SQL injection via unsanitized user input",
        ),
        _issue(
            "performance",
            "warning",
            line_start=3,
            description="inefficient string concatenation in loop",
        ),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 2


def test_dedup_collapses_cross_category_adjacent_synonymous():
    """正向：跨类别 + 相邻行(|Δ|≤2) + 描述同义 → 合并 1 条，保留 critical。"""
    issues = [
        _issue(
            "security",
            "critical",
            line_start=41,
            file_path="a.py",
            description="SQL injection vulnerability",
        ),
        _issue(
            "style",
            "warning",
            line_start=42,
            file_path="a.py",
            description="SQL injection vulnerability here",
        ),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 1
    assert result[0].severity == IssueSeverity.critical


def test_same_category_far_lines_keeps_both():
    """反向护栏：同 file 同 category 但 |Δline|=10 → 保留 2 条（不超 ±2 安全带）。"""
    issues = [
        _issue(
            "security",
            "critical",
            line_start=10,
            file_path="a.py",
            description="hardcoded credential",
        ),
        _issue(
            "security",
            "warning",
            line_start=20,
            file_path="a.py",
            description="hardcoded credential",
        ),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 2


def test_cross_category_same_line_dissimilar_keeps_both():
    """反向护栏：跨类别同行但描述语义不同 → 保留 2 条（核心 lane-bleeding 防误并）。"""
    issues = [
        _issue(
            "security",
            "critical",
            line_start=42,
            file_path="a.py",
            description="SQL injection via string formatting",
        ),
        _issue(
            "performance",
            "warning",
            line_start=42,
            file_path="a.py",
            description="inefficient string concatenation",
        ),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 2


def test_whole_file_none_lines_dissimilar_keeps_both():
    """反向护栏：两条 line_start=None、同 file、描述不同 → 保留 2 条（不能因都 None 误并）。"""
    issues = [
        _issue(
            "security",
            "critical",
            line_start=None,
            file_path="a.py",
            description="missing input validation across module",
        ),
        _issue(
            "style",
            "warning",
            line_start=None,
            file_path="a.py",
            description="module lacks docstrings",
        ),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 2


def test_paste_mode_no_file_path():
    """paste 模式 file_path=None，退化为 (line_start, category) 去重。"""
    issues = [
        _issue("security", "warning", line_start=5, file_path=None),
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
    # 描述互不相似，避免相邻跨类别行被新去重算法合并——本用例只验排序，不验去重。
    issues = [
        _issue("style", "suggestion", line_start=1, description="missing type hints on function"),
        _issue("security", "critical", line_start=2, description="path traversal in file open"),
        _issue("performance", "warning", line_start=3, description="redundant database round trip"),
    ]
    result = deduplicate_issues(issues)
    severities = [i.severity.value for i in result]
    assert severities == ["critical", "warning", "suggestion"]


def test_empty_input():
    assert deduplicate_issues([]) == []


def test_line_start_none_not_confused_with_zero():
    """line_start=None 的 issue 不应和 line_start=0 的 issue 合并。"""
    issues = [
        _issue("security", "warning", line_start=None),
        _issue("security", "critical", line_start=None),
    ]
    result = deduplicate_issues(issues)
    assert len(result) == 1
    assert result[0].severity == IssueSeverity.critical
