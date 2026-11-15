"""鉴权与权限依赖（T18，AC-06 / AC-03）。

当前还没有业务接口消费这些依赖（T19/T20 才开始），
所以用例直接调用依赖函数——它们带 `Depends` 默认值，
显式传参即可绕过 FastAPI 的注入。
"""

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common import clock as clock_module
from app.common.clock import FixedClock
from app.common.deps import (
    bearer_token,
    auth_context,
    require_project_role,
    require_system_admin,
)
from app.common.errors import (
    AccountDisabled,
    Forbidden,
    TokenExpired,
    TokenRevoked,
    Unauthenticated,
)
from app.common.security import hash_password
from app.models.project import Project, ProjectMember
from app.models.user import User

LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"guard-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _token(client: TestClient, username: str) -> str:
    response = client.post(LOGIN, json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return response.json()["access_token"]


def _project(db: Session, owner: User) -> Project:
    project = Project(name=f"guard-project-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=owner.id, role="project_admin"))
    db.flush()
    return project


def test_disabled_user_token_rejected(client: TestClient, db: Session):
    """AC-03 的关键一环：禁用后旧 token 立即不能再用。"""
    user = _user(db)
    token = _token(client, user.username)

    user.status = "disabled"
    db.flush()

    with pytest.raises(AccountDisabled):
        auth_context(session=db, token=token)[0]


def test_active_user_token_accepted(client: TestClient, db: Session):
    user = _user(db)
    token = _token(client, user.username)

    assert auth_context(session=db, token=token)[0].id == user.id


def test_missing_and_malformed_token():
    """AC-06：不带 token 或格式不对都是 UNAUTHENTICATED。"""
    with pytest.raises(Unauthenticated):
        bearer_token(None)

    with pytest.raises(Unauthenticated):
        bearer_token("Basic abc")

    with pytest.raises(Unauthenticated):
        bearer_token("Bearer   ")


def test_unknown_token(db: Session):
    with pytest.raises(Unauthenticated):
        auth_context(session=db, token="not-a-real-token")


def test_expired_token(client: TestClient, db: Session, monkeypatch):
    """AC-06：超时后 401 TOKEN_EXPIRED。"""
    fixed = FixedClock(datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(clock_module, "clock", fixed)
    user = _user(db)
    token = _token(client, user.username)

    fixed.advance(timedelta(hours=9))

    with pytest.raises(TokenExpired):
        auth_context(session=db, token=token)[0]


def test_revoked_token(client: TestClient, db: Session):
    """AC-07：登出后 token 立即失效。"""
    user = _user(db)
    token = _token(client, user.username)
    client.post(LOGOUT, headers={"Authorization": f"Bearer {token}"})

    with pytest.raises(TokenRevoked):
        auth_context(session=db, token=token)[0]


def test_require_system_admin(db: Session):
    admin = _user(db, global_role="system_admin")
    normal = _user(db)

    assert require_system_admin(user=admin).id == admin.id

    with pytest.raises(Forbidden):
        require_system_admin(user=normal)


def test_require_project_role(db: Session):
    owner = _user(db)
    outsider = _user(db)
    project = _project(db, owner)
    admin_only: Callable[..., ProjectMember] = require_project_role("project_admin")

    member = admin_only(project_id=project.id, session=db, user=owner)
    assert (member.project_id, member.user_id) == (project.id, owner.id)

    with pytest.raises(Forbidden):
        admin_only(project_id=project.id, session=db, user=outsider)


def test_require_project_role_rejects_wrong_role(db: Session):
    user = _user(db)
    project = Project(name=f"guard-project-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="guest"))
    db.flush()

    with pytest.raises(Forbidden):
        require_project_role("member", "project_admin")(
            project_id=project.id, session=db, user=user
        )
