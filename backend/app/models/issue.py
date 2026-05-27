import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IssueCategory(str, enum.Enum):
    security = "security"
    performance = "performance"
    style = "style"


class IssueSeverity(str, enum.Enum):
    critical = "critical"
    warning = "warning"
    suggestion = "suggestion"


class Issue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "issues"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[IssueCategory] = mapped_column(
        Enum(IssueCategory, name="issue_category_enum", create_type=False), nullable=False
    )
    severity: Mapped[IssueSeverity] = mapped_column(
        Enum(IssueSeverity, name="issue_severity_enum", create_type=False), nullable=False
    )
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    review: Mapped["Review"] = relationship(back_populates="issues")  # noqa: F821
    patches: Mapped[list["Patch"]] = relationship(  # noqa: F821
        back_populates="issue",
        cascade="all, delete-orphan",
    )
