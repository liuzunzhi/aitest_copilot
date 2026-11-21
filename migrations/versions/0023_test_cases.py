"""test cases（测试用例分析）

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-20

08-test-case-analysis T105：测试用例分析的三张新表 + 留痕枚举扩充 + 种子模板。

1. `test_case_analyses`：一次生成任务的记录（模板版本、状态、统计、错误码）；
2. `test_cases`：用例本体，带评审状态与来源快照；
3. `test_case_steps`：步骤子表，随用例级联删除；
4. `llm_run_logs.task_type` 的 CHECK 增加 `'test_case'`——MySQL 不允许直接改
   CHECK 约束，必须先删后加；
5. 播种一条 `task_type='test_case'` 的提示词模板——该枚举值 0013 就已预留，
   本期第一次使用，不改 `prompt_templates` 的 CHECK。

**两条刻意的设计**：

- `test_point_id` / `test_point_analysis_id` **不建外键**：07 的删测试点、
  删生成记录都是物理删除，建外键会把 07 的既有行为变成 500。这里用逻辑引用 +
  落库快照（`test_point_name` / `target_*` / `chapter_*`）。
- 输出契约里**没有**测试点 id：绑定哪个点由服务端决定，模板示例里也就不存在
  任何「可照抄的 id」（06 期 L2 的照抄坑从结构上消失）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

TEMPLATE_NAME = "测试用例生成·基于已评审测试点"
TEMPLATE_DESCRIPTION = "基于评审通过的测试点生成可评审、可追溯的测试用例"

SYSTEM_PROMPT = (
    "[TEST_CASE_SYSTEM] 你是测试用例设计助手。\n"
    "输入是一个已经评审通过的测试点，以及它来源章节的正文。\n"
    '只输出 JSON：{"cases":[{"title":"用例名称","case_type":"functional|api|ui",'
    '"priority":"high|medium|low","precondition":"前置条件",'
    '"steps":[{"action":"操作步骤","expected":"预期结果"}]}]}。\n'
    "规则：\n"
    "1. 一个测试点可以拆成多条用例，但每条用例都必须能追溯到该测试点；\n"
    "2. case_type 三选一：functional（功能）/ api（接口）/ ui（UI）；\n"
    "3. priority 三选一：high / medium / low；\n"
    "4. steps 至少一步，按执行顺序排列；每步的 expected 写清可观察的结果；\n"
    "5. title 用「场景 + 预期」一句话说清，同一次输出里不要重复；\n"
    "6. 只输出 JSON，不要写 JSON 之外的任何内容。"
)

USER_PROMPT = (
    "[TEST_CASE_USER] 请为下面的测试点设计测试用例：每条用例都要写清前置条件、"
    "可执行的操作步骤与每步的预期结果。"
)


def upgrade() -> None:
    # 1) 生成记录
    op.create_table(
        "test_case_analyses",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("template_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "template_version",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            comment="模板版本快照",
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'mock'"),
        ),
        sa.Column(
            "test_point_analysis_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="本次选了哪个测试点批次；逻辑引用，不建外键",
        ),
        sa.Column(
            "chapter_ids",
            mysql.JSON(),
            nullable=True,
            comment="本次按哪些章节筛选；全量为 NULL",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("stats", mysql.JSON(), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tcanalyses_project"),
        sa.ForeignKeyConstraint(
            ["template_id"], ["prompt_templates.id"], name="fk_tcanalyses_template"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tcanalyses_creator"),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_tcanalyses_status",
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_tcanalyses_project", "test_case_analyses", ["project_id"])
    op.create_index("idx_tcanalyses_template", "test_case_analyses", ["template_id"])
    op.create_index(
        "idx_tcanalyses_point_analysis", "test_case_analyses", ["test_point_analysis_id"]
    )

    # 2) 用例本体
    op.create_table(
        "test_cases",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "analysis_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="生成它的那次任务；手工新增的为 NULL",
        ),
        sa.Column(
            "test_point_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="所属测试点；逻辑引用，不建外键（07 是物理删除）",
        ),
        sa.Column(
            "test_point_name",
            sa.String(length=255),
            nullable=False,
            comment="落库快照：测试点改名 / 被删后历史仍对得上",
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "case_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'functional'"),
        ),
        sa.Column(
            "priority",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'medium'"),
        ),
        sa.Column("precondition", sa.String(length=1000), nullable=True),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("target_name", sa.String(length=255), nullable=False),
        sa.Column("chapter_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("chapter_title", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("reviewed_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("review_comment", sa.String(length=500), nullable=True),
        sa.Column(
            "source_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'llm'"),
        ),
        sa.Column(
            "source_point_fingerprint",
            mysql.CHAR(length=64),
            nullable=True,
            comment="生成时源测试点内容的 SHA-256；NULL = 已确认源删除",
        ),
        sa.Column(
            "needs_review_ack_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
            comment="最近一次确认「已知源变更」的时间",
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
            comment="由服务层显式赋值：MySQL 方言不渲染 ON UPDATE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tcases_project"),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["test_case_analyses.id"], name="fk_tcases_analysis"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tcases_creator"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_tcases_reviewer"),
        sa.CheckConstraint(
            "case_type IN ('functional','api','ui')", name="ck_tcases_case_type"
        ),
        sa.CheckConstraint(
            "priority IN ('high','medium','low')", name="ck_tcases_priority"
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')", name="ck_tcases_status"
        ),
        sa.CheckConstraint(
            "source_type IN ('llm','manual')", name="ck_tcases_source_type"
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_tcases_project", "test_cases", ["project_id"])
    op.create_index("idx_tcases_analysis", "test_cases", ["analysis_id"])
    op.create_index("idx_tcases_test_point", "test_cases", ["test_point_id"])
    op.create_index("idx_tcases_target", "test_cases", ["target_type", "target_id"])
    op.create_index("idx_tcases_status", "test_cases", ["project_id", "status"])

    # 3) 步骤子表
    op.create_table(
        "test_case_steps",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("case_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "step_no",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            comment="服务端按数组顺序重排为 1..n，不信模型给的序号",
        ),
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
            ["case_id"], ["test_cases.id"], name="fk_tcsteps_case", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("case_id", "step_no", name="uk_tcsteps_case_no"),
        sa.CheckConstraint("step_no >= 1", name="ck_tcsteps_no_positive"),
        **TABLE_OPTS,
    )
    op.create_index("idx_tcsteps_case", "test_case_steps", ["case_id"])

    # 4) 留痕表扩枚举。MySQL 不允许直接改 CHECK，必须先删后加。
    op.drop_constraint("ck_llmlogs_task_type", "llm_run_logs", type_="check")
    op.create_check_constraint(
        "ck_llmlogs_task_type",
        "llm_run_logs",
        "task_type IN "
        "('incremental_first','incremental_second','provider_test','test_point','test_case')",
    )

    # 5) 播种模板。created_at / updated_at 走 server default，不手写时间。
    seed = sa.table(
        "prompt_templates",
        sa.column("name", sa.String),
        sa.column("task_type", sa.String),
        sa.column("description", sa.String),
        sa.column("system_prompt", sa.Text),
        sa.column("user_prompt", sa.Text),
        sa.column("version_no", sa.Integer),
        sa.column("status", sa.String),
    )
    op.bulk_insert(
        seed,
        [
            {
                "name": TEMPLATE_NAME,
                "task_type": "test_case",
                "description": TEMPLATE_DESCRIPTION,
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": USER_PROMPT,
                "version_no": 1,
                "status": "active",
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM prompt_templates WHERE name = :name AND task_type = 'test_case'"
        ).bindparams(name=TEMPLATE_NAME)
    )

    # 留痕枚举收回：先清掉 test_case 留痕行，否则重建旧 CHECK 会撞 3819。
    op.execute(sa.text("DELETE FROM llm_run_logs WHERE task_type = 'test_case'"))
    op.drop_constraint("ck_llmlogs_task_type", "llm_run_logs", type_="check")
    op.create_check_constraint(
        "ck_llmlogs_task_type",
        "llm_run_logs",
        "task_type IN "
        "('incremental_first','incremental_second','provider_test','test_point')",
    )

    op.drop_table("test_case_steps")
    op.drop_table("test_cases")
    op.drop_table("test_case_analyses")
