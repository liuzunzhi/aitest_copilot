"""从文档推导基线的记录与候选草稿（04 补期 B · T88）。

两张表：

- `baseline_derives`：一次推导的输入（文档 / 版本 / 模板）、输出统计与状态。
- `baseline_derive_candidates`：推导出的候选草稿。**带 id、可编辑、可删除**，
  用户确认后才采纳进 `baseline_modules/functions/feature_points`。

候选表用 `parent_id` 自引用 + `entity_type` 表达三层：
`parent_id IS NULL` → 模块；父是 module → 功能；父是 function → 功能点。
**不建三张候选表**——候选只是临时草稿，拆三层没有收益。

结构表（`app/models/baseline.py`）**一个字不改**：追溯字段早已预留，
采纳时只写值，不加列。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    JSON,
    String,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, DECIMAL, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

DERIVE_STATUSES = ("running", "succeeded", "failed")
CANDIDATE_ENTITY_TYPES = ("module", "function", "feature_point")
CANDIDATE_STATUSES = ("pending", "adopted", "skipped")


class BaselineDerive(Base):
    """一次文档推导的记录。

    `template_version` / `provider` 是**快照**：模板后来改版、默认模型后来
    换掉，都不该改变「这次推导当时用的什么」。
    """

    __tablename__ = "baseline_derives"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_bderives_project"),
        ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_bderives_document"),
        ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], name="fk_bderives_version"
        ),
        ForeignKeyConstraint(
            ["template_id"], ["prompt_templates.id"], name="fk_bderives_template"
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_bderives_creator"),
        Index("idx_bderives_project", "project_id"),
        Index("idx_bderives_document", "document_id"),
        Index("idx_bderives_version", "document_version_id"),
        Index("idx_bderives_template", "template_id"),
        CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_bderives_status"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    document_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    document_version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    template_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    template_version: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, comment="模板版本快照"
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'mock'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'running'")
    )
    stats: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="章节点数 / 候选计数 / 跳过章节"
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class BaselineDeriveCandidate(Base):
    """推导出的候选草稿。

    `status` 三态：`pending`（待用户决定）/ `adopted`（已写入或复用到结构表）
    / `skipped`（用户跳过）。已决策的候选**不允许重复采纳**。

    同一父下同名同类型只留一条——引擎在落库前已按名字合并，
    唯一索引只是最后一道兜底（MySQL 允许多个 NULL，根节点的
    同名模块仍靠引擎合并保证）。
    """

    __tablename__ = "baseline_derive_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_bcandidates_project"
        ),
        ForeignKeyConstraint(
            ["derive_id"],
            ["baseline_derives.id"],
            name="fk_bcandidates_derive",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["parent_id"], ["baseline_derive_candidates.id"], name="fk_bcandidates_parent"
        ),
        Index(
            "uk_bcandidates_name",
            "derive_id",
            "parent_id",
            "name",
            "entity_type",
            unique=True,
        ),
        Index("idx_bcandidates_derive_type", "derive_id", "entity_type"),
        Index("idx_bcandidates_derive_parent", "derive_id", "parent_id"),
        Index("idx_bcandidates_derive_status", "derive_id", "status"),
        CheckConstraint(
            "entity_type IN ('module','function','feature_point')",
            name="ck_bcandidates_entity_type",
        ),
        CheckConstraint(
            "status IN ('pending','adopted','skipped')", name="ck_bcandidates_status"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    derive_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="父候选；NULL 表示模块"
    )
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_chapter_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="该候选从哪个章节抽出"
    )
    source_chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(DECIMAL(3, 2), nullable=True)
    rationale: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    adopted_entity_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    adopted_entity_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = [
    "BaselineDerive",
    "BaselineDeriveCandidate",
    "CANDIDATE_ENTITY_TYPES",
    "CANDIDATE_STATUSES",
    "DERIVE_STATUSES",
]
