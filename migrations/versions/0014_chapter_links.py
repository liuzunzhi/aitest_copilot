"""create document_chapter_links

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-17

05-incremental 第二期（T71）：章节引用图。

一条边两种目标形态：章节（`to_chapter_id`）或实体名（`entity`），
Check 约束保证二选一。两条唯一键分别覆盖两种形态——MySQL 唯一索引
允许多个 NULL，所以章节边不会撞实体边。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}


def upgrade() -> None:
    op.create_table(
        "document_chapter_links",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("version_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("from_chapter_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "to_chapter_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="章节目标；与 entity 二选一",
        ),
        sa.Column("link_type", sa.String(length=24), nullable=False),
        sa.Column(
            "entity", sa.String(length=128), nullable=True, comment="实体目标（功能点 / 术语名）"
        ),
        sa.Column(
            "confidence",
            mysql.DECIMAL(3, 2),
            nullable=True,
            comment="规则抽取固定值；人工补链为空",
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_chlinks_version"
        ),
        sa.ForeignKeyConstraint(
            ["from_chapter_id"], ["document_chapters.id"], name="fk_chlinks_from"
        ),
        sa.ForeignKeyConstraint(
            ["to_chapter_id"], ["document_chapters.id"], name="fk_chlinks_to"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_chlinks_creator"),
        sa.CheckConstraint(
            "link_type IN ('references','depends_on','mentions_entity')",
            name="ck_chlinks_link_type",
        ),
        sa.CheckConstraint("source IN ('rule','manual')", name="ck_chlinks_source"),
        sa.CheckConstraint(
            "((to_chapter_id IS NOT NULL) <> (entity IS NOT NULL))",
            name="ck_chlinks_target",
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_chlinks_version", "document_chapter_links", ["version_id"])
    op.create_index("idx_chlinks_from", "document_chapter_links", ["from_chapter_id"])
    op.create_index("idx_chlinks_to", "document_chapter_links", ["to_chapter_id"])
    op.create_index(
        "uk_chlinks_to_chapter",
        "document_chapter_links",
        ["version_id", "from_chapter_id", "link_type", "to_chapter_id"],
        unique=True,
    )
    op.create_index(
        "uk_chlinks_entity",
        "document_chapter_links",
        ["version_id", "from_chapter_id", "link_type", "entity"],
        unique=True,
    )


def downgrade() -> None:
    # 直接删表：索引随表一起删，逐个 drop 会先撞外键依赖的索引。
    op.drop_table("document_chapter_links")
