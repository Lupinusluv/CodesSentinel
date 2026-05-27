import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PatchStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    failed = "failed"


class Patch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "patches"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
    )
    issue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=False,
    )

    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    fixed_code: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)

    syntax_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[PatchStatus] = mapped_column(
        Enum(PatchStatus, name="patch_status_enum", create_type=False),
        nullable=False,
        default=PatchStatus.pending,
    )

    review: Mapped["Review"] = relationship(back_populates="patches")  # noqa: F821
    issue: Mapped["Issue"] = relationship(back_populates="patches")  # noqa: F821
