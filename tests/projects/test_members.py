"""项目成员列表（T32，AC-35）。"""

import uuid
from datetime import datetime

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
        username=f"member-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _project(db: Session, *, status: str = "active") -> Project:
    project = Project(name=f"member-{uuid.uuid4().hex[:6]}", status=status)
    db.add(project)
    db.flush()
    return project


def _join(
    db: Session,
    project: Project,
    user: User,
    role: str,
    *,
    joined_at: datetime | None = None,
) -> ProjectMember:
    member = ProjectMember(project_id=project.id, user_id=user.id, role=role)
    if joined_at is not None:
        member.joined_at = joined_at
    db.add(member)
    db.flush()
    return member


def _auth(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _url(project: Project) -> str:
    return f"/api/projects/{project.id}/members"


@pytest.mark.parametrize("role", ["project_admin", "member", "guest"])
def test_ac_35_any_member_can_list(
    client: TestClient, db: Session, role: str
) -> None:
    """三种项目内角色都能读成员列表，字段只含约定的四项。"""
    project = _project(db)
    viewer = _user(db)
    _join(db, project, viewer, role)

    response = client.get(_url(project), headers=_auth(client, viewer))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    row = body[0]
    assert (row["user_id"], row["username"], row["role"]) == (
        viewer.id,
        viewer.username,
        role,
    )
    assert isinstance(row["joined_at"], str)
    assert set(row) == {"user_id", "username", "role", "joined_at"}


def test_ac_35_system_admin_can_list_without_membership(
    client: TestClient, db: Session
) -> None:
    project = _project(db)
    _join(db, project, _user(db), "project_admin")
    admin = _user(db, global_role="system_admin")

    response = client.get(_url(project), headers=_auth(client, admin))

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_ac_35_non_member_forbidden(client: TestClient, db: Session) -> None:
    project = _project(db)
    _join(db, project, _user(db), "project_admin")
    outsider = _user(db)

    response = client.get(_url(project), headers=_auth(client, outsider))

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_35_ordered_by_joined_at_then_user_id(
    client: TestClient, db: Session
) -> None:
    """先按加入时间升序，同一时刻按 user_id 升序，保证顺序稳定。"""
    project = _project(db)
    viewer = _user(db)
    later = _user(db)
    earliest = _user(db)
    tied_second = _user(db)
    _join(db, project, viewer, "project_admin", joined_at=datetime(2026, 1, 1))
    _join(db, project, later, "member", joined_at=datetime(2026, 1, 3))
    _join(db, project, earliest, "member", joined_at=datetime(2026, 1, 2))
    _join(db, project, tied_second, "guest", joined_at=datetime(2026, 1, 2))

    response = client.get(_url(project), headers=_auth(client, viewer))

    assert response.status_code == 200
    tied_first, tied_last = sorted([earliest, tied_second], key=lambda user: user.id)
    assert [row["user_id"] for row in response.json()] == [
        viewer.id,
        tied_first.id,
        tied_last.id,
        later.id,
    ]


def test_ac_35_archived_project_still_readable(
    client: TestClient, db: Session
) -> None:
    """AC-34：归档不影响读接口。"""
    project = _project(db, status="archived")
    viewer = _user(db)
    _join(db, project, viewer, "member")

    response = client.get(_url(project), headers=_auth(client, viewer))

    assert response.status_code == 200
    assert response.json()[0]["user_id"] == viewer.id


def test_ac_35_requires_login(client: TestClient, db: Session) -> None:
    project = _project(db)

    response = client.get(_url(project))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
