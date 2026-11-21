"""测试用例分析的三张表（08-test-case-analysis T105）。

- `test_case_analyses`：一次**生成任务**的记录（模板版本、状态、统计、错误码），
  与 07 的 `test_point_analyses` / 05 的 `incremental_analyses` 同构。
- `test_cases`：用例本体。一条测试点可拆多条用例（1:N），
  带评审生命周期与来源快照，供后续自动化执行（2.4.6）复用。
- `test_case_steps`：步骤与预期结果，**分步建模**（子表）。

两条刻意的设计：

1. `test_point_id` / `test_point_analysis_id` **都不建外键**：07 的删测试点、
   删生成记录都是物理删除，建外键会把 07 的既有行为变成 500。这里用逻辑引用 +
   落库快照（`test_point_name` / `target_*` / `chapter_*`）。
2. `source_point_fingerprint` 是「生成/复核时源测试点内容」的 SHA-256，
   **不是 `updated_at`**——`test_points.updated_at` 只有插入时赋值，
   MySQL 侧没有 `ON UPDATE`，拿它判断「点被改过」永远不触发。
   指纹为 NULL 表示「人工确认过源已删除」。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

CASE_ANALYSIS_STATUSES = ("pending", "running", "succeeded", "failed")
CASE_STATUSES = ("pending", "approved", "rejected")
CASE_TYPES = ("functional", "api", "ui")
CASE_PRIORITIES = ("high", "medium", "low")
CASE_SOURCE_TYPES = ("llm", "manual")


class TestCaseAnalysis(Base):
    """一次测试用例生成任务。

    `test_point_analysis_id` 只是「本次选了哪个测试点批次」的历史标签，
    **不建外键**：07 删测试点生成记录时不能被这里挡住。
    """

    __tablename__ = "test_case_analyses"
    # pytest 会把 `Test*` 开头的类当成测试类收集——显式关掉。
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tcanalyses_project"),
        ForeignKeyConstraint(
            ["template_id"], ["prompt_templates.id"], name="fk_tcanalyses_template"
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tcanalyses_creator"),
        Index("idx_tcanalyses_project", "project_id"),
        Index("idx_tcanalyses_template", "template_id"),
        Index("idx_tcanalyses_point_analysis", "test_point_analysis_id"),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_tcanalyses_status",
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
    test_point_analysis_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True
    )
    chapter_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
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


class TestCase(Base):
    """一条测试用例。

    `analysis_id` 为 NULL 表示手工新增（与 07 的 `test_points.analysis_id` 同口径）。
    `test_point_id` 必填但**不建外键**——手工用例也允许挂 pending 测试点，
    人工补录不该被评审状态卡死。
    `updated_at` 由服务层显式赋值：MySQL 方言不会把 `server_onupdate` 渲染成 `ON UPDATE`。
    """

    __tablename__ = "test_cases"
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tcases_project"),
        ForeignKeyConstraint(
            ["analysis_id"], ["test_case_analyses.id"], name="fk_tcases_analysis"
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tcases_creator"),
        ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_tcases_reviewer"),
        Index("idx_tcases_project", "project_id"),
        Index("idx_tcases_analysis", "analysis_id"),
        Index("idx_tcases_test_point", "test_point_id"),
        Index("idx_tcases_target", "target_type", "target_id"),
        Index("idx_tcases_status", "project_id", "status"),
        CheckConstraint(
            "case_type IN ('functional','api','ui')", name="ck_tcases_case_type"
        ),
        CheckConstraint(
            "priority IN ('high','medium','low')", name="ck_tcases_priority"
        ),
        CheckConstraint("status IN ('pending','approved','rejected')", name="ck_tcases_status"),
        CheckConstraint("source_type IN ('llm','manual')", name="ck_tcases_source_type"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    analysis_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    test_point_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    test_point_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    case_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'functional'")
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'medium'")
    )
    precondition: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    target_name: Mapped[str] = mapped_column(String(255), nullable=False)
    chapter_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    reviewed_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'llm'")
    )
    source_point_fingerprint: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    needs_review_ack_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class TestCaseStep(Base):
    """用例的一个步骤：操作 + 预期结果。

    `step_no` 由服务端按数组顺序重排为 1..n，不信模型给的序号。
    删用例时由数据库级 `ON DELETE CASCADE` 清理，不留孤儿行。
    """

    __tablename__ = "test_case_steps"
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id"],
            ["test_cases.id"],
            name="fk_tcsteps_case",
            ondelete="CASCADE",
        ),
        UniqueConstraint("case_id", "step_no", name="uk_tcsteps_case_no"),
        Index("idx_tcsteps_case", "case_id"),
        CheckConstraint("step_no >= 1", name="ck_tcsteps_no_positive"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    step_no: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    action: Mapped[str] = mapped_column(String(1000), nullable=False)
    expected: Mapped[str] = mapped_column(
        String(1000), nullable=False, server_default=text("''")
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = [
    "CASE_ANALYSIS_STATUSES",
    "CASE_PRIORITIES",
    "CASE_SOURCE_TYPES",
    "CASE_STATUSES",
    "CASE_TYPES",
    "TestCase",
    "TestCaseAnalysis",
    "TestCaseStep",
]
