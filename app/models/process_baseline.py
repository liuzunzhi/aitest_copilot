"""流程基线的四张表（10-process-baseline T117）。

流程基线是 PRD 2.4.2 基线管理下的**另一个子菜单**，与「功能基线」并列：

- `process_baselines`：业务场景（场景名称 / 前置条件 / 状态 / 来源）。
- `process_baseline_steps`：场景的操作步骤列表（有序）。
- `process_baseline_links`：场景 ↔ 功能基线的关联（多对多）。
- `process_baseline_revisions`：审核记录 / 版本快照（一体表）。

**为什么独立建表，不复用功能基线的表**（spec §3.1）：
04 的 `baseline_labels.target_type` CHECK 写死两个层级名、
`baseline_review_items.entity_type` CHECK 写死三个层级名、
`baseline_revisions` 的唯一键让两套基线**抢同一个版本号**。
共用表会污染既有 CHECK、打断 04–09 的回归断言，且版本号互相挤占。

**四条刻意的设计**：

1. `ProcessBaselineLink.target_id` **不建外键**：04 的删功能是**物理删除**
   （`app/baselines/service.py:678`），建 FK 会把 04 的既有行为变成 500。
   用逻辑引用 + `target_name` **名称快照**，目标被删后链接行仍可读。
2. 步骤表是 08 的 `test_case_steps` 的照抄：同样的 `ON DELETE CASCADE`、
   同样的列宽 1000、同样的「`step_no` 由服务端按数组顺序重排」口径。
3. 快照**提交时冻结**进 `draft_snapshot`，审核通过时**原样转正**为
   `structure_json`——保证「审核人看到的」与「最终冻结的」逐字节相同。
4. `ProcessBaseline.version_no` 是**场景自身的修订次数**，
   与 `ProcessBaselineRevision.version_no`（快照版本号 `v1.{n}`）**含义不同**。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
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

# 来源类型：手工添加 / 文档反推（与 04 的 source_type 同名同义）
SOURCE_TYPES = ("manual", "document_derived")
# 场景状态
STATUSES = ("active", "archived")
# 关联目标层级：功能 / 功能点（与 04 的目标层级一致）
TARGET_TYPES = ("function", "feature_point")
# 审核状态（与 04 的 baseline_revisions 同构）
REVISION_STATUSES = ("submitted", "approved", "rejected")


class ProcessBaseline(Base):
    """业务场景。

    `version_no` 是**场景自身的修订次数**（名称 / 描述 / 前置条件 / 步骤 /
    关联，任一变更即 +1），**不是**快照版本号——快照版本号在
    `ProcessBaselineRevision.version_no` 上。

    来源追溯 6 列与 04 的 `baseline_functions` / `baseline_feature_points`
    同名同义：手工添加时**全为 NULL**（PRD：手工添加不做追溯要求）。
    """

    __tablename__ = "process_baselines"
    # pytest 会把 `Test*` 开头的类当成测试类收集——显式关掉。
    # `ProcessBaseline*` 本身不撞这个规则，但统一加上更省心
    # （08 的 `TestCase*`、09 的 `Automation*` 都有先例）。
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_pbaselines_project"),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_pbaselines_creator"),
        Index("uk_pbaselines_project_name", "project_id", "name", unique=True),
        Index("idx_pbaselines_project", "project_id"),
        Index("idx_pbaselines_source", "project_id", "source_type"),
        Index("idx_pbaselines_status", "project_id", "status"),
        CheckConstraint(
            "source_type IN ('manual','document_derived')", name="ck_pbaselines_source"
        ),
        CheckConstraint("status IN ('active','archived')", name="ck_pbaselines_status"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    precondition: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="前置条件"
    )
    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'manual'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    version_no: Mapped[int] = mapped_column(
        INTEGER(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="场景自身的修订次数（内容变更即 +1），不是快照版本号",
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
    source_chapter_title: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="来源章节标题（快照列，章节改名不影响追溯）"
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class ProcessBaselineStep(Base):
    """场景的一个操作步骤：操作 + 预期结果。

    `step_no` 由服务端按数组顺序重排为 1..n，不信客户端给的序号。
    删场景时由数据库级 `ON DELETE CASCADE` 清理，不留孤儿行。
    """

    __tablename__ = "process_baseline_steps"
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(
            ["baseline_id"],
            ["process_baselines.id"],
            name="fk_pbsteps_baseline",
            ondelete="CASCADE",
        ),
        UniqueConstraint("baseline_id", "step_no", name="uk_pbsteps_baseline_no"),
        Index("idx_pbsteps_baseline", "baseline_id"),
        CheckConstraint("step_no >= 1", name="ck_pbsteps_no_positive"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    baseline_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    step_no: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    action: Mapped[str] = mapped_column(String(1000), nullable=False)
    expected: Mapped[str] = mapped_column(
        String(1000), nullable=False, server_default=text("''")
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class ProcessBaselineLink(Base):
    """场景 ↔ 功能基线的关联（多对多，单向）。

    `target_id` **不建外键**（逻辑引用 `baseline_functions.id` /
    `baseline_feature_points.id`）：04 的删功能是物理删除，建 FK 会让 04 的
    既有删除行为变成 500。`target_name` 是**名称快照**——目标被删后
    链接行仍在，读取时返回快照名并标「目标已删除」。

    **为什么用关联表而不是两个可空外键列**：一个场景天然覆盖多个
    功能/功能点，一个功能也会被多个场景引用（M:N），两个可空列表达不了；
    外键列也存不下名称快照。
    """

    __tablename__ = "process_baseline_links"
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(
            ["baseline_id"],
            ["process_baselines.id"],
            name="fk_pblinks_baseline",
            ondelete="CASCADE",
        ),
        Index(
            "uk_pblinks_baseline_target",
            "baseline_id",
            "target_type",
            "target_id",
            unique=True,
        ),
        Index("idx_pblinks_target", "target_type", "target_id"),
        CheckConstraint(
            "target_type IN ('function','feature_point')", name="ck_pblinks_target_type"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    baseline_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        comment="功能或功能点 id（多态，逻辑引用，不建外键）",
    )
    target_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="目标名称快照；目标被删后仍可读"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class ProcessBaselineRevision(Base):
    """审核记录 / 流程基线快照。

    一行既表示一次审核，也表示一份冻结快照：

    - 提交审核时把当前全部 active 场景冻结进 `draft_snapshot`；
    - 审核通过时**原样转正**为 `structure_json`（逐字节相同）；
    - `version_no` 只在通过时分配（项目内 `v1.{n}` 单调递增），
      驳回的记录不占版本号（`version_no` 可空 → MySQL 唯一索引允许多个 NULL）。

    **两列而不是一列**：一列的话「提交时的内容」与「通过时的内容」会互相覆盖，
    驳回后就查不到当初提交的是什么。两列让「所见即所冻」成为可断言的事实。
    """

    __tablename__ = "process_baseline_revisions"
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_pbrevisions_project"
        ),
        ForeignKeyConstraint(
            ["submitted_by"], ["users.id"], name="fk_pbrevisions_submitter"
        ),
        ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name="fk_pbrevisions_reviewer"
        ),
        Index("uk_pbrevisions_project_no", "project_id", "version_no", unique=True),
        Index("idx_pbrevisions_project", "project_id"),
        Index("idx_pbrevisions_project_status", "project_id", "status"),
        CheckConstraint(
            "status IN ('submitted','approved','rejected')", name="ck_pbrevisions_status"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    version_no: Mapped[int | None] = mapped_column(
        INTEGER(unsigned=True), nullable=True, comment="通过时分配，项目内递增"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    draft_snapshot: Mapped[str | None] = mapped_column(
        MEDIUMTEXT, nullable=True, comment="提交时冻结的场景集合 JSON"
    )
    structure_json: Mapped[str | None] = mapped_column(
        MEDIUMTEXT, nullable=True, comment="通过时由 draft_snapshot 原样转正的快照 JSON"
    )
    scenario_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    step_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    link_count: Mapped[int] = mapped_column(
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


__all__ = [
    "REVISION_STATUSES",
    "SOURCE_TYPES",
    "STATUSES",
    "TARGET_TYPES",
    "ProcessBaseline",
    "ProcessBaselineLink",
    "ProcessBaselineRevision",
    "ProcessBaselineStep",
]
