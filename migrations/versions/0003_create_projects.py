"""create projects and project_members

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15

project_members 使用复合主键 (project_id, user_id)，不设代理主键。
FK 与 CHECK 均手写并显式命名，保证与 ORM 模型一致。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_projects_status"),
        **TABLE_OPTS,
    )

    op.create_table(
        "project_members",
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "joined_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_members_project"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_members_user"),
        sa.CheckConstraint(
            "role IN ('project_admin','member','guest')", name="ck_members_role"
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_members_user", "project_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_members_user", table_name="project_members")
    op.drop_table("project_members")
    op.drop_table("projects")
