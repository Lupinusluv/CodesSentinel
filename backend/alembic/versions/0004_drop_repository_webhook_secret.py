"""drop repositories.webhook_secret

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-02

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("repositories", "webhook_secret")


def downgrade() -> None:
    # nullable=True：回滚时已有行无值，NOT NULL 会撞已存在数据。
    op.add_column(
        "repositories",
        sa.Column("webhook_secret", sa.String(length=128), nullable=True),
    )
