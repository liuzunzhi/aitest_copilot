"""add description to projects

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-15

02-projects AC-31 / AC-32：项目元信息补「简介」。
迁移只加列，不改既有数据。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "description",
            sa.String(length=500),
            nullable=True,
            comment="项目简介",
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "description")
