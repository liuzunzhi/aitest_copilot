"""文档四表（T45）。

验证数据库层保障：同项目文档同名唯一、同文档仅一个生效版本、
章节序号在版本内唯一、同一版本只生成一条基线快照。
这些约束失效时应用层看起来仍正常，只有并发或脏数据才暴露。
"""

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.document import (
    BaselineSnapshot,
    Document,
    DocumentChapter,
    DocumentVersion,
)
from app.models.project import Project
from app.models.user import User


def _user(db: Session, username: str = "doc_u1") -> User:
    user = User(username=username, password_hash="x" * 60)
    db.add(user)
    db.flush()
    return user


def _project(db: Session, name: str = "文档项目") -> Project:
    project = Project(name=name)
    db.add(project)
    db.flush()
    return project


def _document(db: Session, project_id: int, user_id: int, name: str = "支付需求") -> Document:
    document = Document(project_id=project_id, name=name, created_by=user_id)
    db.add(document)
    db.flush()
    return document


def _version(
    db: Session,
    document_id: int,
    user_id: int,
    version_no: int = 1,
    status: str = "pending",
) -> DocumentVersion:
    version = DocumentVersion(
        document_id=document_id,
        version_no=version_no,
        status=status,
        file_name="支付需求.md",
        file_path=f"var/uploads/{document_id}/{version_no}.md",
        file_size=128,
        sha256="a" * 64,
        chapter_count=1,
        uploaded_by=user_id,
    )
    db.add(version)
    db.flush()
    return version


def test_document_tables_roundtrip(db: Session):
    """四张表可写入，默认值与生成列符合预期。"""
    user = _user(db)
    project = _project(db)
    document = _document(db, project.id, user.id)
    version = _version(db, document.id, user.id)
    chapter = DocumentChapter(
        version_id=version.id,
        parent_id=None,
        seq=1,
        level=1,
        title="全文",
        content="正文",
        char_count=2,
    )
    db.add(chapter)
    db.flush()
    snapshot = BaselineSnapshot(
        project_id=project.id,
        version_id=version.id,
        version_no=1,
        chapter_count=version.chapter_count,
        created_by=user.id,
    )
    db.add(snapshot)
    db.flush()
    db.refresh(version)

    assert document.created_at is not None
    assert version.status == "pending"
    assert version.chapter_count == 1
    assert version.active_key is None, "pending 版本不应占用 active_key"
    assert snapshot.created_at is not None


def test_document_name_unique_per_project(db: Session):
    """同项目同名文档被唯一索引拦下，跨项目可同名。"""
    user = _user(db)
    project = _project(db)
    other = _project(db, name="另一个项目")
    _document(db, project.id, user.id)
    db.commit()  # 先固化，失败插入回滚后仍能用这些数据

    with pytest.raises(IntegrityError) as exc:
        _document(db, project.id, user.id)
    assert exc.value.orig.args[0] == 1062
    assert "uk_documents_project_name" in str(exc.value.orig.args[1])

    db.rollback()
    _document(db, other.id, user.id)


def test_version_no_unique_in_document(db: Session):
    """版本号在文档内唯一。"""
    user = _user(db)
    project = _project(db)
    document = _document(db, project.id, user.id)
    _version(db, document.id, user.id, version_no=1)

    with pytest.raises(IntegrityError) as exc:
        _version(db, document.id, user.id, version_no=1)
    assert exc.value.orig.args[0] == 1062
    assert "uk_versions_doc_no" in str(exc.value.orig.args[1])


def test_active_key_only_for_active_version(db: Session):
    """`active_key` 生成列：active 时等于 document_id，其余为 NULL。

    同一文档两个 active 版本会撞唯一索引——这是「仅一个生效版本」的数据库兜底。
    """
    user = _user(db)
    project = _project(db)
    document = _document(db, project.id, user.id)
    first = _version(db, document.id, user.id, version_no=1)
    second = _version(db, document.id, user.id, version_no=2)

    first.status = "active"
    db.flush()
    db.refresh(first)
    assert first.active_key == document.id
    db.commit()  # 固化首个 active，后面失败插入回滚不影响它

    with pytest.raises(IntegrityError) as exc:
        second.status = "active"
        db.flush()
    assert exc.value.orig.args[0] == 1062
    assert "uk_versions_active" in str(exc.value.orig.args[1])

    db.rollback()
    first = db.get(DocumentVersion, first.id)
    first.status = "archived"
    db.flush()
    db.refresh(first)
    assert first.active_key is None, "归档后应释放 active_key"


def test_version_status_check(db: Session):
    """status 只接受四个枚举值，非法值被 CHECK 拦下（MySQL 3819）。"""
    user = _user(db)
    project = _project(db)
    document = _document(db, project.id, user.id)

    with pytest.raises(OperationalError) as exc:
        _version(db, document.id, user.id, status="deleted")
    assert exc.value.orig.args[0] == 3819


def test_baseline_unique_per_version(db: Session):
    """同一版本只能生成一条快照。"""
    user = _user(db)
    project = _project(db)
    document = _document(db, project.id, user.id)
    version = _version(db, document.id, user.id)
    db.add(
        BaselineSnapshot(
            project_id=project.id,
            version_id=version.id,
            version_no=1,
            chapter_count=1,
            created_by=user.id,
        )
    )
    db.flush()

    with pytest.raises(IntegrityError) as exc:
        db.add(
            BaselineSnapshot(
                project_id=project.id,
                version_id=version.id,
                version_no=2,
                chapter_count=1,
                created_by=user.id,
            )
        )
        db.flush()
    assert exc.value.orig.args[0] == 1062
    assert "uk_baseline_version" in str(exc.value.orig.args[1])
