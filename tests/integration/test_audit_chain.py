"""申请全链路审计（T26，AC-25）。

一条链路跑完 submit → withdraw → submit → reject → approve → close，
再从审计表按 project_id / applicant_id 两个入口各查一遍。
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.application import ProjectApplication
from app.models.project import Project
from app.models.system import AuditLog
from app.models.user import User
from app.projects.service import archive_project

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)

SUBMIT = "/api/projects/{project_id}/applications"
WITHDRAW = "/api/projects/{project_id}/applications/{application_id}/withdraw"
APPROVE = "/api/projects/{project_id}/applications/{application_id}/approve"
REJECT = "/api/projects/{project_id}/applications/{application_id}/reject"


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"chain-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _project(db: Session) -> Project:
    project = Project(name=f"chain-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    return project


def _headers(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _submit(client: TestClient, user: User, project: Project, db: Session) -> int:
    response = client.post(
        SUBMIT.format(project_id=project.id),
        json={"reason": "链路测试", "desired_role": "member"},
        headers=_headers(client, user),
    )
    assert response.status_code == 201, response.text
    return _application_id(db=db, user=user, project=project)


def _application_id(db: Session, user: User, project: Project) -> int:
    return db.execute(
        select(ProjectApplication.id)
        .where(
            ProjectApplication.applicant_id == user.id,
            ProjectApplication.project_id == project.id,
        )
        .order_by(ProjectApplication.id.desc())
    ).scalars().first()


def _by_project(db: Session, project_id: int) -> list[AuditLog]:
    return list(
        db.execute(
            select(AuditLog)
            .where(AuditLog.project_id == project_id)
            .order_by(AuditLog.id)
        ).scalars()
    )


def _by_applicant(db: Session, applicant_id: int) -> list[AuditLog]:
    return list(
        db.execute(
            select(AuditLog)
            .where(AuditLog.applicant_id == applicant_id)
            .order_by(AuditLog.id)
        ).scalars()
    )


@pytest.fixture
def chain(client: TestClient, db: Session) -> dict:
    """跑完整链路，返回链路里用到的 id 与中间结果。"""
    applicant = _user(db)
    approved_applicant = _user(db)
    closed_applicant = _user(db)
    admin = _user(db, global_role="system_admin")
    first_project = _project(db)
    second_project = _project(db)

    first = _submit(client, applicant, first_project, db)
    assert client.post(
        WITHDRAW.format(project_id=first_project.id, application_id=first),
        headers=_headers(client, applicant),
    ).status_code == 200

    rejected = _submit(client, applicant, first_project, db)
    assert client.post(
        REJECT.format(project_id=first_project.id, application_id=rejected),
        json={"reason": "材料不全"},
        headers=_headers(client, admin),
    ).status_code == 200

    approved = _submit(client, approved_applicant, first_project, db)
    assert client.post(
        APPROVE.format(project_id=first_project.id, application_id=approved),
        json={"role": "member"},
        headers=_headers(client, admin),
    ).status_code == 200

    closed = _submit(client, closed_applicant, second_project, db)
    archive_project(db, project_id=second_project.id, actor=admin)

    return {
        "applicant": applicant.id,
        "approved_applicant": approved_applicant.id,
        "closed_applicant": closed_applicant.id,
        "admin": admin.id,
        "first_project": first_project.id,
        "second_project": second_project.id,
        "first": first,
        "rejected": rejected,
        "approved": approved,
        "closed": closed,
    }


def test_ac_25_retrieve_by_project(db: Session, chain: dict):
    rows = _by_project(db, chain["first_project"])

    assert [row.action for row in rows] == [
        "project.apply.submit",
        "project.apply.withdraw",
        "project.apply.submit",
        "project.apply.reject",
        "project.apply.submit",
        "project.apply.approve",
    ]

    first_submit = next(
        row
        for row in rows
        if row.action == "project.apply.submit" and row.target_id == str(chain["first"])
    )
    assert first_submit.applicant_id == chain["applicant"]

    withdraw_row = next(r for r in rows if r.action == "project.apply.withdraw")
    assert withdraw_row.before_data == {"status": "pending"}
    assert withdraw_row.after_data == {"status": "withdrawn"}
    assert withdraw_row.applicant_id == chain["applicant"]

    reject_row = next(r for r in rows if r.action == "project.apply.reject")
    assert reject_row.before_data == {"status": "pending"}
    assert reject_row.after_data == {"status": "rejected"}
    assert reject_row.reason == "材料不全"
    assert reject_row.actor_id == chain["admin"]
    assert reject_row.applicant_id == chain["applicant"]

    approve_row = next(r for r in rows if r.action == "project.apply.approve")
    assert approve_row.after_data == {"status": "approved", "role": "member"}
    assert approve_row.actor_id == chain["admin"]
    assert approve_row.applicant_id == chain["approved_applicant"]

    assert all(row.created_at is not None for row in rows)


def test_ac_25_retrieve_by_applicant(db: Session, chain: dict):
    rows = _by_applicant(db, chain["applicant"])

    assert [row.action for row in rows] == [
        "project.apply.submit",
        "project.apply.withdraw",
        "project.apply.submit",
        "project.apply.reject",
    ]
    assert all(row.project_id == chain["first_project"] for row in rows)

    approved_rows = _by_applicant(db, chain["approved_applicant"])
    assert [row.action for row in approved_rows] == [
        "project.apply.submit",
        "project.apply.approve",
    ]


def test_ac_25_close_is_traceable(db: Session, chain: dict):
    rows = _by_project(db, chain["second_project"])

    close_row = next(row for row in rows if row.action == "project.apply.close")
    submitted = next(row for row in rows if row.action == "project.apply.submit")
    assert submitted.applicant_id == chain["closed_applicant"]

    assert close_row.target_id == str(chain["closed"])
    assert close_row.applicant_id == chain["closed_applicant"]
    assert close_row.before_data == {"status": "pending"}
    assert close_row.after_data == {"status": "closed"}
    assert close_row.reason == "project_archived"

    by_applicant = _by_applicant(db, chain["closed_applicant"])
    assert [row.action for row in by_applicant] == [
        "project.apply.submit",
        "project.apply.close",
    ]
