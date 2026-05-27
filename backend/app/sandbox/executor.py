"""轻量沙箱：仅做 AST 语法校验，不执行用户代码。

MVP 范围内只关心生成的修复代码"能不能解析"，不验证语义、不跑测试。
"""

import ast
import asyncio
import os
import tempfile

from app.core.logging import get_logger

log = get_logger(__name__)

_PY_LANGS = {"python", "py"}
_JS_LANGS = {"javascript", "js", "jsx"}
_TS_LANGS = {"typescript", "ts", "tsx"}


async def check_syntax(code: str, language: str) -> tuple[bool, str | None]:
    """对修复后的代码做语法校验，返回 (is_valid, error_message)。

    - Python：ast.parse 捕获 SyntaxError
    - JS/JSX：node --check 子进程
    - TS/TSX：node --check 同样尝试一遍；TS 专属语法会失败属预期，调用方据此降级
    - 其他语言：MVP 不做校验，直接通过
    """
    lang = (language or "").lower().strip()
    if lang in _PY_LANGS:
        return _check_python(code)
    if lang in _JS_LANGS or lang in _TS_LANGS:
        return await _check_node(code, lang)
    return True, None


def _check_python(code: str) -> tuple[bool, str | None]:
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as exc:
        line = exc.lineno if exc.lineno is not None else "?"
        return False, f"SyntaxError: {exc.msg} (line {line})"


async def _check_node(code: str, lang: str) -> tuple[bool, str | None]:
    suffix = ".ts" if lang in _TS_LANGS else ".js"
    # delete=False 是为了让子进程能在 Windows 上读到文件；finally 里手动删
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    )
    try:
        tmp.write(code)
        tmp.close()
        try:
            proc = await asyncio.create_subprocess_exec(
                "node", "--check", tmp.name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            # node 不在 PATH，MVP 不强制依赖，降级为通过
            log.warning("node_not_available_for_syntax_check", language=lang)
            return True, None
        _, stderr = await proc.communicate()
        if proc.returncode == 0:
            return True, None
        msg = stderr.decode("utf-8", errors="replace").strip() or "node syntax check failed"
        return False, msg
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
