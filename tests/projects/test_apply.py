"""提交项目申请（T20，AC-13 ~ 19）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.common import settings as settings_service
from app.common.security import hash_password
from app.common.settings import set_setting
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.system import AuditLog
from app.models.user import User

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)
APPLY = "/api/projects/{project_id}/applications"
AVAILABLE = "/api/projects/available"


@pytest.fixture(autouse=True)
def clean_settings_cache():
    settings_service.cache_clear()
    yield
    settings_service.cache_clear()


def _user(db: Session) -> User:
    user = User(username=f"apply-{uuid.uuid4().hex[:8]}", password_hash=PASSWORD_HASH)
    db.add(user)
    db.flush()
    return user


def _project(db: Session, *, status: str = "active") -> Project:
    project = Project(name=f"apply-{uuid.uuid4().hex[:6]}", status=status)
    db.add(project)
    db.flush()
    return project


def _headers(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _submit(client, user, project, **payload):
    body = {"reason": "需要一个测试环境", "desired_role": "member", **payload}
    return client.post(APPLY.format(project_id=project.id), json=body, headers=_headers(client, user))


def test_ac_13_submit_creates_pending(client: TestClient, db: Session):
    user = _user(db)
    project = _project(db)

    response = _submit(client, user, project)

    assert response.status_code == 201
    assert response.json() == {"status": "pending"}

    application = db.execute(
        select(ProjectApplication).where(ProjectApplication.applicant_id == user.id)
    ).scalar_one()
    assert application.status == "pending"
    assert application.reason == "需要一个测试环境"

    audits = db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "project.apply.submit",
            AuditLog.actor_id == user.id,
            AuditLog.project_id == project.id,
        )
    ).scalar_one()
    assert audits == 1


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_ac_14_reason_required(client: TestClient, db: Session, reason):
    user = _user(db)
    project = _project(db)

    response = _submit(client, user, project, reason=reason)

    assert response.status_code == 400
    assert response.json()["code"] == "REASON_REQUIRED"


@pytest.mark.parametrize("role", ["project_admin", "system_admin", None])
def test_ac_15_rejects_privileged_roles(client: TestClient, db: Session, role):
    user = _user(db)
    project = _project(db)

    response = _submit(client, user, project, desired_role=role)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_DESIRED_ROLE"


def test_ac_15_db_check_is_second_line_of_defense(db: Session):
    """绕过服务层直接插库也会被 CHECK 拦住。"""
    user = _user(db)
    project = _project(db)

    # MySQL 的 CHECK 违规是 3819 OperationalError，不是 IntegrityError
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.add(
                ProjectApplication(
                    project_id=project.id,
                    applicant_id=user.id,
                    reason="绕过服务层",
                    desired_role="project_admin",
                )
            )
            db.flush()


def test_ac_16_member_cannot_apply(client: TestClient, db: Session):
    user = _user(db)
    project = _project(db)
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="guest"))
    db.flush()

    response = _submit(client, user, project)

    assert response.status_code == 409
    assert response.json()["code"] == "ALREADY_PROJECT_MEMBER"

    available = client.get(AVAILABLE, headers=_headers(client, user))
    assert project.id not in [item["id"] for item in available.json()]


def test_ac_17_duplicate_pending(client: TestClient, db: Session):
    user = _user(db)
    project = _project(db)

    assert _submit(client, user, project).status_code == 201
    response = _submit(client, user, project)

    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_APPLICATION"


def test_ac_18_apply_disabled(client: TestClient, db: Session):
    user = _user(db)
    project = _project(db)
    set_setting(db, "enable_project_apply", False)

    response = _submit(client, user, project)

    assert response.status_code == 403
    assert response.json()["code"] == "APPLY_DISABLED"
    assert db.execute(
        select(func.count()).select_from(ProjectApplication)
    ).scalar_one() == 0


def test_ac_19_parallel_applications(client: TestClient, db: Session):
    """同一用户可对多个项目各留一条 pending。"""
    user = _user(db)
    first = _project(db)
    second = _project(db)

    assert _submit(client, user, first).status_code == 201
    assert _submit(client, user, second).status_code == 201

    statuses = db.execute(
        select(ProjectApplication.project_id, ProjectApplication.status)
        .where(ProjectApplication.applicant_id == user.id)
        .order_by(ProjectApplication.project_id)
    ).all()
    assert [tuple(row) for row in statuses] == [
        (first.id, "pending"),
        (second.id, "pending"),
    ]


def test_archived_project_cannot_be_applied(client: TestClient, db: Session):
    user = _user(db)
    project = _project(db, status="archived")

    response = _submit(client, user, project)

    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


def test_submit_requires_login(client: TestClient, db: Session):
    project = _project(db)

    response = client.post(
        APPLY.format(project_id=project.id),
        json={"reason": "x", "desired_role": "member"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


WITHDRAW = "/api/projects/{project_id}/applications/{application_id}/withdraw"


def _application(db: Session, user: User, project: Project) -> ProjectApplication:
    return db.execute(
        select(ProjectApplication).where(
            ProjectApplication.applicant_id == user.id,
            ProjectApplication.project_id == project.id,
        )
    ).scalar_one()


def _withdraw(client: TestClient, user: User, project: Project, application_id: int):
    return client.post(
        WITHDRAW.format(project_id=project.id, application_id=application_id),
        headers=_headers(client, user),
    )


def test_ac_20_withdraw_success(client: TestClient, db: Session):
    user = _user(db)
    project = _project(db)
    assert _submit(client, user, project).status_code == 201
    application = _application(db, user, project)

    response = _withdraw(client, user, project, application.id)

    assert response.status_code == 200
    assert response.json() == {"status": "withdrawn"}
    db.refresh(application)
    assert application.status == "withdrawn"

    audits = db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "project.apply.withdraw",
            AuditLog.target_id == str(application.id),
        )
    ).scalar_one()
    assert audits == 1


def test_ac_20_withdraw_frees_pending_slot(client: TestClient, db: Session):
    """撤回归入终态，pending_key 变 NULL，可以再次申请（AC-20）。"""
    user = _user(db)
    project = _project(db)
    assert _submit(client, user, project).status_code == 201
    application = _application(db, user, project)

    assert _withdraw(client, user, project, application.id).status_code == 200
    assert _submit(client, user, project).status_code == 201


def test_ac_20_withdraw_not_owner(client: TestClient, db: Session):
    owner = _user(db)
    other = _user(db)
    project = _project(db)
    assert _submit(client, owner, project).status_code == 201
    application = _application(db, owner, project)

    response = _withdraw(client, other, project, application.id)

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_APPLICATION_OWNER"
    db.refresh(application)
    assert application.status == "pending"


def test_withdraw_wrong_project_not_found(client: TestClient, db: Session):
    """申请不属于该路径下的项目时按不存在处理。"""
    user = _user(db)
    project = _project(db)
    other_project = _project(db)
    assert _submit(client, user, project).status_code == 201
    application = _application(db, user, project)

    response = _withdraw(client, user, other_project, application.id)

    assert response.status_code == 404
    assert response.json()["code"] == "APPLICATION_NOT_FOUND"


def test_withdraw_twice(client: TestClient, db: Session):
    user = _user(db)
    project = _project(db)
    assert _submit(client, user, project).status_code == 201
    application = _application(db, user, project)
    assert _withdraw(client, user, project, application.id).status_code == 200

    now = _withdraw(client, user, project, application.id)

    assert now.status_code == 409
    assert now.json()["code"] == "APPLICATION_NOT_PENDING"


def test_withdraw_requires_login(client: TestClient, db: Session):
    user = _user(db)
    project = _project(db)
    assert _submit(client, user, project).status_code == 201
    application = _application(db, user, project)

    response = client.post(
        WITHDRAW.format(project_id=project.id, application_id=application.id)
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
