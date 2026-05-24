"""全量仓库代码索引到 pgvector。

扫描仓库目录下所有支持的源文件，分块后向量化，批量写入 code_chunks 表。
"""

import uuid
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.rag.chunker import chunk_code
from app.rag.embeddings import embed_texts

_SUPPORTED_SUFFIXES: dict[str, str] = {
    ".py":  "python",
    ".js":  "javascript",
    ".ts":  "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
}

_EMBED_BATCH = 32   # 每批 embedding 调用的最大 chunk 数


async def index_repository(
    db: AsyncSession,
    repository_id: uuid.UUID,
    repo_path: Path,
) -> int:
    """索引整个仓库目录。

    先删除该仓库的旧 chunks，再重新扫描、分块、向量化、写入。
    返回写入的 chunk 数量。
    """
    await db.execute(delete(CodeChunk).where(CodeChunk.repository_id == repository_id))

    chunks_to_insert: list[CodeChunk] = []

    for file_path in repo_path.rglob("*"):
        if not file_path.is_file():
            continue
        language = _SUPPORTED_SUFFIXES.get(file_path.suffix.lower())
        if language is None:
            continue

        try:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        rel_path = str(file_path.relative_to(repo_path))
        chunks = chunk_code(source, language)

        # 批量 embedding
        for batch_start in range(0, len(chunks), _EMBED_BATCH):
            batch = chunks[batch_start : batch_start + _EMBED_BATCH]
            embeddings = await embed_texts([c.content for c in batch])

            for chunk, embedding in zip(batch, embeddings):
                chunks_to_insert.append(CodeChunk(
                    repository_id=repository_id,
                    file_path=rel_path,
                    symbol_name=chunk.symbol_name,
                    symbol_type=chunk.symbol_type,
                    content=chunk.content,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    embedding=embedding,
                ))

    db.add_all(chunks_to_insert)
    await db.commit()
    return len(chunks_to_insert)
