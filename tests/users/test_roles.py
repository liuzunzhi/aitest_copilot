"""全局角色分配与即时生效（T41，AC-45 / AC-46）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.system import AuditLog
from app.models.user import User

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)

USERS = "/api/admin/users"
ROLE = "/api/admin/users/{uid}/role"


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"role-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _headers(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin(db: Session) -> User:
    return _user(db, global_role="system_admin")


def test_ac_45_promote_writes_audit(client: TestClient, db: Session, admin: User):
    target = _user(db)

    response = client.patch(
        ROLE.format(uid=target.id),
        json={"global_role": "system_admin"},
        headers=_headers(client, admin),
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": target.id,
        "username": target.username,
        "global_role": "system_admin",
    }

    db.expire_all()
    assert db.get(User, target.id).global_role == "system_admin"
    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "user.role.change")
    ).scalar_one()
    assert audit.actor_id == admin.id
    assert audit.target_id == str(target.id)
    assert audit.before_data == {"global_role": "user"}
    assert audit.after_data == {"global_role": "system_admin"}


def test_ac_45_demote(client: TestClient, db: Session, admin: User):
    target = _user(db, global_role="system_admin")

    response = client.patch(
        ROLE.format(uid=target.id),
        json={"global_role": "user"},
        headers=_headers(client, admin),
    )

    assert response.status_code == 200
    assert response.json()["global_role"] == "user"

    db.expire_all()
    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "user.role.change")
    ).scalar_one()
    assert audit.before_data == {"global_role": "system_admin"}
    assert audit.after_data == {"global_role": "user"}


@pytest.mark.parametrize("role", ["owner", "project_admin", None])
def test_ac_45_invalid_global_role(
    client: TestClient, db: Session, admin: User, role
):
    target = _user(db)
    payload = {} if role is None else {"global_role": role}

    response = client.patch(
        ROLE.format(uid=target.id), json=payload, headers=_headers(client, admin)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_GLOBAL_ROLE"


def test_ac_45_user_not_found(client: TestClient, db: Session, admin: User):
    response = client.patch(
        ROLE.format(uid=999999999),
        json={"global_role": "user"},
        headers=_headers(client, admin),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_ac_45_cannot_change_own_role(
    client: TestClient, db: Session, admin: User
):
    response = client.patch(
        ROLE.format(uid=admin.id),
        json={"global_role": "user"},
        headers=_headers(client, admin),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "CANNOT_CHANGE_OWN_ROLE"

    db.expire_all()
    assert db.get(User, admin.id).global_role == "system_admin"


def test_ac_45_regular_user_forbidden(client: TestClient, db: Session):
    actor = _user(db)
    target = _user(db)

    response = client.patch(
        ROLE.format(uid=target.id),
        json={"global_role": "system_admin"},
        headers=_headers(client, actor),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_ac_45_same_role_does_not_write_audit(
    client: TestClient, db: Session, admin: User
):
    target = _user(db)

    response = client.patch(
        ROLE.format(uid=target.id),
        json={"global_role": "user"},
        headers=_headers(client, admin),
    )

    assert response.status_code == 200
    assert (
        db.execute(
            select(AuditLog).where(AuditLog.action == "user.role.change")
        ).first()
        is None
    )


def test_ac_46_role_change_takes_effect_on_existing_token(
    client: TestClient, db: Session, admin: User
):
    """同一枚令牌：提升后立即可访问，降级后立即 403，全程不重新登录。"""
    target = _user(db)
    token = _headers(client, target)
    assert client.get(USERS, headers=token).status_code == 403

    client.patch(
        ROLE.format(uid=target.id),
        json={"global_role": "system_admin"},
        headers=_headers(client, admin),
    )
    assert client.get(USERS, headers=token).status_code == 200

    client.patch(
        ROLE.format(uid=target.id),
        json={"global_role": "user"},
        headers=_headers(client, admin),
    )
    downgraded = client.get(USERS, headers=token)
    assert downgraded.status_code == 403
    assert downgraded.json()["code"] == "FORBIDDEN"


def test_ac_45_requires_login(client: TestClient, db: Session):
    target = _user(db)

    response = client.patch(
        ROLE.format(uid=target.id), json={"global_role": "system_admin"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


ADMIN_CALLS = [
    ("get", "/api/admin/users", None),
    ("patch", "/api/admin/users/{uid}/status", {"status": "disabled"}),
    ("patch", "/api/admin/users/{uid}/password", None),
    ("patch", "/api/admin/users/{uid}/role", {"global_role": "system_admin"}),
    ("get", "/api/admin/applications", None),
]


@pytest.mark.parametrize("method,url,payload", ADMIN_CALLS)
def test_ac_48_regular_user_forbidden(
    client: TestClient, db: Session, method: str, url: str, payload
):
    """普通用户跑全部 /api/admin/* 一律 403 FORBIDDEN。"""
    target = _user(db)
    actor = _user(db)
    request = getattr(client, method)

    if payload is None:
        response = request(url.format(uid=target.id), headers=_headers(client, actor))
    else:
        response = request(
            url.format(uid=target.id),
            json=payload,
            headers=_headers(client, actor),
        )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


@pytest.mark.parametrize("method,url,payload", ADMIN_CALLS)
def test_ac_48_requires_login(
    client: TestClient, db: Session, method: str, url: str, payload
):
    target = _user(db)
    request = getattr(client, method)

    if payload is None:
        response = request(url.format(uid=target.id))
    else:
        response = request(url.format(uid=target.id), json=payload)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
