"""写操作审计覆盖（T26 产出，参数化核对每条 action 都有落库）。

这里不关心业务结果，只回答一个问题：这个写操作跑完，审计表里有没有
对应 action 的记录。新增写操作而忘了写审计时，这份清单会缺项。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import clock as clock_module
from app.common.captcha import create_captcha, get_redis
from app.common.clock import FixedClock
from app.common.security import hash_password
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.system import AuditLog
from app.models.user import User
from app.projects.service import archive_project

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)

REGISTER = "/api/auth/register"
LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"
SEND_CODE = "/api/auth/password/send-code"
RESET = "/api/auth/password/reset"
CHANGE = "/api/auth/password/change"
SUBMIT = "/api/projects/{project_id}/applications"
WITHDRAW = "/api/projects/{project_id}/applications/{application_id}/withdraw"
APPROVE = "/api/projects/{project_id}/applications/{application_id}/approve"
REJECT = "/api/projects/{project_id}/applications/{application_id}/reject"
ADMIN_STATUS = "/api/admin/users/{uid}/status"
ADMIN_PASSWORD = "/api/admin/users/{uid}/password"
ADMIN_ROLE = "/api/admin/users/{uid}/role"
PROJECTS = "/api/projects"
PROJECT_MEMBER = "/api/projects/{project_id}/members/{user_id}"


def _user(
    db: Session,
    *,
    global_role: str = "user",
    status: str = "active",
    email: str | None = None,
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"cov-{suffix}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
        status=status,
        email=email or f"cov-{suffix}@example.com",
    )
    db.add(user)
    db.flush()
    return user


def _project(db: Session) -> Project:
    project = Project(name=f"cov-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    return project


def _join(db: Session, project: Project, user: User, role: str = "project_admin") -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def _pending_application(db: Session, project: Project, applicant: User) -> ProjectApplication:
    application = ProjectApplication(
        project_id=project.id,
        applicant_id=applicant.id,
        reason="审计覆盖",
        desired_role="member",
    )
    db.add(application)
    db.flush()
    return application


def _headers(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        LOGIN, json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _lock_user(client: TestClient, user: User) -> None:
    for _ in range(5):
        client.post(LOGIN, json={"username": user.username, "password": "WrongPass1"})


def _register(client: TestClient, db: Session, monkeypatch) -> None:
    captcha = create_captcha()
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        REGISTER,
        json={
            "username": f"cov-new-{suffix}",
            "password": PASSWORD,
            "email": f"cov-new-{suffix}@example.com",
            "phone": None,
            "captcha": captcha.code,
            "captcha_id": captcha.id,
        },
    )
    assert response.status_code == 201, response.text


def _login_success(client: TestClient, db: Session, monkeypatch) -> None:
    user = _user(db)
    assert client.post(
        LOGIN, json={"username": user.username, "password": PASSWORD}
    ).status_code == 200


def _login_disabled(client: TestClient, db: Session, monkeypatch) -> None:
    user = _user(db, status="disabled")
    assert client.post(
        LOGIN, json={"username": user.username, "password": PASSWORD}
    ).status_code == 403


def _login_locked(client: TestClient, db: Session, monkeypatch) -> None:
    fixed = FixedClock(datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(clock_module, "clock", fixed)
    _lock_user(client, _user(db))


def _login_unlocked(client: TestClient, db: Session, monkeypatch) -> None:
    fixed = FixedClock(datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(clock_module, "clock", fixed)
    user = _user(db)
    _lock_user(client, user)
    fixed.advance(timedelta(minutes=31))
    assert client.post(
        LOGIN, json={"username": user.username, "password": PASSWORD}
    ).status_code == 200


def _logout(client: TestClient, db: Session, monkeypatch) -> None:
    user = _user(db)
    headers = _headers(client, user)
    assert client.post(LOGOUT, headers=headers).status_code == 200


def _password_reset(client: TestClient, db: Session, monkeypatch) -> None:
    user = _user(db)
    assert client.post(SEND_CODE, json={"contact": user.email}).status_code == 200
    code = get_redis().get(f"pwdreset:code:{user.email}")
    assert code is not None
    response = client.post(
        RESET,
        json={"contact": user.email, "code": code, "new_password": "Newpass123"},
    )
    assert response.status_code == 200, response.text


def _password_change(client: TestClient, db: Session, monkeypatch) -> None:
    user = _user(db)
    headers = _headers(client, user)
    response = client.post(
        CHANGE,
        json={"old_password": PASSWORD, "new_password": "Newpass123"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _apply_submit(client: TestClient, db: Session, monkeypatch) -> None:
    user = _user(db)
    project = _project(db)
    response = client.post(
        SUBMIT.format(project_id=project.id),
        json={"reason": "审计覆盖", "desired_role": "member"},
        headers=_headers(client, user),
    )
    assert response.status_code == 201, response.text


def _apply_withdraw(client: TestClient, db: Session, monkeypatch) -> None:
    user = _user(db)
    project = _project(db)
    application = _pending_application(db, project, user)
    response = client.post(
        WITHDRAW.format(project_id=project.id, application_id=application.id),
        headers=_headers(client, user),
    )
    assert response.status_code == 200, response.text


def _apply_approve(client: TestClient, db: Session, monkeypatch) -> None:
    applicant = _user(db)
    admin = _user(db, global_role="system_admin")
    project = _project(db)
    application = _pending_application(db, project, applicant)
    response = client.post(
        APPROVE.format(project_id=project.id, application_id=application.id),
        json={"role": "member"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 200, response.text


def _apply_reject(client: TestClient, db: Session, monkeypatch) -> None:
    applicant = _user(db)
    admin = _user(db, global_role="system_admin")
    project = _project(db)
    application = _pending_application(db, project, applicant)
    response = client.post(
        REJECT.format(project_id=project.id, application_id=application.id),
        json={"reason": "材料不全"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 200, response.text


def _apply_close(client: TestClient, db: Session, monkeypatch) -> None:
    applicant = _user(db)
    admin = _user(db, global_role="system_admin")
    project = _project(db)
    _pending_application(db, project, applicant)
    archive_project(db, project_id=project.id, actor=admin)


def _user_disable(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    victim = _user(db)
    response = client.patch(
        ADMIN_STATUS.format(uid=victim.id),
        json={"status": "disabled"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 200


def _user_enable(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    victim = _user(db, status="disabled")
    response = client.patch(
        ADMIN_STATUS.format(uid=victim.id),
        json={"status": "active"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 200


def _user_password_reset(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    victim = _user(db)
    response = client.patch(
        ADMIN_PASSWORD.format(uid=victim.id),
        headers=_headers(client, admin),
    )
    assert response.status_code == 200


def _project_create(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    response = client.post(
        PROJECTS,
        json={"name": f"cov-api-{uuid.uuid4().hex[:6]}", "description": "审计覆盖"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 201, response.text


def _project_update(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    project = _project(db)
    response = client.patch(
        f"{PROJECTS}/{project.id}",
        json={"description": "改简介"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 200, response.text


def _project_archive(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    project = _project(db)
    response = client.post(
        f"{PROJECTS}/{project.id}/archive", headers=_headers(client, admin)
    )
    assert response.status_code == 200, response.text


def _member_add(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    project = _project(db)
    target = _user(db)
    response = client.post(
        f"{PROJECTS}/{project.id}/members",
        json={"user_id": target.id, "role": "member"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 201, response.text


def _member_role(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    project = _project(db)
    target = _user(db)
    _join(db, project, target, "member")
    response = client.patch(
        PROJECT_MEMBER.format(project_id=project.id, user_id=target.id),
        json={"role": "guest"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 200, response.text


def _member_remove(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    project = _project(db)
    target = _user(db)
    _join(db, project, target, "member")
    response = client.delete(
        PROJECT_MEMBER.format(project_id=project.id, user_id=target.id),
        headers=_headers(client, admin),
    )
    assert response.status_code == 200, response.text


def _user_role_change(client: TestClient, db: Session, monkeypatch) -> None:
    admin = _user(db, global_role="system_admin")
    victim = _user(db)
    response = client.patch(
        ADMIN_ROLE.format(uid=victim.id),
        json={"global_role": "system_admin"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 200, response.text


SCENARIOS = {
    "register.submit": _register,
    "login.success": _login_success,
    "login.blocked.disabled": _login_disabled,
    "login.locked": _login_locked,
    "login.unlocked": _login_unlocked,
    "logout": _logout,
    "password.reset": _password_reset,
    "password.change": _password_change,
    "project.apply.submit": _apply_submit,
    "project.apply.withdraw": _apply_withdraw,
    "project.apply.approve": _apply_approve,
    "project.apply.reject": _apply_reject,
    "project.apply.close": _apply_close,
    "user.disable": _user_disable,
    "user.enable": _user_enable,
    "user.password.reset": _user_password_reset,
    "user.role.change": _user_role_change,
    "project.create": _project_create,
    "project.update": _project_update,
    "project.archive": _project_archive,
    "project.member.add": _member_add,
    "project.member.role": _member_role,
    "project.member.remove": _member_remove,
}


@pytest.mark.parametrize("action", sorted(SCENARIOS))
def test_write_action_writes_audit(
    action: str, client: TestClient, db: Session, monkeypatch
):
    SCENARIOS[action](client, db, monkeypatch)

    count = db.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == action)
    ).scalar_one()

    assert count >= 1, f"写操作 {action} 没有产生审计记录"
