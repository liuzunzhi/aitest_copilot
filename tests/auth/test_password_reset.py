"""密码找回与重置（T17，AC-12）。

验证码只存在 Redis，没有邮件/短信通道，所以用例从 Redis 读码，
不为了测试在接口里回显验证码。
"""

import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.captcha import get_redis
from app.common.security import hash_password, verify_password
from app.models.system import AuditLog
from app.models.token import AccessToken
from app.models.user import User

SEND_CODE = "/api/auth/password/send-code"
RESET = "/api/auth/password/reset"
LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"

PASSWORD = "Passw0rd"
NEW_PASSWORD = "NewPassw0rd"
PASSWORD_HASH = hash_password(PASSWORD)


def _user(db: Session, *, with_phone: bool = False) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"reset-{suffix}",
        password_hash=PASSWORD_HASH,
        email=f"reset-{suffix}@example.com",
        phone=f"137{suffix[:8]}" if with_phone else None,
    )
    db.add(user)
    db.flush()
    return user


def _request_code(client: TestClient, contact: str) -> None:
    response = client.post(SEND_CODE, json={"contact": contact})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _read_code(contact: str) -> str:
    code = get_redis().get(f"pwdreset:code:{contact}")
    assert code is not None, "验证码未写入 Redis"
    return code


def _login(client: TestClient, username: str, password: str = PASSWORD) -> str:
    response = client.post(LOGIN, json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_ac_12_send_code(client: TestClient, db: Session):
    """存在与不存在的联系人响应完全一致，且都会写入限流与验证码。"""
    user = _user(db)
    unknown = f"ghost-{uuid.uuid4().hex[:8]}@example.com"

    _request_code(client, user.email)
    _request_code(client, unknown)

    assert _read_code(user.email)
    assert _read_code(unknown)


def test_ac_12_send_code_rate_limited(client: TestClient, db: Session):
    """60s 内重复发送 429；不存在的联系人也一样，避免成为枚举通道。"""
    user = _user(db)
    unknown = f"ghost-{uuid.uuid4().hex[:8]}@example.com"

    _request_code(client, user.email)
    _request_code(client, unknown)

    again = client.post(SEND_CODE, json={"contact": user.email})
    assert again.status_code == 429
    assert again.json()["code"] == "RATE_LIMITED"

    again_unknown = client.post(SEND_CODE, json={"contact": unknown})
    assert again_unknown.status_code == 429
    assert again_unknown.json()["code"] == "RATE_LIMITED"


def test_ac_12_reset_invalidates_all_tokens(client: TestClient, db: Session):
    """重置成功：密码更新、password_changed_at 变化、旧 token 全部失效、写审计。"""
    user = _user(db)
    first_token = _login(client, user.username)
    second_token = _login(client, user.username)
    _request_code(client, user.email)
    code = _read_code(user.email)

    response = client.post(
        RESET,
        json={"contact": user.email, "code": code, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200

    db.refresh(user)
    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert not verify_password(PASSWORD, user.password_hash)
    assert user.password_changed_at.date() >= date(2026, 1, 1)

    revoked = db.execute(
        select(func.count())
        .select_from(AccessToken)
        .where(AccessToken.user_id == user.id, AccessToken.revoked_at.is_not(None))
    ).scalar_one()
    assert revoked == 2

    for token in (first_token, second_token):
        reuse = client.post(LOGOUT, headers={"Authorization": f"Bearer {token}"})
        assert reuse.status_code == 401
        assert reuse.json()["code"] == "TOKEN_REVOKED"

    audits = db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "password.reset", AuditLog.actor_id == user.id)
    ).scalar_one()
    assert audits == 1

    # 新密码可登录，旧密码不可
    assert _login(client, user.username, NEW_PASSWORD)
    old = client.post(LOGIN, json={"username": user.username, "password": PASSWORD})
    assert old.status_code == 401


def test_ac_12_reset_with_code_sent_to_phone(client: TestClient, db: Session):
    user = _user(db, with_phone=True)
    _request_code(client, user.phone)
    code = _read_code(user.phone)

    response = client.post(
        RESET,
        json={"contact": user.phone, "code": code, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    db.refresh(user)
    assert verify_password(NEW_PASSWORD, user.password_hash)


def test_ac_12_weak_new_password(client: TestClient, db: Session):
    """弱密码 400，且验证码不被消耗——用户换强密码可以继续用。"""
    user = _user(db)
    _request_code(client, user.email)
    code = _read_code(user.email)

    response = client.post(
        RESET,
        json={"contact": user.email, "code": code, "new_password": "weakpass"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "WEAK_PASSWORD"
    assert _read_code(user.email) == code

    ok = client.post(
        RESET,
        json={"contact": user.email, "code": code, "new_password": NEW_PASSWORD},
    )
    assert ok.status_code == 200


def test_ac_12_wrong_code(client: TestClient, db: Session):
    user = _user(db)
    _request_code(client, user.email)

    response = client.post(
        RESET,
        json={"contact": user.email, "code": "000000", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_RESET_CODE"
    db.refresh(user)
    assert not verify_password(NEW_PASSWORD, user.password_hash)


def test_ac_12_unknown_contact(client: TestClient):
    unknown = f"ghost-{uuid.uuid4().hex[:8]}@example.com"
    _request_code(client, unknown)

    response = client.post(
        RESET,
        json={
            "contact": unknown,
            "code": _read_code(unknown),
            "new_password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_RESET_CODE"


def test_ac_12_code_single_use(client: TestClient, db: Session):
    user = _user(db)
    _request_code(client, user.email)
    code = _read_code(user.email)
    payload = {"contact": user.email, "code": code, "new_password": NEW_PASSWORD}

    assert client.post(RESET, json=payload).status_code == 200

    again = client.post(RESET, json={**payload, "new_password": "AnotherPass1"})
    assert again.status_code == 400
    assert again.json()["code"] == "INVALID_RESET_CODE"
