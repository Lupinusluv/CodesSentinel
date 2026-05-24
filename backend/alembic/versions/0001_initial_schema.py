"""initial schema — all tables + pgvector extension

Revision ID: 0001
Revises:
Create Date: 2026-05-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    # ── pgvector 扩展 ─────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── PostgreSQL 枚举类型 ───────────────────────────────────────────────────
    op.execute("CREATE TYPE platform_enum AS ENUM ('github', 'gitlab', 'gitee')")
    op.execute(
        "CREATE TYPE review_status_enum AS ENUM ('pending', 'running', 'done', 'failed')"
    )
    op.execute(
        "CREATE TYPE issue_category_enum AS ENUM ('security', 'performance', 'style')"
    )
    op.execute(
        "CREATE TYPE issue_severity_enum AS ENUM ('critical', 'warning', 'suggestion')"
    )

    # ── repositories ──────────────────────────────────────────────────────────
    op.create_table(
        "repositories",
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
            "platform",
            sa.Enum("github", "gitlab", "gitee", name="platform_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("url", sa.String(512), nullable=False, unique=True),
        sa.Column("webhook_secret", sa.String(128), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── reviews ───────────────────────────────────────────────────────────────
    op.create_table(
        "reviews",
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
            "repository_id",
            UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("pr_number", sa.Integer, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "done", "failed",
                name="review_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("total_issues", sa.Integer, nullable=False, server_default="0"),
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("source_code", sa.Text, nullable=True),
        sa.Column("head_sha", sa.String(64), nullable=True),
        sa.Column("report_text", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    # ── issues ────────────────────────────────────────────────────────────────
    op.create_table(
        "issues",
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
        ),
        sa.Column(
            "category",
            sa.Enum(
                "security", "performance", "style",
                name="issue_category_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "critical", "warning", "suggestion",
                name="issue_severity_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("line_start", sa.Integer, nullable=True),
        sa.Column("line_end", sa.Integer, nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("suggestion", sa.Text, nullable=True),
        sa.Column(
            "fixed", sa.Boolean, nullable=False, server_default=sa.false()
        ),
    )

    # ── code_chunks ───────────────────────────────────────────────────────────
    op.create_table(
        "code_chunks",
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
            "repository_id",
            UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("symbol_name", sa.String(256), nullable=True),
        sa.Column("symbol_type", sa.String(32), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("start_line", sa.Integer, nullable=True),
        sa.Column("end_line", sa.Integer, nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("code_chunks")
    op.drop_table("issues")
    op.drop_table("reviews")
    op.drop_table("repositories")
    op.execute("DROP TYPE IF EXISTS issue_severity_enum")
    op.execute("DROP TYPE IF EXISTS issue_category_enum")
    op.execute("DROP TYPE IF EXISTS review_status_enum")
    op.execute("DROP TYPE IF EXISTS platform_enum")
