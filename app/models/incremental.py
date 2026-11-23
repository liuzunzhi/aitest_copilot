"""增量分析模型（05-incremental 第一期）。

三张表：

- `prompt_templates` 提示词模板：本期只读，由迁移播种一条 `incremental` 模板。
  模板内容必须来自数据库，这样改文案不用改代码、不用发版。
- `incremental_analyses` 分析记录：一次分析一行，记录模板快照、比对基准、
  文档版本、状态与统计。
- `incremental_conclusions` 第一遍局部结论：逐条落库，带章节与目标。
  被丢弃的结论（越界、`new`）**不落本表**，只记进 `analyses.stats.discarded`。

与 04 的硬约束：表名 `incremental_analyses`、列 `baseline_revision_id`、
列 `status` 三个名字不能改——`app/baselines/references.py` 的引用解析器
按这三个名字探测，改一个字「快照被引用禁止删除」就会静默失效。
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
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, DECIMAL, INTEGER, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

TASK_TYPES = (
    "document_parse",
    "incremental",
    "test_point",
    "test_case",
    # 10 期新增：流程基线的文档反推（PRD 2.4.2「流程基线 · 来源：文档反推」）。
    # **必须独立成一个类型**：复用 `document_parse` 会让 04 的推导下拉里
    # 混进流程基线模板，而 04 的服务端只校验 `task_type == 'document_parse'`
    # （`app/baselines/service.py:2416-2420`）——选错不报错，
    # 解析器会拿到 `{"scenarios": [...]}` 直接根结构校验失败，
    # 报错信息完全指不到真因。
    "process_baseline",
)
TEMPLATE_STATUSES = ("active", "disabled")
ANALYSIS_STATUSES = ("pending", "running", "succeeded", "failed")
SPLIT_GRANULARITIES = ("chapter",)
TARGET_TYPES = ("function", "feature_point")
CONCLUSION_LABEL_TYPES = ("changed", "affected", "unchanged")
SECOND_PASS_STATUSES = ("running", "succeeded", "failed")
DECISION_TYPES = ("changed", "affected", "unchanged")
CONFLICT_TYPES = ("conflict", "possible_impact", "new")
CONFLICT_STATUSES = ("pending", "confirmed", "rejected")
# 第三期：产出段状态。NULL 表示从未应用过。
APPLY_STATUSES = ("running", "succeeded", "failed")
# 产出段只写变更类标签，「确实没变」不落标签
APPLIED_LABEL_TYPES = ("changed", "affected")


class PromptTemplate(Base):
    """提示词模板。本期只被读取，不做增删改查接口。"""

    __tablename__ = "prompt_templates"
    __table_args__ = (
        Index("uk_ptemplates_type_name", "task_type", "name", unique=True),
        CheckConstraint(
            "task_type IN "
            "('document_parse','incremental','test_point','test_case','process_baseline')",
            name="ck_ptemplates_task_type",
        ),
        CheckConstraint(
            "status IN ('active','disabled')", name="ck_ptemplates_status"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    system_prompt: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    user_prompt: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    version_no: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("1")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        server_onupdate=text("CURRENT_TIMESTAMP(3)"),
    )


class IncrementalAnalysis(Base):
    """一次增量分析。同步跑完第一遍后回填状态与统计。"""

    __tablename__ = "incremental_analyses"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_ianalyses_project"),
        ForeignKeyConstraint(
            ["template_id"], ["prompt_templates.id"], name="fk_ianalyses_template"
        ),
        ForeignKeyConstraint(
            ["baseline_revision_id"],
            ["baseline_revisions.id"],
            name="fk_ianalyses_revision",
        ),
        ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_ianalyses_document"),
        ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_ianalyses_version",
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_ianalyses_creator"),
        ForeignKeyConstraint(
            ["second_pass_template_id"],
            ["prompt_templates.id"],
            name="fk_ianalyses_2b_template",
        ),
        ForeignKeyConstraint(
            ["apply_revision_id"],
            ["baseline_revisions.id"],
            name="fk_ianalyses_apply_revision",
        ),
        Index("idx_ianalyses_project", "project_id"),
        Index("idx_ianalyses_template", "template_id"),
        # 04 引用解析器按该列查询，索引必须保留
        Index("idx_ianalyses_revision", "baseline_revision_id"),
        Index("idx_ianalyses_document", "document_id"),
        Index("idx_ianalyses_version", "document_version_id"),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_ianalyses_status",
        ),
        CheckConstraint(
            "split_granularity IN ('chapter')", name="ck_ianalyses_granularity"
        ),
        CheckConstraint(
            "second_pass_status IS NULL OR second_pass_status IN ('running','succeeded','failed')",
            name="ck_ianalyses_2b_status",
        ),
        CheckConstraint(
            "apply_status IS NULL OR apply_status IN ('running','succeeded','failed')",
            name="ck_ianalyses_apply_status",
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    template_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    template_version: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'mock'")
    )
    baseline_revision_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    document_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    document_version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    split_granularity: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'chapter'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    # ---- 第二遍（第二期）。NULL 表示从未跑过；与第一遍 status 互不覆盖 ----
    second_pass_template_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="第二遍按点分治模板"
    )
    second_pass_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    second_pass_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    second_pass_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    second_pass_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    second_pass_started_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True
    )
    second_pass_finished_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True
    )
    # ---- 产出段（第三期）。NULL 表示从未应用过；与第一遍 / 第二遍状态互不覆盖 ----
    apply_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    apply_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    apply_revision_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="产物标签挂在哪份快照上"
    )
    apply_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    apply_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    apply_started_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True
    )
    apply_finished_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True
    )
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class IncrementalConclusion(Base):
    """第一遍局部结论。目标为功能或功能点（多态，不建外键）。"""

    __tablename__ = "incremental_conclusions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_id"],
            ["incremental_analyses.id"],
            name="fk_iconclusions_analysis",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["chapter_id"], ["document_chapters.id"], name="fk_iconclusions_chapter"
        ),
        # 同一次分析里，同一章节对同一目标的结论只留一条
        Index(
            "uk_iconclusions_unique",
            "analysis_id",
            "chapter_id",
            "target_type",
            "target_id",
            unique=True,
        ),
        Index("idx_iconclusions_analysis", "analysis_id"),
        Index("idx_iconclusions_chapter", "chapter_id"),
        CheckConstraint(
            "target_type IN ('function','feature_point')",
            name="ck_iconclusions_target_type",
        ),
        CheckConstraint(
            "label_type IN ('changed','affected','unchanged')",
            name="ck_iconclusions_label_type",
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    chapter_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    chapter_title: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="落库时快照，章节改名不影响历史结论"
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="功能或功能点 id（多态，不建外键）"
    )
    label_type: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(DECIMAL(3, 2), nullable=True)
    rationale: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class IncrementalDecision(Base):
    """第二遍无争议裁决。目标为功能或功能点（多态，不建外键）。

    `new` 不落本表——新增没有基线 id，只能进 `incremental_conflicts`。
    """

    __tablename__ = "incremental_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_id"],
            ["incremental_analyses.id"],
            name="fk_idecisions_analysis",
            ondelete="CASCADE",
        ),
        Index(
            "uk_idecisions_target",
            "analysis_id",
            "target_type",
            "target_id",
            unique=True,
        ),
        Index("idx_idecisions_analysis", "analysis_id"),
        CheckConstraint(
            "target_type IN ('function','feature_point')",
            name="ck_idecisions_target_type",
        ),
        CheckConstraint(
            "decision IN ('changed','affected','unchanged')",
            name="ck_idecisions_decision",
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="功能或功能点 id（多态，不建外键）"
    )
    target_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="裁决时快照名称"
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(DECIMAL(3, 2), nullable=True)
    rationale: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="{chapter_ids, conclusion_ids, propagated_from}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class IncrementalConflict(Base):
    """第二遍待人工裁决队列：冲突 / 可能连带变更 / 新增。

    不加数据库唯一键：`new` 的 `target_id` 为 NULL，唯一键对它会失效，
    去重由服务层保证（spec-phase2 §4.3）。
    """

    __tablename__ = "incremental_conflicts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_id"],
            ["incremental_analyses.id"],
            name="fk_iconflicts_analysis",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["resolved_by"], ["users.id"], name="fk_iconflicts_resolver"
        ),
        Index("idx_iconflicts_analysis", "analysis_id"),
        Index("idx_iconflicts_status", "analysis_id", "status"),
        CheckConstraint(
            "target_type IN ('function','feature_point')",
            name="ck_iconflicts_target_type",
        ),
        CheckConstraint(
            "conflict_type IN ('conflict','possible_impact','new')",
            name="ck_iconflicts_type",
        ),
        CheckConstraint(
            "status IN ('pending','confirmed','rejected')",
            name="ck_iconflicts_status",
        ),
        CheckConstraint(
            "resolved_label_type IS NULL OR resolved_label_type IN ('changed','affected','unchanged')",
            name="ck_iconflicts_resolved_label",
        ),
        CheckConstraint(
            "(conflict_type = 'new' AND target_id IS NULL)"
            " OR (conflict_type <> 'new' AND target_id IS NOT NULL)",
            name="ck_iconflicts_target",
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="new 没有基线 id"
    )
    target_name: Mapped[str] = mapped_column(String(255), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(16), nullable=False)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    resolved_label_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class IncrementalLabel(Base):
    """产出段标签映射：分析 ↔ 04 基线标签（双向可追溯）。

    重跑产出走逻辑清除，旧映射行必须保留，因此唯一键只能是
    `(analysis_id, baseline_label_id)`；若按目标建唯一键，旧行会挡住新一行。
    查询「当前产出」时需与 `baseline_labels.status='active'` 联查。
    """

    __tablename__ = "incremental_labels"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_id"],
            ["incremental_analyses.id"],
            name="fk_ilabels_analysis",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["baseline_label_id"],
            ["baseline_labels.id"],
            name="fk_ilabels_label",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["revision_id"], ["baseline_revisions.id"], name="fk_ilabels_revision"
        ),
        # 一个标签只能被一条映射行指向；重跑新增映射，不覆盖旧行
        Index(
            "uk_ilabels_analysis_label",
            "analysis_id",
            "baseline_label_id",
            unique=True,
        ),
        Index("idx_ilabels_analysis", "analysis_id"),
        Index("idx_ilabels_label", "baseline_label_id"),
        Index("idx_ilabels_revision", "revision_id"),
        # 普通索引：按目标查「本次分析产出的标签」
        Index(
            "idx_ilabels_target",
            "analysis_id",
            "target_type",
            "target_id",
            "label_type",
        ),
        CheckConstraint(
            "target_type IN ('function','feature_point')",
            name="ck_ilabels_target_type",
        ),
        CheckConstraint(
            "label_type IN ('changed','affected')", name="ck_ilabels_label_type"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    baseline_label_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    revision_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="标签挂在哪份快照上"
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, comment="功能或功能点 id（多态，不建外键）"
    )
    label_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = [
    "ANALYSIS_STATUSES",
    "APPLIED_LABEL_TYPES",
    "APPLY_STATUSES",
    "CONCLUSION_LABEL_TYPES",
    "CONFLICT_STATUSES",
    "CONFLICT_TYPES",
    "DECISION_TYPES",
    "IncrementalAnalysis",
    "IncrementalConclusion",
    "IncrementalConflict",
    "IncrementalDecision",
    "IncrementalLabel",
    "PromptTemplate",
    "SECOND_PASS_STATUSES",
    "SPLIT_GRANULARITIES",
    "TARGET_TYPES",
    "TASK_TYPES",
    "TEMPLATE_STATUSES",
]
