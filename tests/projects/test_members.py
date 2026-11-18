"""项目成员列表（T32，AC-35）与添加成员（T33，AC-36）。"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.common.db import session_scope
from app.common.errors import AlreadyProjectMember, LastProjectAdmin
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
        select(AuditLog).where(
            AuditLog.action == "project.member.add",
            AuditLog.project_id == project.id,
        )
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


def _member_url(project: Project, user: User) -> str:
    return f"/api/projects/{project.id}/members/{user.id}"


def test_ac_37_update_role(client: TestClient, db: Session) -> None:
    """项目管理员改角色：200、落库、审计 before/after 都是 {"role": ...}。"""
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    target = _user(db)
    _join(db, project, target, "member")

    response = client.patch(
        _member_url(project, target),
        json={"role": "guest"},
        headers=_auth(client, admin),
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["user_id"], body["username"], body["role"]) == (
        target.id,
        target.username,
        "guest",
    )

    db.expire_all()
    assert db.get(ProjectMember, (project.id, target.id)).role == "guest"

    audit = db.execute(
        select(AuditLog).where(
            AuditLog.action == "project.member.role",
            AuditLog.project_id == project.id,
        )
    ).scalar_one()
    assert audit.before_data == {"role": "member"}
    assert audit.after_data == {"role": "guest"}
    assert audit.target_type == "project_member"
    assert audit.target_id == str(target.id)


@pytest.mark.parametrize("role", ["system_admin", "owner", None])
def test_ac_37_invalid_role(client: TestClient, db: Session, role) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    target = _user(db)
    _join(db, project, target, "member")
    payload = {} if role is None else {"role": role}

    response = client.patch(
        _member_url(project, target), json=payload, headers=_auth(client, admin)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_ROLE_ASSIGNMENT"


def test_ac_37_member_not_found(client: TestClient, db: Session) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    outsider = _user(db)

    response = client.patch(
        _member_url(project, outsider),
        json={"role": "member"},
        headers=_auth(client, admin),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "MEMBER_NOT_FOUND"


def test_ac_37_last_project_admin_cannot_be_downgraded(
    client: TestClient, db: Session
) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")

    response = client.patch(
        _member_url(project, admin),
        json={"role": "member"},
        headers=_auth(client, admin),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "LAST_PROJECT_ADMIN"

    db.expire_all()
    assert db.get(ProjectMember, (project.id, admin.id)).role == "project_admin"


def test_ac_37_downgrade_when_two_admins(client: TestClient, db: Session) -> None:
    project = _project(db)
    first = _user(db)
    second = _user(db)
    _join(db, project, first, "project_admin")
    _join(db, project, second, "project_admin")

    response = client.patch(
        _member_url(project, second),
        json={"role": "member"},
        headers=_auth(client, first),
    )

    assert response.status_code == 200
    assert response.json()["role"] == "member"


def test_ac_37_archived_project_read_only(client: TestClient, db: Session) -> None:
    project = _project(db, status="archived")
    admin = _user(db)
    target = _user(db)
    _join(db, project, admin, "project_admin")
    _join(db, project, target, "member")

    response = client.patch(
        _member_url(project, target),
        json={"role": "guest"},
        headers=_auth(client, admin),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_37_member_cannot_update_role(client: TestClient, db: Session) -> None:
    project = _project(db)
    member = _user(db)
    _join(db, project, member, "member")
    target = _user(db)
    _join(db, project, target, "guest")

    response = client.patch(
        _member_url(project, target),
        json={"role": "member"},
        headers=_auth(client, member),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_37_concurrent_downgrade_keeps_one_admin() -> None:
    """两名管理员互相降级：只能成功一个，最后仍剩一名 project_admin。"""
    suffix = uuid.uuid4().hex[:8]
    with session_scope() as session:
        first = User(username=f"race-role-first-{suffix}", password_hash=PASSWORD_HASH)
        second = User(username=f"race-role-second-{suffix}", password_hash=PASSWORD_HASH)
        project = Project(name=f"race-role-{suffix}")
        session.add_all([first, second, project])
        session.flush()
        session.add_all(
            [
                ProjectMember(
                    project_id=project.id, user_id=first.id, role="project_admin"
                ),
                ProjectMember(
                    project_id=project.id, user_id=second.id, role="project_admin"
                ),
            ]
        )
        session.flush()
        project_id = project.id
        pair = [(first.id, second.id), (second.id, first.id)]

    def attempt(index: int) -> str:
        actor_id, target_id = pair[index]
        with session_scope() as session:
            actor = session.get(User, actor_id)
            try:
                service.update_member_role(
                    session,
                    actor=actor,
                    project_id=project_id,
                    user_id=target_id,
                    role="member",
                )
            except LastProjectAdmin:
                return "conflict"
            return "updated"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(attempt, range(2))) == ["conflict", "updated"]

        with session_scope() as session:
            admins = session.execute(
                select(func.count())
                .select_from(ProjectMember)
                .where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.role == "project_admin",
                )
            ).scalar_one()
            assert admins == 1
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
                text("DELETE FROM users WHERE username IN (:first, :second)"),
                {
                    "first": f"race-role-first-{suffix}",
                    "second": f"race-role-second-{suffix}",
                },
            )


def test_ac_38_remove_member(client: TestClient, db: Session) -> None:
    """移除成员：200、记录删除、审计留角色、目标用户立即失去项目访问。"""
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    target = _user(db)
    _join(db, project, target, "member")
    headers = _auth(client, target)

    response = client.delete(_member_url(project, target), headers=_auth(client, admin))

    assert response.status_code == 200
    assert response.json() == {"status": "removed"}

    db.expire_all()
    assert db.get(ProjectMember, (project.id, target.id)) is None

    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "project.member.remove")
    ).scalar_one()
    assert audit.before_data == {"role": "member"}
    assert audit.target_id == str(target.id)

    assert client.get(_url(project), headers=headers).status_code == 403
    assert client.get("/api/projects", headers=headers).json() == []


def test_ac_38_cannot_remove_self(client: TestClient, db: Session) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")

    response = client.delete(_member_url(project, admin), headers=_auth(client, admin))

    assert response.status_code == 400
    assert response.json()["code"] == "CANNOT_REMOVE_SELF"

    db.expire_all()
    assert db.get(ProjectMember, (project.id, admin.id)) is not None


def test_ac_38_project_admin_cannot_remove_system_admin(
    client: TestClient, db: Session
) -> None:
    project = _project(db)
    admin = _user(db)
    target = _user(db, global_role="system_admin")
    _join(db, project, admin, "project_admin")
    _join(db, project, target, "member")

    response = client.delete(_member_url(project, target), headers=_auth(client, admin))

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"

    db.expire_all()
    assert db.get(ProjectMember, (project.id, target.id)) is not None


def test_ac_38_last_project_admin_cannot_be_removed(
    client: TestClient, db: Session
) -> None:
    project = _project(db)
    sole_admin = _user(db)
    _join(db, project, sole_admin, "project_admin")
    system_admin = _user(db, global_role="system_admin")

    response = client.delete(
        _member_url(project, sole_admin), headers=_auth(client, system_admin)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "LAST_PROJECT_ADMIN"


def test_ac_38_member_not_found(client: TestClient, db: Session) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    outsider = _user(db)

    response = client.delete(_member_url(project, outsider), headers=_auth(client, admin))

    assert response.status_code == 404
    assert response.json()["code"] == "MEMBER_NOT_FOUND"


def test_ac_38_archived_project_read_only(client: TestClient, db: Session) -> None:
    project = _project(db, status="archived")
    admin = _user(db)
    target = _user(db)
    _join(db, project, admin, "project_admin")
    _join(db, project, target, "member")

    response = client.delete(_member_url(project, target), headers=_auth(client, admin))

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_38_member_cannot_remove(client: TestClient, db: Session) -> None:
    project = _project(db)
    member = _user(db)
    target = _user(db)
    _join(db, project, member, "member")
    _join(db, project, target, "guest")

    response = client.delete(_member_url(project, target), headers=_auth(client, member))

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"
