"""add patches table

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "review_id",
            UUID(as_uuid=True),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "issue_id",
            UUID(as_uuid=True),
            sa.ForeignKey("issues.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("original_code", sa.Text, nullable=False),
        sa.Column("fixed_code", sa.Text, nullable=False),
        sa.Column("diff", sa.Text, nullable=False),
        sa.Column(
            "syntax_valid",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "done", "failed",
                name="patch_status_enum",
            ),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    op.drop_table("patches")
    op.execute("DROP TYPE IF EXISTS patch_status_enum")
