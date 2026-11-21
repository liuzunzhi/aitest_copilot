"""测试用例用例的造数与登录辅助。"""

import json
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import PromptTemplate
from app.models.project import Project, ProjectMember
from app.models.test_point import TestPoint
from app.models.user import User

PASSWORD = "TestCasePass1"
PASSWORD_HASH = hash_password(PASSWORD)

BASE = "/api/projects/{project_id}/test-cases"
ANALYSES = BASE + "/analyses"
CASES = BASE + "/cases"


def make_user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"tc-{uuid.uuid4().hex[:10]}",
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
    project = Project(name=f"用例项目-{uuid.uuid4().hex[:6]}", status=status)
    db.add(project)
    db.flush()
    return project


def add_member(db: Session, project: Project, user: User, role: str = "member") -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def seed_template(db: Session) -> PromptTemplate:
    """迁移 0023 播种的 test_case 模板。"""
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "test_case")
    )
    assert template is not None, "迁移 0023 应播种一条 test_case 模板"
    return template


def make_chapter(
    db: Session, project: Project, user: User, *, title: str = "登录", content: str = "正文"
) -> DocumentChapter:
    document = Document(
        project_id=project.id, name=f"需求-{uuid.uuid4().hex[:6]}", created_by=user.id
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
        sha256="c" * 64,
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
        content=content,
        char_count=len(content),
    )
    db.add(chapter)
    db.flush()
    return chapter


def make_point(
    db: Session,
    project: Project,
    user: User,
    *,
    status: str = "approved",
    name: str = "扫码登录连续失败 5 次后锁定",
    chapter: DocumentChapter | None = None,
    target_id: int = 10096,
    target_name: str = "用户扫码登录",
    priority: str = "high",
    precondition: str = "账号已存在且未锁定",
    verification: str = "连续输错密码 5 次，提示锁定",
    point_analysis_id: int | None = None,
) -> TestPoint:
    point = TestPoint(
        project_id=project.id,
        analysis_id=point_analysis_id,
        name=name,
        target_type="function",
        target_id=target_id,
        target_name=target_name,
        priority=priority,
        precondition=precondition,
        verification=verification,
        chapter_id=chapter.id if chapter is not None else None,
        chapter_title=chapter.title if chapter is not None else None,
        status=status,
        source_type="manual",
        created_by=user.id,
    )
    db.add(point)
    db.flush()
    return point


def now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------- 模型响应


def make_case(
    title: str = "连续输错密码 5 次后账号锁定",
    *,
    case_type: str = "functional",
    priority: str = "high",
    precondition: str = "账号已存在",
    steps: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "case_type": case_type,
        "priority": priority,
        "precondition": precondition,
        "steps": steps
        or [
            {"action": "输入正确用户名与错误密码", "expected": "提示用户名或密码错误"},
            {"action": "连续重复 4 次", "expected": "仍提示用户名或密码错误"},
        ],
    }


def case_response(*cases: dict) -> str:
    return json.dumps({"cases": list(cases)}, ensure_ascii=False)


def fenced_response(content: str) -> str:
    return f"```json\n{content}\n```"


__all__ = [
    "ANALYSES",
    "BASE",
    "CASES",
    "PASSWORD",
    "add_member",
    "case_response",
    "fenced_response",
    "login",
    "make_case",
    "make_chapter",
    "make_point",
    "make_project",
    "make_user",
    "now_naive",
    "seed_template",
]
