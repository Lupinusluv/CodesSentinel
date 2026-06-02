"""Unit tests for _group_issues_by_range (autofix_task).

零 DB 依赖：用 SimpleNamespace 鸭子类型模拟 Issue。函数只读取
id / line_start / line_end / severity / description / suggestion 这几个属性。
"""

import uuid
from types import SimpleNamespace

from app.tasks.autofix_task import _group_issues_by_range


def _issue(
    *,
    line_start: int | None,
    line_end: int | None,
    severity: str,
    description: str = "issue",
    suggestion: str | None = None,
    issue_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(issue_id) if issue_id else uuid.uuid4(),
        line_start=line_start,
        line_end=line_end,
        severity=SimpleNamespace(value=severity),
        description=description,
        suggestion=suggestion,
    )


# ── 基本聚合行为 ──────────────────────────────────────────────────────────────


def test_empty_input_returns_empty():
    refs, reps, _grep = _group_issues_by_range([])
    assert refs == []
    assert reps == {}


def test_single_issue_yields_one_group():
    i = _issue(line_start=10, line_end=12, severity="warning", description="bad")
    refs, reps, _grep = _group_issues_by_range([i])
    assert len(refs) == 1
    assert refs[0].issue_id == str(i.id)
    assert refs[0].description == "bad"  # 单条不加 bullet 前缀
    assert refs[0].line_start == 10
    assert refs[0].line_end == 12
    assert reps == {str(i.id): [str(i.id)]}


def test_two_distinct_ranges_stay_separate():
    a = _issue(line_start=1, line_end=1, severity="warning")
    b = _issue(line_start=5, line_end=5, severity="warning")
    refs, reps, _grep = _group_issues_by_range([a, b])
    assert len(refs) == 2
    assert {r.issue_id for r in refs} == {str(a.id), str(b.id)}


# ── representative 选举：severity 优先级 ───────────────────────────────────────


def test_same_range_picks_critical_as_representative():
    s = _issue(line_start=3, line_end=3, severity="suggestion", description="s-desc")
    c = _issue(line_start=3, line_end=3, severity="critical", description="c-desc")
    w = _issue(line_start=3, line_end=3, severity="warning", description="w-desc")
    refs, reps, _grep = _group_issues_by_range([s, c, w])
    assert len(refs) == 1
    assert refs[0].issue_id == str(c.id)
    # 全部三条都挂在 critical 的 rep 下
    members = set(reps[str(c.id)])
    assert members == {str(s.id), str(c.id), str(w.id)}


def test_warning_preferred_over_suggestion_when_no_critical():
    s = _issue(line_start=7, line_end=7, severity="suggestion")
    w = _issue(line_start=7, line_end=7, severity="warning")
    refs, reps, _grep = _group_issues_by_range([s, w])
    assert refs[0].issue_id == str(w.id)


# ── description / suggestion 合并 ─────────────────────────────────────────────


def test_merged_description_uses_bullet_lines():
    a = _issue(line_start=2, line_end=2, severity="warning", description="alpha")
    b = _issue(line_start=2, line_end=2, severity="critical", description="beta")
    refs, _, _grep = _group_issues_by_range([a, b])
    # critical 排前面（rep），warning 在后；都以 "- " 开头
    desc = refs[0].description
    assert desc.startswith("- ")
    assert "alpha" in desc and "beta" in desc
    assert desc.count("\n") == 1


def test_suggestion_takes_first_non_empty():
    a = _issue(line_start=4, line_end=4, severity="critical", suggestion=None)
    b = _issue(line_start=4, line_end=4, severity="warning", suggestion="do this")
    c = _issue(line_start=4, line_end=4, severity="warning", suggestion="or that")
    refs, _, _grep = _group_issues_by_range([a, b, c])
    # critical 是 rep，但它 suggestion 为 None；应回退到下一个非空
    assert refs[0].suggestion == "do this"


# ── None 行号归一 ────────────────────────────────────────────────────────────


def test_none_line_range_all_grouped_together():
    a = _issue(line_start=None, line_end=None, severity="warning", description="a")
    b = _issue(line_start=None, line_end=None, severity="critical", description="b")
    refs, reps, _grep = _group_issues_by_range([a, b])
    assert len(refs) == 1  # 都归到 (-1, -1)
    assert refs[0].issue_id == str(b.id)
    assert set(reps[str(b.id)]) == {str(a.id), str(b.id)}


def test_none_line_does_not_merge_with_numeric_range():
    a = _issue(line_start=None, line_end=None, severity="warning")
    b = _issue(line_start=1, line_end=1, severity="warning")
    refs, _, _grep = _group_issues_by_range([a, b])
    assert len(refs) == 2


# ── severity 容错：原始字符串而非 Enum ────────────────────────────────────────


def test_severity_as_plain_string_still_works():
    """防御性：万一传进来的不是 Enum 而是已经取过 .value 的 str，也应能排序。"""
    a = SimpleNamespace(
        id=uuid.uuid4(),
        line_start=1,
        line_end=1,
        severity="suggestion",
        description="s",
        suggestion=None,
    )
    b = SimpleNamespace(
        id=uuid.uuid4(),
        line_start=1,
        line_end=1,
        severity="critical",
        description="c",
        suggestion=None,
    )
    refs, _, _grep = _group_issues_by_range([a, b])
    assert refs[0].issue_id == str(b.id)


# ── global_rep_id：跨 group 选 severity 最高的那条 ─────────────────────────────


def test_global_rep_id_is_none_for_empty_input():
    _, _, grep = _group_issues_by_range([])
    assert grep is None


def test_global_rep_id_is_critical_across_groups():
    """不同行 group 之间也要按 severity 选全局 rep。"""
    line1_warn = _issue(line_start=1, line_end=1, severity="warning")
    line5_crit = _issue(line_start=5, line_end=5, severity="critical")
    line9_sug = _issue(line_start=9, line_end=9, severity="suggestion")
    _, _, grep = _group_issues_by_range([line1_warn, line5_crit, line9_sug])
    assert grep == str(line5_crit.id)


def test_global_rep_id_single_issue_is_itself():
    only = _issue(line_start=2, line_end=4, severity="warning")
    _, _, grep = _group_issues_by_range([only])
    assert grep == str(only.id)
