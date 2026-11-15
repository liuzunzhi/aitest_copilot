"""baseline

建立迁移链起点，不含任何表结构变更。

Revision ID: 0001
Revises:
Create Date: 2026-11-15

"""
from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
