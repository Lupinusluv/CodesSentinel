"""embeddings._get_client 接线单测。

v0.5.1 根因：客户端误用 deepseek_* 字段去调 DashScope 的 text-embedding-v3，
DeepSeek 没有 embeddings 端点 → 生产 404，RAG 从未真正生效。本测试锁定
_get_client() 必须用 dashscope_api_key / dashscope_base_url 构造客户端。

纯接线断言，不打网络。
"""

from types import SimpleNamespace

from app.rag import embeddings


def test_get_client_uses_dashscope_credentials(monkeypatch):
    """_get_client 用 dashscope_* 字段（而非 deepseek_*）构造 AsyncOpenAI。"""
    fake = SimpleNamespace(
        dashscope_api_key="ds-fake-key",
        dashscope_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        deepseek_api_key="should-not-be-used",
        deepseek_base_url="https://api.deepseek.com/v1",
    )
    monkeypatch.setattr(embeddings, "get_settings", lambda: fake)
    monkeypatch.setattr(embeddings, "_client", None)

    client = embeddings._get_client()

    assert client.api_key == "ds-fake-key"
    assert str(client.base_url).rstrip("/") == fake.dashscope_base_url
