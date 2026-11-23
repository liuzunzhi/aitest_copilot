"""流程基线用例的造数与登录辅助（T118）。

**零真实 socket**：本目录不引入任何网络客户端，
请求全部走 `fastapi.testclient.TestClient`（进程内 ASGI）。
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.baseline import BaselineFeaturePoint, BaselineFunction, BaselineModule
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.project import Project, ProjectMember
from app.models.user import User

PASSWORD = "ProcessPass1"
PASSWORD_HASH = hash_password(PASSWORD)

BASE = "/api/projects/{project_id}/process-baselines"
SCENARIOS = BASE + "/scenarios"
# 04 的功能基线路由——用来验证「04 物理删功能后流程基线的链接仍可读」
BASELINES = "/api/projects/{project_id}/baselines"


def make_user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"pb-{uuid.uuid4().hex[:10]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def login(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_project(db: Session, *, status: str = "active") -> Project:
    project = Project(name=f"流程基线项目-{uuid.uuid4().hex[:6]}", status=status)
    db.add(project)
    db.flush()
    return project


def add_member(db: Session, project: Project, user: User, role: str = "member") -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def make_chain(db: Session, *, role: str = "project_admin", status: str = "active") -> dict:
    """一条最小链：用户 + 项目 + 成员关系。"""
    user = make_user(db)
    project = make_project(db, status=status)
    add_member(db, project, user, role)
    return {"user": user, "project": project}


def make_function(
    db: Session,
    project: Project,
    user: User,
    *,
    name: str = "用户扫码登录",
    status: str = "active",
) -> BaselineFunction:
    """建一个功能（04 的功能基线）——关联目标的来源。"""
    module = BaselineModule(
        project_id=project.id, name=f"模块-{uuid.uuid4().hex[:6]}", created_by=user.id
    )
    db.add(module)
    db.flush()
    function = BaselineFunction(
        project_id=project.id,
        module_id=module.id,
        name=name,
        status=status,
        created_by=user.id,
    )
    db.add(function)
    db.flush()
    return function


def make_feature_point(
    db: Session,
    project: Project,
    user: User,
    function: BaselineFunction,
    *,
    name: str = "展示扫码二维码",
    status: str = "active",
) -> BaselineFeaturePoint:
    point = BaselineFeaturePoint(
        project_id=project.id,
        function_id=function.id,
        name=name,
        status=status,
        created_by=user.id,
    )
    db.add(point)
    db.flush()
    return point


def make_document(
    db: Session,
    project: Project,
    user: User,
    *,
    title: str = "4.2 登录失败次数限制",
) -> tuple[Document, DocumentVersion, DocumentChapter]:
    """建一份文档 + 版本 + 章节——来源追溯三元组的来源。"""
    document = Document(
        project_id=project.id,
        name=f"需求-{uuid.uuid4().hex[:6]}",
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
    chapter = DocumentChapter(
        version_id=version.id,
        parent_id=None,
        seq=1,
        level=1,
        title=title,
        content="正文",
        char_count=2,
    )
    db.add(chapter)
    db.flush()
    return document, version, chapter


def scenario_body(**overrides) -> dict:
    """一个手工场景的请求体。"""
    body = {
        "name": "扫码登录连续失败 5 次后锁定",
        "description": "账号已存在且未锁定时，连续输错密码达阈值后账号被锁定",
        "precondition": "账号已注册且处于未锁定状态",
        "source_type": "manual",
        "steps": [
            {"action": "打开登录页并选择「扫码登录」", "expected": "展示扫码二维码"},
            {"action": "连续 5 次输入错误密码", "expected": "提示账号已被锁定"},
        ],
    }
    body.update(overrides)
    return body


def create_scenario(
    client: TestClient,
    chain: dict,
    headers: dict[str, str],
    **overrides,
) -> dict:
    """建一个场景，返回响应体（断言 201）。"""
    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={"scenarios": [scenario_body(**overrides)]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def count_rows(db: Session, model) -> int:
    """某张表的行数。"""
    return db.query(model).count()


__all__ = [
    "BASE",
    "BASELINES",
    "PASSWORD",
    "SCENARIOS",
    "add_member",
    "count_rows",
    "create_scenario",
    "login",
    "make_chain",
    "make_document",
    "make_feature_point",
    "make_function",
    "make_project",
    "make_user",
    "scenario_body",
]
