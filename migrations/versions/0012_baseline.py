"""create baseline_* tables and projects.baseline_snapshot_max_count

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-16

04-baseline（T55）。五张表一次性建好：

- `baseline_modules` 模块，项目内同名唯一；
- `baseline_functions` 功能，挂在模块下，同模块同名唯一；
- `baseline_feature_points` 功能点，挂在功能下，同功能同名唯一；
- `baseline_revisions` 审核记录 / 基线快照合表，`status='approved'` 时
  `structure_json` 冻结，`version_no` 项目内单调递增；
- `baseline_labels` 标签，`active_key` 用 STORED 生成列
  `IF(status = 'active', CONCAT(revision_id,':',target_type,':',target_id,':',label_type), NULL)`
  + 唯一索引，保证同快照同实体同类型仅一条生效标签
  （MySQL 无条件唯一索引但允许多个 NULL，已清除标签不占位，可重新打标）。

`projects.baseline_snapshot_max_count` 空 = 不启用（默认永久保留），
放项目表而不是 `system_settings`，因为 PRD 要求项目级。

生成列必须建表时一并创建，所以这里不拆成多个迁移。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

LABEL_ACTIVE_KEY_EXPR = (
    "IF(status = 'active', "
    "CONCAT(revision_id, ':', target_type, ':', target_id, ':', label_type), NULL)"
)


def upgrade() -> None:
    op.create_table(
        "baseline_modules",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "sort_order", mysql.INTEGER(unsigned=True), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "source_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_bmodules_project"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_bmodules_creator"),
        sa.CheckConstraint(
            "source_type IN ('manual','document_derived')", name="ck_bmodules_source"
        ),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_bmodules_status"),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_bmodules_project_name", "baseline_modules", ["project_id", "name"], unique=True
    )

    op.create_table(
        "baseline_functions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("module_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "version_no", mysql.INTEGER(unsigned=True), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "source_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column(
            "moved_from_module_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="最近一次迁移的来源模块",
        ),
        sa.Column(
            "source_document_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="文档推导来源：来源文档",
        ),
        sa.Column(
            "source_version_id", mysql.BIGINT(unsigned=True), nullable=True, comment="来源文档版本"
        ),
        sa.Column(
            "source_chapter_id", mysql.BIGINT(unsigned=True), nullable=True, comment="来源章节"
        ),
        sa.Column("source_chapter_title", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_bfunctions_project"),
        sa.ForeignKeyConstraint(
            ["module_id"], ["baseline_modules.id"], name="fk_bfunctions_module"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_bfunctions_creator"),
        sa.CheckConstraint(
            "source_type IN ('manual','document_derived')", name="ck_bfunctions_source"
        ),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_bfunctions_status"),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_bfunctions_module_name", "baseline_functions", ["module_id", "name"], unique=True
    )

    op.create_table(
        "baseline_feature_points",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("function_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "source_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column("source_document_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("source_version_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("source_chapter_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("source_chapter_title", sa.String(length=255), nullable=True),
        sa.Column("source_method", sa.String(length=32), nullable=True),
        sa.Column("source_analysis_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_bpoints_project"),
        sa.ForeignKeyConstraint(
            ["function_id"], ["baseline_functions.id"], name="fk_bpoints_function"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_bpoints_creator"),
        sa.CheckConstraint(
            "source_type IN ('manual','document_derived')", name="ck_bpoints_source"
        ),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_bpoints_status"),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_bpoints_function_name",
        "baseline_feature_points",
        ["function_id", "name"],
        unique=True,
    )

    op.create_table(
        "baseline_revisions",
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
            "structure_json",
            mysql.MEDIUMTEXT(),
            nullable=True,
            comment="通过时冻结的三级结构 JSON",
        ),
        sa.Column(
            "module_count", mysql.INTEGER(unsigned=True), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "function_count",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "feature_point_count",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "label_count", mysql.INTEGER(unsigned=True), nullable=False, server_default=sa.text("0")
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_brevisions_project"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], name="fk_brevisions_submitter"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_brevisions_reviewer"),
        sa.CheckConstraint(
            "status IN ('submitted','approved','rejected')", name="ck_brevisions_status"
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_brevisions_project_no", "baseline_revisions", ["project_id", "version_no"], unique=True
    )

    op.create_table(
        "baseline_labels",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("revision_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column(
            "target_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="功能或功能点 id（多态，不建外键）",
        ),
        sa.Column("label_type", sa.String(length=16), nullable=False),
        sa.Column("source_analysis_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("confirmed_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "confirmed_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column("cleared_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("cleared_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("clear_reason", sa.String(length=32), nullable=True),
        sa.Column("clear_note", sa.String(length=500), nullable=True),
        sa.Column(
            "active_key",
            sa.String(length=160),
            sa.Computed(LABEL_ACTIVE_KEY_EXPR, persisted=True),
            comment="生成列：active 时拼出唯一键，其余为 NULL",
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_blabels_project"),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["baseline_revisions.id"], name="fk_blabels_revision"
        ),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], name="fk_blabels_confirmer"),
        sa.ForeignKeyConstraint(["cleared_by"], ["users.id"], name="fk_blabels_clearer"),
        sa.CheckConstraint(
            "target_type IN ('function','feature_point')", name="ck_blabels_target_type"
        ),
        sa.CheckConstraint(
            "label_type IN ('new','changed','affected','unchanged')",
            name="ck_blabels_label_type",
        ),
        sa.CheckConstraint("status IN ('active','cleared')", name="ck_blabels_status"),
        **TABLE_OPTS,
    )
    op.create_index("uk_blabels_active", "baseline_labels", ["active_key"], unique=True)
    op.create_index("idx_blabels_target", "baseline_labels", ["target_type", "target_id"])
    op.create_index("idx_blabels_revision", "baseline_labels", ["revision_id"])

    op.add_column(
        "projects",
        sa.Column(
            "baseline_snapshot_max_count",
            mysql.INTEGER(unsigned=True),
            nullable=True,
            comment="基线快照保留上限，空 = 不启用（永久保留）",
        ),
    )


def downgrade() -> None:
    # 不逐个 drop_index：这些唯一索引同时承担外键的列索引，
    # 先删索引会报 1553（Cannot drop index needed in a foreign key constraint）。
    # 直接删表，索引随表一起消失。
    op.drop_column("projects", "baseline_snapshot_max_count")
    op.drop_table("baseline_labels")
    op.drop_table("baseline_revisions")
    op.drop_table("baseline_feature_points")
    op.drop_table("baseline_functions")
    op.drop_table("baseline_modules")
