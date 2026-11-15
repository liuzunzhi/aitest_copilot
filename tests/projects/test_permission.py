"""审批权限边界（T23，AC-23）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.user import User

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)

APPROVE = "/api/projects/{project_id}/applications/{application_id}/approve"
REJECT = "/api/projects/{project_id}/applications/{application_id}/reject"


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"perm-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _project(db: Session) -> Project:
    project = Project(name=f"perm-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    return project


def _join(db: Session, project: Project, user: User, role: str) -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def _pending_application(db: Session, project: Project, applicant: User) -> int:
    application = ProjectApplication(
        project_id=project.id,
        applicant_id=applicant.id,
        reason="需要加入",
        desired_role="member",
    )
    db.add(application)
    db.flush()
    return application.id


def _headers(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _approve(client: TestClient, user: User, project: Project, application_id: int):
    return client.post(
        APPROVE.format(project_id=project.id, application_id=application_id),
        json={"role": "member"},
        headers=_headers(client, user),
    )


def _reject(client: TestClient, user: User, project: Project, application_id: int):
    return client.post(
        REJECT.format(project_id=project.id, application_id=application_id),
        json={"reason": "不允许"},
        headers=_headers(client, user),
    )


def test_project_admin_can_review_own_project(client: TestClient, db: Session):
    applicant = _user(db)
    admin = _user(db)
    project = _project(db)
    _join(db, project, admin, "project_admin")
    application_id = _pending_application(db, project, applicant)

    assert _approve(client, admin, project, application_id).status_code == 200

    other_applicant = _user(db)
    other_id = _pending_application(db, project, other_applicant)
    assert _reject(client, admin, project, other_id).status_code == 200


def test_project_admin_cannot_review_other_project(client: TestClient, db: Session):
    """AC-23：A 是 P1 管理员、不是 P2 成员，不能审 P2。"""
    applicant = _user(db)
    admin = _user(db)
    first = _project(db)
    second = _project(db)
    _join(db, first, admin, "project_admin")
    application_id = _pending_application(db, second, applicant)

    response = _approve(client, admin, second, application_id)

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"

    db.expire_all()
    assert db.get(ProjectApplication, application_id).status == "pending"


def test_regular_member_cannot_review(client: TestClient, db: Session):
    applicant = _user(db)
    member = _user(db)
    project = _project(db)
    _join(db, project, member, "member")
    application_id = _pending_application(db, project, applicant)

    response = _approve(client, member, project, application_id)

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_outsider_cannot_review(client: TestClient, db: Session):
    applicant = _user(db)
    outsider = _user(db)
    project = _project(db)
    application_id = _pending_application(db, project, applicant)

    response = _reject(client, outsider, project, application_id)

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_system_admin_can_review_any_project(client: TestClient, db: Session):
    """系统管理员非项目成员也能审批（AC-23 兜底）。"""
    applicant = _user(db)
    system_admin = _user(db, global_role="system_admin")
    project = _project(db)
    application_id = _pending_application(db, project, applicant)

    assert _approve(client, system_admin, project, application_id).status_code == 200

    second_applicant = _user(db)
    second_id = _pending_application(db, project, second_applicant)
    assert _reject(client, system_admin, project, second_id).status_code == 200


def test_review_requires_login(client: TestClient, db: Session):
    applicant = _user(db)
    project = _project(db)
    application_id = _pending_application(db, project, applicant)

    response = client.post(
        APPROVE.format(project_id=project.id, application_id=application_id),
        json={"role": "member"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
