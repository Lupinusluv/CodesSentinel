import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Review(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reviews"

    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=True,
    )
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status_enum", create_type=False),
        nullable=False,
        default=ReviewStatus.pending,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_issues: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    repository: Mapped["Repository | None"] = relationship(  # noqa: F821
        back_populates="reviews"
    )
    issues: Mapped[list["Issue"]] = relationship(  # noqa: F821
        back_populates="review",
        cascade="all, delete-orphan",
    )
    patches: Mapped[list["Patch"]] = relationship(  # noqa: F821
        back_populates="review",
        cascade="all, delete-orphan",
    )
