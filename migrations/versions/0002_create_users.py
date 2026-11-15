"""create users

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-15

CHECK 约束与索引名均为手写——Alembic autogenerate 不识别 CHECK。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column(
            "password_hash", sa.String(length=100), nullable=False, comment="bcrypt"
        ),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column(
            "global_role",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
        sa.Column(
            "failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("locked_until", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "password_changed_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_users_status"),
        sa.CheckConstraint("global_role IN ('user','system_admin')", name="ck_users_role"),
        mysql_default_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )

    # 三个唯一索引靠 utf8mb4_0900_ai_ci 实现大小写不敏感去重，
    # 因此不建 lower() 函数索引。
    op.create_index("uk_users_username", "users", ["username"], unique=True)
    op.create_index("uk_users_email", "users", ["email"], unique=True)
    op.create_index("uk_users_phone", "users", ["phone"], unique=True)


def downgrade() -> None:
    op.drop_index("uk_users_phone", table_name="users")
    op.drop_index("uk_users_email", table_name="users")
    op.drop_index("uk_users_username", table_name="users")
    op.drop_table("users")
