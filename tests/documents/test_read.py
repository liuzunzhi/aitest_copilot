"""文档 / 版本 / 章节读取（T48 / AC-53、AC-58）。"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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


def _upload(
    client: TestClient,
    project,
    headers,
    *,
    body: str = SAMPLE_MD,
    name: str = "支付需求.md",
    document_id: int | None = None,
):
    data = {"document_id": str(document_id)} if document_id else None
    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(body, name),
        data=data,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ac_53_document_list(client: TestClient, db: Session, upload_root):
    """文档列表带版本数、待确认数；未确认时 active_version 为空。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)

    response = client.get(f"/api/projects/{project.id}/documents", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    item = body[0]
    assert item["id"] == uploaded["document"]["id"]
    assert item["name"] == "支付需求"
    assert item["version_count"] == 1
    assert item["pending_count"] == 1
    assert item["active_version"] is None
    assert "file_path" not in response.text


def test_ac_53_versions_sorted_desc(client: TestClient, db: Session, upload_root):
    """版本列表新版本在前，状态可读。"""
    project, headers, _ = _setup(client, db)
    first = _upload(client, project, headers)
    document_id = first["document"]["id"]
    _upload(client, project, headers, body="# 支付\nv2 正文", document_id=document_id)

    response = client.get(
        f"/api/projects/{project.id}/documents/{document_id}/versions", headers=headers
    )

    assert response.status_code == 200
    versions = response.json()
    assert [v["version_no"] for v in versions] == [2, 1]
    assert [v["status"] for v in versions] == ["pending", "pending"]
    assert "file_path" not in response.text


def test_ac_53_chapter_tree(client: TestClient, db: Session, upload_root):
    """章节树保持层级与顺序，`content` 只含直属正文。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)
    document_id = uploaded["document"]["id"]
    version_id = uploaded["version"]["id"]

    response = client.get(
        f"/api/projects/{project.id}/documents/{document_id}/versions/{version_id}/chapters",
        headers=headers,
    )

    assert response.status_code == 200
    tree = response.json()
    assert [node["title"] for node in tree] == ["支付"]
    root = tree[0]
    assert root["level"] == 1
    assert root["content"] == "总述"
    assert root["char_count"] == 2
    assert [child["title"] for child in root["children"]] == ["下单", "退款"]
    assert [child["content"] for child in root["children"]] == ["下单正文", "退款正文"]
    assert [child["seq"] for child in root["children"]] == [2, 3]
    assert "file_path" not in response.text


def test_ac_53_guest_can_read(client: TestClient, db: Session, upload_root):
    """访客只读：成员传的文档，访客能看列表与章节。"""
    project, member_headers, _ = _setup(client, db)
    uploaded = _upload(client, project, member_headers)

    guest = make_user(db)
    add_member(db, project, guest, role="guest")
    guest_headers = login(client, guest)

    listing = client.get(f"/api/projects/{project.id}/documents", headers=guest_headers)
    chapters = client.get(
        f"/api/projects/{project.id}/documents/{uploaded['document']['id']}"
        f"/versions/{uploaded['version']['id']}/chapters",
        headers=guest_headers,
    )

    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert chapters.status_code == 200


def test_ac_53_outsider_forbidden(client: TestClient, db: Session, upload_root):
    """非成员读文档接口一律 403 NOT_PROJECT_MEMBER。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)

    outsider = make_user(db)
    outsider_headers = login(client, outsider)

    responses = [
        client.get(f"/api/projects/{project.id}/documents", headers=outsider_headers),
        client.get(
            f"/api/projects/{project.id}/documents/{uploaded['document']['id']}/versions",
            headers=outsider_headers,
        ),
        client.get(
            f"/api/projects/{project.id}/documents/{uploaded['document']['id']}"
            f"/versions/{uploaded['version']['id']}/chapters",
            headers=outsider_headers,
        ),
    ]
    assert [r.status_code for r in responses] == [403, 403, 403]
    assert {r.json()["code"] for r in responses} == {"NOT_PROJECT_MEMBER"}


def test_ac_53_system_admin_can_read(client: TestClient, db: Session, upload_root):
    """系统管理员不是成员也能读任意项目。"""
    project, headers, _ = _setup(client, db)
    _upload(client, project, headers)

    admin = make_user(db, global_role="system_admin")
    admin_headers = login(client, admin)

    response = client.get(f"/api/projects/{project.id}/documents", headers=admin_headers)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_ac_53_document_not_found(client: TestClient, db: Session, upload_root):
    """文档 id 不存在时 404，不返回空列表糊弄前端。"""
    project, headers, _ = _setup(client, db)

    responses = [
        client.get(f"/api/projects/{project.id}/documents/987654/versions", headers=headers),
        client.get(
            f"/api/projects/{project.id}/documents/987654/versions/1/chapters",
            headers=headers,
        ),
    ]
    assert [r.status_code for r in responses] == [404, 404]
    assert {r.json()["code"] for r in responses} == {"DOCUMENT_NOT_FOUND"}


def test_ac_53_document_of_other_project(client: TestClient, db: Session, upload_root):
    """拿别的项目的文档 id 也找不到，不泄露存在性。"""
    project, headers, _ = _setup(client, db)
    other_user = make_user(db)
    other = make_project(db, name="另一个项目")
    add_member(db, other, other_user, role="member")
    foreign = _upload(client, other, login(client, other_user))

    response = client.get(
        f"/api/projects/{project.id}/documents/{foreign['document']['id']}/versions",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_NOT_FOUND"


def test_ac_53_version_not_found(client: TestClient, db: Session, upload_root):
    """版本不属于该文档时 404，不做跨文档读取。"""
    project, headers, _ = _setup(client, db)
    first = _upload(client, project, headers)
    second = _upload(client, project, headers, name="退款需求.md")

    response = client.get(
        f"/api/projects/{project.id}/documents/{first['document']['id']}"
        f"/versions/{second['version']['id']}/chapters",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_VERSION_NOT_FOUND"


def test_ac_59_archived_project_still_readable(client: TestClient, db: Session, upload_root):
    """归档只锁写操作，列表与章节仍可读。"""
    project, headers, _ = _setup(client, db)
    uploaded = _upload(client, project, headers)
    project.status = "archived"
    db.flush()

    listing = client.get(f"/api/projects/{project.id}/documents", headers=headers)
    chapters = client.get(
        f"/api/projects/{project.id}/documents/{uploaded['document']['id']}"
        f"/versions/{uploaded['version']['id']}/chapters",
        headers=headers,
    )

    assert listing.status_code == 200
    assert chapters.status_code == 200
