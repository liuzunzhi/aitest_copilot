"""测试点分析的两张表（07-test-points T99）。

- `test_point_analyses`：一次**生成任务**的记录（模板版本、状态、统计、错误码），
  与 05 的 `incremental_analyses` 同构——三段能力各占一组状态列，
  本期只有一段，所以只有 `status` 一组。
- `test_points`：生成出来的**测试点本体**。

两张表分开的理由与 05 的 `analyses` / `conclusions` 一致：
生成任务是一次性的、可能失败；测试点是产出物，有独立的评审生命周期
（待评审 → 通过 / 驳回），会被手工增删改，还可能被下游（08 期用例生成）引用。

**不建唯一键**：测试点允许同名——不同章节、不同功能的同名测试点是合法的
（比如两个功能都要验「连续失败 5 次锁定」）。只靠 `idx_tpoints_target` 检索。
"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, String, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

ANALYSIS_STATUSES = ("pending", "running", "succeeded", "failed")
POINT_STATUSES = ("pending", "approved", "rejected")
POINT_TARGET_TYPES = ("function", "feature_point")
POINT_PRIORITIES = ("high", "medium", "low")
POINT_SOURCE_TYPES = ("llm", "manual")


class TestPointAnalysis(Base):
    """一次测试点生成任务。

    `provider` 记的是「用的哪条配置」（配置名），不是供应商类型——
    与 06 期 `llm_run_logs` 的口径一致。
    `document_id` / `document_version_id` / `analysis_id` / `baseline_revision_id`
    都可空：输入可以是「增量结论 + 基线」，也可以是「只给基线」。
    """

    __tablename__ = "test_point_analyses"
    # pytest 会把 `Test*` 开头的类当成测试类收集——显式关掉。
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tpanalyses_project"),
        ForeignKeyConstraint(
            ["template_id"], ["prompt_templates.id"], name="fk_tpanalyses_template"
        ),
        ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_tpanalyses_document"),
        ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], name="fk_tpanalyses_version"
        ),
        ForeignKeyConstraint(
            ["analysis_id"], ["incremental_analyses.id"], name="fk_tpanalyses_analysis"
        ),
        ForeignKeyConstraint(
            ["baseline_revision_id"], ["baseline_revisions.id"], name="fk_tpanalyses_revision"
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tpanalyses_creator"),
        Index("idx_tpanalyses_project", "project_id"),
        Index("idx_tpanalyses_template", "template_id"),
        Index("idx_tpanalyses_analysis", "analysis_id"),
        Index("idx_tpanalyses_revision", "baseline_revision_id"),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_tpanalyses_status",
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    template_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    template_version: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'mock'")
    )
    document_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    document_version_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    analysis_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    baseline_revision_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class TestPoint(Base):
    """一条测试点。

    `target_name` / `chapter_title` 是**落库快照**：目标或章节后来改名、
    被删，历史测试点仍然对得上原文。
    `source_label_id` / `source_conclusion_id` 记来源（可空——手工新增的没有来源）。
    `needs_review` 标「依赖的标签已被清除，请复核」：
    清除标签**不改测试点内容**，只加这个标记（spec AC-149）。
    `analysis_id` 为 NULL 表示手工新增。
    """

    __tablename__ = "test_points"
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tpoints_project"),
        ForeignKeyConstraint(
            ["analysis_id"], ["test_point_analyses.id"], name="fk_tpoints_analysis"
        ),
        ForeignKeyConstraint(
            ["chapter_id"], ["document_chapters.id"], name="fk_tpoints_chapter"
        ),
        ForeignKeyConstraint(
            ["source_label_id"], ["baseline_labels.id"], name="fk_tpoints_source_label"
        ),
        ForeignKeyConstraint(
            ["source_conclusion_id"],
            ["incremental_conclusions.id"],
            name="fk_tpoints_source_conclusion",
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tpoints_creator"),
        ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_tpoints_reviewer"),
        Index("idx_tpoints_project", "project_id"),
        Index("idx_tpoints_analysis", "analysis_id"),
        Index("idx_tpoints_target", "target_type", "target_id"),
        Index("idx_tpoints_status", "project_id", "status"),
        CheckConstraint(
            "target_type IN ('function','feature_point')", name="ck_tpoints_target_type"
        ),
        CheckConstraint(
            "priority IN ('high','medium','low')", name="ck_tpoints_priority"
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected')", name="ck_tpoints_status"
        ),
        CheckConstraint("source_type IN ('llm','manual')", name="ck_tpoints_source_type"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    analysis_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    target_name: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'medium'")
    )
    precondition: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    verification: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    chapter_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_label_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    source_conclusion_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    reviewed_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    needs_review: Mapped[int] = mapped_column(
        TINYINT(unsigned=True), nullable=False, server_default=text("0")
    )
    needs_review_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    needs_review_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'llm'")
    )
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        server_onupdate=text("CURRENT_TIMESTAMP(3)"),
    )


__all__ = [
    "ANALYSIS_STATUSES",
    "POINT_PRIORITIES",
    "POINT_SOURCE_TYPES",
    "POINT_STATUSES",
    "POINT_TARGET_TYPES",
    "TestPoint",
    "TestPointAnalysis",
]
