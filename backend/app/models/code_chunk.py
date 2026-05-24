import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# DeepSeek text-embedding-v3 输出维度
EMBEDDING_DIM = 1024


class CodeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """AST 级别代码分块，按函数/类边界切分后存储到 pgvector。"""

    __tablename__ = "code_chunks"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    symbol_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    symbol_type: Mapped[str | None] = mapped_column(String(32), nullable=True)   # "function" | "class"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int | None] = mapped_column(nullable=True)
    end_line: Mapped[int | None] = mapped_column(nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
