"""访问令牌模型。"""

from datetime import datetime

from sqlalchemy import ForeignKeyConstraint, Index, String, text
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class AccessToken(Base):
    """不透明访问令牌。

    明文只返回客户端一次，库中只存 sha256 十六进制。
    `token_hash` 用 ascii_bin：十六进制只占 64 字节，比较区分大小写、不进校对规则。
    """

    __tablename__ = "access_tokens"
    __table_args__ = (
        ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_tokens_user"),
        Index("uk_tokens_hash", "token_hash", unique=True),
        Index("idx_tokens_user", "user_id", "revoked_at"),
        Index("idx_tokens_exp", "expires_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_default_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        CHAR(64, charset="ascii", collation="ascii_bin"),
        nullable=False,
        comment="sha256 十六进制",
    )
    issued_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True, comment="IPv4/IPv6")


__all__ = ["AccessToken"]
