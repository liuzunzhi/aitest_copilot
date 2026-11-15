"""令牌服务（T13）。

要守住的三件事：明文只出现一次、库里只有 sha256、吊销/过期后 resolve 失败。
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.auth.tokens import (
    InvalidToken,
    TokenExpired,
    TokenRevoked,
    issue,
    resolve,
    revoke,
    revoke_all,
)
from app.common import clock as clock_module
from app.common.clock import FixedClock
from app.models.token import AccessToken
from app.models.user import User


def _user(db: Session, username: str = "token-user") -> User:
    user = User(username=username, password_hash="x" * 60)
    db.add(user)
    db.flush()
    return user


def test_issue_stores_only_hash(db: Session):
    """返回明文，库里只有 sha256，且过期时间晚于签发时间。"""
    user = _user(db)

    token = issue(db, user.id, 3600)

    assert isinstance(token, str) and token
    row = db.query(AccessToken).one()
    assert row.user_id == user.id
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.token_hash != token
    assert len(row.token_hash) == 64
    assert row.revoked_at is None
    assert row.expires_at > row.issued_at


def test_resolve_ok(db: Session):
    user = _user(db)
    token = issue(db, user.id, 3600)

    resolved_user, token_row = resolve(db, token)

    assert resolved_user.id == user.id
    assert token_row.user_id == user.id


def test_resolve_unknown_token(db: Session):
    """不存在的令牌与空令牌都按无效处理。"""
    with pytest.raises(InvalidToken):
        resolve(db, "no-such-token")

    with pytest.raises(InvalidToken):
        resolve(db, "")


def test_revoke_then_resolve_fails(db: Session):
    user = _user(db)
    token = issue(db, user.id, 3600)

    assert revoke(db, token) is True

    with pytest.raises(TokenRevoked):
        resolve(db, token)

    # 重复吊销幂等，不再命中未吊销记录
    assert revoke(db, token) is False


def test_revoke_unknown_token(db: Session):
    assert revoke(db, "no-such-token") is False


def test_expired_token_rejected(db: Session, monkeypatch):
    """过过期边界即拒绝，时间由 FixedClock 注入，不 sleep。"""
    fixed = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(clock_module, "clock", fixed)

    user = _user(db)
    token = issue(db, user.id, 60)

    fixed.advance(timedelta(seconds=59))
    assert resolve(db, token)[1].user_id == user.id

    fixed.advance(timedelta(seconds=2))
    with pytest.raises(TokenExpired):
        resolve(db, token)


def test_revoke_all(db: Session):
    """改密/禁用场景：该用户全部令牌一次性失效，其他用户不受影响。"""
    user = _user(db)
    other = _user(db, username="other-user")
    first = issue(db, user.id, 3600)
    second = issue(db, user.id, 3600)
    kept = issue(db, other.id, 3600)

    assert revoke_all(db, user.id) == 2

    with pytest.raises(TokenRevoked):
        resolve(db, first)
    with pytest.raises(TokenRevoked):
        resolve(db, second)
    assert resolve(db, kept)[0].id == other.id

    # 再吊销一次没有可作用的记录
    assert revoke_all(db, user.id) == 0
