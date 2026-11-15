"""create system_settings and audit_logs

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15

`key` 是 MySQL 保留字，建表时按标识符引用。
audit_logs 刻意不建外键，审计记录要在目标对象被删除后仍然留存。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("key"),
        **TABLE_OPTS,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("before_data", sa.JSON(), nullable=True),
        sa.Column("after_data", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_OPTS,
    )
    op.create_index("idx_audit_project", "audit_logs", ["project_id", "created_at"])
    op.create_index("idx_audit_actor", "audit_logs", ["actor_id", "created_at"])
    op.create_index("idx_audit_action", "audit_logs", ["action", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_action", table_name="audit_logs")
    op.drop_index("idx_audit_actor", table_name="audit_logs")
    op.drop_index("idx_audit_project", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("system_settings")
