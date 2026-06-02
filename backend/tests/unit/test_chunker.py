"""Unit tests for chunk_code in rag/chunker."""

from app.rag.chunker import chunk_code

PYTHON_CODE = """\
import os

API_KEY = "sk-1234"

def transfer(sender_id, amount):
    db.execute(f"UPDATE users SET balance={amount}")

async def refund(order_id):
    pass

class PaymentService:
    def process(self, order):
        return transfer(order.user_id, order.total)

    async def cancel(self, order):
        pass
"""

JS_CODE = """\
const SECRET = "abc";

function fetchUser(id) {
    return db.query(`SELECT * FROM users WHERE id=${id}`);
}

class UserService {
    async getAll() {
        return fetchUser(0);
    }
}
"""


def test_python_splits_functions_and_classes():
    chunks = chunk_code(PYTHON_CODE, "python")
    types = {c.symbol_type for c in chunks}
    names = {c.symbol_name for c in chunks}
    assert "function" in types
    assert "class" in types
    assert "transfer" in names
    assert "PaymentService" in names


def test_python_nested_methods_not_duplicated():
    chunks = chunk_code(PYTHON_CODE, "python")
    # PaymentService 的方法不应成为独立 chunk（嵌套在类内部，_walk 遇到类节点后不再递归）
    names = [c.symbol_name for c in chunks]
    assert "process" not in names
    assert "cancel" not in names


def test_python_line_numbers_are_1_based():
    chunks = chunk_code(PYTHON_CODE, "python")
    for chunk in chunks:
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line


def test_python_async_function_detected():
    chunks = chunk_code(PYTHON_CODE, "python")
    names = [c.symbol_name for c in chunks]
    assert "refund" in names


def test_javascript_splits_function_and_class():
    chunks = chunk_code(JS_CODE, "javascript")
    names = {c.symbol_name for c in chunks}
    assert "fetchUser" in names
    assert "UserService" in names


JS_FUNCTIONAL_CODE = """\
const add = (a, b) => a + b;

export const fetchAll = async () => {
    return db.query("SELECT 1");
};

const handler = function process(req) {
    return req.body;
};

const obj = {
    compute() {
        return [1, 2, 3].map(x => x * 2);
    },
};
"""


def test_js_named_arrow_gets_name():
    # const foo = () => … 的名字在父 variable_declarator 上，必须被取到
    chunks = chunk_code(JS_FUNCTIONAL_CODE, "javascript")
    names = {c.symbol_name for c in chunks}
    assert "add" in names
    assert "fetchAll" in names  # export 包裹也要穿透


def test_js_named_function_expression_gets_name():
    chunks = chunk_code(JS_FUNCTIONAL_CODE, "javascript")
    names = {c.symbol_name for c in chunks}
    assert "handler" in names


def test_js_object_method_gets_name():
    # method 名是 property_identifier，旧实现只认 identifier → 丢名
    chunks = chunk_code(JS_FUNCTIONAL_CODE, "javascript")
    names = {c.symbol_name for c in chunks}
    assert "compute" in names


def test_js_inline_callback_produces_no_empty_name_noise():
    # arr.map(x => …) 这类内联回调无 declarator 父节点，不应单独成块、不应产生空名 chunk
    code = "const add = (a, b) => a + b;\n[1, 2, 3].map(x => x * 2);\n"
    chunks = chunk_code(code, "javascript")
    names = [c.symbol_name for c in chunks]
    assert names == ["add"]


def test_unsupported_language_returns_single_chunk():
    code = 'fn main() { println!("hello"); }'
    chunks = chunk_code(code, "rust")
    assert len(chunks) == 1
    assert chunks[0].symbol_name is None
    assert chunks[0].content == code


def test_empty_code_returns_single_chunk():
    chunks = chunk_code("", "python")
    assert len(chunks) == 1


def test_code_with_no_functions_returns_single_chunk():
    code = "x = 1\ny = 2\nprint(x + y)\n"
    chunks = chunk_code(code, "python")
    assert len(chunks) == 1


def test_chunk_content_matches_source_lines():
    chunks = chunk_code(PYTHON_CODE, "python")
    lines = PYTHON_CODE.splitlines()
    for chunk in chunks:
        expected = "\n".join(lines[chunk.start_line - 1 : chunk.end_line])
        assert chunk.content == expected
