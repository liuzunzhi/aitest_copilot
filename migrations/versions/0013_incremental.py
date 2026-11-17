"""create prompt_templates / incremental_analyses / incremental_conclusions

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-17

05-incremental（T68）。三张表按外键依赖顺序建：

- `prompt_templates` 提示词模板，本期只读；
- `incremental_analyses` 分析记录，引用模板 / 基线快照 / 文档版本；
- `incremental_conclusions` 第一遍局部结论，随分析记录级联删除。

与 04 的硬约束：`incremental_analyses` 表名、`baseline_revision_id`、
`status` 两列是 `app/baselines/references.py` 的探测依据，不能改名。
建表后「快照被增量分析引用 → 禁止删除」自动生效。

播种一条 `task_type='incremental'` 模板：`system_prompt` / `user_prompt`
分别以 `[INCREMENTAL_SYSTEM]` / `[INCREMENTAL_USER]` 开头。
前缀是给用例断言 AC-78 用的稳定锚点，改文案不会破坏「Prompt 来自数据库」的判定。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

SEED_TEMPLATE_NAME = "增量分析·第一遍·章节局部"
SEED_SYSTEM_PROMPT = (
    "[INCREMENTAL_SYSTEM] 你是需求变更分析助手。\n"
    "根据章节正文，判断基线中哪些功能或功能点发生了变更。\n"
    "只输出 JSON：{\"conclusions\": [{\"target_type\": \"function|feature_point\", "
    "\"target_id\": 1, \"label_type\": \"changed|affected|unchanged\", "
    "\"confidence\": 0.8, \"rationale\": \"理由\"}]}。\n"
    "不要输出 JSON 之外的任何内容；不要使用 new 标签。"
)
SEED_USER_PROMPT = (
    "[INCREMENTAL_USER] 请阅读下面的章节内容，并与比对基准基线中的功能 / 功能点对照，"
    "给出局部结论。"
)


def upgrade() -> None:
    # 1) 提示词模板
    op.create_table(
        "prompt_templates",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("system_prompt", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("user_prompt", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column(
            "version_no", mysql.INTEGER(unsigned=True), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
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
        sa.CheckConstraint(
            "task_type IN ('document_parse','incremental','test_point','test_case')",
            name="ck_ptemplates_task_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','disabled')", name="ck_ptemplates_status"
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_ptemplates_type_name", "prompt_templates", ["task_type", "name"], unique=True
    )

    # 2) 分析记录
    op.create_table(
        "incremental_analyses",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("template_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("template_version", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column(
            "provider", sa.String(length=32), nullable=False, server_default=sa.text("'mock'")
        ),
        sa.Column(
            "baseline_revision_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="04 引用解析器依赖此列",
        ),
        sa.Column("document_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("document_version_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "split_granularity",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'chapter'"),
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_ianalyses_project"),
        sa.ForeignKeyConstraint(
            ["template_id"], ["prompt_templates.id"], name="fk_ianalyses_template"
        ),
        sa.ForeignKeyConstraint(
            ["baseline_revision_id"], ["baseline_revisions.id"], name="fk_ianalyses_revision"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_ianalyses_document"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], name="fk_ianalyses_version"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_ianalyses_creator"),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_ianalyses_status",
        ),
        sa.CheckConstraint(
            "split_granularity IN ('chapter')", name="ck_ianalyses_granularity"
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_ianalyses_project", "incremental_analyses", ["project_id"])
    op.create_index("idx_ianalyses_template", "incremental_analyses", ["template_id"])
    op.create_index(
        "idx_ianalyses_revision", "incremental_analyses", ["baseline_revision_id"]
    )
    op.create_index("idx_ianalyses_document", "incremental_analyses", ["document_id"])
    op.create_index(
        "idx_ianalyses_version", "incremental_analyses", ["document_version_id"]
    )

    # 3) 第一遍局部结论
    op.create_table(
        "incremental_conclusions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("analysis_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("chapter_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("chapter_title", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column(
            "target_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="功能或功能点 id（多态，不建外键）",
        ),
        sa.Column("label_type", sa.String(length=16), nullable=False),
        sa.Column("confidence", mysql.DECIMAL(3, 2), nullable=True),
        sa.Column("rationale", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["incremental_analyses.id"],
            name="fk_iconclusions_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"], ["document_chapters.id"], name="fk_iconclusions_chapter"
        ),
        sa.CheckConstraint(
            "target_type IN ('function','feature_point')",
            name="ck_iconclusions_target_type",
        ),
        sa.CheckConstraint(
            "label_type IN ('changed','affected','unchanged')",
            name="ck_iconclusions_label_type",
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_iconclusions_unique",
        "incremental_conclusions",
        ["analysis_id", "chapter_id", "target_type", "target_id"],
        unique=True,
    )
    op.create_index(
        "idx_iconclusions_analysis", "incremental_conclusions", ["analysis_id"]
    )
    op.create_index("idx_iconclusions_chapter", "incremental_conclusions", ["chapter_id"])

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
                "name": SEED_TEMPLATE_NAME,
                "task_type": "incremental",
                "description": "第一期种子模板：逐章节比对基线功能与功能点。",
                "system_prompt": SEED_SYSTEM_PROMPT,
                "user_prompt": SEED_USER_PROMPT,
                "version_no": 1,
                "status": "active",
            }
        ],
    )


def downgrade() -> None:
    # 反序删表；不逐个 drop_index（唯一索引同时是外键列索引，先删会报 1553）。
    op.drop_table("incremental_conclusions")
    op.drop_table("incremental_analyses")
    op.drop_table("prompt_templates")
