"""登录接口（T15，AC-01 ~ AC-05）。"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import service
from app.common import clock as clock_module
from app.common import settings as settings_service
from app.common.clock import FixedClock
from app.common.db import session_scope
from app.common.errors import InvalidCredentials
from app.common.security import hash_password
from app.common.settings import set_setting
from app.models.system import AuditLog
from app.models.token import AccessToken
from app.models.user import User

LOGIN = "/api/auth/login"

# 全模块复用同一份哈希：bcrypt cost 12 每次约 250ms，反复算会拖慢用例
PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture(autouse=True)
def clean_settings_cache():
    settings_service.cache_clear()
    yield
    settings_service.cache_clear()


def _user(db: Session, *, username: str | None = None, **fields) -> User:
    data = {
        "username": username or f"login-{uuid.uuid4().hex[:8]}",
        "password_hash": PASSWORD_HASH,
        "status": "active",
        "failed_login_count": 0,
    }
    data.update(fields)
    user = User(**data)
    db.add(user)
    db.flush()
    return user


def _state(db: Session, user_id: int) -> tuple[int, datetime | None]:
    row = db.execute(
        select(User.failed_login_count, User.locked_until).where(User.id == user_id)
    ).one()
    return row.failed_login_count, row.locked_until


def _audit_count(db: Session, action: str, user_id: int) -> int:
    return db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == action, AuditLog.target_id == str(user_id))
    ).scalar_one()


def test_ac_01_login_success(client: TestClient, db: Session):
    """200 + token（8h）、失败计数归零、审计 login.success。"""
    user = _user(db, failed_login_count=3)

    response = client.post(
        LOGIN, json={"username": user.username, "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]

    token_row = db.execute(
        select(AccessToken).where(AccessToken.user_id == user.id)
    ).scalar_one()
    assert token_row.expires_at - token_row.issued_at == timedelta(hours=8)

    expires_at = datetime.fromisoformat(body["expires_at"])
    # 响应时间与写库时间取的是两次 now()，允许毫秒级偏差
    assert abs(expires_at.replace(tzinfo=None) - token_row.expires_at) < timedelta(
        seconds=1
    )

    count, locked_until = _state(db, user.id)
    assert count == 0
    assert locked_until is None
    assert _audit_count(db, "login.success", user.id) == 1


def test_ac_02_invalid_credentials_identical(client: TestClient, db: Session):
    """密码错误与用户不存在响应完全一致；只有前者计数 +1。"""
    user = _user(db)

    wrong_password = client.post(
        LOGIN, json={"username": user.username, "password": "WrongPass1"}
    )
    unknown_user = client.post(
        LOGIN, json={"username": "ghost-user", "password": "WrongPass1"}
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert wrong_password.json()["code"] == "INVALID_CREDENTIALS"

    count, _ = _state(db, user.id)
    assert count == 1


def test_ac_03_disabled_account(client: TestClient, db: Session):
    """禁用账号密码正确也 403，且不增加失败计数。"""
    user = _user(db, status="disabled", failed_login_count=2)

    response = client.post(
        LOGIN, json={"username": user.username, "password": PASSWORD}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_DISABLED"

    count, _ = _state(db, user.id)
    assert count == 2
    assert _audit_count(db, "login.blocked.disabled", user.id) == 1


def test_ac_04_lock_then_unlock(client: TestClient, db: Session, monkeypatch):
    """连续 5 次失败锁定 30 分钟；锁定期内 423，到期后登录成功并审计解锁。"""
    fixed = FixedClock(datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(clock_module, "clock", fixed)
    user = _user(db)

    for attempt in range(5):
        response = client.post(
            LOGIN, json={"username": user.username, "password": "WrongPass1"}
        )
        assert response.status_code == 401, f"第 {attempt + 1} 次失败应为 401"

    count, locked_until = _state(db, user.id)
    assert count == 5
    assert locked_until == fixed.now().replace(tzinfo=None) + timedelta(minutes=30)
    assert _audit_count(db, "login.locked", user.id) == 1

    blocked = client.post(LOGIN, json={"username": user.username, "password": PASSWORD})
    assert blocked.status_code == 423
    blocked_body = blocked.json()
    assert blocked_body["code"] == "ACCOUNT_LOCKED"
    assert datetime.fromisoformat(blocked_body["unlock_at"]).replace(
        tzinfo=None
    ) == locked_until
    assert _state(db, user.id)[0] == 5

    fixed.advance(timedelta(minutes=31))
    unlocked = client.post(
        LOGIN, json={"username": user.username, "password": PASSWORD}
    )

    assert unlocked.status_code == 200
    count, locked_until = _state(db, user.id)
    assert count == 0
    assert locked_until is None
    assert _audit_count(db, "login.unlocked", user.id) == 1


def test_ac_04_threshold_is_configurable(client: TestClient, db: Session):
    """阈值来自 system_settings，改动后下一次登录立即生效。"""
    set_setting(db, "max_login_failures", 2)
    user = _user(db)

    for _ in range(2):
        client.post(LOGIN, json={"username": user.username, "password": "WrongPass1"})

    count, locked_until = _state(db, user.id)
    assert count == 2
    assert locked_until is not None

    blocked = client.post(LOGIN, json={"username": user.username, "password": PASSWORD})
    assert blocked.status_code == 423


def test_ac_04_concurrent_failures_are_counted():
    """并发失败不能丢计数，且锁定审计只写一条。

    这条用例必须真实提交（多连接并发），因此自己建用户、结束时清理。
    """
    username = f"race-{uuid.uuid4().hex[:8]}"
    with session_scope() as session:
        user = User(username=username, password_hash=PASSWORD_HASH)
        session.add(user)
        session.flush()
        user_id = user.id

    def attempt(_: int) -> bool:
        with session_scope() as session:
            try:
                service.login(session, username=username, password="WrongPass1")
            except InvalidCredentials:
                return True
            return False

    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(attempt, range(5)))

        assert all(results)
        with session_scope() as session:
            count, locked_until = session.execute(
                select(User.failed_login_count, User.locked_until).where(
                    User.id == user_id
                )
            ).one()
            assert count == 5
            assert locked_until is not None
            locked_audits = session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "login.locked",
                    AuditLog.target_id == str(user_id),
                )
            ).scalar_one()
            assert locked_audits == 1
    finally:
        with session_scope() as session:
            session.execute(
                text(
                    "DELETE FROM audit_logs WHERE target_id = :tid AND target_type = 'user'"
                ),
                {"tid": str(user_id)},
            )
            session.execute(
                text("DELETE FROM access_tokens WHERE user_id = :uid"), {"uid": user_id}
            )
            session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})


@pytest.mark.parametrize(
    "remember, expected",
    [(True, timedelta(days=30)), (False, timedelta(hours=8)), (None, timedelta(hours=8))],
    ids=["remember-true", "remember-false", "remember-absent"],
)
def test_ac_05_remember_ttl(
    client: TestClient, db: Session, remember: bool | None, expected: timedelta
):
    user = _user(db)
    payload: dict = {"username": user.username, "password": PASSWORD}
    if remember is not None:
        payload["remember"] = remember

    response = client.post(LOGIN, json=payload)

    assert response.status_code == 200
    token_row = db.execute(
        select(AccessToken).where(AccessToken.user_id == user.id)
    ).scalar_one()
    assert token_row.expires_at - token_row.issued_at == expected
