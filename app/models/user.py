"""用户模型。"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class User(Base):
    """平台用户。

    只有 active / disabled 两态——注册即激活，不存在待审批状态。
    系统管理员身份由 `global_role` 承载，项目内角色在 project_members。
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("uk_users_username", "username", unique=True),
        Index("uk_users_email", "email", unique=True),
        Index("uk_users_phone", "phone", unique=True),
        CheckConstraint("status IN ('active','disabled')", name="ck_users_status"),
        CheckConstraint("global_role IN ('user','system_admin')", name="ck_users_role"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False, comment="bcrypt")
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    global_role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'user'")
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), comment="管理员重置后强制改密"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
    )


__all__ = ["User"]
