"""create documents / document_versions / document_chapters / baseline_snapshots

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-15

03-documents 解析段（T45）。四张表一次性建好：

- `documents` 逻辑文档，项目内同名唯一；
- `document_versions` 每次上传一条，`active_key` 用 STORED 生成列
  `IF(status = 'active', document_id, NULL)` + 唯一索引，保证同文档仅一个生效版本
  （MySQL 无条件唯一索引，但允许多个 NULL，归档/作废互不冲突）；
- `document_chapters` 章节树，`seq` 在版本内唯一；
- `baseline_snapshots` 只增不改，`version_id` 唯一防止同版本重复建快照。

生成列必须建表时一并创建，所以这里不拆成多个迁移。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

ACTIVE_KEY_EXPR = "IF(status = 'active', document_id, NULL)"


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_documents_project"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_documents_creator"),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_documents_project_name", "documents", ["project_id", "name"], unique=True
    )

    op.create_table(
        "document_versions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("document_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("version_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column(
            "file_path", sa.String(length=500), nullable=False, comment="相对路径，不对外返回"
        ),
        sa.Column("file_size", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "chapter_count",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("uploaded_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "active_key",
            mysql.BIGINT(unsigned=True),
            sa.Computed(ACTIVE_KEY_EXPR, persisted=True),
            comment="生成列：active 时等于 document_id，其余为 NULL",
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_versions_document"
        ),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name="fk_versions_uploader"),
        sa.CheckConstraint(
            "status IN ('pending','active','archived','void')",
            name="ck_versions_status",
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_versions_doc_no", "document_versions", ["document_id", "version_no"], unique=True
    )
    op.create_index("uk_versions_active", "document_versions", ["active_key"], unique=True)

    op.create_table(
        "document_chapters",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("version_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("parent_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("seq", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("level", mysql.TINYINT(unsigned=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("char_count", mysql.INTEGER(unsigned=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_chapters_version"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["document_chapters.id"], name="fk_chapters_parent"
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_chapters_version_seq", "document_chapters", ["version_id", "seq"], unique=True
    )
    op.create_index("idx_chapters_parent", "document_chapters", ["parent_id"])

    op.create_table(
        "baseline_snapshots",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("version_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "version_no", mysql.INTEGER(unsigned=True), nullable=False, comment="项目内基线序号"
        ),
        sa.Column("chapter_count", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_baseline_project"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_baseline_version"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_baseline_creator"),
        **TABLE_OPTS,
    )
    op.create_index("uk_baseline_version", "baseline_snapshots", ["version_id"], unique=True)
    op.create_index(
        "uk_baseline_project_no", "baseline_snapshots", ["project_id", "version_no"], unique=True
    )


def downgrade() -> None:
    # 不逐个 drop_index：这些唯一索引同时承担外键的列索引，
    # 先删索引会报 1553（Cannot drop index needed in a foreign key constraint）。
    # 直接删表，索引随表一起消失。
    op.drop_table("baseline_snapshots")
    op.drop_table("document_chapters")
    op.drop_table("document_versions")
    op.drop_table("documents")
