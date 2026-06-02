"""Patch 校验工具：语法校验 + unified diff 生成。"""

import difflib

from app.sandbox.executor import check_syntax


async def validate_patch(original: str, fixed: str, language: str) -> tuple[bool, str | None]:
    """对修复后的代码做语法校验。

    保留独立 validator 入口是为将来增加更多 patch 级校验（语义 diff、必要
    替换是否生效等）留扩展点；当前 MVP 只委托给 executor.check_syntax。
    """
    return await check_syntax(fixed, language)


def make_unified_diff(
    original: str,
    fixed: str,
    *,
    from_file: str = "original",
    to_file: str = "fixed",
) -> str:
    """生成标准 unified diff 文本，前端直接喂给 Monaco DiffEditor 即可。"""
    original_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)
    diff_iter = difflib.unified_diff(
        original_lines,
        fixed_lines,
        fromfile=from_file,
        tofile=to_file,
        n=3,
    )
    return "".join(diff_iter)
