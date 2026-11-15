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
from app.common.errors import (
    DocumentNameTaken,
    DocumentNotFound,
    DocumentTooLarge,
    EmptyDocument,
    ProjectArchived,
    ProjectNotFound,
)
from app.documents.parser import ChapterNode, parse
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.project import Project
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


__all__ = ["upload_document"]
