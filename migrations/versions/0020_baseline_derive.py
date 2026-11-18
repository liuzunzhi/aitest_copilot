"""baseline derive（从文档推导基线）

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-18

04 补期 B（T88）：从文档推导基线的落库结构与种子模板。

1. `baseline_derives`：一次推导的输入（文档 / 版本 / 模板）、状态与统计；
2. `baseline_derive_candidates`：候选草稿。`parent_id` 自引用 + `entity_type`
   表达三层；用户确认后才采纳进结构表，**绝不直接落结构表**；
3. 种子一条 `task_type='document_parse'` 的提示词模板——该枚举值 06 期
   就已预留，本期第一次使用，不需要改表。

结构表（`baseline_modules` 等）**零改动**：追溯字段早已预留。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

TEMPLATE_NAME = "基线推导·文档结构抽取"
TEMPLATE_DESCRIPTION = "从需求文档章节中抽取「模块 → 功能 → 功能点」三层结构"

SYSTEM_PROMPT = (
    "[DERIVE_SYSTEM] 你是需求文档结构分析助手。\n"
    "从给定的章节正文中抽取「模块 → 功能 → 功能点」三层结构。\n"
    '只输出 JSON：{"modules":[{"name":"...","description":"...",'
    '"functions":[{"name":"...","description":"...",'
    '"feature_points":[{"name":"...","description":"..."}]}]}]}。\n'
    "规则：\n"
    "1. 只抽正文里明确写到的内容，不要臆造、不要补全常识；\n"
    "2. 章节是背景介绍、没有可抽取的功能时，输出 {\"modules\": []}；\n"
    "3. 名称用文档里的原词，不要改写；\n"
    "4. 不要输出 JSON 之外的任何内容。"
)

USER_PROMPT = (
    "从下面章节中抽取功能基线结构。\n"
    "若下方「已有基线结构」里已有同名模块 / 功能，优先复用已有名称，不要重复抽取。"
)


def upgrade() -> None:
    # 1) 推导记录
    op.create_table(
        "baseline_derives",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("document_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("document_version_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("template_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "template_version",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            comment="模板版本快照",
        ),
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'mock'"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column(
            "stats",
            sa.JSON(),
            nullable=True,
            comment="章节点数 / 候选计数 / 跳过章节",
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_bderives_project"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_bderives_document"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_bderives_version",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["prompt_templates.id"], name="fk_bderives_template"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_bderives_creator"),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_bderives_status"
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_bderives_project", "baseline_derives", ["project_id"])
    op.create_index("idx_bderives_document", "baseline_derives", ["document_id"])
    op.create_index(
        "idx_bderives_version", "baseline_derives", ["document_version_id"]
    )
    op.create_index("idx_bderives_template", "baseline_derives", ["template_id"])

    # 2) 候选草稿
    op.create_table(
        "baseline_derive_candidates",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("derive_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "parent_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="父候选；NULL 表示模块",
        ),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "source_chapter_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="该候选从哪个章节抽出",
        ),
        sa.Column("source_chapter_title", sa.String(length=255), nullable=True),
        sa.Column("confidence", mysql.DECIMAL(3, 2), nullable=True),
        sa.Column("rationale", sa.String(length=1000), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("adopted_entity_type", sa.String(length=16), nullable=True),
        sa.Column("adopted_entity_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_bcandidates_project"
        ),
        sa.ForeignKeyConstraint(
            ["derive_id"],
            ["baseline_derives.id"],
            name="fk_bcandidates_derive",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["baseline_derive_candidates.id"],
            name="fk_bcandidates_parent",
        ),
        sa.CheckConstraint(
            "entity_type IN ('module','function','feature_point')",
            name="ck_bcandidates_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','adopted','skipped')",
            name="ck_bcandidates_status",
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_bcandidates_name",
        "baseline_derive_candidates",
        ["derive_id", "parent_id", "name", "entity_type"],
        unique=True,
    )
    op.create_index(
        "idx_bcandidates_derive_type",
        "baseline_derive_candidates",
        ["derive_id", "entity_type"],
    )
    op.create_index(
        "idx_bcandidates_derive_parent",
        "baseline_derive_candidates",
        ["derive_id", "parent_id"],
    )
    op.create_index(
        "idx_bcandidates_derive_status",
        "baseline_derive_candidates",
        ["derive_id", "status"],
    )

    # 3) 种子模板（task_type 枚举 06 期已预留，不新增枚举值）
    op.execute(
        sa.text(
            "INSERT INTO prompt_templates "
            "(name, task_type, description, system_prompt, user_prompt, version_no, status) "
            "VALUES (:name, 'document_parse', :description, :system_prompt, "
            ":user_prompt, 1, 'active')"
        ).bindparams(
            name=TEMPLATE_NAME,
            description=TEMPLATE_DESCRIPTION,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM prompt_templates "
            "WHERE task_type = 'document_parse' AND name = :name"
        ).bindparams(name=TEMPLATE_NAME)
    )
    op.drop_table("baseline_derive_candidates")
    op.drop_table("baseline_derives")
