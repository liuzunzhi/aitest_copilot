"""文档上传（T47 / AC-49 ~ AC-51）。"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.models.system import AuditLog
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.project import Project
from tests.documents.helpers import (
    SAMPLE_MD,
    add_member,
    login,
    make_pdf,
    make_project,
    make_user,
    md_payload,
    pdf_payload,
)


def _counts(db: Session, project_id: int) -> tuple[int, int, int, int]:
    """返回（文档, 版本, 章节, 上传审计）数量，失败用例靠它证明没落脏数据。"""
    documents = select(Document.id).where(Document.project_id == project_id).subquery()
    versions = (
        select(DocumentVersion.id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.project_id == project_id)
        .subquery()
    )
    return (
        db.scalar(select(func.count()).select_from(documents)),
        db.scalar(select(func.count()).select_from(versions)),
        db.scalar(
            select(func.count())
            .select_from(DocumentChapter)
            .join(DocumentVersion, DocumentVersion.id == DocumentChapter.version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.project_id == project_id)
        ),
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.project_id == project_id,
                AuditLog.action == "document.upload",
            )
        ),
    )


def test_ac_49_upload_new_document(client: TestClient, db: Session, upload_root):
    """成员上传 md：新建文档 + v1 + 章节树，原文落盘。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    headers = login(client, user)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(SAMPLE_MD),
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["name"] == "支付需求"
    assert body["document"]["version_count"] == 1
    assert body["version"]["version_no"] == 1
    assert body["version"]["status"] == "pending"
    assert body["version"]["chapter_count"] == 3
    assert body["version"]["file_name"] == "支付需求.md"

    version = db.get(DocumentVersion, body["version"]["id"])
    assert not version.file_path.startswith("/"), "库里只存相对路径"
    assert version.file_path.startswith(f"{project.id}/")
    assert (upload_root / version.file_path).read_bytes() == SAMPLE_MD.encode("utf-8")

    chapters = db.scalars(
        select(DocumentChapter)
        .where(DocumentChapter.version_id == version.id)
        .order_by(DocumentChapter.seq)
    ).all()
    assert [(c.title, c.level, c.parent_id) for c in chapters] == [
        ("支付", 1, None),
        ("下单", 2, chapters[0].id),
        ("退款", 2, chapters[0].id),
    ]

    assert db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.project_id == project.id, AuditLog.action == "document.upload")
    ) == 1


def test_ac_50_unsupported_type(client: TestClient, db: Session, upload_root):
    """未知扩展名不支持：400，且不落盘、不落库、不写审计。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    headers = login(client, user)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files={"file": ("需求.xlsx", b"PK\x03\x04", "application/vnd.ms-excel")},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "UNSUPPORTED_DOC_TYPE"
    assert _counts(db, project.id) == (0, 0, 0, 0)
    assert list(upload_root.rglob("*")) == []


def test_ac_50_corrupted_pdf(client: TestClient, db: Session, upload_root):
    """扩展名是 .pdf 但内容坏了：400 DOCUMENT_PARSE_FAILED，不留半成品。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    headers = login(client, user)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files={"file": ("需求.pdf", b"%PDF-1.4 broken", "application/pdf")},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "DOCUMENT_PARSE_FAILED"
    assert _counts(db, project.id) == (0, 0, 0, 0)
    assert list(upload_root.rglob("*")) == []


def test_ac_119_upload_pdf_document(client: TestClient, db: Session, upload_root):
    """PDF 上传成功：文档 + 版本 + 章节树都落库。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    headers = login(client, user)
    data = make_pdf(
        [
            [("Chapter 1 Payment", 22, 72)],
            [("payment overview", 10, 72)],
            [("1.1 Refund", 16, 72)],
            [("refund body", 10, 72)],
        ]
    )

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=pdf_payload(data, name="需求说明.pdf"),
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["name"] == "需求说明"
    assert body["version"]["chapter_count"] == 2

    version = db.get(DocumentVersion, body["version"]["id"])
    chapters = db.scalars(
        select(DocumentChapter)
        .where(DocumentChapter.version_id == version.id)
        .order_by(DocumentChapter.seq)
    ).all()
    assert [(c.title, c.level) for c in chapters] == [
        ("Chapter 1 Payment", 1),
        ("1.1 Refund", 2),
    ]
    assert "refund body" in chapters[1].content


def test_ac_50_file_too_large(client: TestClient, db: Session, upload_root, monkeypatch):
    """超过上限直接 400，不读完整文件也不落库。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    headers = login(client, user)
    monkeypatch.setattr(get_settings(), "doc_max_bytes", 64)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload("# 标题\n" + "正" * 200),
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "DOC_TOO_LARGE"
    assert _counts(db, project.id) == (0, 0, 0, 0)


def test_ac_50_empty_file(client: TestClient, db: Session, upload_root):
    """0 字节按空文档处理，不是「解析失败」。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    headers = login(client, user)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files={"file": ("空.md", b"", "text/markdown")},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "EMPTY_DOCUMENT"
    assert _counts(db, project.id) == (0, 0, 0, 0)


def test_ac_50_duplicate_name(client: TestClient, db: Session, upload_root):
    """同项目同名不覆盖、不产生第二个文档，也不留下第二份文件。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    headers = login(client, user)
    url = f"/api/projects/{project.id}/documents"

    assert client.post(url, files=md_payload(SAMPLE_MD), headers=headers).status_code == 201
    response = client.post(url, files=md_payload(SAMPLE_MD), headers=headers)

    assert response.status_code == 409
    assert response.json()["code"] == "DOCUMENT_NAME_TAKEN"
    assert _counts(db, project.id) == (1, 1, 3, 1)
    assert len(list(upload_root.rglob("*.md"))) == 1


def test_ac_50_guest_cannot_upload(client: TestClient, db: Session, upload_root):
    """访客只读，上传报 FORBIDDEN。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user, role="guest")
    headers = login(client, user)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(SAMPLE_MD),
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert _counts(db, project.id) == (0, 0, 0, 0)


def test_ac_50_outsider_cannot_upload(client: TestClient, db: Session, upload_root):
    """非成员上传报 NOT_PROJECT_MEMBER。"""
    user = make_user(db)
    project = make_project(db)
    headers = login(client, user)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(SAMPLE_MD),
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"
    assert _counts(db, project.id) == (0, 0, 0, 0)


def test_ac_51_upload_new_version(client: TestClient, db: Session, upload_root):
    """带 document_id 再传一次是追加版本，原版本状态不变。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    headers = login(client, user)
    url = f"/api/projects/{project.id}/documents"

    first = client.post(url, files=md_payload(SAMPLE_MD), headers=headers)
    assert first.status_code == 201
    document_id = first.json()["document"]["id"]

    second = client.post(
        url,
        files=md_payload("# 支付\n新版正文"),
        data={"document_id": str(document_id)},
        headers=headers,
    )

    assert second.status_code == 201, second.text
    body = second.json()
    assert body["document"]["id"] == document_id
    assert body["document"]["version_count"] == 2
    assert body["version"]["version_no"] == 2
    assert body["version"]["status"] == "pending"

    versions = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_no)
    ).all()
    assert [v.status for v in versions] == ["pending", "pending"]
    assert len(list(upload_root.rglob("*.md"))) == 2


def test_ac_51_document_not_found(client: TestClient, db: Session, upload_root):
    """追加到不存在的文档：404，不产生任何记录。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    headers = login(client, user)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(SAMPLE_MD),
        data={"document_id": "987654"},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_NOT_FOUND"
    assert _counts(db, project.id) == (0, 0, 0, 0)


def test_ac_51_document_of_other_project(client: TestClient, db: Session, upload_root):
    """跨项目追加要当不存在，不能借 document_id 越权。"""
    user = make_user(db)
    project = make_project(db)
    other = make_project(db, name="另一个项目")
    add_member(db, project, user)
    foreign = Document(project_id=other.id, name="别人的文档", created_by=user.id)
    db.add(foreign)
    db.flush()
    headers = login(client, user)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(SAMPLE_MD),
        data={"document_id": str(foreign.id)},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_NOT_FOUND"
    assert _counts(db, project.id) == (0, 0, 0, 0)


def test_ac_49_archived_project_rejects_upload(client: TestClient, db: Session, upload_root):
    """归档项目只读：上传 409，提示项目已归档。"""
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user)
    project.status = "archived"
    db.flush()
    headers = login(client, user)

    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(SAMPLE_MD),
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"
    assert _counts(db, project.id) == (0, 0, 0, 0)
