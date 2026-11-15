"""create access_tokens and project_applications

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15

MySQL 不支持条件唯一索引，project_applications 用 STORED 生成列
`pending_key` + 唯一索引替代「同一项目仅一条 pending」的约束。
生成列必须建表时一并创建，不能后续 ALTER 追加索引表达式。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

PENDING_KEY_EXPR = "IF(status = 'pending', CONCAT(project_id, ':', applicant_id), NULL)"


def upgrade() -> None:
    op.create_table(
        "access_tokens",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "token_hash",
            mysql.CHAR(length=64, charset="ascii", collation="ascii_bin"),
            nullable=False,
            comment="sha256 十六进制",
        ),
        sa.Column(
            "issued_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column("expires_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True, comment="IPv4/IPv6"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_tokens_user"),
        **TABLE_OPTS,
    )
    op.create_index("uk_tokens_hash", "access_tokens", ["token_hash"], unique=True)
    op.create_index("idx_tokens_user", "access_tokens", ["user_id", "revoked_at"])
    op.create_index("idx_tokens_exp", "access_tokens", ["expires_at"])

    op.create_table(
        "project_applications",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("applicant_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("desired_role", sa.String(length=16), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("reviewer_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("closed_reason", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column(
            "pending_key",
            sa.String(length=64),
            sa.Computed(PENDING_KEY_EXPR, persisted=True),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_app_project"),
        sa.ForeignKeyConstraint(["applicant_id"], ["users.id"], name="fk_app_user"),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','withdrawn','closed')",
            name="ck_app_status",
        ),
        sa.CheckConstraint("desired_role IN ('member','guest')", name="ck_app_role"),
        **TABLE_OPTS,
    )
    op.create_index("uk_app_pending", "project_applications", ["pending_key"], unique=True)
    op.create_index(
        "idx_app_project", "project_applications", ["project_id", "status"]
    )
    op.create_index(
        "idx_app_applicant", "project_applications", ["applicant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_app_applicant", table_name="project_applications")
    op.drop_index("idx_app_project", table_name="project_applications")
    op.drop_index("uk_app_pending", table_name="project_applications")
    op.drop_table("project_applications")

    op.drop_index("idx_tokens_exp", table_name="access_tokens")
    op.drop_index("idx_tokens_user", table_name="access_tokens")
    op.drop_index("uk_tokens_hash", table_name="access_tokens")
    op.drop_table("access_tokens")
