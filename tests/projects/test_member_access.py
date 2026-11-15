"""项目内管理接口的成员边界（T42，AC-47）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.project import Project, ProjectMember
from app.models.user import User

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)

READ_PATHS = ("members", "overview")


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"access-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _project(db: Session) -> Project:
    project = Project(name=f"access-{uuid.uuid4().hex[:6]}")
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


@pytest.mark.parametrize("role", ["member", "guest"])
@pytest.mark.parametrize("path", READ_PATHS)
def test_ac_47_member_reads_allowed(
    client: TestClient, db: Session, role: str, path: str
) -> None:
    project = _project(db)
    viewer = _user(db)
    _join(db, project, viewer, role)

    response = client.get(
        f"/api/projects/{project.id}/{path}", headers=_auth(client, viewer)
    )

    assert response.status_code == 200


@pytest.mark.parametrize("path", READ_PATHS + ("applications",))
def test_ac_47_outsider_reads_forbidden(
    client: TestClient, db: Session, path: str
) -> None:
    """非成员访问读接口统一 NOT_PROJECT_MEMBER，不泄露项目是否存在。"""
    project = _project(db)
    outsider = _user(db)

    response = client.get(
        f"/api/projects/{project.id}/{path}", headers=_auth(client, outsider)
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


@pytest.mark.parametrize("role", ["member", "guest"])
def test_ac_47_applications_requires_project_admin(
    client: TestClient, db: Session, role: str
) -> None:
    project = _project(db)
    viewer = _user(db)
    _join(db, project, viewer, role)

    response = client.get(
        f"/api/projects/{project.id}/applications", headers=_auth(client, viewer)
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def _member_writes(client: TestClient, project: Project, headers: dict, target: User):
    base = f"/api/projects/{project.id}/members"
    return [
        client.post(base, json={"user_id": target.id, "role": "member"}, headers=headers),
        client.patch(
            f"{base}/{target.id}", json={"role": "guest"}, headers=headers
        ),
        client.delete(f"{base}/{target.id}", headers=headers),
    ]


@pytest.mark.parametrize("role", ["member", "guest"])
def test_ac_47_member_cannot_write(
    client: TestClient, db: Session, role: str
) -> None:
    project = _project(db)
    viewer = _user(db)
    _join(db, project, viewer, role)
    target = _user(db)

    for response in _member_writes(client, project, _auth(client, viewer), target):
        assert response.status_code == 403
        assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_47_outsider_cannot_write(client: TestClient, db: Session) -> None:
    """非成员写接口 403，具体 code 允许 NOT_PROJECT_MEMBER / NOT_PROJECT_ADMIN。"""
    project = _project(db)
    outsider = _user(db)
    target = _user(db)

    for response in _member_writes(client, project, _auth(client, outsider), target):
        assert response.status_code == 403
        assert response.json()["code"] in {
            "NOT_PROJECT_MEMBER",
            "NOT_PROJECT_ADMIN",
        }


@pytest.mark.parametrize("role", ["member", "guest"])
def test_ac_47_member_cannot_edit_or_archive(
    client: TestClient, db: Session, role: str
) -> None:
    project = _project(db)
    viewer = _user(db)
    _join(db, project, viewer, role)
    headers = _auth(client, viewer)

    edit = client.patch(
        f"/api/projects/{project.id}", json={"name": "改名"}, headers=headers
    )
    archive = client.post(f"/api/projects/{project.id}/archive", headers=headers)

    assert edit.status_code == 403
    assert edit.json()["code"] == "NOT_PROJECT_ADMIN"
    assert archive.status_code == 403
    assert archive.json()["code"] == "FORBIDDEN"


def test_ac_47_project_admin_can_read_applications(client: TestClient, db: Session) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")

    response = client.get(
        f"/api/projects/{project.id}/applications", headers=_auth(client, admin)
    )

    assert response.status_code == 200
