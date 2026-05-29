"""AST 级别代码分块器。

使用 tree-sitter 按函数/类边界切分，保证每个 chunk 语义完整。
目前支持 Python 和 JavaScript/TypeScript。
"""

from dataclasses import dataclass

import tree_sitter_javascript as tsjs
import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

_LANGUAGES: dict[str, Language] = {
    "python":     Language(tspython.language()),
    "javascript": Language(tsjs.language()),
    "typescript": Language(tsjs.language()),
}

# 作为分块边界的节点类型
_SPLIT_TYPES = {
    "function_definition",       # Python def
    "async_function_definition", # Python async def
    "class_definition",          # Python class
    "function_declaration",      # JS/TS function
    "method_definition",         # JS/TS method
    "class_declaration",         # JS/TS class
}

# JS/TS 函数本身匿名（arrow / function expression），名字挂在父 variable_declarator 上。
# 只在具名声明处切块（const foo = () => …），内联回调（arr.map(x => …)）因无
# declarator 父节点天然被排除，不再产生空名噪声 chunk。
_FUNC_VALUE_TYPES = {"arrow_function", "function_expression"}

# 取符号名的节点类型：identifier（Python def/class、JS function/变量名）、
# property_identifier（JS/TS method 名）。
_NAME_TYPES = {"identifier", "property_identifier"}


@dataclass
class Chunk:
    symbol_name: str | None
    symbol_type: str | None   # "function" | "class" | None
    content: str
    start_line: int           # 1-based
    end_line: int             # 1-based


def chunk_code(source_code: str, language: str) -> list[Chunk]:
    """将源代码按 AST 函数/类边界切分为 Chunk 列表。

    若语言不支持 AST 解析，退化为整段作为单个 chunk。
    """
    lang = _LANGUAGES.get(language.lower())
    if lang is None:
        return [Chunk(None, None, source_code, 1, source_code.count("\n") + 1)]

    parser = Parser(lang)
    tree = parser.parse(source_code.encode())
    source_lines = source_code.splitlines()

    chunks: list[Chunk] = []
    _walk(tree.root_node, source_lines, chunks, depth=0)

    # 若 AST 解析没找到任何顶层符号，整段作为单个 chunk
    if not chunks:
        return [Chunk(None, None, source_code, 1, len(source_lines))]

    return chunks


def _walk(node: Node, lines: list[str], chunks: list[Chunk], depth: int) -> None:
    if node.type in _SPLIT_TYPES:
        sym_type = "class" if "class" in node.type else "function"
        _append_chunk(node, _get_name(node), sym_type, lines, chunks)
        # 不继续递归子节点，避免嵌套函数产生重复 chunk
        return

    # 具名箭头/函数表达式：以整个 declarator 为 chunk（含 `foo = ` 前缀，
    # 保留变量名语境），名字取 declarator 的 identifier。
    if node.type == "variable_declarator" and _has_func_init(node):
        _append_chunk(node, _get_name(node), "function", lines, chunks)
        return

    for child in node.children:
        _walk(child, lines, chunks, depth + 1)


def _append_chunk(
    node: Node,
    name: str | None,
    sym_type: str,
    lines: list[str],
    chunks: list[Chunk],
) -> None:
    start = node.start_point[0]  # 0-based
    end = node.end_point[0]      # 0-based
    content = "\n".join(lines[start : end + 1])
    chunks.append(Chunk(
        symbol_name=name,
        symbol_type=sym_type,
        content=content,
        start_line=start + 1,
        end_line=end + 1,
    ))


def _has_func_init(node: Node) -> bool:
    """variable_declarator 的初始化值是否为箭头函数 / 函数表达式。"""
    return any(child.type in _FUNC_VALUE_TYPES for child in node.children)


def _get_name(node: Node) -> str | None:
    for child in node.children:
        if child.type in _NAME_TYPES:
            return child.text.decode() if child.text else None
    return None
