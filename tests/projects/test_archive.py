"""项目归档关闭待审批（T24，AC-24）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.errors import ProjectNotFound
from app.common.security import hash_password
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.projects.service import CLOSED_REASON_ARCHIVED, archive_project

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)


def _user(db: Session) -> User:
    user = User(username=f"arch-{uuid.uuid4().hex[:8]}", password_hash=PASSWORD_HASH)
    db.add(user)
    db.flush()
    return user


def _project(db: Session) -> Project:
    project = Project(name=f"arch-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    return project


def _application(db: Session, project: Project, applicant: User, status: str):
    application = ProjectApplication(
        project_id=project.id,
        applicant_id=applicant.id,
        reason="需要加入",
        desired_role="member",
        status=status,
    )
    db.add(application)
    db.flush()
    return application


def _headers(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_ac_24_archive_closes_only_pending(db: Session):
    project = _project(db)
    pending_first = _application(db, project, _user(db), "pending")
    pending_second = _application(db, project, _user(db), "pending")
    approved = _application(db, project, _user(db), "approved")
    rejected = _application(db, project, _user(db), "rejected")

    archive_project(db, project_id=project.id)

    db.expire_all()
    assert db.get(Project, project.id).status == "archived"

    for application in (pending_first, pending_second):
        row = db.get(ProjectApplication, application.id)
        assert row.status == "closed"
        assert row.closed_reason == CLOSED_REASON_ARCHIVED

    assert db.get(ProjectApplication, approved.id).status == "approved"
    assert db.get(ProjectApplication, rejected.id).status == "rejected"
    assert db.get(ProjectApplication, approved.id).closed_reason is None


def test_ac_24_closed_applications_reject_review(client: TestClient, db: Session):
    """归档后待审批已终态：审批接口返回 409，而不是改回 approved。"""
    applicant = _user(db)
    admin = _user(db)
    project = _project(db)
    db.add(ProjectMember(project_id=project.id, user_id=admin.id, role="project_admin"))
    application = _application(db, project, applicant, "pending")
    archive_project(db, project_id=project.id)

    headers = _headers(client, admin)
    approve = client.post(
        f"/api/projects/{project.id}/applications/{application.id}/approve",
        json={"role": "member"},
        headers=headers,
    )
    reject = client.post(
        f"/api/projects/{project.id}/applications/{application.id}/reject",
        json={"reason": "归档了"},
        headers=headers,
    )

    assert approve.status_code == 409
    assert approve.json()["code"] == "APPLICATION_NOT_PENDING"
    assert reject.status_code == 409
    assert reject.json()["code"] == "APPLICATION_NOT_PENDING"

    db.expire_all()
    assert db.get(ProjectApplication, application.id).status == "closed"
    assert db.get(ProjectMember, (project.id, applicant.id)) is None


def test_archive_missing_project(db: Session):
    with pytest.raises(ProjectNotFound):
        archive_project(db, project_id=999_999_999)


def test_archive_is_idempotent(db: Session):
    project = _project(db)
    application = _application(db, project, _user(db), "pending")

    archive_project(db, project_id=project.id)
    archive_project(db, project_id=project.id)

    db.expire_all()
    assert db.get(Project, project.id).status == "archived"
    assert db.get(ProjectApplication, application.id).status == "closed"
