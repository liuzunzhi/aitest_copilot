"""incremental apply: labels mapping + analyses apply columns

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-17

05-incremental 第三期（T79）：产出段的落库结构。

1. `incremental_labels`：分析 ↔ 04 基线标签的映射（双向可追溯）。
   唯一键只能是 `(analysis_id, baseline_label_id)`——重跑产出走逻辑清除，
   旧映射行必须保留，按目标建唯一键会与旧行撞车；
2. `incremental_analyses` 追加 `apply_*` 列，`apply_status` 为 NULL 表示未应用过；
   产出段状态与第一遍 `status`、第二遍 `second_pass_status` 互不覆盖；
3. 无种子数据。

`down_revision` 指向 0015（第二遍裁决）。downgrade 反序：先删映射表，
再删 `apply_revision_id` 上的外键与状态 CHECK（MySQL 不允许直接删被约束引用的列），
最后逐个删除扩展列。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

APPLY_COLUMNS = (
    "apply_status",
    "apply_stats",
    "apply_revision_id",
    "apply_error_code",
    "apply_error_message",
    "apply_started_at",
    "apply_finished_at",
)


def upgrade() -> None:
    # 1) 产出标签映射
    op.create_table(
        "incremental_labels",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("analysis_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("baseline_label_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "revision_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="标签挂在哪份快照上",
        ),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column(
            "target_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="功能或功能点 id（多态，不建外键）",
        ),
        sa.Column("label_type", sa.String(length=16), nullable=False),
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
            name="fk_ilabels_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_label_id"],
            ["baseline_labels.id"],
            name="fk_ilabels_label",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["baseline_revisions.id"], name="fk_ilabels_revision"
        ),
        sa.CheckConstraint(
            "target_type IN ('function','feature_point')",
            name="ck_ilabels_target_type",
        ),
        sa.CheckConstraint(
            "label_type IN ('changed','affected')", name="ck_ilabels_label_type"
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_ilabels_analysis_label",
        "incremental_labels",
        ["analysis_id", "baseline_label_id"],
        unique=True,
    )
    op.create_index("idx_ilabels_analysis", "incremental_labels", ["analysis_id"])
    op.create_index("idx_ilabels_label", "incremental_labels", ["baseline_label_id"])
    op.create_index("idx_ilabels_revision", "incremental_labels", ["revision_id"])
    op.create_index(
        "idx_ilabels_target",
        "incremental_labels",
        ["analysis_id", "target_type", "target_id", "label_type"],
    )

    # 2) 分析记录扩展列（产出段状态独立，不覆盖前两遍）
    op.add_column(
        "incremental_analyses",
        sa.Column("apply_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "incremental_analyses", sa.Column("apply_stats", sa.JSON(), nullable=True)
    )
    op.add_column(
        "incremental_analyses",
        sa.Column(
            "apply_revision_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="产物标签挂在哪份快照上",
        ),
    )
    op.add_column(
        "incremental_analyses",
        sa.Column("apply_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "incremental_analyses",
        sa.Column("apply_error_message", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "incremental_analyses",
        sa.Column("apply_started_at", mysql.DATETIME(fsp=3), nullable=True),
    )
    op.add_column(
        "incremental_analyses",
        sa.Column("apply_finished_at", mysql.DATETIME(fsp=3), nullable=True),
    )
    op.create_foreign_key(
        "fk_ianalyses_apply_revision",
        "incremental_analyses",
        "baseline_revisions",
        ["apply_revision_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_ianalyses_apply_status",
        "incremental_analyses",
        "apply_status IS NULL OR apply_status IN ('running','succeeded','failed')",
    )


def downgrade() -> None:
    op.drop_table("incremental_labels")

    # 先删外键 / CHECK 再删列：MySQL 不允许直接删被约束引用的列
    op.drop_constraint(
        "fk_ianalyses_apply_revision", "incremental_analyses", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_ianalyses_apply_status", "incremental_analyses", type_="check"
    )
    for column in reversed(APPLY_COLUMNS):
        op.drop_column("incremental_analyses", column)
