import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Platform(str, enum.Enum):
    github = "github"
    gitlab = "gitlab"
    gitee = "gitee"


class Repository(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "repositories"

    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, name="platform_enum", create_type=False), nullable=False
    )
    url: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    reviews: Mapped[list["Review"]] = relationship(  # noqa: F821
        back_populates="repository",
        cascade="all, delete-orphan",
    )
