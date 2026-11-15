"""add rejected_at to project_applications

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-15

AC-22 的冷却期需要知道「上一次被驳回的时间」。`reviewed_at` 同时被通过
与驳回写入，不能代替，所以单独加一列。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_applications",
        sa.Column("rejected_at", mysql.DATETIME(fsp=3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_applications", "rejected_at")
