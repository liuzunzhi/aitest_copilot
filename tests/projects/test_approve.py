"""审批通过 / 驳回（T22，AC-21 / AC-22）。"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.common import clock as clock_module
from app.common import settings as settings_service
from app.common.clock import FixedClock
from app.common.db import session_scope
from app.common.errors import ApplicationNotPending
from app.common.security import hash_password
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.system import AuditLog
from app.models.user import User
from app.projects import apply_service

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)

SUBMIT = "/api/projects/{project_id}/applications"
APPROVE = "/api/projects/{project_id}/applications/{application_id}/approve"
REJECT = "/api/projects/{project_id}/applications/{application_id}/reject"
PROJECTS = "/api/projects"


@pytest.fixture(autouse=True)
def clean_settings_cache():
    settings_service.cache_clear()
    yield
    settings_service.cache_clear()


def _user(db: Session) -> User:
    user = User(username=f"review-{uuid.uuid4().hex[:8]}", password_hash=PASSWORD_HASH)
    db.add(user)
    db.flush()
    return user


def _project(db: Session) -> Project:
    project = Project(name=f"review-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    return project


def _admin(db: Session, project: Project) -> User:
    """审批人必须是该项目管理员（AC-23）。"""
    user = _user(db)
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="project_admin"))
    db.flush()
    return user


def _headers(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _application_id(db: Session, user: User, project: Project) -> int:
    return db.execute(
        select(ProjectApplication.id)
        .where(
            ProjectApplication.applicant_id == user.id,
            ProjectApplication.project_id == project.id,
        )
        .order_by(ProjectApplication.id.desc())
    ).scalars().first()


def _approve(client, reviewer, project, application_id, **payload):
    return client.post(
        APPROVE.format(project_id=project.id, application_id=application_id),
        json={"role": "member", **payload},
        headers=_headers(client, reviewer),
    )


def _reject(client, reviewer, project, application_id, **payload):
    return client.post(
        REJECT.format(project_id=project.id, application_id=application_id),
        json={"reason": "暂不开放", **payload},
        headers=_headers(client, reviewer),
    )


def test_ac_21_approve_adds_member(client: TestClient, db: Session):
    """状态 approved、写入成员、旧 token 立即可访问项目、审计 before/after。"""
    applicant = _user(db)
    project = _project(db)
    reviewer = _admin(db, project)
    applicant_headers = _headers(client, applicant)
    assert (
        client.post(
            SUBMIT.format(project_id=project.id),
            json={"reason": "需要加入", "desired_role": "member"},
            headers=applicant_headers,
        ).status_code
        == 201
    )
    application_id = _application_id(db, applicant, project)

    response = _approve(client, reviewer, project, application_id)

    assert response.status_code == 200
    assert response.json() == {"status": "approved"}

    application = db.get(ProjectApplication, application_id)
    db.refresh(application)
    assert application.status == "approved"
    assert application.reviewer_id == reviewer.id
    assert application.reviewed_at is not None

    member = db.get(ProjectMember, (project.id, applicant.id))
    assert member is not None and member.role == "member"

    # 审批前签发的 token，无需重新登录就能看到项目
    projects = client.get(PROJECTS, headers=applicant_headers)
    assert project.id in [item["id"] for item in projects.json()]

    audit = db.execute(
        select(AuditLog).where(
            AuditLog.action == "project.apply.approve",
            AuditLog.target_id == str(application_id),
        )
    ).scalar_one()
    assert audit.before_data == {"status": "pending"}
    assert audit.after_data == {"status": "approved", "role": "member"}


def test_ac_21_approve_with_project_admin_role(client: TestClient, db: Session):
    applicant = _user(db)
    project = _project(db)
    reviewer = _admin(db, project)
    assert (
        client.post(
            SUBMIT.format(project_id=project.id),
            json={"reason": "需要管理", "desired_role": "member"},
            headers=_headers(client, applicant),
        ).status_code
        == 201
    )
    application_id = _application_id(db, applicant, project)

    assert _approve(
        client, reviewer, project, application_id, role="project_admin"
    ).status_code == 200

    db.expire_all()
    member = db.get(ProjectMember, (project.id, applicant.id))
    assert member is not None and member.role == "project_admin"


@pytest.mark.parametrize("role", ["system_admin", None, "owner"])
def test_ac_21_invalid_role_assignment(client: TestClient, db: Session, role):
    applicant = _user(db)
    project = _project(db)
    reviewer = _admin(db, project)
    assert (
        client.post(
            SUBMIT.format(project_id=project.id),
            json={"reason": "需要加入", "desired_role": "member"},
            headers=_headers(client, applicant),
        ).status_code
        == 201
    )
    application_id = _application_id(db, applicant, project)

    response = _approve(client, reviewer, project, application_id, role=role)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_ROLE_ASSIGNMENT"
    db.expire_all()
    assert db.get(ProjectApplication, application_id).status == "pending"


def test_ac_21_approve_twice_conflicts(client: TestClient, db: Session):
    applicant = _user(db)
    project = _project(db)
    reviewer = _admin(db, project)
    assert (
        client.post(
            SUBMIT.format(project_id=project.id),
            json={"reason": "需要加入", "desired_role": "member"},
            headers=_headers(client, applicant),
        ).status_code
        == 201
    )
    application_id = _application_id(db, applicant, project)
    assert _approve(client, reviewer, project, application_id).status_code == 200

    again = _approve(client, reviewer, project, application_id)

    assert again.status_code == 409
    assert again.json()["code"] == "APPLICATION_NOT_PENDING"


def test_ac_22_reject(client: TestClient, db: Session):
    applicant = _user(db)
    project = _project(db)
    reviewer = _admin(db, project)
    assert (
        client.post(
            SUBMIT.format(project_id=project.id),
            json={"reason": "需要加入", "desired_role": "member"},
            headers=_headers(client, applicant),
        ).status_code
        == 201
    )
    application_id = _application_id(db, applicant, project)

    response = _reject(client, reviewer, project, application_id)

    assert response.status_code == 200
    assert response.json() == {"status": "rejected"}

    application = db.get(ProjectApplication, application_id)
    db.refresh(application)
    assert application.status == "rejected"
    assert application.reject_reason == "暂不开放"
    assert application.rejected_at is not None

    audit = db.execute(
        select(AuditLog).where(
            AuditLog.action == "project.apply.reject",
            AuditLog.target_id == str(application_id),
        )
    ).scalar_one()
    assert audit.reason == "暂不开放"

    assert db.get(ProjectMember, (project.id, applicant.id)) is None


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_ac_22_reject_reason_required(client: TestClient, db: Session, reason):
    applicant = _user(db)
    project = _project(db)
    reviewer = _admin(db, project)
    assert (
        client.post(
            SUBMIT.format(project_id=project.id),
            json={"reason": "需要加入", "desired_role": "member"},
            headers=_headers(client, applicant),
        ).status_code
        == 201
    )
    application_id = _application_id(db, applicant, project)

    response = _reject(client, reviewer, project, application_id, reason=reason)

    assert response.status_code == 400
    assert response.json()["code"] == "REASON_REQUIRED"
    db.expire_all()
    assert db.get(ProjectApplication, application_id).status == "pending"


def test_ac_22_cooldown_boundary(client: TestClient, db: Session, monkeypatch):
    """驳回后 12h 再申请 429 并带 next_available_at；25h 后恢复。"""
    fixed = FixedClock(datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(clock_module, "clock", fixed)

    applicant = _user(db)
    project = _project(db)
    reviewer = _admin(db, project)

    assert (
        client.post(
            SUBMIT.format(project_id=project.id),
            json={"reason": "需要加入", "desired_role": "member"},
            headers=_headers(client, applicant),
        ).status_code
        == 201
    )
    application_id = _application_id(db, applicant, project)
    assert _reject(client, reviewer, project, application_id).status_code == 200

    fixed.advance(timedelta(hours=12))
    blocked = client.post(
        SUBMIT.format(project_id=project.id),
        json={"reason": "再试一次", "desired_role": "member"},
        headers=_headers(client, applicant),
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "APPLY_COOLDOWN"
    assert blocked.json()["next_available_at"] == "2026-05-02T09:00:00Z"

    fixed.advance(timedelta(hours=13))
    allowed = client.post(
        SUBMIT.format(project_id=project.id),
        json={"reason": "再试一次", "desired_role": "member"},
        headers=_headers(client, applicant),
    )
    assert allowed.status_code == 201
    assert allowed.json() == {"status": "pending"}


def test_concurrent_approvals_only_one_wins():
    """双批并发：一条成功、一条 409，成员与审计都只落一条。

    这条用例必须真实提交（多连接并发），因此自己建数据、结束时清理。
    """
    suffix = uuid.uuid4().hex[:8]
    with session_scope() as session:
        applicant = User(username=f"race-applicant-{suffix}", password_hash=PASSWORD_HASH)
        reviewer = User(username=f"race-reviewer-{suffix}", password_hash=PASSWORD_HASH)
        project = Project(name=f"race-{suffix}")
        session.add_all([applicant, reviewer, project])
        session.flush()
        application = ProjectApplication(
            project_id=project.id,
            applicant_id=applicant.id,
            reason="并发审批",
            desired_role="member",
        )
        session.add(application)
        session.flush()
        project_id, application_id = project.id, application.id
        reviewer_id = reviewer.id

    def attempt(_: int) -> str:
        with session_scope() as session:
            reviewer_obj = session.get(User, reviewer_id)
            try:
                apply_service.approve(
                    session,
                    reviewer=reviewer_obj,
                    project_id=project_id,
                    application_id=application_id,
                    role="member",
                )
            except ApplicationNotPending:
                return "conflict"
            return "approved"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(pool.map(attempt, range(2)))

        assert results == ["approved", "conflict"]

        with session_scope() as session:
            members = session.execute(
                select(func.count())
                .select_from(ProjectMember)
                .where(ProjectMember.project_id == project_id)
            ).scalar_one()
            audits = session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "project.apply.approve",
                    AuditLog.target_id == str(application_id),
                )
            ).scalar_one()
            status_value = session.execute(
                select(ProjectApplication.status).where(
                    ProjectApplication.id == application_id
                )
            ).scalar_one()

        assert (members, audits, status_value) == (1, 1, "approved")
    finally:
        with session_scope() as session:
            session.execute(
                text("DELETE FROM audit_logs WHERE project_id = :pid"), {"pid": project_id}
            )
            session.execute(
                text("DELETE FROM project_members WHERE project_id = :pid"),
                {"pid": project_id},
            )
            session.execute(
                text("DELETE FROM project_applications WHERE project_id = :pid"),
                {"pid": project_id},
            )
            session.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id})
            session.execute(
                text(
                    "DELETE FROM users WHERE username IN "
                    "(:applicant, :reviewer)"
                ),
                {
                    "applicant": f"race-applicant-{suffix}",
                    "reviewer": f"race-reviewer-{suffix}",
                },
            )
