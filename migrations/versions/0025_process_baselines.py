"""流程基线的四张表 + 提示词模板枚举扩展（10-process-baseline T117）

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-22

10-process-baseline T117：PRD 2.4.2 基线管理下的另一个子菜单「流程基线」。

1. `process_baselines`：业务场景（场景名称 / 前置条件 / 状态 / 来源）。
2. `process_baseline_steps`：场景的操作步骤列表（有序）。
3. `process_baseline_links`：场景 ↔ 功能基线的关联（多对多、单向）。
4. `process_baseline_revisions`：审核记录 / 版本快照（一体表）。
5. `prompt_templates.task_type` 的 CHECK 扩一个 `'process_baseline'`，
   并播种一条流程基线反推模板。

**为什么独立建表，不复用功能基线的表**（spec §3.1）：
04 的 `baseline_labels.target_type` CHECK 写死两个层级名、
`baseline_review_items.entity_type` CHECK 写死三个层级名、
`baseline_revisions` 的唯一键让两套基线**抢同一个版本号**。
共用表会污染既有 CHECK、打断 04–09 的回归断言，且版本号互相挤占。

**四条刻意的设计**：

- `process_baseline_links.target_id` **不建外键**：04 的删功能是**物理删除**
  （`app/baselines/service.py:678`），建 FK 会把 04 的既有行为变成 500。
  用逻辑引用 + `target_name` **名称快照**，目标被删后链接行仍可读。
- 步骤表是 08 的 `test_case_steps` 的照抄：同样的 `ON DELETE CASCADE`、
  同样的列宽 1000、同样的「`step_no` 由服务端按数组顺序重排」口径。
- 快照**提交时冻结**进 `draft_snapshot`，审核通过时**原样转正**为
  `structure_json`——保证「审核人看到的」与「最终冻结的」逐字节相同。
- `process_baselines.version_no` 是**场景自身的修订次数**，
  与 `process_baseline_revisions.version_no`（快照版本号 `v1.{n}`）含义不同。

**upgrade / downgrade 的三条顺序约束**（都是踩过坑的）：

1. **先扩 CHECK 再播种模板**：反了的话插入 `task_type='process_baseline'`
   的行会被旧 CHECK 拒（3819）。
2. **MySQL 不允许直接改 CHECK**，必须先 `drop_constraint` 再
   `create_check_constraint`（08 期在 `llm_run_logs` 上踩过同一件事，
   见 `0023_test_cases.py:279-285`）。
3. **downgrade 必须先删模板行再重建旧 CHECK**：残留的
   `task_type='process_baseline'` 行会让旧 CHECK 重建失败（3819）。
   这正是 08 期在 `llm_run_logs` 上踩过的坑
   （`0023_test_cases.py:321-322` 的注释写明了原因）。

**`llm_run_logs.task_type` 不动**：04 的文档推导**不写运行留痕**
（`app/baselines/service.py:2387` 的 `run_document_derive` 里没有
`run_log.record_run`），本期的反推同构——不写留痕 → 不需要扩它的 CHECK。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

# `prompt_templates.task_type` 的 CHECK：旧四值 → 新五值。
# 写成常量而不是散落两处：upgrade / downgrade 共用这一处，
# 避免改了 upgrade 忘了 downgrade（降级后旧 CHECK 认不了新枚举值）。
OLD_TEMPLATE_TASK_TYPES = (
    "document_parse",
    "incremental",
    "test_point",
    "test_case",
)
NEW_TEMPLATE_TASK_TYPES = (*OLD_TEMPLATE_TASK_TYPES, "process_baseline")


def _task_types_sql(task_types: tuple[str, ...]) -> str:
    """把枚举拼成 CHECK 约束的 SQL 字面量片段。"""
    joined = ",".join(f"'{value}'" for value in task_types)
    return f"task_type IN ({joined})"


TEMPLATE_NAME = "流程基线推导·场景抽取"
TEMPLATE_DESCRIPTION = "从需求文档章节中抽取「完整业务场景」及其操作步骤与关联目标"

SYSTEM_PROMPT = (
    "[PROCESS_BASELINE_SYSTEM] 你是需求文档业务场景分析助手。\n"
    "从给定的章节正文中抽取「完整业务场景」——每个场景包含场景名称、"
    "前置条件、有序的操作步骤列表（每步含预期结果），以及它覆盖的功能基线目标。\n"
    '只输出 JSON：{"scenarios":[{"name":"...","description":"...",'
    '"precondition":"...","confidence":0.0,"rationale":"...",'
    '"steps":[{"action":"...","expected":"..."}],'
    '"links":[{"target_type":"function","feature_point","target_id":0}]}]}。\n'
    "规则：\n"
    "1. 只抽正文里明确写到的内容，不要臆造、不要补全常识；\n"
    "2. 章节是背景介绍、没有可抽取的场景时，输出 {\"scenarios\": []}；\n"
    "3. 场景名称用文档里的原词，不要改写；\n"
    "4. 步骤必须有序，每步的 expected 可以留空字符串，但 action 不能为空；\n"
    "5. links 里的 target_id **只能取自「可关联的功能基线目标」清单**——"
    "清单里没有的目标不要输出；\n"
    "6. 不要输出 JSON 之外的任何内容。"
)

USER_PROMPT = (
    "从下面章节中抽取完整业务场景。\n"
    "若下方「已有流程基线场景」里已有同名场景，优先复用已有名称，不要重复抽取。\n"
    "关联的功能基线目标请从「可关联的功能基线目标」清单里选，"
    "不要自己编造 target_id。"
)


def upgrade() -> None:
    # 0) 扩 prompt_templates 的 CHECK 枚举（**必须先扩，再播种**）
    op.drop_constraint("ck_ptemplates_task_type", "prompt_templates", type_="check")
    op.create_check_constraint(
        "ck_ptemplates_task_type",
        "prompt_templates",
        _task_types_sql(NEW_TEMPLATE_TASK_TYPES),
    )

    # 1) 播种流程基线反推模板
    op.execute(
        sa.text(
            "INSERT INTO prompt_templates "
            "(name, task_type, description, system_prompt, user_prompt, version_no, status) "
            "VALUES (:name, 'process_baseline', :description, :system_prompt, "
            ":user_prompt, 1, 'active')"
        ).bindparams(
            name=TEMPLATE_NAME,
            description=TEMPLATE_DESCRIPTION,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
        )
    )

    # 2) 业务场景
    op.create_table(
        "process_baselines",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "precondition",
            sa.String(length=1000),
            nullable=True,
            comment="前置条件",
        ),
        sa.Column(
            "source_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "version_no",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("1"),
            comment="场景自身的修订次数（内容变更即 +1），不是快照版本号",
        ),
        sa.Column(
            "source_document_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="文档推导来源：来源文档",
        ),
        sa.Column(
            "source_version_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="来源文档版本",
        ),
        sa.Column(
            "source_chapter_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="来源章节",
        ),
        sa.Column(
            "source_chapter_title",
            sa.String(length=255),
            nullable=True,
            comment="来源章节标题（快照列，章节改名不影响追溯）",
        ),
        sa.Column(
            "source_method",
            sa.String(length=32),
            nullable=True,
            comment="baseline_reverse / incremental_new",
        ),
        sa.Column(
            "source_analysis_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="关联增量分析记录",
        ),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_pbaselines_project"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_pbaselines_creator"),
        sa.CheckConstraint(
            "source_type IN ('manual','document_derived')", name="ck_pbaselines_source"
        ),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_pbaselines_status"),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_pbaselines_project_name", "process_baselines", ["project_id", "name"], unique=True
    )
    op.create_index("idx_pbaselines_project", "process_baselines", ["project_id"])
    op.create_index(
        "idx_pbaselines_source", "process_baselines", ["project_id", "source_type"]
    )
    op.create_index("idx_pbaselines_status", "process_baselines", ["project_id", "status"])

    # 3) 操作步骤
    op.create_table(
        "process_baseline_steps",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("baseline_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("step_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("action", sa.String(length=1000), nullable=False),
        sa.Column(
            "expected",
            sa.String(length=1000),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["baseline_id"],
            ["process_baselines.id"],
            name="fk_pbsteps_baseline",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("baseline_id", "step_no", name="uk_pbsteps_baseline_no"),
        sa.CheckConstraint("step_no >= 1", name="ck_pbsteps_no_positive"),
        **TABLE_OPTS,
    )
    op.create_index("idx_pbsteps_baseline", "process_baseline_steps", ["baseline_id"])

    # 4) 关联功能基线（target_id 不建外键——04 的删功能是物理删除）
    op.create_table(
        "process_baseline_links",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("baseline_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column(
            "target_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="功能或功能点 id（多态，逻辑引用，不建外键）",
        ),
        sa.Column(
            "target_name",
            sa.String(length=255),
            nullable=False,
            comment="目标名称快照；目标被删后仍可读",
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["baseline_id"],
            ["process_baselines.id"],
            name="fk_pblinks_baseline",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "target_type IN ('function','feature_point')", name="ck_pblinks_target_type"
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_pblinks_baseline_target",
        "process_baseline_links",
        ["baseline_id", "target_type", "target_id"],
        unique=True,
    )
    op.create_index(
        "idx_pblinks_target",
        "process_baseline_links",
        ["target_type", "target_id"],
    )

    # 5) 审核记录 / 版本快照
    op.create_table(
        "process_baseline_revisions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "version_no",
            mysql.INTEGER(unsigned=True),
            nullable=True,
            comment="通过时分配，项目内递增",
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "draft_snapshot",
            mysql.MEDIUMTEXT(),
            nullable=True,
            comment="提交时冻结的场景集合 JSON",
        ),
        sa.Column(
            "structure_json",
            mysql.MEDIUMTEXT(),
            nullable=True,
            comment="通过时由 draft_snapshot 原样转正的快照 JSON",
        ),
        sa.Column(
            "scenario_count",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "step_count",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "link_count",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("submitted_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("submitted_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("reviewed_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("review_comment", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_pbrevisions_project"
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["users.id"], name="fk_pbrevisions_submitter"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name="fk_pbrevisions_reviewer"
        ),
        sa.CheckConstraint(
            "status IN ('submitted','approved','rejected')", name="ck_pbrevisions_status"
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_pbrevisions_project_no",
        "process_baseline_revisions",
        ["project_id", "version_no"],
        unique=True,
    )
    op.create_index("idx_pbrevisions_project", "process_baseline_revisions", ["project_id"])
    op.create_index(
        "idx_pbrevisions_project_status",
        "process_baseline_revisions",
        ["project_id", "status"],
    )


def downgrade() -> None:
    # 1) 删表（严格反序：先删被引用的）
    op.drop_table("process_baseline_revisions")
    op.drop_table("process_baseline_links")
    op.drop_table("process_baseline_steps")
    op.drop_table("process_baselines")

    # 2) 删模板行（**必须在重建旧 CHECK 之前**——
    #    残留的 task_type='process_baseline' 会让旧 CHECK 重建失败（3819））
    op.execute(
        sa.text(
            "DELETE FROM prompt_templates WHERE task_type = 'process_baseline'"
        )
    )

    # 3) 恢复旧 CHECK
    op.drop_constraint("ck_ptemplates_task_type", "prompt_templates", type_="check")
    op.create_check_constraint(
        "ck_ptemplates_task_type",
        "prompt_templates",
        _task_types_sql(OLD_TEMPLATE_TASK_TYPES),
    )
