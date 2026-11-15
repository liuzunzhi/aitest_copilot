"""系统配置与审计日志模型。"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class SystemSetting(Base):
    """键值配置。

    `value` 是 JSON 标量（布尔/数字）而非字符串，读侧按 `get_setting` 约定取类型。
    """

    __tablename__ = "system_settings"
    __table_args__ = (_TABLE_OPTS,)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
    )


class AuditLog(Base):
    """审计日志。

    刻意不建外键：`actor_id` / `project_id` 指向的对象可能已被删除，
    但审计记录必须留存；外键会连带阻塞删除或级联清空历史。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_project", "project_id", "created_at"),
        Index("idx_audit_actor", "actor_id", "created_at"),
        Index("idx_audit_applicant", "applicant_id", "created_at"),
        Index("idx_audit_action", "action", "created_at"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    applicant_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    project_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_data: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    after_data: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = ["AuditLog", "SystemSetting"]
