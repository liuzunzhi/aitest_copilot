"""作废版本（T50 / AC-55、AC-56、AC-59）。"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import DocumentVersion
from app.models.system import AuditLog
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
    return project, login(client, user), user


def _upload(client: TestClient, project, headers):
    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(SAMPLE_MD),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _void(client: TestClient, project, headers, document_id: int, version_id: int):
    return client.post(
        f"/api/projects/{project.id}/documents/{document_id}"
        f"/versions/{version_id}/void",
        headers=headers,
    )


def _activate(client: TestClient, project, headers, document_id: int, version_id: int):
    return client.post(
        f"/api/projects/{project.id}/documents/{document_id}"
        f"/versions/{version_id}/activate",
        headers=headers,
    )


def test_ac_55_member_voids_own_version(client: TestClient, db: Session, upload_root):
    """成员作废自己上传的待确认版本：状态 void、写审计、之后不能再生效。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)
    document_id = uploaded["document"]["id"]
    version_id = uploaded["version"]["id"]

    response = _void(client, project, headers, document_id, version_id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "void"
    assert db.get(DocumentVersion, version_id).status == "void"
    assert db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.project_id == project.id,
            AuditLog.action == "document.version.void",
        )
    ) == 1

    again = _activate(client, project, headers, document_id, version_id)
    assert again.status_code == 409
    assert again.json()["code"] == "INVALID_VERSION_STATUS"


def test_ac_55_cannot_void_active_version(client: TestClient, db: Session, upload_root):
    """已生效版本不能作废：基线快照会指向不存在的内容。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)
    document_id = uploaded["document"]["id"]
    version_id = uploaded["version"]["id"]
    assert _activate(client, project, headers, document_id, version_id).status_code == 200

    response = _void(client, project, headers, document_id, version_id)

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_VERSION_STATUS"
    assert db.get(DocumentVersion, version_id).status == "active"


def test_ac_55_void_twice(client: TestClient, db: Session, upload_root):
    """重复作废 409，只留一条作废审计。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)
    document_id = uploaded["document"]["id"]
    version_id = uploaded["version"]["id"]
    assert _void(client, project, headers, document_id, version_id).status_code == 200

    response = _void(client, project, headers, document_id, version_id)

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_VERSION_STATUS"
    assert db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.project_id == project.id,
            AuditLog.action == "document.version.void",
        )
    ) == 1


def test_ac_56_member_cannot_void_others(client: TestClient, db: Session, upload_root):
    """普通成员不能作废别人上传的版本。"""
    project, uploader_headers, _ = _setup(client, db)
    uploaded = _upload(client, project, uploader_headers)

    other = make_user(db)
    add_member(db, project, other, role="member")
    response = _void(
        client,
        project,
        login(client, other),
        uploaded["document"]["id"],
        uploaded["version"]["id"],
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"
    assert db.get(DocumentVersion, uploaded["version"]["id"]).status == "pending"


def test_ac_56_project_admin_voids_any(client: TestClient, db: Session, upload_root):
    """项目管理员可作废任何人的版本。"""
    project, uploader_headers, _ = _setup(client, db)
    uploaded = _upload(client, project, uploader_headers)

    admin = make_user(db)
    add_member(db, project, admin, role="project_admin")
    response = _void(
        client,
        project,
        login(client, admin),
        uploaded["document"]["id"],
        uploaded["version"]["id"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == "void"


def test_ac_56_guest_cannot_void(client: TestClient, db: Session, upload_root):
    """访客不可作废。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)

    guest = make_user(db)
    add_member(db, project, guest, role="guest")
    response = _void(
        client,
        project,
        login(client, guest),
        uploaded["document"]["id"],
        uploaded["version"]["id"],
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_56_outsider_cannot_void(client: TestClient, db: Session, upload_root):
    """非成员不可作废。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)

    outsider = make_user(db)
    response = _void(
        client,
        project,
        login(client, outsider),
        uploaded["document"]["id"],
        uploaded["version"]["id"],
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_59_archived_project_rejects_void(client: TestClient, db: Session, upload_root):
    """归档项目不能作废版本。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)
    project.status = "archived"
    db.flush()

    response = _void(
        client, project, headers, uploaded["document"]["id"], uploaded["version"]["id"]
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"
    assert db.get(DocumentVersion, uploaded["version"]["id"]).status == "pending"


def test_ac_55_void_version_not_found(client: TestClient, db: Session, upload_root):
    """版本不存在 → 404。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)

    response = _void(
        client, project, headers, uploaded["document"]["id"], 987654
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_VERSION_NOT_FOUND"
