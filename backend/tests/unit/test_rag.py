"""retriever 降级路径单测。

embedding 服务故障（如 DeepSeek 无 embeddings 端点 → 404）时，retrieve_context
必须优雅降级返回 ""，而不是让异常冒泡毁掉整个审查任务。这条路径此前零覆盖，
正是它在 v0.5.0 webhook 实战中让真实 review 崩掉（worker 抛 openai.NotFoundError 404）。

零 DB 依赖：异常在 pgvector 查询前就 return，db 传 mock 即可。
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.rag import retriever


@pytest.mark.asyncio
async def test_retrieve_context_degrades_when_embedding_fails(monkeypatch):
    """embed_text 抛异常时，retrieve_context 返回 "" 而不向上抛，且不触碰 DB。"""

    async def _boom(*args, **kwargs):
        raise RuntimeError("embeddings endpoint 404")

    monkeypatch.setattr(retriever, "embed_text", _boom)

    db = AsyncMock()
    result = await retriever.retrieve_context(db, "any code", uuid.uuid4())

    assert result == ""
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_context_paste_mode_returns_empty():
    """paste 模式（repository_id=None）直接返回 ""，不调 embedding、不触碰 DB。"""
    db = AsyncMock()
    result = await retriever.retrieve_context(db, "any code", None)

    assert result == ""
    db.execute.assert_not_called()
