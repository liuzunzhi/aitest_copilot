"""测试点用例的造数与登录辅助。

**一条铁律**（06 期 L2 的血泪教训）：Mock 的默认响应里 `target_id=123`，
而真实清单里是真实 id → 全被当越界丢弃。
所以**断言落库条数的用例必须显式给 `MockProvider(queue=[...])`**，
响应里的 `target_id` 要命中真实清单。

`point_response()` 就是干这个的：它接收真实的 `target_id`，
生成一条**命中清单**的模型响应。
"""

import json
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.baseline import (
    BaselineFeaturePoint,
    BaselineFunction,
    BaselineLabel,
    BaselineModule,
    BaselineRevision,
)
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import (
    IncrementalAnalysis,
    IncrementalConclusion,
    PromptTemplate,
)
from app.models.project import Project, ProjectMember
from app.models.user import User

PASSWORD = "TestPointPass1"
# bcrypt 很慢，模块级算一次，所有用例共用同一个 hash
PASSWORD_HASH = hash_password(PASSWORD)

BASE = "/api/projects/{project_id}/test-points"


def make_user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"tp-{uuid.uuid4().hex[:10]}",
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
        name=name or f"测试点项目-{uuid.uuid4().hex[:6]}", status=status
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
    """迁移 0022 播种的 test_point 模板。"""
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "test_point")
    )
    assert template is not None, "迁移 0022 应播种一条 test_point 模板"
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
) -> tuple[Document, DocumentVersion, list[DocumentChapter]]:
    """建文档 + 版本 + 章节。`chapters` 为 (标题, 正文) 列表。"""
    document = Document(
        project_id=project.id,
        name=f"需求-{uuid.uuid4().hex[:6]}",
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
    for seq, (title, content) in enumerate(
        chapters or [("登录", "账号密码登录")], start=1
    ):
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
    module_name: str = "登录模块",
    function_name: str = "用户扫码登录",
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


def make_label(
    db: Session,
    project: Project,
    revision: BaselineRevision,
    user: User,
    *,
    target_type: str = "function",
    target_id: int,
    label_type: str = "changed",
    status: str = "active",
    source_analysis_id: int | None = None,
) -> BaselineLabel:
    """建一条标签。标签必须挂在**已 approved 的快照**上（`revision_id` 非空）。"""
    label = BaselineLabel(
        project_id=project.id,
        revision_id=revision.id,
        target_type=target_type,
        target_id=target_id,
        label_type=label_type,
        source_analysis_id=source_analysis_id,
        confirmed_by=user.id,
        status=status,
    )
    db.add(label)
    db.flush()
    return label


def make_analysis(
    db: Session, chain: dict, *, status: str = "succeeded"
) -> IncrementalAnalysis:
    """直接建一条增量分析记录（绕过接口，便于引擎级用例）。"""
    analysis = IncrementalAnalysis(
        project_id=chain["project"].id,
        template_id=chain["template"].id,
        template_version=chain["template"].version_no,
        baseline_revision_id=chain["revision"].id,
        document_id=chain["document"].id,
        document_version_id=chain["version"].id,
        status=status,
        created_by=chain["admin"].id,
    )
    db.add(analysis)
    db.flush()
    return analysis


def make_conclusion(
    db: Session,
    analysis: IncrementalAnalysis,
    *,
    chapter_id: int,
    target_type: str,
    target_id: int,
    label_type: str = "changed",
    confidence: str | None = "0.80",
    rationale: str | None = "正文有改动",
) -> IncrementalConclusion:
    row = IncrementalConclusion(
        analysis_id=analysis.id,
        chapter_id=chapter_id,
        chapter_title=db.get(DocumentChapter, chapter_id).title,
        target_type=target_type,
        target_id=target_id,
        label_type=label_type,
        confidence=confidence,
        rationale=rationale,
    )
    db.add(row)
    db.flush()
    return row


def build_chain(
    db: Session,
    *,
    chapters: list[tuple[str, str]] | None = None,
    with_function: bool = True,
    project_status: str = "active",
) -> dict:
    """一条可直接发起生成的完整链路：管理员 / 项目 / 模板 / 快照 / 版本 / 结构。"""
    admin = make_user(db)
    project = make_project(db, status=project_status)
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


# --------------------------------------------------------------- 模型响应


def point_response(
    *,
    target_id: int,
    target_type: str = "function",
    name: str = "扫码登录连续失败 5 次后锁定",
    priority: str = "high",
    precondition: str = "账号已存在且未锁定",
    verification: str = "连续输错密码 5 次，提示锁定",
    extra: list[dict] | None = None,
) -> str:
    """构造一条**命中清单**的模型响应（JSON 字符串）。

    `target_id` 必须传**真实清单里的 id**——用 `123` 会全被当越界丢弃。
    `extra` 里可以塞额外的条目（用来测越界 / 非法字段）。
    """
    payload = {
        "test_points": [
            {
                "name": name,
                "target_type": target_type,
                "target_id": target_id,
                "priority": priority,
                "precondition": precondition,
                "verification": verification,
            }
        ]
    }
    if extra:
        payload["test_points"].extend(extra)
    return json.dumps(payload, ensure_ascii=False)


def fenced_response(content: str) -> str:
    """带 Markdown 围栏的响应（测 `parse_llm_json` 的容错）。"""
    return f"```json\n{content}\n```"


__all__ = [
    "BASE",
    "PASSWORD",
    "add_member",
    "build_chain",
    "fenced_response",
    "login",
    "make_analysis",
    "make_conclusion",
    "make_document_version",
    "make_function",
    "make_label",
    "make_project",
    "make_revision",
    "make_user",
    "point_response",
    "seed_template",
]
