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
from app.common.captcha import get_redis
from app.common.clock import FixedClock
from app.common.config import get_settings
from app.common.security import hash_password
from app.main import app as fastapi_app
from app.models.application import ProjectApplication
from app.models.baseline import (
    BaselineFunction,
    BaselineLabel,
    BaselineModule,
    BaselineRevision,
)
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import (
    IncrementalAnalysis,
    IncrementalConflict,
    IncrementalDecision,
    PromptTemplate,
)
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
DOCUMENTS = "/api/projects/{project_id}/documents"
ACTIVATE = DOCUMENTS + "/{document_id}/versions/{version_id}/activate"
VOID = DOCUMENTS + "/{document_id}/versions/{version_id}/void"
BASELINES = "/api/projects/{project_id}/baselines"
INCREMENTAL = "/api/projects/{project_id}/incremental"
CHAPTER_LINKS = (
    DOCUMENTS + "/{document_id}/versions/{version_id}/links"
)
TEST_POINTS = "/api/projects/{project_id}/test-points"


@pytest.fixture(autouse=True)
def _upload_root(tmp_path, monkeypatch):
    """本文件会真实上传文件，原文目录指向临时目录，别写进仓库。"""
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    return tmp_path


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
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        REGISTER,
        json={
            "username": f"cov-new-{suffix}",
            "password": PASSWORD,
            "email": f"cov-new-{suffix}@example.com",
            "phone": None,
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


def _uploaded(client: TestClient, db: Session):
    """建项目 + 项目管理员上传一份 md，返回 (project, user, headers, 响应体)。"""
    user = _user(db)
    project = _project(db)
    _join(db, project, user, "project_admin")
    headers = _headers(client, user)
    response = client.post(
        DOCUMENTS.format(project_id=project.id),
        files={"file": ("审计.md", "# 审计\n正文".encode("utf-8"), "text/markdown")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return project, user, headers, response.json()


def _document_upload(client: TestClient, db: Session, monkeypatch) -> None:
    _uploaded(client, db)


def _version_activate(client: TestClient, db: Session, monkeypatch) -> None:
    project, _, headers, body = _uploaded(client, db)
    response = client.post(
        ACTIVATE.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        ),
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _version_void(client: TestClient, db: Session, monkeypatch) -> None:
    project, _, headers, body = _uploaded(client, db)
    response = client.post(
        VOID.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        ),
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_snapshot(client: TestClient, db: Session, monkeypatch) -> None:
    """快照与确认生效同事务，走同一条链路即可。"""
    _version_activate(client, db, monkeypatch)


# ------------------------------------------------- 功能基线（04 模块）场景


def _baseline_setup(client: TestClient, db: Session):
    """建项目 + 两个项目管理员（一个提交、一个审核），返回 (project, 头, 审核头)。"""
    user = _user(db)
    reviewer = _user(db)
    project = _project(db)
    _join(db, project, user, "project_admin")
    _join(db, project, reviewer, "project_admin")
    return project, _headers(client, user), _headers(client, reviewer)


def _baseline_module(client: TestClient, db: Session, monkeypatch=None):
    project, headers, reviewer_headers = _baseline_setup(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id) + "/modules",
        json={"name": "支付模块"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return project, headers, reviewer_headers, response.json()


def _baseline_module_update(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, module = _baseline_module(client, db)
    response = client.patch(
        BASELINES.format(project_id=project.id) + f"/modules/{module['id']}",
        json={"description": "改描述"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_module_delete(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, module = _baseline_module(client, db)
    response = client.delete(
        BASELINES.format(project_id=project.id) + f"/modules/{module['id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_function(client: TestClient, db: Session, monkeypatch=None):
    project, headers, reviewer_headers, module = _baseline_module(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id) + "/functions",
        json={"module_id": module["id"], "name": "下单"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return project, headers, reviewer_headers, module, response.json()


def _baseline_function_update(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, _, function = _baseline_function(client, db)
    response = client.patch(
        BASELINES.format(project_id=project.id) + f"/functions/{function['id']}",
        json={"name": "提交订单"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_function_delete(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, _, function = _baseline_function(client, db)
    response = client.delete(
        BASELINES.format(project_id=project.id) + f"/functions/{function['id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_point(client: TestClient, db: Session, monkeypatch=None):
    project, headers, reviewer_headers, _, function = _baseline_function(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id)
        + f"/functions/{function['id']}/feature-points",
        json={"name": "填写收货地址"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return project, headers, reviewer_headers, function, response.json()


def _baseline_point_update(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, _, point = _baseline_point(client, db)
    response = client.patch(
        BASELINES.format(project_id=project.id) + f"/feature-points/{point['id']}",
        json={"name": "填写地址"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_point_delete(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, _, point = _baseline_point(client, db)
    response = client.delete(
        BASELINES.format(project_id=project.id) + f"/feature-points/{point['id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_migrate(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, module, function = _baseline_function(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id) + "/modules",
        json={"name": "交易模块"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    target = response.json()
    response = client.post(
        BASELINES.format(project_id=project.id)
        + f"/modules/{module['id']}/migrate",
        json={"target_module_id": target["id"], "function_ids": [function["id"]]},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_snapshot_revision(client: TestClient, db: Session):
    """走一遍提交 → 审核通过，返回 (project, 头, 审核头, revision)。"""
    project, headers, reviewer_headers, _, function = _baseline_function(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id) + "/reviews/submit",
        json={},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    revision = response.json()
    response = client.post(
        BASELINES.format(project_id=project.id)
        + f"/reviews/{revision['id']}/approve",
        json={},
        headers=reviewer_headers,
    )
    assert response.status_code == 200, response.text
    return project, headers, reviewer_headers, function, response.json()


def _baseline_label_create(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, function, revision = _baseline_snapshot_revision(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id) + "/labels",
        json={
            "revision_id": revision["id"],
            "target_type": "function",
            "target_id": function["id"],
            "label_type": "changed",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _baseline_label_clear(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, function, revision = _baseline_snapshot_revision(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id) + "/labels",
        json={
            "revision_id": revision["id"],
            "target_type": "function",
            "target_id": function["id"],
            "label_type": "changed",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    label = response.json()
    response = client.post(
        BASELINES.format(project_id=project.id) + f"/labels/{label['id']}/clear",
        json={"clear_reason": "requirement_done"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_revision_submit(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, _, _ = _baseline_function(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id) + "/reviews/submit",
        json={},
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _baseline_revision_approve(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, reviewer_headers, _, _ = _baseline_function(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id) + "/reviews/submit",
        json={},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    revision = response.json()
    response = client.post(
        BASELINES.format(project_id=project.id)
        + f"/reviews/{revision['id']}/approve",
        json={},
        headers=reviewer_headers,
    )
    assert response.status_code == 200, response.text


def _baseline_revision_reject(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, reviewer_headers, _, _ = _baseline_function(client, db)
    response = client.post(
        BASELINES.format(project_id=project.id) + "/reviews/submit",
        json={},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    revision = response.json()
    response = client.post(
        BASELINES.format(project_id=project.id)
        + f"/reviews/{revision['id']}/reject",
        json={"comment": "结构不对"},
        headers=reviewer_headers,
    )
    assert response.status_code == 200, response.text


def _baseline_snapshot_delete(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, _, revision = _baseline_snapshot_revision(client, db)
    response = client.delete(
        BASELINES.format(project_id=project.id) + f"/revisions/{revision['id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _baseline_retention_update(client: TestClient, db: Session, monkeypatch) -> None:
    project, headers, _, _, _ = _baseline_function(client, db)
    response = client.patch(
        BASELINES.format(project_id=project.id) + "/retention",
        json={"max_count": 5},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _incremental_analysis_create(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """发起增量分析（05）：文档版本生效 + 审核通过的快照 + 种子模板。"""
    project, _, headers, body = _uploaded(client, db)
    response = client.post(
        ACTIVATE.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        ),
        headers=headers,
    )
    assert response.status_code == 200, response.text

    revision = BaselineRevision(project_id=project.id, status="approved")
    db.add(revision)
    db.flush()
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.name == "增量分析·第一遍·章节局部",
        )
    )
    assert template is not None

    response = client.post(
        INCREMENTAL.format(project_id=project.id) + "/analyses",
        json={
            "template_id": template.id,
            "baseline_revision_id": revision.id,
            "document_version_id": body["version"]["id"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _incremental_second_pass_run(client: TestClient, db: Session, monkeypatch) -> None:
    """05 第二期：跑第二遍全局裁决。"""
    project, _, headers, body = _uploaded(client, db)
    response = client.post(
        ACTIVATE.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        ),
        headers=headers,
    )
    assert response.status_code == 200, response.text

    revision = BaselineRevision(project_id=project.id, status="approved")
    db.add(revision)
    db.flush()
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.name == "增量分析·第一遍·章节局部",
        )
    )
    assert template is not None

    response = client.post(
        INCREMENTAL.format(project_id=project.id) + "/analyses",
        json={
            "template_id": template.id,
            "baseline_revision_id": revision.id,
            "document_version_id": body["version"]["id"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    analysis_id = response.json()["id"]

    response = client.post(
        INCREMENTAL.format(project_id=project.id)
        + f"/analyses/{analysis_id}/second-pass",
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _incremental_conflict_resolve(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """05 第二期：人工裁决一条冲突。"""
    project, _, headers, body = _uploaded(client, db)
    response = client.post(
        ACTIVATE.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        ),
        headers=headers,
    )
    assert response.status_code == 200, response.text

    revision = BaselineRevision(project_id=project.id, status="approved")
    db.add(revision)
    db.flush()
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.name == "增量分析·第一遍·章节局部",
        )
    )
    assert template is not None

    response = client.post(
        INCREMENTAL.format(project_id=project.id) + "/analyses",
        json={
            "template_id": template.id,
            "baseline_revision_id": revision.id,
            "document_version_id": body["version"]["id"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    analysis_id = response.json()["id"]

    analysis = db.get(IncrementalAnalysis, analysis_id)
    conflict = IncrementalConflict(
        analysis_id=analysis_id,
        target_type="feature_point",
        target_id=None,
        target_name="审计新增功能点",
        conflict_type="new",
        candidates=[{"label_type": "new", "source": "point_pass"}],
    )
    db.add(conflict)
    db.flush()

    response = client.post(
        INCREMENTAL.format(project_id=project.id)
        + f"/analyses/{analysis_id}/conflicts/{conflict.id}/resolve",
        json={"decision": "rejected"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert analysis is not None


def _incremental_apply_run(client: TestClient, db: Session, monkeypatch) -> None:
    """05 第三期：应用产出（第二遍成功 + 已裁决 + 可落标签目标）。"""
    project, user, headers, body = _uploaded(client, db)
    response = client.post(
        ACTIVATE.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        ),
        headers=headers,
    )
    assert response.status_code == 200, response.text

    revision = BaselineRevision(project_id=project.id, status="approved")
    db.add(revision)
    db.flush()
    module = BaselineModule(
        project_id=project.id, name="审计模块", created_by=user.id
    )
    db.add(module)
    db.flush()
    function = BaselineFunction(
        project_id=project.id,
        module_id=module.id,
        name="审计功能",
        created_by=user.id,
    )
    db.add(function)
    db.flush()

    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.name == "增量分析·第一遍·章节局部",
        )
    )
    assert template is not None
    analysis = IncrementalAnalysis(
        project_id=project.id,
        template_id=template.id,
        template_version=template.version_no,
        baseline_revision_id=revision.id,
        document_id=body["document"]["id"],
        document_version_id=body["version"]["id"],
        status="succeeded",
        second_pass_status="succeeded",
        created_by=user.id,
    )
    db.add(analysis)
    db.flush()
    db.add(
        IncrementalDecision(
            analysis_id=analysis.id,
            target_type="function",
            target_id=function.id,
            target_name="审计功能",
            decision="changed",
        )
    )
    db.flush()

    response = client.post(
        INCREMENTAL.format(project_id=project.id)
        + f"/analyses/{analysis.id}/apply",
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _test_point_chain(client: TestClient, db: Session):
    """造出 07 期测试点需要的一条链：项目 + 文档版本 + 快照 + 结构 + 生效标签。

    返回 `(project, user, headers, function, version_id)`。
    """
    user = _user(db)
    project = _project(db)
    _join(db, project, user, "project_admin")
    headers = _headers(client, user)

    # 上传并生效一份文档——测试点要挂在章节上
    uploaded = client.post(
        DOCUMENTS.format(project_id=project.id),
        files={"file": ("审计.md", "# 审计\n正文".encode("utf-8"), "text/markdown")},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    activated = client.post(
        ACTIVATE.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        ),
        headers=headers,
    )
    assert activated.status_code == 200, activated.text

    revision = BaselineRevision(project_id=project.id, status="approved")
    db.add(revision)
    db.flush()
    module = BaselineModule(
        project_id=project.id, name="审计模块", created_by=user.id
    )
    db.add(module)
    db.flush()
    function = BaselineFunction(
        project_id=project.id,
        module_id=module.id,
        name="审计功能",
        created_by=user.id,
    )
    db.add(function)
    db.flush()
    db.add(
        BaselineLabel(
            project_id=project.id,
            revision_id=revision.id,
            target_type="function",
            target_id=function.id,
            label_type="changed",
            confirmed_by=user.id,
        )
    )
    db.flush()
    return project, user, headers, function, revision.id, body["version"]["id"]


def _test_point_analysis_create(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """07 期：发起一次测试点生成（走真实接口，模型侧用 Mock）。"""
    import json as _json

    from app.llm.mock import MockProvider
    from app.llm.provider import get_provider

    project, _, headers, function, revision_id, version_id = _test_point_chain(
        client, db
    )
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "test_point")
    )
    assert template is not None

    provider = MockProvider(
        queue=[
            _json.dumps(
                {
                    "test_points": [
                        {
                            "name": "审计测试点",
                            "target_type": "function",
                            "target_id": function.id,
                            "priority": "high",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )
    monkeypatch.setitem(
        fastapi_app.dependency_overrides, get_provider, lambda: provider
    )

    response = client.post(
        TEST_POINTS.format(project_id=project.id) + "/analyses",
        json={
            "template_id": template.id,
            "baseline_revision_id": revision_id,
            "document_version_id": version_id,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _chapter_link_analyze(client: TestClient, db: Session, monkeypatch) -> None:
    """12 期：AI 分析章节引用关系。

    需要一个可编程的模型供应商——审计覆盖用例跑的是真实接口，
    而 AI 分析要调模型。覆盖 `get_provider` 依赖换成 Mock。
    """
    from app.llm.mock import MockProvider
    from app.llm.provider import get_provider
    from app.main import app as fastapi_app

    mock = MockProvider()
    fastapi_app.dependency_overrides[get_provider] = lambda: mock

    project, _, headers, body = _uploaded(client, db)
    response = client.post(
        CHAPTER_LINKS.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        )
        + "/analyze",
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _chapter_link_create(client: TestClient, db: Session, monkeypatch) -> None:
    """05 第二期：人工补一条章节引用边。"""
    project, _, headers, body = _uploaded(client, db)
    chapter_id = db.scalar(
        select(DocumentChapter.id)
        .where(DocumentChapter.version_id == body["version"]["id"])
        .limit(1)
    )
    assert chapter_id is not None
    response = client.post(
        CHAPTER_LINKS.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        ),
        json={
            "from_chapter_id": chapter_id,
            "link_type": "mentions_entity",
            "entity": "审计功能",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


# ------------------------------------------------- 10 流程基线（10 期）场景


PROCESS_BASELINES = "/api/projects/{project_id}/process-baselines"
PROCESS_SCENARIOS = PROCESS_BASELINES + "/scenarios"
PROCESS_REVIEWS = PROCESS_BASELINES + "/reviews"


def _process_baseline_setup(client: TestClient, db: Session):
    """建项目 + 两个项目管理员（一个提交、一个审核）。

    返回 `(project, 提交人, 提交头, 审核头)`——审核用**另一个人**，
    更贴近真实的双人复核场景。
    """
    user = _user(db)
    reviewer = _user(db)
    project = _project(db)
    _join(db, project, user, "project_admin")
    _join(db, project, reviewer, "project_admin")
    return project, user, _headers(client, user), _headers(client, reviewer)


def _process_baseline_scenario(
    client: TestClient,
    db: Session,
    project: Project,
    headers: dict[str, str],
    *,
    name: str | None = None,
    links: list[dict] | None = None,
) -> int:
    """建一个流程基线场景，返回场景 id。"""
    body = {
        "name": name or f"审计场景-{uuid.uuid4().hex[:8]}",
        "description": "审计覆盖用的场景",
        "precondition": "已注册且未锁定",
        "source_type": "manual",
        "steps": [
            {"action": "打开登录页", "expected": "展示登录页"},
            {"action": "连续输错密码 5 次", "expected": "提示账号已锁定"},
        ],
    }
    if links:
        body["links"] = links
    response = client.post(
        PROCESS_SCENARIOS.format(project_id=project.id),
        json={"scenarios": [body]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["items"][0]["id"]


def _process_baseline_scenario_create(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """10 期：批量新建流程基线场景。"""
    project, _, headers, _ = _process_baseline_setup(client, db)
    _process_baseline_scenario(client, db, project, headers)


def _process_baseline_scenario_update(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """10 期：改流程基线场景。"""
    project, _, headers, _ = _process_baseline_setup(client, db)
    scenario_id = _process_baseline_scenario(client, db, project, headers)
    response = client.patch(
        PROCESS_SCENARIOS.format(project_id=project.id) + f"/{scenario_id}",
        json={"description": "改过的描述"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _process_baseline_scenario_delete(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """10 期：删流程基线场景。"""
    project, _, headers, _ = _process_baseline_setup(client, db)
    scenario_id = _process_baseline_scenario(client, db, project, headers)
    response = client.delete(
        PROCESS_SCENARIOS.format(project_id=project.id) + f"/{scenario_id}",
        headers=headers,
    )
    assert response.status_code == 204, response.text


def _process_baseline_steps_update(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """10 期：整体覆盖流程基线步骤。"""
    project, _, headers, _ = _process_baseline_setup(client, db)
    scenario_id = _process_baseline_scenario(client, db, project, headers)
    response = client.put(
        PROCESS_SCENARIOS.format(project_id=project.id) + f"/{scenario_id}/steps",
        json={"steps": [{"action": "新步骤", "expected": "新预期"}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _process_baseline_links_update(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """10 期：整体覆盖流程基线关联。"""
    project, user, headers, _ = _process_baseline_setup(client, db)
    module = BaselineModule(
        project_id=project.id,
        name=f"审计模块-{uuid.uuid4().hex[:6]}",
        created_by=user.id,
    )
    db.add(module)
    db.flush()
    function = BaselineFunction(
        project_id=project.id,
        module_id=module.id,
        name=f"审计功能-{uuid.uuid4().hex[:6]}",
        created_by=user.id,
    )
    db.add(function)
    db.flush()
    scenario_id = _process_baseline_scenario(client, db, project, headers)
    response = client.put(
        PROCESS_SCENARIOS.format(project_id=project.id) + f"/{scenario_id}/links",
        json={"links": [{"target_type": "function", "target_id": function.id}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _process_baseline_derive_run(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """10 期：发起流程基线文档反推（模型侧用 Mock，不产生真实 socket）。"""
    from app.llm.mock import MockProvider
    from app.llm.provider import get_provider

    project, user, headers, _ = _process_baseline_setup(client, db)

    document = Document(
        project_id=project.id,
        name=f"审计需求-{uuid.uuid4().hex[:6]}",
        created_by=user.id,
    )
    db.add(document)
    db.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        status="active",
        file_name="需求.md",
        file_path=f"var/uploads/{project.id}/{uuid.uuid4().hex}.md",
        file_size=128,
        sha256="d" * 64,
        chapter_count=1,
        uploaded_by=user.id,
    )
    db.add(version)
    db.flush()
    db.add(
        DocumentChapter(
            version_id=version.id,
            parent_id=None,
            seq=1,
            level=1,
            title="4.2 登录失败次数限制",
            content="账号连续输错密码 5 次后锁定",
            char_count=12,
        )
    )
    db.flush()

    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "process_baseline",
            PromptTemplate.status == "active",
        )
    )
    assert template is not None, "迁移 0025 应播种一条 process_baseline 模板"

    provider = MockProvider()
    monkeypatch.setitem(
        fastapi_app.dependency_overrides, get_provider, lambda: provider
    )

    response = client.post(
        PROCESS_BASELINES.format(project_id=project.id) + "/derive",
        json={
            "document_id": document.id,
            "document_version_id": version.id,
            "template_id": template.id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _process_baseline_review_submit(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """10 期：提交流程基线审核（**必须有 active 场景**，否则 400 不建快照）。"""
    project, _, headers, _ = _process_baseline_setup(client, db)
    _process_baseline_scenario(client, db, project, headers)
    response = client.post(
        PROCESS_REVIEWS.format(project_id=project.id) + "/submit",
        json={},
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _process_baseline_review_approve(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """10 期：审核通过流程基线快照（先提交，再由**另一个**管理员通过）。"""
    project, _, headers, reviewer_headers = _process_baseline_setup(client, db)
    _process_baseline_scenario(client, db, project, headers)
    submitted = client.post(
        PROCESS_REVIEWS.format(project_id=project.id) + "/submit",
        json={},
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    response = client.post(
        PROCESS_REVIEWS.format(project_id=project.id)
        + f"/{submitted.json()['id']}/approve",
        json={},
        headers=reviewer_headers,
    )
    assert response.status_code == 200, response.text


def _process_baseline_review_reject(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """10 期：驳回流程基线快照（意见必填）。"""
    project, _, headers, reviewer_headers = _process_baseline_setup(client, db)
    _process_baseline_scenario(client, db, project, headers)
    submitted = client.post(
        PROCESS_REVIEWS.format(project_id=project.id) + "/submit",
        json={},
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    response = client.post(
        PROCESS_REVIEWS.format(project_id=project.id)
        + f"/{submitted.json()['id']}/reject",
        json={"comment": "步骤写漏了"},
        headers=reviewer_headers,
    )
    assert response.status_code == 200, response.text


# ------------------------------------------------- 06 大模型配置与模板


def _llm_provider_create(client: TestClient, db: Session, monkeypatch) -> None:
    """06 期：新建一条大模型配置。"""
    admin = _user(db, global_role="system_admin")
    response = client.post(
        "/api/admin/llm-providers",
        json={
            "name": "审计配置",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-audit-1234",
            "model": "deepseek-chat",
            "timeout_seconds": 60,
        },
        headers=_headers(client, admin),
    )
    assert response.status_code == 201, response.text


def _llm_provider_update(client: TestClient, db: Session, monkeypatch) -> None:
    """06 期：更新一条大模型配置。"""
    admin = _user(db, global_role="system_admin")
    headers = _headers(client, admin)
    created = client.post(
        "/api/admin/llm-providers",
        json={
            "name": "待改配置",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-audit-1234",
            "model": "deepseek-chat",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    provider_id = created.json()["id"]
    response = client.put(
        f"/api/admin/llm-providers/{provider_id}",
        json={"model": "deepseek-reasoner"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _prompt_template_update(client: TestClient, db: Session, monkeypatch) -> None:
    """06 期：编辑一条提示词模板。"""
    admin = _user(db, global_role="system_admin")
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.name == "增量分析·第一遍·章节局部",
        )
    )
    assert template is not None
    response = client.put(
        f"/api/admin/prompt-templates/{template.id}",
        json={"description": "审计覆盖改的描述"},
        headers=_headers(client, admin),
    )
    assert response.status_code == 200, response.text


def _automation_run_execute(client: TestClient, db: Session, monkeypatch) -> None:
    """09 期 T114：触发一次自动化执行（走真实接口，真跑一次 pytest）。"""
    import sys
    import tempfile
    from pathlib import Path

    from app.automation.schemas import AssetCreateItem, AssetsCreate
    from app.automation.service import confirm_assets

    root = Path(tempfile.mkdtemp(prefix="audit-auto-"))
    (root / "test_audit.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    monkeypatch.setenv("AUTOMATION_ROOT", str(root))
    get_settings.cache_clear()

    user = _user(db)
    project = _project(db)
    _join(db, project, user, "project_admin")
    headers = _headers(client, user)

    created = confirm_assets(
        db,
        project_id=project.id,
        actor=user,
        payload=AssetsCreate(
            assets=[
                AssetCreateItem(
                    file_path="test_audit.py",
                    name="test_audit.py",
                    framework="pytest",
                )
            ]
        ),
    )
    asset_id = created["items"][0]["asset_id"]

    response = client.post(
        f"/api/projects/{project.id}/automation/runs",
        json={"asset_ids": [asset_id]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert sys.executable  # 执行器用的就是当前解释器


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
    "document.upload": _document_upload,
    "document.version.activate": _version_activate,
    "document.version.void": _version_void,
    "baseline.snapshot.create": _baseline_snapshot,
    "baseline.module.create": _baseline_module,
    "baseline.module.update": _baseline_module_update,
    "baseline.module.delete": _baseline_module_delete,
    "baseline.function.create": _baseline_function,
    "baseline.function.update": _baseline_function_update,
    "baseline.function.delete": _baseline_function_delete,
    "baseline.feature_point.create": _baseline_point,
    "baseline.feature_point.update": _baseline_point_update,
    "baseline.feature_point.delete": _baseline_point_delete,
    "baseline.module.migrate": _baseline_migrate,
    "baseline.label.create": _baseline_label_create,
    "baseline.label.clear": _baseline_label_clear,
    "baseline.revision.submit": _baseline_revision_submit,
    "baseline.revision.approve": _baseline_revision_approve,
    "baseline.revision.reject": _baseline_revision_reject,
    "baseline.snapshot.delete": _baseline_snapshot_delete,
    "baseline.retention.update": _baseline_retention_update,
    "incremental.analysis.create": _incremental_analysis_create,
    "incremental.second_pass.run": _incremental_second_pass_run,
    "incremental.conflict.resolve": _incremental_conflict_resolve,
    "incremental.apply.run": _incremental_apply_run,
    "document.chapter_link.create": _chapter_link_create,
    "document.chapter_link.analyze": _chapter_link_analyze,
    "llm.provider.create": _llm_provider_create,
    "llm.provider.update": _llm_provider_update,
    "prompt_template.update": _prompt_template_update,
    "test_point.analysis.create": _test_point_analysis_create,
    "automation.run.execute": _automation_run_execute,
    "process_baseline.scenario.create": _process_baseline_scenario_create,
    "process_baseline.scenario.update": _process_baseline_scenario_update,
    "process_baseline.scenario.delete": _process_baseline_scenario_delete,
    "process_baseline.steps.update": _process_baseline_steps_update,
    "process_baseline.links.update": _process_baseline_links_update,
    "process_baseline.derive.run": _process_baseline_derive_run,
    "process_baseline.review.submit": _process_baseline_review_submit,
    "process_baseline.review.approve": _process_baseline_review_approve,
    "process_baseline.review.reject": _process_baseline_review_reject,
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


def test_ac_61_document_actions_carry_scope(client: TestClient, db: Session):
    """文档相关审计要能定位到项目、操作者与目标对象。"""
    project, user, headers, body = _uploaded(client, db)
    assert client.post(
        ACTIVATE.format(
            project_id=project.id,
            document_id=body["document"]["id"],
            version_id=body["version"]["id"],
        ),
        headers=headers,
    ).status_code == 200

    rows = {
        row.action: row
        for row in db.scalars(
            select(AuditLog).where(AuditLog.project_id == project.id)
        ).all()
    }

    upload = rows["document.upload"]
    assert (upload.actor_id, upload.target_type, upload.target_id) == (
        user.id,
        "document_version",
        str(body["version"]["id"]),
    )
    assert upload.after_data["document_id"] == body["document"]["id"]

    activate = rows["document.version.activate"]
    assert (activate.actor_id, activate.target_type, activate.target_id) == (
        user.id,
        "document_version",
        str(body["version"]["id"]),
    )

    snapshot = rows["baseline.snapshot.create"]
    assert snapshot.actor_id == user.id
    assert snapshot.target_type == "baseline_snapshot"
    assert snapshot.target_id is not None
    assert snapshot.after_data["baseline_version_no"] == 1


def test_ac_75_baseline_actions_carry_scope(client: TestClient, db: Session):
    """功能基线的审计要带项目、操作者、目标类型与目标 id（AC-75）。"""
    project, headers, reviewer_headers, module, function = _baseline_function(
        client, db
    )

    rows = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action.in_(
                [
                    "baseline.module.create",
                    "baseline.function.create",
                ]
            ),
        )
    ).all()
    by_action = {row.action: row for row in rows}

    module_log = by_action["baseline.module.create"]
    assert module_log.actor_id is not None
    assert module_log.target_type == "baseline_module"
    assert module_log.target_id == str(module["id"])

    function_log = by_action["baseline.function.create"]
    assert function_log.actor_id is not None
    assert function_log.target_type == "baseline_function"
    assert function_log.target_id == str(function["id"])


def test_ac_75_failed_operation_writes_no_audit(client: TestClient, db: Session):
    """失败操作不写审计：重名模块被拒时不产生 module.create。"""
    project, headers, _, module = _baseline_module(client, db)

    conflict = client.post(
        BASELINES.format(project_id=project.id) + "/modules",
        json={"name": "支付模块"},
        headers=headers,
    )
    assert conflict.status_code == 409

    count = db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.project_id == project.id,
            AuditLog.action == "baseline.module.create",
        )
    ).scalar_one()
    assert count == 1
