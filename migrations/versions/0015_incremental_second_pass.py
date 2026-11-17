"""incremental second pass: decisions / conflicts + analyses columns

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-17

05-incremental 第二期（T72）：第二遍全局裁决的落库结构。

1. `incremental_decisions`：无争议裁决，唯一 `(analysis_id, target_type, target_id)`；
2. `incremental_conflicts`：待人工裁决队列（冲突 / 可能连带 / 新增）。
   不加唯一键——`new` 的 `target_id` 为 NULL 会让唯一键失效，去重放服务层；
3. `incremental_analyses` 追加第二遍列，`second_pass_status` 为 NULL 表示未跑过；
4. 播种第二遍模板：`system_prompt` / `user_prompt` 以
   `[INCREMENTAL_2B_SYSTEM]` / `[INCREMENTAL_2B_USER]` 开头，作为 AC-89 的稳定锚点。

`down_revision` 指向 0014（章节引用图）。downgrade 反序：先建的表后删，
先删列上的外键再删列（MySQL 不允许直接删被外键引用的列），最后删模板行。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

SECOND_PASS_COLUMNS = (
    "second_pass_template_id",
    "second_pass_status",
    "second_pass_stats",
    "second_pass_error_code",
    "second_pass_error_message",
    "second_pass_started_at",
    "second_pass_finished_at",
)

SEED_TEMPLATE_NAME = "增量分析·第二遍·按点分治"
SEED_SYSTEM_PROMPT = (
    "[INCREMENTAL_2B_SYSTEM] 你是需求变更全局裁决助手。\n"
    "输入是单个功能或功能点的局部结论集合，请判断它的最终标签。\n"
    "只输出 JSON：{\"decision\": \"changed|affected|unchanged\", "
    "\"confidence\": 0.8, \"rationale\": \"理由\", "
    "\"new_points\": [{\"name\": \"新增功能点名称\", \"confidence\": 0.6, "
    "\"rationale\": \"理由\"}]}。\n"
    "不要输出 JSON 之外的任何内容。"
)
SEED_USER_PROMPT = (
    "[INCREMENTAL_2B_USER] 请基于下面的局部结论与关联章节，给出该目标的全局裁决；"
    "若发现基线没有的新功能点，放进 new_points。"
)


def upgrade() -> None:
    # 1) 第二遍裁决
    op.create_table(
        "incremental_decisions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("analysis_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column(
            "target_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="功能或功能点 id（多态，不建外键）",
        ),
        sa.Column(
            "target_name", sa.String(length=255), nullable=False, comment="裁决时快照名称"
        ),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("confidence", mysql.DECIMAL(3, 2), nullable=True),
        sa.Column("rationale", sa.String(length=1000), nullable=True),
        sa.Column(
            "evidence",
            sa.JSON(),
            nullable=True,
            comment="{chapter_ids, conclusion_ids, propagated_from}",
        ),
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
            name="fk_idecisions_analysis",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "target_type IN ('function','feature_point')",
            name="ck_idecisions_target_type",
        ),
        sa.CheckConstraint(
            "decision IN ('changed','affected','unchanged')",
            name="ck_idecisions_decision",
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_idecisions_target",
        "incremental_decisions",
        ["analysis_id", "target_type", "target_id"],
        unique=True,
    )
    op.create_index("idx_idecisions_analysis", "incremental_decisions", ["analysis_id"])

    # 2) 待人工裁决队列
    op.create_table(
        "incremental_conflicts",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("analysis_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column(
            "target_id", mysql.BIGINT(unsigned=True), nullable=True, comment="new 没有基线 id"
        ),
        sa.Column("target_name", sa.String(length=255), nullable=False),
        sa.Column("conflict_type", sa.String(length=16), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("resolved_label_type", sa.String(length=16), nullable=True),
        sa.Column("resolved_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("resolved_at", mysql.DATETIME(fsp=3), nullable=True),
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
            name="fk_iconflicts_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["users.id"], name="fk_iconflicts_resolver"
        ),
        sa.CheckConstraint(
            "target_type IN ('function','feature_point')",
            name="ck_iconflicts_target_type",
        ),
        sa.CheckConstraint(
            "conflict_type IN ('conflict','possible_impact','new')",
            name="ck_iconflicts_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','confirmed','rejected')",
            name="ck_iconflicts_status",
        ),
        sa.CheckConstraint(
            "resolved_label_type IS NULL OR resolved_label_type IN "
            "('changed','affected','unchanged')",
            name="ck_iconflicts_resolved_label",
        ),
        sa.CheckConstraint(
            "(conflict_type = 'new' AND target_id IS NULL)"
            " OR (conflict_type <> 'new' AND target_id IS NOT NULL)",
            name="ck_iconflicts_target",
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_iconflicts_analysis", "incremental_conflicts", ["analysis_id"])
    op.create_index(
        "idx_iconflicts_status", "incremental_conflicts", ["analysis_id", "status"]
    )

    # 3) 分析记录扩展列（第二遍状态独立，不覆盖第一遍 status）
    op.add_column(
        "incremental_analyses",
        sa.Column(
            "second_pass_template_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="第二遍按点分治模板",
        ),
    )
    op.add_column(
        "incremental_analyses",
        sa.Column("second_pass_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "incremental_analyses", sa.Column("second_pass_stats", sa.JSON(), nullable=True)
    )
    op.add_column(
        "incremental_analyses",
        sa.Column("second_pass_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "incremental_analyses",
        sa.Column("second_pass_error_message", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "incremental_analyses",
        sa.Column("second_pass_started_at", mysql.DATETIME(fsp=3), nullable=True),
    )
    op.add_column(
        "incremental_analyses",
        sa.Column("second_pass_finished_at", mysql.DATETIME(fsp=3), nullable=True),
    )
    op.create_foreign_key(
        "fk_ianalyses_2b_template",
        "incremental_analyses",
        "prompt_templates",
        ["second_pass_template_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_ianalyses_2b_status",
        "incremental_analyses",
        "second_pass_status IS NULL OR second_pass_status IN ('running','succeeded','failed')",
    )

    # 4) 播种第二遍模板。created_at / updated_at 走 server default。
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
                "description": "第二期种子模板：按功能点分治做全局裁决。",
                "system_prompt": SEED_SYSTEM_PROMPT,
                "user_prompt": SEED_USER_PROMPT,
                "version_no": 1,
                "status": "active",
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("incremental_conflicts")
    op.drop_table("incremental_decisions")

    # 先删外键再删列：MySQL 不允许直接删被外键引用的列
    op.drop_constraint(
        "fk_ianalyses_2b_template", "incremental_analyses", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_ianalyses_2b_status", "incremental_analyses", type_="check"
    )
    for column in reversed(SECOND_PASS_COLUMNS):
        op.drop_column("incremental_analyses", column)

    op.execute(
        sa.text("DELETE FROM prompt_templates WHERE name = :name").bindparams(
            name=SEED_TEMPLATE_NAME
        )
    )
