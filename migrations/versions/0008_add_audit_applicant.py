"""add applicant_id to audit_logs

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-15

AC-25 要求审计可按 applicant_id 检索。此前只有 actor_id / target_id，
申请人维度无法直接查——审批人的 actor_id 不是申请人。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("applicant_id", mysql.BIGINT(unsigned=True), nullable=True),
    )
    op.create_index(
        "idx_audit_applicant", "audit_logs", ["applicant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_audit_applicant", table_name="audit_logs")
    op.drop_column("audit_logs", "applicant_id")
