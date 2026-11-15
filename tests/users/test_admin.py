"""管理员用户管理（T25，AC-03）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.system import AuditLog
from app.models.user import User

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)

USERS = "/api/admin/users"
STATUS = "/api/admin/users/{uid}/status"
PASSWORD_API = "/api/admin/users/{uid}/password"
PROJECTS = "/api/projects"


def _user(db: Session, *, global_role: str = "user", status: str = "active") -> User:
    user = User(
        username=f"admin-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
        status=status,
    )
    db.add(user)
    db.flush()
    return user


def _headers(client: TestClient, user: User, password: str = PASSWORD) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": password}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin(db: Session) -> User:
    return _user(db, global_role="system_admin")


def test_list_users(client: TestClient, db: Session, admin: User):
    victim = _user(db)

    response = client.get(USERS, headers=_headers(client, admin))

    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body]
    assert admin.id in ids and victim.id in ids
    assert "password_hash" not in body[0]


def test_list_forbidden_for_regular_user(client: TestClient, db: Session):
    user = _user(db)

    response = client.get(USERS, headers=_headers(client, user))

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_list_requires_login(client: TestClient):
    assert client.get(USERS).status_code == 401


def test_ac_03_disable_invalidates_issued_token(
    client: TestClient, db: Session, admin: User
):
    """AC-03：禁用后旧 token 立即失效，且不再能登录。"""
    victim = _user(db)
    victim_headers = _headers(client, victim)
    assert client.get(PROJECTS, headers=victim_headers).status_code == 200

    response = client.patch(
        STATUS.format(uid=victim.id),
        json={"status": "disabled"},
        headers=_headers(client, admin),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "disabled"}

    blocked = client.get(PROJECTS, headers=victim_headers)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "ACCOUNT_DISABLED"

    relogin = client.post(
        "/api/auth/login", json={"username": victim.username, "password": PASSWORD}
    )
    assert relogin.status_code == 403
    assert relogin.json()["code"] == "ACCOUNT_DISABLED"

    audit = db.execute(
        select(AuditLog).where(
            AuditLog.action == "user.disable",
            AuditLog.target_id == str(victim.id),
        )
    ).scalar_one()
    assert audit.before_data == {"status": "active"}
    assert audit.after_data == {"status": "disabled"}


def test_enable_restores_access(client: TestClient, db: Session, admin: User):
    """状态是唯一开关：重新启用后旧 token 随状态恢复可用。"""
    victim = _user(db)
    old_headers = _headers(client, victim)
    headers = _headers(client, admin)
    assert (
        client.patch(
            STATUS.format(uid=victim.id), json={"status": "disabled"}, headers=headers
        ).status_code
        == 200
    )

    enabled = client.patch(
        STATUS.format(uid=victim.id), json={"status": "active"}, headers=headers
    )

    assert enabled.status_code == 200
    assert enabled.json() == {"status": "active"}
    assert client.get(PROJECTS, headers=old_headers).status_code == 200
    assert client.post(
        "/api/auth/login", json={"username": victim.username, "password": PASSWORD}
    ).status_code == 200


def test_disable_unknown_user(client: TestClient, admin: User):
    response = client.patch(
        STATUS.format(uid=999_999_999),
        json={"status": "disabled"},
        headers=_headers(client, admin),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


@pytest.mark.parametrize("status", ["locked", None, "ACTIVE"])
def test_invalid_status(client: TestClient, db: Session, admin: User, status):
    victim = _user(db)

    response = client.patch(
        STATUS.format(uid=victim.id),
        json={"status": status},
        headers=_headers(client, admin),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_STATUS"


def test_admin_reset_password(client: TestClient, db: Session, admin: User):
    """管理员重置：随机临时密码只回显一次 + 强制首登改密。"""
    victim = _user(db)
    old_headers = _headers(client, victim)

    response = client.patch(
        PASSWORD_API.format(uid=victim.id), headers=_headers(client, admin)
    )

    assert response.status_code == 200
    body = response.json()
    temporary_password = body["temporary_password"]
    assert body["must_change_password"] is True
    assert len(temporary_password) >= 8
    assert any(char.isdigit() for char in temporary_password)
    assert any(char.isalpha() for char in temporary_password)

    # 旧令牌已吊销，旧密码失效
    assert client.get(PROJECTS, headers=old_headers).json()["code"] == "TOKEN_REVOKED"
    assert client.post(
        "/api/auth/login", json={"username": victim.username, "password": PASSWORD}
    ).status_code == 401

    # 临时密码可登录，但登录响应要求先改密
    relogin = client.post(
        "/api/auth/login",
        json={"username": victim.username, "password": temporary_password},
    )
    assert relogin.status_code == 200
    assert relogin.json()["must_change_password"] is True
    temp_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}

    blocked = client.get(PROJECTS, headers=temp_headers)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    changed = client.post(
        "/api/auth/password/change",
        json={"old_password": temporary_password, "new_password": "Newpass123"},
        headers=temp_headers,
    )
    assert changed.status_code == 200
    assert client.get(PROJECTS, headers=temp_headers).status_code == 200

    final = client.post(
        "/api/auth/login",
        json={"username": victim.username, "password": "Newpass123"},
    )
    assert final.status_code == 200
    assert final.json()["must_change_password"] is False

    assert db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "user.password.reset",
            AuditLog.target_id == str(victim.id),
        )
    ).scalar_one() == 1


def test_admin_reset_unknown_user(client: TestClient, admin: User):
    response = client.patch(
        PASSWORD_API.format(uid=999_999_999), headers=_headers(client, admin)
    )

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_admin_endpoints_forbidden_for_regular_user(client: TestClient, db: Session):
    user = _user(db)
    victim = _user(db)
    headers = _headers(client, user)

    status_response = client.patch(
        STATUS.format(uid=victim.id), json={"status": "disabled"}, headers=headers
    )
    password_response = client.patch(
        PASSWORD_API.format(uid=victim.id), headers=headers
    )

    assert status_response.status_code == 403
    assert password_response.status_code == 403
