"""baseline review rounds / items（分点审核）

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-18

04 补期 A（T93）：局部通过 / 局部驳回的过程记录。

- `baseline_review_rounds`：一轮审核（同一 revision 被驳回后再提 → 新一轮）；
- `baseline_review_items`：逐项决策，`(round_id, entity_type, entity_id)` 唯一。

`baseline_revisions.structure_json` 格式**不动**，结构表**不加**状态列。
**无种子数据**。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}


def upgrade() -> None:
    op.create_table(
        "baseline_review_rounds",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("revision_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("round_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("submitted_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("reviewed_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("summary_comment", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_rrounds_project"),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["baseline_revisions.id"],
            name="fk_rrounds_revision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["users.id"], name="fk_rrounds_submitter"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name="fk_rrounds_reviewer"
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')", name="ck_rrounds_status"
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_rrounds_revision_no",
        "baseline_review_rounds",
        ["revision_id", "round_no"],
        unique=True,
    )
    op.create_index("idx_rrounds_project", "baseline_review_rounds", ["project_id"])
    op.create_index(
        "idx_rrounds_project_status",
        "baseline_review_rounds",
        ["project_id", "status"],
    )

    op.create_table(
        "baseline_review_items",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("round_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("revision_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("entity_name", sa.String(length=128), nullable=False),
        sa.Column(
            "decision",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("decided_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("decided_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_ritems_project"),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["baseline_review_rounds.id"],
            name="fk_ritems_round",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["baseline_revisions.id"],
            name="fk_ritems_revision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name="fk_ritems_decider"),
        sa.CheckConstraint(
            "entity_type IN ('module','function','feature_point')",
            name="ck_ritems_entity_type",
        ),
        sa.CheckConstraint(
            "decision IN ('pending','approved','rejected')",
            name="ck_ritems_decision",
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_ritems_round_entity",
        "baseline_review_items",
        ["round_id", "entity_type", "entity_id"],
        unique=True,
    )
    op.create_index(
        "idx_ritems_round_decision",
        "baseline_review_items",
        ["round_id", "decision"],
    )
    op.create_index(
        "idx_ritems_project_entity",
        "baseline_review_items",
        ["project_id", "entity_type", "entity_id"],
    )


def downgrade() -> None:
    op.drop_table("baseline_review_items")
    op.drop_table("baseline_review_rounds")
