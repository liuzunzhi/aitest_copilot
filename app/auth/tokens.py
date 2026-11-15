"""访问令牌：签发、校验、吊销。

明文 token 只返回客户端一次，库里只存 sha256 十六进制。
不用 JWT：登出（AC-07）、改密（AC-12）、禁用账号（AC-03）都要求立即失效，
无状态令牌反而要再加一张黑名单表，复杂度更高。
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.clock import utcnow_naive
from app.models.token import AccessToken
from app.models.user import User

TOKEN_BYTES = 32


class TokenError(Exception):
    """令牌校验失败基类，由上层映射为 401。"""


class InvalidToken(TokenError):
    """令牌不存在或为空。"""


class TokenRevoked(TokenError):
    """令牌已吊销（登出、改密、禁用）。"""


class TokenExpired(TokenError):
    """令牌已过期。"""


def hash_token(token: str) -> str:
    """令牌的 sha256 十六进制，库中只存这个。"""
    return hashlib.sha256(token.encode()).hexdigest()


def issue(
    session: Session,
    user_id: int,
    ttl_seconds: int,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> str:
    """签发令牌，返回明文。明文只在这里出现一次。"""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    issued_at = utcnow_naive()
    session.add(
        AccessToken(
            user_id=user_id,
            token_hash=hash_token(token),
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=ttl_seconds),
            user_agent=user_agent,
            ip=ip,
        )
    )
    session.flush()
    return token


def resolve(session: Session, token: str) -> tuple[User, AccessToken]:
    """校验令牌并返回 (用户, 令牌记录)。

    这里只管令牌自身三态：命中、未吊销、未过期。
    「用户是否 active」由 `deps.current_user` 判定（T18），
    避免同一个校验逻辑分散在两处。
    """
    if not token:
        raise InvalidToken

    row = session.execute(
        select(AccessToken, User)
        .join(User, User.id == AccessToken.user_id)
        .where(AccessToken.token_hash == hash_token(token))
    ).first()

    if row is None:
        raise InvalidToken

    token_row, user = row
    if token_row.revoked_at is not None:
        raise TokenRevoked
    if token_row.expires_at <= utcnow_naive():
        raise TokenExpired
    return user, token_row


def revoke(session: Session, token: str) -> bool:
    """吊销单个令牌。条件更新保证幂等，返回是否真的吊销了一条。"""
    result = session.execute(
        update(AccessToken)
        .where(
            AccessToken.token_hash == hash_token(token),
            AccessToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow_naive())
    )
    return result.rowcount == 1


def revoke_all(session: Session, user_id: int) -> int:
    """吊销该用户全部仍有效的令牌，返回影响条数。"""
    result = session.execute(
        update(AccessToken)
        .where(
            AccessToken.user_id == user_id,
            AccessToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow_naive())
    )
    return result.rowcount


__all__ = [
    "InvalidToken",
    "TOKEN_BYTES",
    "TokenError",
    "TokenExpired",
    "TokenRevoked",
    "hash_token",
    "issue",
    "resolve",
    "revoke",
    "revoke_all",
]
