"""Embedding 模型封装。

复用 DeepSeek /embeddings 端点（OpenAI 格式兼容），批量处理文本列表。
"""

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.models.code_chunk import EMBEDDING_DIM

_client: AsyncOpenAI | None = None

# DeepSeek embedding 模型名
_EMBED_MODEL = "text-embedding-v3"


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncOpenAI(api_key=s.deepseek_api_key, base_url=s.deepseek_base_url)
    return _client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """将文本列表批量转为向量，返回与输入等长的 embedding 列表。"""
    if not texts:
        return []

    client = _get_client()
    response = await client.embeddings.create(
        model=_EMBED_MODEL,
        input=texts,
        dimensions=EMBEDDING_DIM,
    )
    # 按 index 排序保证顺序
    items = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in items]


async def embed_text(text: str) -> list[float]:
    """单文本 embedding，供 retriever 查询使用。"""
    results = await embed_texts([text])
    return results[0]
