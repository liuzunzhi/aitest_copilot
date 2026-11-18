"""分点审核的轮次与逐项决策（04 补期 A · T93）。

两张表只记录**审核过程**，不碰快照格式：

- `baseline_review_rounds`：一轮审核（谁提的、何时决的、整体结论）；
- `baseline_review_items`：这一轮里每个实体的决策（`pending/approved/rejected`）。

`baseline_revisions.structure_json` 仍然是"一棵干净的冻结树"，
不加 `node_status`；结构表也不加状态列——状态属于轮次，不属于实体。
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

ROUND_STATUSES = ("pending", "approved", "rejected")
ITEM_DECISIONS = ("pending", "approved", "rejected")
ITEM_ENTITY_TYPES = ("module", "function", "feature_point")


class BaselineReviewRound(Base):
    """一轮审核。同一个 revision 多次提交（被驳回后再提）就有多轮。"""

    __tablename__ = "baseline_review_rounds"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_rrounds_project"),
        ForeignKeyConstraint(
            ["revision_id"],
            ["baseline_revisions.id"],
            name="fk_rrounds_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["submitted_by"], ["users.id"], name="fk_rrounds_submitter"
        ),
        ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name="fk_rrounds_reviewer"
        ),
        Index("uk_rrounds_revision_no", "revision_id", "round_no", unique=True),
        Index("idx_rrounds_project", "project_id"),
        Index("idx_rrounds_project_status", "project_id", "status"),
        CheckConstraint(
            "status IN ('pending','approved','rejected')", name="ck_rrounds_status"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    revision_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    round_no: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    submitted_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    summary_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class BaselineReviewItem(Base):
    """一轮里对一个实体的决策。

    `entity_name` 是**决策时快照**：实体后来改名，历史意见仍然对得上。
    `revision_id` 冗余一份，是为了"按快照查决策"不用回表 join 轮次。
    """

    __tablename__ = "baseline_review_items"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_ritems_project"),
        ForeignKeyConstraint(
            ["round_id"],
            ["baseline_review_rounds.id"],
            name="fk_ritems_round",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["revision_id"],
            ["baseline_revisions.id"],
            name="fk_ritems_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["decided_by"], ["users.id"], name="fk_ritems_decider"),
        Index(
            "uk_ritems_round_entity",
            "round_id",
            "entity_type",
            "entity_id",
            unique=True,
        ),
        Index("idx_ritems_round_decision", "round_id", "decision"),
        Index("idx_ritems_project_entity", "project_id", "entity_type", "entity_id"),
        CheckConstraint(
            "entity_type IN ('module','function','feature_point')",
            name="ck_ritems_entity_type",
        ),
        CheckConstraint(
            "decision IN ('pending','approved','rejected')",
            name="ck_ritems_decision",
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    round_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    revision_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = [
    "BaselineReviewItem",
    "BaselineReviewRound",
    "ITEM_DECISIONS",
    "ITEM_ENTITY_TYPES",
    "ROUND_STATUSES",
]
