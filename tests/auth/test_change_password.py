"""改密接口（管理员重置后的强制首登修改）。"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.system import AuditLog
from app.models.user import User

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)

LOGIN = "/api/auth/login"
CHANGE = "/api/auth/password/change"
PROJECTS = "/api/projects"


def _user(db: Session, *, must_change_password: bool = False) -> User:
    user = User(
        username=f"chg-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.flush()
    return user


def _login(client: TestClient, user: User, password: str = PASSWORD) -> dict:
    response = client.post(LOGIN, json={"username": user.username, "password": password})
    assert response.status_code == 200
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_change_requires_login(client: TestClient):
    response = client.post(
        CHANGE, json={"old_password": PASSWORD, "new_password": "Newpass123"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_forced_change_unlocks_other_endpoints(client: TestClient, db: Session):
    user = _user(db, must_change_password=True)
    body = _login(client, user)
    assert body["must_change_password"] is True
    token = body["access_token"]

    blocked = client.get(PROJECTS, headers=_headers(token))
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    changed = client.post(
        CHANGE,
        json={"old_password": PASSWORD, "new_password": "Newpass123"},
        headers=_headers(token),
    )

    assert changed.status_code == 200
    assert client.get(PROJECTS, headers=_headers(token)).status_code == 200

    db.expire_all()
    assert db.get(User, user.id).must_change_password is False
    assert db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "password.change",
            AuditLog.target_id == str(user.id),
        )
    ).scalar_one() == 1

    assert _login(client, user, "Newpass123")["must_change_password"] is False


def test_wrong_old_password(client: TestClient, db: Session):
    user = _user(db, must_change_password=True)
    token = _login(client, user)["access_token"]

    response = client.post(
        CHANGE,
        json={"old_password": "WrongPass1", "new_password": "Newpass123"},
        headers=_headers(token),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    db.expire_all()
    assert db.get(User, user.id).must_change_password is True


def test_weak_new_password(client: TestClient, db: Session):
    user = _user(db, must_change_password=True)
    token = _login(client, user)["access_token"]

    response = client.post(
        CHANGE,
        json={"old_password": PASSWORD, "new_password": "short1"},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "WEAK_PASSWORD"
    db.expire_all()
    assert db.get(User, user.id).must_change_password is True


def test_change_revokes_other_devices(client: TestClient, db: Session):
    user = _user(db)
    current = _login(client, user)["access_token"]
    other_device = _login(client, user)["access_token"]

    response = client.post(
        CHANGE,
        json={"old_password": PASSWORD, "new_password": "Newpass123"},
        headers=_headers(current),
    )

    assert response.status_code == 200
    assert client.get(PROJECTS, headers=_headers(current)).status_code == 200
    revoked = client.get(PROJECTS, headers=_headers(other_device))
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "TOKEN_REVOKED"


def test_normal_user_can_change_password(client: TestClient, db: Session):
    user = _user(db)
    token = _login(client, user)["access_token"]

    response = client.post(
        CHANGE,
        json={"old_password": PASSWORD, "new_password": "Newpass123"},
        headers=_headers(token),
    )

    assert response.status_code == 200
    assert client.post(
        LOGIN, json={"username": user.username, "password": PASSWORD}
    ).status_code == 401
    assert client.post(
        LOGIN, json={"username": user.username, "password": "Newpass123"}
    ).status_code == 200
