"""删除引用边（12-chapter-link-ai T133 / AC-225 / AC-227）。

覆盖：删除成功（三种来源都可删）、跨版本删被拒、边不存在 404、
权限矩阵、归档项目 409、审计。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chapter_link import DocumentChapterLink
from app.models.document import DocumentChapter, DocumentVersion
from app.models.system import AuditLog
from tests.incremental import helpers

LINKS = (
    "/api/projects/{project_id}/documents/{document_id}"
    "/versions/{version_id}/links"
)

CHAPTERS = [
    ("1 概述", "总体说明，详见第 2 章。"),
    ("2 登录", "账号密码登录。"),
    ("2.1 登录流程", "输入账号密码后跳转首页。"),
]


def _chain(
    db: Session,
    *,
    chapters: list[tuple[str, str]] | None = None,
    project_status: str = "active",
    role: str = "project_admin",
):
    """项目 + 成员 + 文档版本（章节）。返回 (用户, 项目, 文档, 版本, 章节行)。"""
    admin = helpers.make_user(db)
    project = helpers.make_project(db, status=project_status)
    helpers.add_member(db, project, admin, role)
    document, version, rows = helpers.make_document_version(
        db, project, admin, chapters=chapters or CHAPTERS
    )
    return admin, project, document, version, rows


def _url(project, document, version) -> str:
    return LINKS.format(
        project_id=project.id, document_id=document.id, version_id=version.id
    )


def _rows(db: Session, version) -> list[DocumentChapterLink]:
    return list(
        db.scalars(
            select(DocumentChapterLink)
            .where(DocumentChapterLink.version_id == version.id)
            .order_by(DocumentChapterLink.id)
        ).all()
    )


# ------------------------------------------------------------ 删除成功


def test_ac_225_delete_manual_link(client: TestClient, db: Session):
    """删人工边 → 204，边消失。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    created = client.post(
        url,
        json={
            "from_chapter_id": rows[0].id,
            "link_type": "mentions_entity",
            "entity": "退款审核",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    link_id = created.json()["id"]

    response = client.delete(f"{url}/{link_id}", headers=headers)

    assert response.status_code == 204, response.text
    assert _rows(db, version) == []


def test_ac_225_delete_rule_link(client: TestClient, db: Session):
    """删规则边 → 204（允许；重抽会重新生成它）。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    assert client.post(f"{url}/extract", headers=headers).status_code == 200
    rule_rows = [row for row in _rows(db, version) if row.source == "rule"]
    assert rule_rows

    response = client.delete(f"{url}/{rule_rows[0].id}", headers=headers)

    assert response.status_code == 204, response.text
    assert [row for row in _rows(db, version) if row.source == "rule"] == []


def test_ac_225_delete_ai_link(client: TestClient, db: Session, provider):
    """删 AI 边 → 204（这正是「AI 结果错了要能删」的诉求）。"""
    import json

    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    provider.queue.append(
        json.dumps(
            {
                "references": [
                    {
                        "from_chapter_id": rows[0].id,
                        "to_chapter_id": rows[1].id,
                        "link_type": "references",
                        "confidence": 0.9,
                    }
                ]
            }
        )
    )
    assert client.post(f"{url}/analyze", headers=headers).status_code == 200

    ai_rows = [row for row in _rows(db, version) if row.source == "ai"]
    assert len(ai_rows) == 1

    response = client.delete(f"{url}/{ai_rows[0].id}", headers=headers)

    assert response.status_code == 204, response.text
    assert [row for row in _rows(db, version) if row.source == "ai"] == []


def test_ac_225_delete_only_affects_target_link(client: TestClient, db: Session):
    """删一条不影响其他边。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    first = client.post(
        url,
        json={
            "from_chapter_id": rows[0].id,
            "link_type": "mentions_entity",
            "entity": "退款审核",
        },
        headers=headers,
    )
    second = client.post(
        url,
        json={
            "from_chapter_id": rows[1].id,
            "link_type": "mentions_entity",
            "entity": "登录失败",
        },
        headers=headers,
    )
    assert first.status_code == 201 and second.status_code == 201

    response = client.delete(f"{url}/{first.json()['id']}", headers=headers)

    assert response.status_code == 204, response.text
    remaining = _rows(db, version)
    assert len(remaining) == 1
    assert remaining[0].entity == "登录失败"


# ------------------------------------------------------------ 不存在与越界


def test_ac_225_delete_unknown_link_returns_404(client: TestClient, db: Session):
    """删不存在的边 → 404 `CHAPTER_LINK_NOT_FOUND`。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    response = client.delete(
        f"{_url(project, document, version)}/999999", headers=headers
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "CHAPTER_LINK_NOT_FOUND"


def test_ac_225_cannot_delete_link_of_other_version(client: TestClient, db: Session):
    """跨版本删边被拒 → 404（不校验归属就能删掉别的版本的边）。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    created = client.post(
        url,
        json={
            "from_chapter_id": rows[0].id,
            "link_type": "mentions_entity",
            "entity": "退款审核",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    link_id = created.json()["id"]

    # 造**同一个文档**的另一个版本（边挂在老版本上）。
    # 必须是同一个 document——跨 document 时 `_load_version` 会先拦下
    # （`DOCUMENT_VERSION_NOT_FOUND`），那验证的是另一道防线。
    # 新版本用 `pending`：一个文档只能有一个 active 版本（`uk_versions_active`）。
    other_version = DocumentVersion(
        document_id=document.id,
        version_no=2,
        status="pending",
        file_name="需求-v2.md",
        file_path="var/uploads/2/2.md",
        file_size=128,
        sha256="b" * 64,
        chapter_count=1,
        uploaded_by=admin.id,
    )
    db.add(other_version)
    db.flush()
    other_chapter = DocumentChapter(
        version_id=other_version.id,
        parent_id=None,
        seq=1,
        level=1,
        title="9 其他",
        content="别的版本",
        char_count=4,
    )
    db.add(other_chapter)
    db.flush()
    other_url = _url(project, document, other_version)

    response = client.delete(f"{other_url}/{link_id}", headers=headers)

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "CHAPTER_LINK_NOT_FOUND"
    # 老版本的边还在
    assert len(_rows(db, version)) == 1


def test_ac_225_cannot_delete_link_of_other_document(client: TestClient, db: Session):
    """跨文档删边被拒 → 404 `DOCUMENT_VERSION_NOT_FOUND`。

    这是**更早一道防线**：版本不属于该文档时，`_load_version` 先拦下。
    """
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    created = client.post(
        url,
        json={
            "from_chapter_id": rows[0].id,
            "link_type": "mentions_entity",
            "entity": "退款审核",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    link_id = created.json()["id"]

    # 另一个文档的版本：用**别的 document_id** 去访问它
    other_doc, other_ver, _ = helpers.make_document_version(
        db, project, admin, chapters=[("9 其他", "别的版本")]
    )
    other_url = LINKS.format(
        project_id=project.id,
        document_id=other_doc.id,
        version_id=other_ver.id,
    )

    response = client.delete(f"{other_url}/{link_id}", headers=headers)

    assert response.status_code == 404, response.text
    # 老版本的边还在
    assert len(_rows(db, version)) == 1


# ------------------------------------------------------------ 权限


def test_ac_227_guest_cannot_delete(client: TestClient, db: Session):
    """访客可读不可删 → 403 `NOT_PROJECT_ADMIN`。"""
    admin, project, document, version, rows = _chain(db)
    guest = helpers.make_user(db)
    helpers.add_member(db, project, guest, "guest")
    guest_headers = helpers.login(client, guest)
    url = _url(project, document, version)

    created = client.post(
        url,
        json={
            "from_chapter_id": rows[0].id,
            "link_type": "mentions_entity",
            "entity": "退款审核",
        },
        headers=guest_headers,
    )
    assert created.status_code == 403

    response = client.delete(f"{url}/1", headers=guest_headers)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_227_member_cannot_delete(client: TestClient, db: Session):
    """普通成员不可删 → 403 `NOT_PROJECT_ADMIN`。"""
    admin, project, document, version, rows = _chain(db)
    member = helpers.make_user(db)
    helpers.add_member(db, project, member, "member")
    member_headers = helpers.login(client, member)

    response = client.delete(
        f"{_url(project, document, version)}/1", headers=member_headers
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_227_archived_project_cannot_delete(client: TestClient, db: Session):
    """归档项目不可删 → 409 `PROJECT_ARCHIVED`。"""
    admin, project, document, version, rows = _chain(db, project_status="archived")
    headers = helpers.login(client, admin)

    response = client.delete(
        f"{_url(project, document, version)}/1", headers=headers
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROJECT_ARCHIVED"


# ------------------------------------------------------------ 审计


def test_ac_225_delete_writes_audit(client: TestClient, db: Session):
    """删除写 `document.chapter_link.delete` 审计，带删除前的快照。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    created = client.post(
        url,
        json={
            "from_chapter_id": rows[0].id,
            "link_type": "mentions_entity",
            "entity": "退款审核",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    link_id = created.json()["id"]

    assert client.delete(f"{url}/{link_id}", headers=headers).status_code == 204

    log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "document.chapter_link.delete",
            AuditLog.project_id == project.id,
        )
    )
    assert log is not None
    assert log.actor_id == admin.id
    assert log.target_type == "document_chapter_link"
    assert log.target_id == str(link_id)
    assert log.before_data["entity"] == "退款审核"
    assert log.before_data["source"] == "manual"


def test_ac_225_failed_delete_writes_no_audit(client: TestClient, db: Session):
    """删不存在的边 → 失败，不写审计。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    assert client.delete(
        f"{_url(project, document, version)}/999999", headers=headers
    ).status_code == 404

    count = db.scalar(
        select(AuditLog).where(AuditLog.action == "document.chapter_link.delete")
    )
    assert count is None
