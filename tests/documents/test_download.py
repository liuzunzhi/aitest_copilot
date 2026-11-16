"""原文下载（T51 / AC-58）。"""

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.document import DocumentVersion
from tests.documents.helpers import (
    SAMPLE_MD,
    add_member,
    login,
    make_project,
    make_user,
    md_payload,
)


def _setup(client: TestClient, db: Session, *, role: str = "member"):
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user, role=role)
    return project, login(client, user)


def _upload(client: TestClient, project, headers):
    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(SAMPLE_MD),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _download_url(project, document_id: int, version_id: int) -> str:
    return (
        f"/api/projects/{project.id}/documents/{document_id}"
        f"/versions/{version_id}/download"
    )


def test_ac_58_download_bytes_unchanged(client: TestClient, db: Session, upload_root):
    """下载字节与上传一致，文件名按 UTF-8 编码，Content-Disposition 为 attachment。"""
    project, headers = _setup(client, db)
    uploaded = _upload(client, project, headers)

    response = client.get(
        _download_url(project, uploaded["document"]["id"], uploaded["version"]["id"]),
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.content == SAMPLE_MD.encode("utf-8")
    assert hashlib.sha256(response.content).hexdigest() == hashlib.sha256(
        SAMPLE_MD.encode("utf-8")
    ).hexdigest()

    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert "filename*=utf-8''" in disposition.lower()
    assert "%E6%94%AF%E4%BB%98" in disposition  # “支付”


def test_ac_58_guest_can_download(client: TestClient, db: Session, upload_root):
    """访客可下载；非成员 403。"""
    project, headers = _setup(client, db)
    uploaded = _upload(client, project, headers)
    url = _download_url(project, uploaded["document"]["id"], uploaded["version"]["id"])

    guest = make_user(db)
    add_member(db, project, guest, role="guest")
    assert client.get(url, headers=login(client, guest)).status_code == 200

    outsider = make_user(db)
    denied = client.get(url, headers=login(client, outsider))
    assert denied.status_code == 403
    assert denied.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_58_download_not_found(client: TestClient, db: Session, upload_root):
    """文档或版本不存在 → 404，不泄露磁盘路径。"""
    project, headers = _setup(client, db)
    uploaded = _upload(client, project, headers)

    cases = [
        _download_url(project, uploaded["document"]["id"], 987654),
        _download_url(project, 987654, uploaded["version"]["id"]),
    ]
    responses = [client.get(url, headers=headers) for url in cases]

    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json()["code"] == "DOCUMENT_VERSION_NOT_FOUND"
    assert responses[1].json()["code"] == "DOCUMENT_NOT_FOUND"
    assert "var" not in responses[0].text


def test_ac_58_missing_file_on_disk(client: TestClient, db: Session, upload_root):
    """文件被误删时 404，而不是 500 或把路径抛给前端。"""
    project, headers = _setup(client, db)
    uploaded = _upload(client, project, headers)
    version = db.get(DocumentVersion, uploaded["version"]["id"])
    (upload_root / version.file_path).unlink()

    response = client.get(
        _download_url(project, uploaded["document"]["id"], version.id), headers=headers
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_VERSION_NOT_FOUND"


def test_ac_58_archived_project_still_downloadable(client: TestClient, db: Session, upload_root):
    """归档只锁写操作，原文仍可下载。"""
    project, headers = _setup(client, db)
    uploaded = _upload(client, project, headers)
    project.status = "archived"
    db.flush()

    response = client.get(
        _download_url(project, uploaded["document"]["id"], uploaded["version"]["id"]),
        headers=headers,
    )

    assert response.status_code == 200
    assert response.content == SAMPLE_MD.encode("utf-8")
