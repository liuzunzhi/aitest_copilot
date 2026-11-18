"""项目列表 / 可申请列表 / 数据隔离（T19，AC-26 ~ 30）。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import settings as settings_service
from app.common.errors import NotProjectMember
from app.common.scoped_repo import ProjectScopedRepo
from app.common.security import hash_password
from app.common.settings import set_setting
from app.models.project import Project, ProjectMember
from app.models.user import User

PROJECTS = "/api/projects"
AVAILABLE = "/api/projects/available"

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)


class _MemberRepo(ProjectScopedRepo):
    """测试用的最小子类：只声明要隔离的模型。"""

    model = ProjectMember


@pytest.fixture(autouse=True)
def clean_settings_cache():
    settings_service.cache_clear()
    yield
    settings_service.cache_clear()


def _user(db: Session) -> User:
    user = User(
        username=f"iso-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
    )
    db.add(user)
    db.flush()
    return user


def _project(db: Session, *, name: str | None = None, status: str = "active") -> Project:
    project = Project(name=name or f"project-{uuid.uuid4().hex[:6]}", status=status)
    db.add(project)
    db.flush()
    return project


def _join(db: Session, project: Project, user: User, role: str = "member") -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def _token(client: TestClient, user: User) -> str:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(client: TestClient, user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(client, user)}"}


def test_list_only_returns_joined_projects(client: TestClient, db: Session):
    """AC-26：只返回自己加入的项目，并带上项目内角色。"""
    user = _user(db)
    joined = _project(db)
    _project(db)
    _join(db, joined, user, role="project_admin")

    response = client.get(PROJECTS, headers=_auth(client, user))

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [joined.id]
    assert body[0]["role"] == "project_admin"
    assert body[0]["name"] == joined.name


def test_list_empty_without_projects(client: TestClient, db: Session):
    """AC-28：无项目用户返回空数组，不报错、不返回任何项目元信息。"""
    user = _user(db)
    _project(db)

    response = client.get(PROJECTS, headers=_auth(client, user))

    assert response.status_code == 200
    assert response.json() == []


def test_list_requires_login(client: TestClient):
    response = client.get(PROJECTS)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_available_returns_all_unjoined_projects(client: TestClient, db: Session):
    """AC-29：返回全部未加入的项目，不返回已加入的。

    只断言**本用例造出来的**项目：开发库里可能有管理员手工建的项目，
    全表比对会因那些数据而失败。
    """
    user = _user(db)
    joined = _project(db)
    second = _project(db)
    third = _project(db)
    _join(db, joined, user)

    response = client.get(AVAILABLE, headers=_auth(client, user))

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()]
    assert second.id in ids
    assert third.id in ids
    assert joined.id not in ids


def test_available_excludes_archived(client: TestClient, db: Session):
    """归档项目无法再加入，不出现在可申请列表里。"""
    user = _user(db)
    active = _project(db)
    archived = _project(db, status="archived")

    response = client.get(AVAILABLE, headers=_auth(client, user))

    ids = [item["id"] for item in response.json()]
    assert active.id in ids
    assert archived.id not in ids


def test_available_empty_state(client: TestClient, db: Session):
    """AC-30 的后端部分：没有可申请项目时返回空数组。

    把当前所有生效项目都加入该用户 → 可申请列表必然为空。
    这样断言不依赖开发库里有没有别的手工项目。
    """
    user = _user(db)
    for project in db.scalars(
        select(Project).where(Project.status == "active")
    ).all():
        _join(db, project, user)

    response = client.get(AVAILABLE, headers=_auth(client, user))

    assert response.status_code == 200
    assert response.json() == []


def test_available_not_affected_by_apply_switch(client: TestClient, db: Session):
    """AC-29：enable_project_apply 开关不影响列表，只影响提交。"""
    user = _user(db)
    open_project = _project(db)
    set_setting(db, "enable_project_apply", False)

    response = client.get(AVAILABLE, headers=_auth(client, user))

    assert open_project.id in [item["id"] for item in response.json()]


def test_scoped_repo_rejects_non_member(db: Session):
    """AC-27：隔离类的构造即校验成员身份。"""
    owner = _user(db)
    outsider = _user(db)
    project = _project(db)
    _join(db, project, owner)

    with pytest.raises(NotProjectMember):
        _MemberRepo(db, project.id, outsider.id)

    repo = _MemberRepo(db, project.id, owner.id)
    assert repo.scoped(select(ProjectMember.user_id)).scalars().all() == [owner.id]


def test_scoped_repo_filters_other_projects(db: Session):
    """同一张表里其他项目的数据不能被读出来。"""
    user = _user(db)
    first = _project(db)
    second = _project(db)
    _join(db, first, user)
    other = _user(db)
    _join(db, second, other)

    repo = _MemberRepo(db, first.id, user.id)

    assert repo.scoped(select(ProjectMember.user_id)).scalars().all() == [user.id]
