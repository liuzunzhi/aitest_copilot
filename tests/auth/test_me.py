"""当前登录用户接口（前端工程接入用）。

前端登录后需要知道用户名与全局角色，才能决定是否展示系统管理入口。
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.user import User

LOGIN = "/api/auth/login"
ME = "/api/auth/me"

PASSWORD = "Passw0rd"


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"me-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(PASSWORD),
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _token(client: TestClient, username: str) -> str:
    response = client.post(LOGIN, json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_me_returns_current_user(client: TestClient, db: Session) -> None:
    user = _user(db, global_role="system_admin")
    token = _token(client, user.username)

    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {
        "id": user.id,
        "username": user.username,
        "global_role": "system_admin",
        "must_change_password": False,
    }


def test_me_requires_token(client: TestClient) -> None:
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_me_allows_must_change_password_user(client: TestClient, db: Session) -> None:
    """待改密用户也要能读到自己的状态，否则前端无法引导改密。"""
    user = _user(db)
    user.must_change_password = True
    db.flush()
    token = _token(client, user.username)

    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
