"""混合检索：pgvector 余弦相似度。

为 paste 模式（无仓库上下文）提供降级处理，直接返回空字符串。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.code_chunk import CodeChunk
from app.rag.embeddings import embed_text

log = get_logger(__name__)

_TOP_K = 8
_MAX_CONTEXT_CHARS = 6000  # 拼接后传给 Agent 的最大字符数


async def retrieve_context(
    db: AsyncSession,
    query: str,
    repository_id: uuid.UUID | None,
    top_k: int = _TOP_K,
) -> str:
    """检索与 query 最相关的代码 chunk，拼接为上下文字符串。

    paste 模式（repository_id=None）直接返回空字符串。
    """
    if repository_id is None:
        return ""

    try:
        query_vec = await embed_text(query[:4000])
    except Exception as exc:
        # RAG 是增强项，不应让一次 embedding 失败毁掉整个审查
        log.warning("rag_embedding_failed", repository_id=str(repository_id), error=str(exc))
        return ""

    # pgvector 余弦距离（<=>），越小越相似
    stmt = (
        select(CodeChunk)
        .where(CodeChunk.repository_id == repository_id)
        .order_by(CodeChunk.embedding.op("<=>")(query_vec))
        .limit(top_k)
    )
    result = await db.execute(stmt)
    chunks = result.scalars().all()

    if not chunks:
        return ""

    parts: list[str] = []
    total = 0
    for chunk in chunks:
        header = f"# {chunk.file_path}"
        if chunk.symbol_name:
            header += f" :: {chunk.symbol_name}"
        if chunk.start_line:
            header += f" (L{chunk.start_line}–{chunk.end_line})"
        block = f"{header}\n{chunk.content}"

        if total + len(block) > _MAX_CONTEXT_CHARS:
            break
        parts.append(block)
        total += len(block)

    return "\n\n---\n\n".join(parts)
