"""登出接口（T16，AC-07）。"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import clock as clock_module
from app.common.clock import FixedClock
from app.common.security import hash_password
from app.models.system import AuditLog
from app.models.token import AccessToken
from app.models.user import User

LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)


def _user(db: Session) -> User:
    user = User(
        username=f"logout-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
    )
    db.add(user)
    db.flush()
    return user


def _login(client: TestClient, username: str) -> str:
    response = client.post(LOGIN, json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token_row(db: Session, user_id: int) -> AccessToken:
    return db.execute(
        select(AccessToken).where(AccessToken.user_id == user_id)
    ).scalar_one()


def test_ac_07_logout_revokes_token(client: TestClient, db: Session):
    """200、revoked_at 落库、审计 logout；同一 token 再用返回 TOKEN_REVOKED。"""
    user = _user(db)
    token = _login(client, user.username)

    response = client.post(LOGOUT, headers=_auth(token))

    assert response.status_code == 200
    assert _token_row(db, user.id).revoked_at is not None

    audits = db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "logout", AuditLog.actor_id == user.id)
    ).scalar_one()
    assert audits == 1

    again = client.post(LOGOUT, headers=_auth(token))
    assert again.status_code == 401
    assert again.json()["code"] == "TOKEN_REVOKED"


def test_ac_07_logout_without_token(client: TestClient):
    response = client.post(LOGOUT)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_ac_07_logout_with_malformed_header(client: TestClient):
    response = client.post(LOGOUT, headers={"Authorization": "Basic abc"})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_ac_07_logout_with_unknown_token(client: TestClient):
    response = client.post(LOGOUT, headers=_auth("not-a-real-token"))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_ac_07_logout_with_expired_token(client: TestClient, db: Session, monkeypatch):
    fixed = FixedClock(datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(clock_module, "clock", fixed)
    user = _user(db)
    token = _login(client, user.username)

    fixed.advance(timedelta(hours=9))
    response = client.post(LOGOUT, headers=_auth(token))

    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"
