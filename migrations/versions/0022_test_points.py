"""test points（测试点分析）

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-19

07-test-points T99：测试点分析的两张新表 + 留痕枚举扩充 + 种子模板。

1. `test_point_analyses`：一次生成任务的记录（模板版本、状态、统计、错误码）；
2. `test_points`：测试点本体，带来源追溯与评审状态；
3. `llm_run_logs.task_type` 的 CHECK 增加 `'test_point'`——MySQL 不允许直接改
   CHECK 约束，必须先删后加；
4. 播种一条 `task_type='test_point'` 的提示词模板——该枚举值 0013 就已预留，
   本期第一次使用，不改 `prompt_templates` 的 CHECK。

**模板示例里的 `target_id` 必须写 `123`（看起来像占位符）**：
真实模型会照抄示例值（06 期 L2 实测——模板写死 `"target_id": 1`，
模型就抄 1，真实的 10096 / 10097 全被当越界丢弃）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

TEMPLATE_NAME = "测试点生成·基于标签与增量结论"
TEMPLATE_DESCRIPTION = "基于生效中的基线标签与增量分析结论生成测试点"

SYSTEM_PROMPT = (
    "[TEST_POINT_SYSTEM] 你是测试设计助手。\n"
    "输入是一份需求文档的章节正文，以及可对照的基线目标、标签依据与增量结论。\n"
    '只输出 JSON：{"test_points":[{"name":"测试点名称",'
    '"target_type":"function|feature_point","target_id": 123,'
    '"priority":"high|medium|low","precondition":"前置条件",'
    '"verification":"验证要点"}]}。\n'
    "规则：\n"
    "1. target_id **必须取自「可对照的基线目标」清单里的编号**，不要臆造编号；\n"
    "2. target_type 只有两种：function（功能）与 feature_point（功能点）；\n"
    "3. priority 三选一：high / medium / low；\n"
    "4. name 用「场景 + 预期」一句话说清，别写成长段描述；\n"
    "5. 只输出 JSON 之外的任何内容都不要写。"
)

USER_PROMPT = (
    "[TEST_POINT_USER] 请基于下面的标签依据与增量结论，为该章节设计测试点；"
    "每个测试点都要挂到清单里的某个功能或功能点上。"
)


def upgrade() -> None:
    # 1) 生成记录
    op.create_table(
        "test_point_analyses",
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
        sa.Column("document_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("document_version_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("analysis_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("baseline_revision_id", mysql.BIGINT(unsigned=True), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tpanalyses_project"),
        sa.ForeignKeyConstraint(
            ["template_id"], ["prompt_templates.id"], name="fk_tpanalyses_template"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_tpanalyses_document"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], name="fk_tpanalyses_version"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["incremental_analyses.id"], name="fk_tpanalyses_analysis"
        ),
        sa.ForeignKeyConstraint(
            ["baseline_revision_id"], ["baseline_revisions.id"], name="fk_tpanalyses_revision"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tpanalyses_creator"),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_tpanalyses_status",
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_tpanalyses_project", "test_point_analyses", ["project_id"])
    op.create_index("idx_tpanalyses_template", "test_point_analyses", ["template_id"])
    op.create_index("idx_tpanalyses_analysis", "test_point_analyses", ["analysis_id"])
    op.create_index("idx_tpanalyses_revision", "test_point_analyses", ["baseline_revision_id"])

    # 2) 测试点本体
    op.create_table(
        "test_points",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "analysis_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="生成它的那次任务；手工新增的为 NULL",
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "target_name",
            sa.String(length=255),
            nullable=False,
            comment="落库快照：目标改名后历史仍对得上",
        ),
        sa.Column(
            "priority",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'medium'"),
        ),
        sa.Column("precondition", sa.String(length=1000), nullable=True),
        sa.Column("verification", sa.String(length=2000), nullable=True),
        sa.Column("chapter_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("chapter_title", sa.String(length=255), nullable=True),
        sa.Column("source_label_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("source_conclusion_id", mysql.BIGINT(unsigned=True), nullable=True),
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
            "needs_review",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
            comment="依赖的标签已被清除，请复核",
        ),
        sa.Column("needs_review_reason", sa.String(length=255), nullable=True),
        sa.Column("needs_review_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "source_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'llm'"),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tpoints_project"),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["test_point_analyses.id"], name="fk_tpoints_analysis"
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"], ["document_chapters.id"], name="fk_tpoints_chapter"
        ),
        sa.ForeignKeyConstraint(
            ["source_label_id"], ["baseline_labels.id"], name="fk_tpoints_source_label"
        ),
        sa.ForeignKeyConstraint(
            ["source_conclusion_id"],
            ["incremental_conclusions.id"],
            name="fk_tpoints_source_conclusion",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tpoints_creator"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_tpoints_reviewer"),
        sa.CheckConstraint(
            "target_type IN ('function','feature_point')", name="ck_tpoints_target_type"
        ),
        sa.CheckConstraint(
            "priority IN ('high','medium','low')", name="ck_tpoints_priority"
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')", name="ck_tpoints_status"
        ),
        sa.CheckConstraint("source_type IN ('llm','manual')", name="ck_tpoints_source_type"),
        **TABLE_OPTS,
    )
    op.create_index("idx_tpoints_project", "test_points", ["project_id"])
    op.create_index("idx_tpoints_analysis", "test_points", ["analysis_id"])
    op.create_index("idx_tpoints_target", "test_points", ["target_type", "target_id"])
    op.create_index("idx_tpoints_status", "test_points", ["project_id", "status"])

    # 3) 留痕表扩枚举。MySQL 不允许直接改 CHECK，必须先删后加。
    op.drop_constraint("ck_llmlogs_task_type", "llm_run_logs", type_="check")
    op.create_check_constraint(
        "ck_llmlogs_task_type",
        "llm_run_logs",
        "task_type IN "
        "('incremental_first','incremental_second','provider_test','test_point')",
    )

    # 4) 播种模板。created_at / updated_at 走 server default，不手写时间。
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
                "task_type": "test_point",
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
        sa.text("DELETE FROM prompt_templates WHERE name = :name").bindparams(
            name=TEMPLATE_NAME
        )
    )

    # 留痕表枚举收回（顺序与 upgrade 相反：先删新 CHECK，再建旧 CHECK）
    op.drop_constraint("ck_llmlogs_task_type", "llm_run_logs", type_="check")
    op.create_check_constraint(
        "ck_llmlogs_task_type",
        "llm_run_logs",
        "task_type IN ('incremental_first','incremental_second','provider_test')",
    )

    op.drop_table("test_points")
    op.drop_table("test_point_analyses")
