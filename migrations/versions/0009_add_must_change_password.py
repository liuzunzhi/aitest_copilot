"""add must_change_password to users

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-15

管理员重置密码改为「随机强密码 + 强制首登修改」（spec 待确认 4）：
登录仍签发令牌，但在改密前除改密接口外一律 403 PASSWORD_CHANGE_REQUIRED。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="管理员重置后强制改密",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
