"""功能基线模型（04-baseline）。

三级结构：模块 → 功能 → 功能点；标签挂在功能/功能点上，
但**归属于某一份快照**（`baseline_revisions`），因此「旧快照清除标签不影响新快照」
靠复制成新行实现，而不是靠级联清除。

`baseline_labels.active_key` 是 STORED 生成列：仅当标签 `active` 时拼出
「快照:实体类型:实体:标签类型」，配合唯一索引保证
「同一快照、同一实体、同一标签类型只允许一条生效标签」。
MySQL 唯一索引允许多个 NULL，所以已清除的标签不占位，可以重新打标。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

LABEL_ACTIVE_KEY_EXPR = (
    "IF(status = 'active', "
    "CONCAT(revision_id, ':', target_type, ':', target_id, ':', label_type), NULL)"
)


class BaselineModule(Base):
    """功能基线的模块级。"""

    __tablename__ = "baseline_modules"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_bmodules_project"),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_bmodules_creator"),
        Index("uk_bmodules_project_name", "project_id", "name", unique=True),
        CheckConstraint(
            "source_type IN ('manual','document_derived')", name="ck_bmodules_source"
        ),
        CheckConstraint("status IN ('active','archived')", name="ck_bmodules_status"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'manual'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class BaselineFunction(Base):
    """功能。挂在模块下，`version_no` 每次内容修改递增。"""

    __tablename__ = "baseline_functions"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_bfunctions_project"),
        ForeignKeyConstraint(["module_id"], ["baseline_modules.id"], name="fk_bfunctions_module"),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_bfunctions_creator"),
        Index("uk_bfunctions_module_name", "module_id", "name", unique=True),
        CheckConstraint(
            "source_type IN ('manual','document_derived')", name="ck_bfunctions_source"
        ),
        CheckConstraint("status IN ('active','archived')", name="ck_bfunctions_status"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    module_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version_no: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("1")
    )
    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'manual'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    moved_from_module_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="最近一次迁移的来源模块"
    )
    source_document_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="文档推导来源：来源文档"
    )
    source_version_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="来源文档版本"
    )
    source_chapter_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="来源章节"
    )
    source_chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_method: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="baseline_reverse / incremental_new"
    )
    source_analysis_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="关联增量分析记录"
    )
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class BaselineFeaturePoint(Base):
    """功能点。挂在功能下。"""

    __tablename__ = "baseline_feature_points"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_bpoints_project"),
        ForeignKeyConstraint(
            ["function_id"], ["baseline_functions.id"], name="fk_bpoints_function"
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_bpoints_creator"),
        Index("uk_bpoints_function_name", "function_id", "name", unique=True),
        CheckConstraint(
            "source_type IN ('manual','document_derived')", name="ck_bpoints_source"
        ),
        CheckConstraint("status IN ('active','archived')", name="ck_bpoints_status"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    function_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'manual'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    source_document_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    source_version_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    source_chapter_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    source_chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_analysis_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class BaselineRevision(Base):
    """审核记录 / 基线快照。

    一行既表示一次审核，也表示一份冻结快照：
    `status='approved'` 时 `structure_json` 有效且不再变更。
    `version_no` 只在通过时分配（项目内 `v1.{n}` 单调递增），
    驳回的记录不占版本号。
    """

    __tablename__ = "baseline_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_brevisions_project"),
        ForeignKeyConstraint(["submitted_by"], ["users.id"], name="fk_brevisions_submitter"),
        ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_brevisions_reviewer"),
        Index("uk_brevisions_project_no", "project_id", "version_no", unique=True),
        CheckConstraint(
            "status IN ('submitted','approved','rejected')", name="ck_brevisions_status"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    version_no: Mapped[int | None] = mapped_column(
        INTEGER(unsigned=True), nullable=True, comment="通过时分配，项目内递增"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    structure_json: Mapped[str | None] = mapped_column(
        MEDIUMTEXT, nullable=True, comment="通过时冻结的三级结构 JSON"
    )
    module_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    function_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    feature_point_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    label_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    submitted_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class BaselineLabel(Base):
    """标签。挂在功能或功能点上，归属于某一份快照。"""

    __tablename__ = "baseline_labels"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_blabels_project"),
        ForeignKeyConstraint(["revision_id"], ["baseline_revisions.id"], name="fk_blabels_revision"),
        ForeignKeyConstraint(["confirmed_by"], ["users.id"], name="fk_blabels_confirmer"),
        ForeignKeyConstraint(["cleared_by"], ["users.id"], name="fk_blabels_clearer"),
        Index("uk_blabels_active", "active_key", unique=True),
        Index("idx_blabels_target", "target_type", "target_id"),
        Index("idx_blabels_revision", "revision_id"),
        CheckConstraint(
            "target_type IN ('function','feature_point')", name="ck_blabels_target_type"
        ),
        CheckConstraint(
            "label_type IN ('new','changed','affected','unchanged')",
            name="ck_blabels_label_type",
        ),
        CheckConstraint("status IN ('active','cleared')", name="ck_blabels_status"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    revision_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="功能或功能点 id（多态，不建外键）"
    )
    label_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_analysis_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    confirmed_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    cleared_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    clear_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    clear_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active_key: Mapped[str | None] = mapped_column(
        String(160),
        Computed(LABEL_ACTIVE_KEY_EXPR, persisted=True),
        comment="生成列：active 时拼出唯一键，其余为 NULL",
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = [
    "BaselineFeaturePoint",
    "BaselineFunction",
    "BaselineLabel",
    "BaselineModule",
    "BaselineRevision",
]
