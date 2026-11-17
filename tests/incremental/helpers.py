"""增量分析用例的造数与登录辅助。"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.baseline import (
    BaselineFeaturePoint,
    BaselineFunction,
    BaselineModule,
    BaselineRevision,
)
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import PromptTemplate
from app.models.project import Project, ProjectMember
from app.models.user import User

PASSWORD = "IncrementalPass1"
# bcrypt 很慢，模块级算一次，所有用例共用同一个 hash
PASSWORD_HASH = hash_password(PASSWORD)

BASE = "/api/projects/{project_id}/incremental"
ANALYSES = BASE + "/analyses"


def make_user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"inc-{uuid.uuid4().hex[:10]}",
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


def make_project(
    db: Session, *, name: str | None = None, status: str = "active"
) -> Project:
    project = Project(
        name=name or f"增量项目-{uuid.uuid4().hex[:6]}", status=status
    )
    db.add(project)
    db.flush()
    return project


def add_member(
    db: Session, project: Project, user: User, role: str = "member"
) -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def seed_template(db: Session) -> PromptTemplate:
    """迁移 0013 播种的第一遍 incremental 模板（第二遍也有模板，必须按名字取）。"""
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.name == "增量分析·第一遍·章节局部",
        )
    )
    assert template is not None, "迁移 0013 应播种一条 incremental 模板"
    return template


def make_revision(
    db: Session,
    project: Project,
    *,
    status: str = "approved",
    version_no: int = 0,
) -> BaselineRevision:
    revision = BaselineRevision(
        project_id=project.id, status=status, version_no=version_no
    )
    db.add(revision)
    db.flush()
    return revision


def make_document_version(
    db: Session,
    project: Project,
    user: User,
    *,
    chapters: list[tuple[str, str]] | None = None,
    status: str = "active",
    version_no: int = 1,
    document_name: str | None = None,
) -> tuple[Document, DocumentVersion, list[DocumentChapter]]:
    """建文档 + 版本 + 章节。`chapters` 为 (标题, 正文) 列表。"""
    document = Document(
        project_id=project.id,
        name=document_name or f"需求-{uuid.uuid4().hex[:6]}",
        created_by=user.id,
    )
    db.add(document)
    db.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_no=version_no,
        status=status,
        file_name=f"{document.name}.md",
        file_path=f"var/uploads/{project.id}/{uuid.uuid4().hex}.md",
        file_size=128,
        sha256="a" * 64,
        chapter_count=len(chapters or []),
        uploaded_by=user.id,
    )
    db.add(version)
    db.flush()

    rows: list[DocumentChapter] = []
    for seq, (title, content) in enumerate(chapters or [("登录", "账号密码登录")], start=1):
        chapter = DocumentChapter(
            version_id=version.id,
            parent_id=None,
            seq=seq,
            level=1,
            title=title,
            content=content,
            char_count=len(content),
        )
        db.add(chapter)
        rows.append(chapter)
    db.flush()
    return document, version, rows


def make_function(
    db: Session,
    project: Project,
    user: User,
    *,
    module_name: str = "支付模块",
    function_name: str = "下单",
    point_name: str | None = None,
) -> dict:
    """建基线结构：模块 → 功能（→ 可选功能点）。"""
    module = BaselineModule(
        project_id=project.id, name=module_name, created_by=user.id
    )
    db.add(module)
    db.flush()

    function = BaselineFunction(
        project_id=project.id, module_id=module.id, name=function_name, created_by=user.id
    )
    db.add(function)
    db.flush()

    point = None
    if point_name is not None:
        point = BaselineFeaturePoint(
            project_id=project.id,
            function_id=function.id,
            name=point_name,
            created_by=user.id,
        )
        db.add(point)
        db.flush()
    return {"module": module, "function": function, "point": point}


def conclusion_payload(
    *,
    target_type: str = "function",
    target_id: int,
    label_type: str = "changed",
    confidence: float = 0.9,
    rationale: str = "正文有改动",
) -> dict:
    """构造 Mock 返回的一条结论。"""
    return {
        "target_type": target_type,
        "target_id": target_id,
        "label_type": label_type,
        "confidence": confidence,
        "rationale": rationale,
    }


def analysis_payload(
    *,
    template_id: int,
    baseline_revision_id: int | None,
    document_version_id: int,
    split_granularity: str | None = None,
) -> dict:
    payload = {
        "template_id": template_id,
        "document_version_id": document_version_id,
    }
    if baseline_revision_id is not None:
        payload["baseline_revision_id"] = baseline_revision_id
    if split_granularity is not None:
        payload["split_granularity"] = split_granularity
    return payload


def build_chain(
    db: Session,
    *,
    chapters: list[tuple[str, str]] | None = None,
    with_function: bool = True,
) -> dict:
    """一条可直接发起分析的完整链路：管理员 / 项目 / 模板 / 快照 / 版本 / 结构。"""
    admin = make_user(db)
    project = make_project(db)
    add_member(db, project, admin, "project_admin")
    template = seed_template(db)
    revision = make_revision(db, project)
    document, version, chapter_rows = make_document_version(
        db, project, admin, chapters=chapters
    )
    structure = make_function(db, project, admin) if with_function else None
    return {
        "admin": admin,
        "project": project,
        "template": template,
        "revision": revision,
        "document": document,
        "version": version,
        "chapters": chapter_rows,
        "structure": structure,
    }

