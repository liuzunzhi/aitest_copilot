"""项目概览（T36，AC-40）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.project import Project, ProjectMember
from app.models.user import User

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"overview-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _project(db: Session, *, status: str = "active") -> Project:
    project = Project(name=f"overview-{uuid.uuid4().hex[:6]}", status=status)
    db.add(project)
    db.flush()
    return project


def _join(db: Session, project: Project, user: User, role: str) -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def _auth(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _url(project: Project) -> str:
    return f"/api/projects/{project.id}/overview"


@pytest.mark.parametrize("role", ["project_admin", "member", "guest"])
def test_ac_40_member_can_read_overview(
    client: TestClient, db: Session, role: str
) -> None:
    """成员数取真实行数，其余字段为占位值。"""
    project = _project(db)
    viewer = _user(db)
    _join(db, project, viewer, role)
    _join(db, project, _user(db), "member")
    _join(db, project, _user(db), "guest")

    response = client.get(_url(project), headers=_auth(client, viewer))

    assert response.status_code == 200
    assert response.json() == {
        "member_count": 3,
        "document_count": 0,
        "baseline_count": 0,
        "latest_execution": None,
    }


def test_ac_40_system_admin_can_read_without_membership(
    client: TestClient, db: Session
) -> None:
    project = _project(db)
    _join(db, project, _user(db), "project_admin")
    admin = _user(db, global_role="system_admin")

    response = client.get(_url(project), headers=_auth(client, admin))

    assert response.status_code == 200
    assert response.json()["member_count"] == 1


def test_ac_40_non_member_forbidden(client: TestClient, db: Session) -> None:
    project = _project(db)
    _join(db, project, _user(db), "project_admin")
    outsider = _user(db)

    response = client.get(_url(project), headers=_auth(client, outsider))

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_40_archived_project_still_readable(
    client: TestClient, db: Session
) -> None:
    project = _project(db, status="archived")
    viewer = _user(db)
    _join(db, project, viewer, "member")

    response = client.get(_url(project), headers=_auth(client, viewer))

    assert response.status_code == 200


def test_ac_40_requires_login(client: TestClient, db: Session) -> None:
    project = _project(db)

    response = client.get(_url(project))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
