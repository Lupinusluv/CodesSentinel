"""Unit tests for sandbox executor + validator.

零 DB 依赖：所有测试只对纯函数传字符串、断言返回值。
"""

import pytest

from app.sandbox.executor import check_syntax
from app.sandbox.validator import make_unified_diff, validate_patch


# ── check_syntax: Python ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_python_valid_code():
    code = "def foo(x: int) -> int:\n    return x + 1\n"
    valid, err = await check_syntax(code, "python")
    assert valid is True
    assert err is None


@pytest.mark.asyncio
async def test_python_invalid_code_returns_message():
    code = "def foo(:\n    return 1\n"  # 括号语法错
    valid, err = await check_syntax(code, "python")
    assert valid is False
    assert err is not None
    assert "SyntaxError" in err


@pytest.mark.asyncio
async def test_python_indent_error():
    code = "def foo():\nreturn 1\n"
    valid, err = await check_syntax(code, "python")
    assert valid is False
    assert err and "line" in err.lower()


@pytest.mark.asyncio
async def test_python_empty_string_is_valid():
    """空字符串在 ast 看来是合法的空模块，不应误报。"""
    valid, err = await check_syntax("", "python")
    assert valid is True
    assert err is None


@pytest.mark.asyncio
async def test_python_alias_py():
    valid, _ = await check_syntax("x = 1\n", "py")
    assert valid is True


# ── check_syntax: 未知语言降级 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_language_passes_through():
    """MVP 范围：不识别的语言不做校验，直接 (True, None)。"""
    valid, err = await check_syntax("anything <broken {", "rust")
    assert valid is True
    assert err is None


@pytest.mark.asyncio
async def test_blank_language_passes_through():
    valid, err = await check_syntax("foo bar", "")
    assert valid is True
    assert err is None


# ── validate_patch: 委托链路 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_patch_delegates_to_check_syntax():
    valid, err = await validate_patch(original="x = 1\n", fixed="x = 2\n", language="python")
    assert valid is True
    assert err is None


@pytest.mark.asyncio
async def test_validate_patch_catches_bad_fixed_code():
    valid, err = await validate_patch(original="x = 1\n", fixed="def f(:\n", language="python")
    assert valid is False
    assert err is not None


# ── make_unified_diff ─────────────────────────────────────────────────────────


def test_diff_identical_input_returns_empty():
    diff = make_unified_diff("foo\nbar\n", "foo\nbar\n")
    assert diff == ""


def test_diff_contains_added_removed_markers():
    original = "a\nb\nc\n"
    fixed = "a\nB\nc\n"
    diff = make_unified_diff(original, fixed)
    assert "---" in diff
    assert "+++" in diff
    assert "-b" in diff
    assert "+B" in diff


def test_diff_includes_filenames():
    diff = make_unified_diff("x\n", "y\n", from_file="orig.py", to_file="fix.py")
    assert "orig.py" in diff
    assert "fix.py" in diff


def test_diff_handles_no_trailing_newline():
    """splitlines(keepends=True) 应保留末尾无 \\n 的情况，不抛异常。"""
    diff = make_unified_diff("abc", "abd")
    assert "abc" in diff
    assert "abd" in diff
