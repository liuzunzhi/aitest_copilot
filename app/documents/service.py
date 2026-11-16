"""文档上传（T47）。

上传是「解析段」唯一写原文件的入口，顺序很关键：
校验 → 解析 → 查重 → 落盘 → 落库 → 审计，任一步失败都不留半成品。
解析在落盘前完成，所以不支持的类型、损坏的 docx 连磁盘都不会碰。
"""

import hashlib
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.config import get_settings
from app.common.deps import SYSTEM_ADMIN
from app.common.errors import (
    DocumentNameTaken,
    DocumentNotFound,
    DocumentTooLarge,
    DocumentVersionNotFound,
    EmptyDocument,
    InvalidVersionStatus,
    NotProjectAdmin,
    NotProjectMember,
    ProjectArchived,
    ProjectNotFound,
)
from app.documents.parser import ChapterNode, parse
from app.models.document import (
    BaselineSnapshot,
    Document,
    DocumentChapter,
    DocumentVersion,
)
from app.models.project import Project, ProjectMember
from app.models.user import User


def upload_document(
    session: Session,
    *,
    project_id: int,
    actor: User,
    file_name: str,
    data: bytes,
    document_id: int | None = None,
) -> tuple[Document, DocumentVersion, int]:
    """上传新文档或给已有文档追加版本，返回 (文档, 版本, 版本总数)。

    `file_name` 只取文件名部分（浏览器会带路径），扩展名决定解析方式；
    `document_id` 为空表示新建文档，否则视为追加版本。
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFound("项目不存在")
    if project.status != "active":
        raise ProjectArchived("项目已归档，不可上传文档")

    max_bytes = get_settings().doc_max_bytes
    if len(data) > max_bytes:
        raise DocumentTooLarge(f"文件不能超过 {max_bytes // (1024 * 1024)}MB")
    if not data:
        raise EmptyDocument()

    # 解析失败（类型不支持 / 结构损坏 / 无正文）在这里直接抛，不落盘不落库
    chapters = parse(file_name, data)
    chapter_count = _count(chapters)

    if document_id is None:
        name = Path(file_name).stem.strip() or "未命名文档"
        exists = session.scalar(
            select(Document.id).where(
                Document.project_id == project_id, Document.name == name
            )
        )
        if exists is not None:
            raise DocumentNameTaken("同项目已存在同名文档")
        document = Document(project_id=project_id, name=name, created_by=actor.id)
        session.add(document)
        session.flush()
    else:
        document = session.scalar(
            select(Document).where(
                Document.id == document_id, Document.project_id == project_id
            )
        )
        if document is None:
            raise DocumentNotFound("文档不存在")

    version_no = _next_version_no(session, document.id)

    # 库里只存相对 upload_dir 的路径，换机器/改配置不用改数据
    relative_path = f"{project_id}/{uuid.uuid4().hex}{Path(file_name).suffix.lower()}"
    target = Path(get_settings().upload_dir) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    try:
        version = DocumentVersion(
            document_id=document.id,
            version_no=version_no,
            status="pending",
            file_name=file_name,
            file_path=relative_path,
            file_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            chapter_count=chapter_count,
            uploaded_by=actor.id,
        )
        session.add(version)
        session.flush()

        _insert_chapters(session, version.id, chapters)

        write_audit(
            session,
            "document.upload",
            actor_id=actor.id,
            actor_role=actor.global_role,
            project_id=project_id,
            target_type="document_version",
            target_id=version.id,
            after_data={
                "document_id": document.id,
                "document_name": document.name,
                "version_no": version_no,
                "chapter_count": chapter_count,
                "file_name": file_name,
                "file_size": len(data),
            },
        )
        session.commit()
    except Exception:
        # 落库失败必须把已经写下的文件删掉，否则会留下无人引用的孤儿文件
        session.rollback()
        target.unlink(missing_ok=True)
        raise

    version_count = session.scalar(
        select(func.count())
        .select_from(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
    )
    return document, version, int(version_count or 0)


def list_documents(session: Session, project_id: int) -> list[dict]:
    """文档列表：一次取全量版本再在内存分组，避免按文档逐个查版本（N+1）。"""
    documents = session.scalars(
        select(Document).where(Document.project_id == project_id).order_by(Document.id)
    ).all()
    versions = session.scalars(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.project_id == project_id)
        .order_by(DocumentVersion.document_id, DocumentVersion.version_no.desc())
    ).all()

    grouped: dict[int, list[DocumentVersion]] = {}
    for version in versions:
        grouped.setdefault(version.document_id, []).append(version)

    items: list[dict] = []
    for document in documents:
        doc_versions = grouped.get(document.id, [])
        items.append(
            {
                "id": document.id,
                "name": document.name,
                "created_at": document.created_at,
                "version_count": len(doc_versions),
                "pending_count": sum(1 for v in doc_versions if v.status == "pending"),
                "active_version": next(
                    (v for v in doc_versions if v.status == "active"), None
                ),
            }
        )
    return items


def list_versions(
    session: Session, *, project_id: int, document_id: int
) -> list[DocumentVersion]:
    """版本列表，新版本在前。"""
    _load_document(session, project_id=project_id, document_id=document_id)
    return list(
        session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_no.desc())
        ).all()
    )


def list_chapters(
    session: Session, *, project_id: int, document_id: int, version_id: int
) -> list[dict]:
    """章节树。按 `seq` 升序取回，再按 `parent_id` 在内存组树。"""
    _load_document(session, project_id=project_id, document_id=document_id)
    _load_version(session, document_id=document_id, version_id=version_id)

    rows = session.scalars(
        select(DocumentChapter)
        .where(DocumentChapter.version_id == version_id)
        .order_by(DocumentChapter.seq)
    ).all()
    nodes = {
        row.id: {
            "id": row.id,
            "seq": row.seq,
            "level": row.level,
            "title": row.title,
            "content": row.content,
            "char_count": row.char_count,
            "children": [],
        }
        for row in rows
    }
    roots: list[dict] = []
    for row in rows:
        node = nodes[row.id]
        if row.parent_id is None:
            roots.append(node)
        else:
            nodes[row.parent_id]["children"].append(node)
    return roots


def _load_document(
    session: Session, *, project_id: int, document_id: int
) -> Document:
    document = session.scalar(
        select(Document).where(
            Document.id == document_id, Document.project_id == project_id
        )
    )
    if document is None:
        raise DocumentNotFound("文档不存在")
    return document


def _load_version(
    session: Session, *, document_id: int, version_id: int
) -> DocumentVersion:
    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.document_id == document_id,
        )
    )
    if version is None:
        raise DocumentVersionNotFound("版本不存在")
    return version


def activate_version(
    session: Session,
    *,
    project_id: int,
    document_id: int,
    version_id: int,
    actor: User,
) -> tuple[Document, DocumentVersion, BaselineSnapshot]:
    """确认版本生效，并在同一事务里生成项目基线快照。

    锁项目行取号：`baseline_snapshots.version_no` 是项目内递增序号，
    并发确认两个版本时若不加锁会撞 `UNIQUE(project_id, version_no)`。
    """
    project = session.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    if project is None:
        raise ProjectNotFound("项目不存在")
    if project.status != "active":
        raise ProjectArchived("项目已归档，不可确认版本")

    document = _load_document(session, project_id=project_id, document_id=document_id)
    version = _load_version(session, document_id=document_id, version_id=version_id)
    _ensure_can_operate(session, project_id=project_id, actor=actor, version=version)

    if version.status != "pending":
        raise InvalidVersionStatus("只有待确认的版本可以生效")

    # 先归档旧版本再激活新版本：两步各 flush 一次，
    # 避免瞬间出现两个 active 撞上 uk_versions_active。
    previous = session.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.status == "active",
        )
    ).all()
    for old in previous:
        old.status = "archived"
    session.flush()

    version.status = "active"
    session.flush()

    snapshot = BaselineSnapshot(
        project_id=project_id,
        version_id=version.id,
        version_no=_next_baseline_no(session, project_id),
        chapter_count=version.chapter_count,
        created_by=actor.id,
    )
    session.add(snapshot)
    session.flush()

    write_audit(
        session,
        "document.version.activate",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="document_version",
        target_id=version.id,
        after_data={
            "document_id": document.id,
            "document_name": document.name,
            "version_no": version.version_no,
            "archived_version_ids": [old.id for old in previous],
        },
    )
    write_audit(
        session,
        "baseline.snapshot.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_snapshot",
        target_id=snapshot.id,
        after_data={
            "baseline_version_no": snapshot.version_no,
            "document_version_id": version.id,
            "chapter_count": snapshot.chapter_count,
        },
    )
    session.commit()
    return document, version, snapshot


def list_baselines(session: Session, project_id: int) -> list[dict]:
    """基线快照列表，新序号在前；带上文档名便于前端直接展示。"""
    rows = session.execute(
        select(BaselineSnapshot, DocumentVersion, Document)
        .join(DocumentVersion, DocumentVersion.id == BaselineSnapshot.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(BaselineSnapshot.project_id == project_id)
        .order_by(BaselineSnapshot.version_no.desc())
    ).all()
    return [
        {
            "id": snapshot.id,
            "version_no": snapshot.version_no,
            "chapter_count": snapshot.chapter_count,
            "created_at": snapshot.created_at,
            "document_id": document.id,
            "document_name": document.name,
            "document_version_no": version.version_no,
        }
        for snapshot, version, document in rows
    ]


def _ensure_can_operate(
    session: Session, *, project_id: int, actor: User, version: DocumentVersion
) -> None:
    """确认/作废的权限：管理员任意，成员仅自己上传的版本，访客不可写。"""
    if actor.global_role == SYSTEM_ADMIN:
        return
    member = session.get(ProjectMember, (project_id, actor.id))
    if member is None:
        raise NotProjectMember("不是该项目成员")
    if member.role == "guest":
        raise NotProjectAdmin("只有项目管理员可以确认或作废版本")
    if member.role == "project_admin":
        return
    if version.uploaded_by != actor.id:
        raise NotProjectAdmin("只能操作自己上传的版本")


def _next_baseline_no(session: Session, project_id: int) -> int:
    current = session.scalar(
        select(func.max(BaselineSnapshot.version_no)).where(
            BaselineSnapshot.project_id == project_id
        )
    )
    return int(current or 0) + 1


def _count(nodes: list[ChapterNode]) -> int:
    return sum(1 + _count(node.children) for node in nodes)


def _next_version_no(session: Session, document_id: int) -> int:
    current = session.scalar(
        select(func.max(DocumentVersion.version_no)).where(
            DocumentVersion.document_id == document_id
        )
    )
    return int(current or 0) + 1


def _insert_chapters(
    session: Session,
    version_id: int,
    nodes: list[ChapterNode],
    *,
    parent_id: int | None = None,
    counter: list[int] | None = None,
) -> None:
    """递归落库，`seq` 是版本内的全局文档顺序（表上有唯一索引）。"""
    counter = counter or [0]
    for node in nodes:
        counter[0] += 1
        chapter = DocumentChapter(
            version_id=version_id,
            parent_id=parent_id,
            seq=counter[0],
            level=node.level,
            title=node.title,
            content=node.content,
            char_count=len(node.content),
        )
        session.add(chapter)
        session.flush()
        _insert_chapters(
            session,
            version_id,
            node.children,
            parent_id=chapter.id,
            counter=counter,
        )


__all__ = [
    "activate_version",
    "list_baselines",
    "list_chapters",
    "list_documents",
    "list_versions",
    "upload_document",
]
