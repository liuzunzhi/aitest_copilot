"""项目申请模型。"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

PENDING_KEY_EXPR = "IF(status = 'pending', CONCAT(project_id, ':', applicant_id), NULL)"


class ProjectApplication(Base):
    """用户加入项目的申请。

    MySQL 不支持条件唯一索引，用 STORED 生成列 `pending_key` 替代：
    只有 pending 记录生成非 NULL 值，从而由唯一索引保证
    「同一用户在同一项目仅一条 pending」；终态记录生成 NULL，
    多个 NULL 不冲突，冷却后可直接新建记录再申请。
    """

    __tablename__ = "project_applications"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_app_project"),
        ForeignKeyConstraint(["applicant_id"], ["users.id"], name="fk_app_user"),
        Index("uk_app_pending", "pending_key", unique=True),
        Index("idx_app_project", "project_id", "status"),
        Index("idx_app_applicant", "applicant_id", "created_at"),
        CheckConstraint(
            "status IN ('pending','approved','rejected','withdrawn','closed')",
            name="ck_app_status",
        ),
        CheckConstraint("desired_role IN ('member','guest')", name="ck_app_role"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    applicant_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    desired_role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    reviewer_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    pending_key: Mapped[str | None] = mapped_column(
        String(64), Computed(PENDING_KEY_EXPR, persisted=True)
    )


__all__ = ["PENDING_KEY_EXPR", "ProjectApplication"]
