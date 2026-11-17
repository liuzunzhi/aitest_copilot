"""章节引用图模型（05-incremental 第二期 · 2b-3 图传播）。

一条边表示「源章节」引用 / 依赖「目标章节」，或提及某个实体名（功能点 / 术语）。
目标二选一：`to_chapter_id` 指向同版本的章节，`entity` 存实体名，不允许同时有值。

MySQL 允许唯一索引上出现多个 NULL，所以两条唯一键分别管章节目标与实体目标：
`uk_chlinks_to_chapter` 在 `to_chapter_id IS NULL` 时不约束，
`uk_chlinks_entity` 在 `entity IS NULL` 时不约束，互不干扰。

规则抽取的边 `source='rule'`，每次重抽按 `(version_id, source='rule')` 先删后插；
人工补链的边 `source='manual'`，不受重抽影响。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

CHAPTER_LINK_TYPES = ("references", "depends_on", "mentions_entity")
CHAPTER_LINK_SOURCES = ("rule", "manual")


class DocumentChapterLink(Base):
    """章节引用图的一条边。"""

    __tablename__ = "document_chapter_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_chlinks_version"
        ),
        ForeignKeyConstraint(
            ["from_chapter_id"], ["document_chapters.id"], name="fk_chlinks_from"
        ),
        ForeignKeyConstraint(
            ["to_chapter_id"], ["document_chapters.id"], name="fk_chlinks_to"
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_chlinks_creator"),
        Index("idx_chlinks_version", "version_id"),
        Index("idx_chlinks_from", "from_chapter_id"),
        Index("idx_chlinks_to", "to_chapter_id"),
        Index(
            "uk_chlinks_to_chapter",
            "version_id",
            "from_chapter_id",
            "link_type",
            "to_chapter_id",
            unique=True,
        ),
        Index(
            "uk_chlinks_entity",
            "version_id",
            "from_chapter_id",
            "link_type",
            "entity",
            unique=True,
        ),
        CheckConstraint(
            "link_type IN ('references','depends_on','mentions_entity')",
            name="ck_chlinks_link_type",
        ),
        CheckConstraint("source IN ('rule','manual')", name="ck_chlinks_source"),
        CheckConstraint(
            "((to_chapter_id IS NOT NULL) <> (entity IS NOT NULL))",
            name="ck_chlinks_target",
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    from_chapter_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    to_chapter_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="章节目标；与 entity 二选一"
    )
    link_type: Mapped[str] = mapped_column(String(24), nullable=False)
    entity: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="实体目标（功能点 / 术语名）"
    )
    confidence: Mapped[Decimal | None] = mapped_column(
        DECIMAL(3, 2), nullable=True, comment="规则抽取固定值；人工补链为空"
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = ["CHAPTER_LINK_SOURCES", "CHAPTER_LINK_TYPES", "DocumentChapterLink"]
