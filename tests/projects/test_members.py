"""项目成员列表（T32，AC-35）与添加成员（T33，AC-36）。"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.common.db import session_scope
from app.common.errors import AlreadyProjectMember
from app.common.security import hash_password
from app.models.project import Project, ProjectMember
from app.models.system import AuditLog
from app.models.user import User
from app.projects import service

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


def _add(
    client: TestClient,
    project: Project,
    target: User,
    *,
    role: str | None = "member",
    headers: dict[str, str],
):
    payload: dict = {"user_id": target.id}
    if role is not None:
        payload["role"] = role
    return client.post(_url(project), json=payload, headers=headers)


def test_ac_36_add_member(client: TestClient, db: Session) -> None:
    """项目管理员添加成员：201、落成员表、写 project.member.add 审计。"""
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    target = _user(db)

    response = _add(client, project, target, headers=_auth(client, admin))

    assert response.status_code == 201
    body = response.json()
    assert (body["user_id"], body["username"], body["role"]) == (
        target.id,
        target.username,
        "member",
    )
    assert isinstance(body["joined_at"], str)

    db.expire_all()
    assert db.get(ProjectMember, (project.id, target.id)).role == "member"

    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "project.member.add")
    ).scalar_one()
    assert audit.actor_id == admin.id
    assert audit.target_type == "project_member"
    assert audit.target_id == str(target.id)
    assert audit.after_data == {"role": "member"}


def test_ac_36_system_admin_can_add_without_membership(
    client: TestClient, db: Session
) -> None:
    project = _project(db)
    target = _user(db)
    admin = _user(db, global_role="system_admin")

    response = _add(client, project, target, headers=_auth(client, admin))

    assert response.status_code == 201


@pytest.mark.parametrize("role", ["system_admin", "owner", None])
def test_ac_36_invalid_role(client: TestClient, db: Session, role) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    target = _user(db)

    response = _add(client, project, target, role=role, headers=_auth(client, admin))

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_ROLE_ASSIGNMENT"


def test_ac_36_user_not_found(client: TestClient, db: Session) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")

    response = client.post(
        _url(project), json={"user_id": 999999999, "role": "member"}, headers=_auth(client, admin)
    )

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_ac_36_duplicate_member(client: TestClient, db: Session) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    target = _user(db)
    _join(db, project, target, "guest")

    response = _add(client, project, target, headers=_auth(client, admin))

    assert response.status_code == 409
    assert response.json()["code"] == "ALREADY_PROJECT_MEMBER"


def test_ac_36_archived_project_read_only(client: TestClient, db: Session) -> None:
    project = _project(db, status="archived")
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    target = _user(db)

    response = _add(client, project, target, headers=_auth(client, admin))

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_36_member_cannot_add(client: TestClient, db: Session) -> None:
    project = _project(db)
    member = _user(db)
    _join(db, project, member, "member")
    target = _user(db)

    response = _add(client, project, target, headers=_auth(client, member))

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_36_concurrent_add_only_one_wins() -> None:
    """并发重复添加：一条成功、一条 409，成员与审计都只落一条。

    这条用例必须真实提交，因此自己建数据、结束时清理。
    """
    suffix = uuid.uuid4().hex[:8]
    with session_scope() as session:
        admin = User(username=f"race-add-admin-{suffix}", password_hash=PASSWORD_HASH)
        target = User(username=f"race-add-target-{suffix}", password_hash=PASSWORD_HASH)
        project = Project(name=f"race-add-{suffix}")
        session.add_all([admin, target, project])
        session.flush()
        session.add(
            ProjectMember(
                project_id=project.id, user_id=admin.id, role="project_admin"
            )
        )
        session.flush()
        project_id, admin_id, target_id = project.id, admin.id, target.id

    def attempt(_: int) -> str:
        with session_scope() as session:
            admin_obj = session.get(User, admin_id)
            try:
                service.add_member(
                    session,
                    actor=admin_obj,
                    project_id=project_id,
                    user_id=target_id,
                    role="member",
                )
            except AlreadyProjectMember:
                return "conflict"
            return "added"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(attempt, range(2))) == ["added", "conflict"]

        with session_scope() as session:
            members = session.execute(
                select(func.count())
                .select_from(ProjectMember)
                .where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == target_id,
                )
            ).scalar_one()
            audits = session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "project.member.add",
                    AuditLog.project_id == project_id,
                )
            ).scalar_one()
            assert (members, audits) == (1, 1)
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
                text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id}
            )
            session.execute(
                text("DELETE FROM users WHERE username IN (:admin, :target)"),
                {
                    "admin": f"race-add-admin-{suffix}",
                    "target": f"race-add-target-{suffix}",
                },
            )
