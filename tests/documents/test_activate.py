"""确认生效与基线快照（T49 / AC-54 ~ AC-57）。"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import BaselineSnapshot, DocumentVersion
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


def _upload(client: TestClient, project, headers, *, body: str = SAMPLE_MD, name: str = "支付需求.md", document_id=None):
    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(body, name),
        data={"document_id": str(document_id)} if document_id else None,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _activate(client: TestClient, project, headers, document_id: int, version_id: int):
    return client.post(
        f"/api/projects/{project.id}/documents/{document_id}"
        f"/versions/{version_id}/activate",
        headers=headers,
    )


def _audit_count(db: Session, project_id: int, action: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.project_id == project_id, AuditLog.action == action)
    )


def test_ac_54_member_activates_own_version(client: TestClient, db: Session, upload_root):
    """普通成员确认自己上传的版本：版本 active + 快照 1 号 + 两条审计。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)

    response = _activate(
        client, project, headers, uploaded["document"]["id"], uploaded["version"]["id"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"]["status"] == "active"
    assert body["baseline"]["version_no"] == 1
    assert body["baseline"]["chapter_count"] == 3
    assert body["baseline"]["document_name"] == "支付需求"
    assert body["baseline"]["document_version_no"] == 1
    assert _audit_count(db, project.id, "document.version.activate") == 1
    assert _audit_count(db, project.id, "baseline.snapshot.create") == 1

    listing = client.get(f"/api/projects/{project.id}/documents", headers=headers).json()
    assert listing[0]["active_version"]["version_no"] == 1
    assert listing[0]["pending_count"] == 0


def test_ac_54_new_active_archives_old(client: TestClient, db: Session, upload_root):
    """确认 v2 后 v1 自动归档，任何时刻只有一个 active。"""
    project, headers, _ = _setup(client, db)
    first = _upload(client, project, headers)
    document_id = first["document"]["id"]
    _activate(client, project, headers, document_id, first["version"]["id"])

    second = _upload(client, project, headers, body="# 支付\nv2", document_id=document_id)
    response = _activate(client, project, headers, document_id, second["version"]["id"])

    assert response.status_code == 200
    statuses = db.scalars(
        select(DocumentVersion.status)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_no)
    ).all()
    assert statuses == ["archived", "active"]
    assert response.json()["baseline"]["version_no"] == 2

    listing = client.get(f"/api/projects/{project.id}/documents", headers=headers).json()
    assert listing[0]["active_version"]["version_no"] == 2


def test_ac_54_activate_twice_conflict(client: TestClient, db: Session, upload_root):
    """重复确认 409，且不会生成第二条快照。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)
    document_id = uploaded["document"]["id"]
    version_id = uploaded["version"]["id"]
    assert _activate(client, project, headers, document_id, version_id).status_code == 200

    response = _activate(client, project, headers, document_id, version_id)

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_VERSION_STATUS"
    assert db.scalar(
        select(func.count())
        .select_from(BaselineSnapshot)
        .where(BaselineSnapshot.project_id == project.id)
    ) == 1


def test_ac_57_baseline_no_increments_per_project(client: TestClient, db: Session, upload_root):
    """基线序号按项目递增，不是按文档。"""
    project, headers, _ = _setup(client, db)
    first = _upload(client, project, headers)
    second = _upload(client, project, headers, body="# 退款", name="退款需求.md")

    first_baseline = _activate(
        client, project, headers, first["document"]["id"], first["version"]["id"]
    ).json()["baseline"]
    second_baseline = _activate(
        client, project, headers, second["document"]["id"], second["version"]["id"]
    ).json()["baseline"]

    assert first_baseline["version_no"] == 1
    assert second_baseline["version_no"] == 2


def test_ac_57_list_baselines(client: TestClient, db: Session, upload_root):
    """基线列表倒序、带文档名；访客可读、非成员 403。"""
    project, headers, _ = _setup(client, db)
    first = _upload(client, project, headers)
    second = _upload(client, project, headers, body="# 退款", name="退款需求.md")
    _activate(client, project, headers, first["document"]["id"], first["version"]["id"])
    _activate(client, project, headers, second["document"]["id"], second["version"]["id"])

    response = client.get(f"/api/projects/{project.id}/baselines", headers=headers)

    assert response.status_code == 200
    rows = response.json()
    assert [row["version_no"] for row in rows] == [2, 1]
    assert rows[0]["document_name"] == "退款需求"
    assert rows[1]["document_name"] == "支付需求"

    guest = make_user(db)
    add_member(db, project, guest, role="guest")
    assert client.get(
        f"/api/projects/{project.id}/baselines", headers=login(client, guest)
    ).status_code == 200

    outsider = make_user(db)
    denied = client.get(
        f"/api/projects/{project.id}/baselines", headers=login(client, outsider)
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_56_member_cannot_activate_others(client: TestClient, db: Session, upload_root):
    """普通成员只能确认自己上传的版本。"""
    project, uploader_headers, _ = _setup(client, db)
    uploaded = _upload(client, project, uploader_headers)

    other = make_user(db)
    add_member(db, project, other, role="member")
    response = _activate(
        client,
        project,
        login(client, other),
        uploaded["document"]["id"],
        uploaded["version"]["id"],
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"
    assert db.get(DocumentVersion, uploaded["version"]["id"]).status == "pending"


def test_ac_56_project_admin_activates_any(client: TestClient, db: Session, upload_root):
    """项目管理员可确认任何人的版本。"""
    project, uploader_headers, _ = _setup(client, db)
    uploaded = _upload(client, project, uploader_headers)

    admin = make_user(db)
    add_member(db, project, admin, role="project_admin")
    response = _activate(
        client,
        project,
        login(client, admin),
        uploaded["document"]["id"],
        uploaded["version"]["id"],
    )

    assert response.status_code == 200
    assert response.json()["version"]["status"] == "active"


def test_ac_56_guest_cannot_activate(client: TestClient, db: Session, upload_root):
    """访客即使能看到章节也不能确认。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)

    guest = make_user(db)
    add_member(db, project, guest, role="guest")
    response = _activate(
        client,
        project,
        login(client, guest),
        uploaded["document"]["id"],
        uploaded["version"]["id"],
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_56_outsider_cannot_activate(client: TestClient, db: Session, upload_root):
    """非成员 403 NOT_PROJECT_MEMBER。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)

    outsider = make_user(db)
    response = _activate(
        client,
        project,
        login(client, outsider),
        uploaded["document"]["id"],
        uploaded["version"]["id"],
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_59_archived_project_rejects_activate(client: TestClient, db: Session, upload_root):
    """归档项目不能确认版本。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)
    project.status = "archived"
    db.flush()

    response = _activate(
        client, project, headers, uploaded["document"]["id"], uploaded["version"]["id"]
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"
    assert db.get(DocumentVersion, uploaded["version"]["id"]).status == "pending"


def test_ac_54_activate_version_not_found(client: TestClient, db: Session, upload_root):
    """版本不存在或不属于该文档 → 404。"""
    project, headers, _ = _setup(client, db)
    first = _upload(client, project, headers)
    second = _upload(client, project, headers, body="# 退款", name="退款需求.md")

    response = _activate(
        client,
        project,
        headers,
        first["document"]["id"],
        second["version"]["id"],
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_VERSION_NOT_FOUND"
