"""工作台待办计数（T110.5，AC-193）。

三项待办构成「基线产出 → 评审 → 用例」的主链路待办：
待审核基线 / 待评审测试点 / 待评审用例。

**项目隔离是本文件的第一红线**：另一个项目的待评审数据不得计入本项目。
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.baseline import BaselineRevision
from app.models.project import Project, ProjectMember
from app.models.test_case import TestCase
from app.models.test_point import TestPoint
from app.models.user import User

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"todos-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _project(db: Session, *, status: str = "active") -> Project:
    project = Project(name=f"todos-{uuid.uuid4().hex[:6]}", status=status)
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
    return f"/api/projects/{project.id}/todos"


def _revision(db: Session, project: Project, *, status: str) -> BaselineRevision:
    """一条审核记录。`structure_json` 只在 approved 时有意义，这里不填。"""
    revision = BaselineRevision(project_id=project.id, status=status)
    db.add(revision)
    db.flush()
    return revision


def _point(db: Session, project: Project, *, status: str, actor: User) -> TestPoint:
    point = TestPoint(
        project_id=project.id,
        name=f"测试点-{uuid.uuid4().hex[:6]}",
        target_type="function",
        target_id=1,
        target_name="功能",
        status=status,
        created_by=actor.id,
    )
    db.add(point)
    db.flush()
    return point


def _case(db: Session, project: Project, *, status: str, actor: User) -> TestCase:
    case = TestCase(
        project_id=project.id,
        test_point_id=1,
        test_point_name="测试点",
        title=f"用例-{uuid.uuid4().hex[:6]}",
        target_type="function",
        target_id=1,
        target_name="功能",
        status=status,
        created_by=actor.id,
    )
    db.add(case)
    db.flush()
    return case


def test_ac_193_counts_three_pending_kinds(
    client: TestClient, db: Session
) -> None:
    """三项计数与实际造数一致，`total` 是三项之和。"""
    project = _project(db)
    viewer = _user(db)
    _join(db, project, viewer, "project_admin")

    for _ in range(2):
        _revision(db, project, status="submitted")
    for _ in range(5):
        _point(db, project, status="pending", actor=viewer)
    for _ in range(8):
        _case(db, project, status="pending", actor=viewer)

    response = client.get(_url(project), headers=_auth(client, viewer))

    assert response.status_code == 200
    assert response.json() == {
        "pending_baseline_reviews": 2,
        "pending_test_point_reviews": 5,
        "pending_test_case_reviews": 8,
        "total": 15,
    }


def test_ac_193_excludes_non_pending_rows(
    client: TestClient, db: Session
) -> None:
    """已通过 / 已驳回 / 已归档的记录不计入待办。"""
    project = _project(db)
    viewer = _user(db)
    _join(db, project, viewer, "project_admin")

    _revision(db, project, status="approved")
    _revision(db, project, status="rejected")
    _point(db, project, status="approved", actor=viewer)
    _point(db, project, status="rejected", actor=viewer)
    _case(db, project, status="approved", actor=viewer)
    _case(db, project, status="rejected", actor=viewer)

    response = client.get(_url(project), headers=_auth(client, viewer))

    assert response.status_code == 200
    assert response.json() == {
        "pending_baseline_reviews": 0,
        "pending_test_point_reviews": 0,
        "pending_test_case_reviews": 0,
        "total": 0,
    }


def test_ac_193_isolated_between_projects(
    client: TestClient, db: Session
) -> None:
    """另一个项目的待评审数据不计入本项目（项目隔离）。"""
    project_a = _project(db)
    project_b = _project(db)
    viewer = _user(db)
    _join(db, project_a, viewer, "project_admin")
    _join(db, project_b, viewer, "project_admin")

    _revision(db, project_b, status="submitted")
    _point(db, project_b, status="pending", actor=viewer)
    _case(db, project_b, status="pending", actor=viewer)

    response = client.get(_url(project_a), headers=_auth(client, viewer))

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_ac_193_member_can_read(client: TestClient, db: Session) -> None:
    """成员可读——待办是团队共享的工作队列，不是管理员专属。"""
    project = _project(db)
    member = _user(db)
    _join(db, project, member, "member")

    response = client.get(_url(project), headers=_auth(client, member))

    assert response.status_code == 200


def test_ac_193_guest_can_read(client: TestClient, db: Session) -> None:
    """访客也是项目成员，可读待办计数。"""
    project = _project(db)
    guest = _user(db)
    _join(db, project, guest, "guest")

    response = client.get(_url(project), headers=_auth(client, guest))

    assert response.status_code == 200


def test_ac_193_system_admin_can_read_without_membership(
    client: TestClient, db: Session
) -> None:
    project = _project(db)
    _join(db, project, _user(db), "project_admin")
    admin = _user(db, global_role="system_admin")

    response = client.get(_url(project), headers=_auth(client, admin))

    assert response.status_code == 200


def test_ac_193_non_member_forbidden(client: TestClient, db: Session) -> None:
    """非项目成员 → 403 `NOT_PROJECT_MEMBER`。"""
    project = _project(db)
    _join(db, project, _user(db), "project_admin")
    outsider = _user(db)

    response = client.get(_url(project), headers=_auth(client, outsider))

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_193_missing_project_returns_404(client: TestClient, db: Session) -> None:
    """项目不存在 → 404 `PROJECT_NOT_FOUND`（与「不是成员」区分开）。"""
    viewer = _user(db)

    response = client.get("/api/projects/999999/todos", headers=_auth(client, viewer))

    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


def test_ac_193_archived_project_still_readable(
    client: TestClient, db: Session
) -> None:
    """归档项目读接口正常——归档只挡写。"""
    project = _project(db, status="archived")
    viewer = _user(db)
    _join(db, project, viewer, "project_admin")

    response = client.get(_url(project), headers=_auth(client, viewer))

    assert response.status_code == 200


def test_ac_193_requires_login(client: TestClient, db: Session) -> None:
    project = _project(db)

    response = client.get(_url(project))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
