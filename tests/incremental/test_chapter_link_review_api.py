"""12.5 期 · 采纳接口与列表字段（T140 / AC-229 / AC-230 / AC-238）。

接口层覆盖：列表带 `status` / `rationale`、单条与批量采纳、幂等、
整批原子、错误码、权限矩阵、审计。

服务层语义（落库即 pending、重分析不冲掉已采纳）由
`test_chapter_link_review.py` 覆盖，本文件不重复。
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chapter_link import DocumentChapterLink
from app.models.system import AuditLog
from tests.incremental import helpers

LINKS = (
    "/api/projects/{project_id}/documents/{document_id}"
    "/versions/{version_id}/links"
)

CHAPTERS = [
    ("1 概述", "总体说明，详见第 2 章。"),
    ("2 登录", "账号密码登录。"),
    ("3 支付", "支付回调说明。"),
]


def _chain(db: Session, *, project_status: str = "active", role: str = "project_admin"):
    admin = helpers.make_user(db)
    project = helpers.make_project(db, status=project_status)
    helpers.add_member(db, project, admin, role)
    document, version, rows = helpers.make_document_version(
        db, project, admin, chapters=CHAPTERS
    )
    return admin, project, document, version, rows


def _url(project, document, version) -> str:
    return LINKS.format(
        project_id=project.id, document_id=document.id, version_id=version.id
    )


def _ref(from_id: int, to_id: int) -> dict:
    return {
        "from_chapter_id": from_id,
        "to_chapter_id": to_id,
        "link_type": "references",
        "confidence": 0.9,
        "rationale": "1 节提到「详见第 2 章」",
    }


def _analyze(client: TestClient, provider, project, document, version, headers, *refs):
    provider.queue.append(
        json.dumps({"references": list(refs)}, ensure_ascii=False)
    )
    response = client.post(f"{_url(project, document, version)}/analyze", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _ai_rows(db: Session, version) -> list[DocumentChapterLink]:
    return list(
        db.scalars(
            select(DocumentChapterLink)
            .where(
                DocumentChapterLink.version_id == version.id,
                DocumentChapterLink.source == "ai",
            )
            .order_by(DocumentChapterLink.id)
        ).all()
    )


# ------------------------------------------------------------ 列表字段


def test_ac_229_list_returns_status_and_rationale(
    client: TestClient, db: Session, provider
):
    """列表每条边带 `status` 与 `rationale`；AI 边是 `pending`。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    _analyze(
        client, provider, project, document, version, headers, _ref(rows[0].id, rows[1].id)
    )

    response = client.get(_url(project, document, version), headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "pending"
    assert body[0]["rationale"] == "1 节提到「详见第 2 章」"
    assert body[0]["source"] == "ai"


def test_ac_229_manual_link_listed_as_approved(client: TestClient, db: Session):
    """人工补的边在列表里是 `approved`，`rationale` 为 null。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    created = client.post(
        _url(project, document, version),
        json={
            "from_chapter_id": rows[0].id,
            "link_type": "mentions_entity",
            "entity": "退款审核",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "approved"
    assert created.json()["rationale"] is None


# ------------------------------------------------------------ 单条采纳


def test_ac_230_approve_endpoint(client: TestClient, db: Session, provider):
    """`POST /{id}/approve` → 200，边变 `approved`，响应体是最新状态。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    _analyze(
        client, provider, project, document, version, headers, _ref(rows[0].id, rows[1].id)
    )
    link = _ai_rows(db, version)[0]

    response = client.post(
        f"{_url(project, document, version)}/{link.id}/approve", headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    assert _ai_rows(db, version)[0].status == "approved"


def test_ac_230_approve_endpoint_is_idempotent(
    client: TestClient, db: Session, provider
):
    """重复采纳返回 200，不报 409。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    _analyze(
        client, provider, project, document, version, headers, _ref(rows[0].id, rows[1].id)
    )
    link = _ai_rows(db, version)[0]
    url = f"{_url(project, document, version)}/{link.id}/approve"

    assert client.post(url, headers=headers).status_code == 200
    second = client.post(url, headers=headers)

    assert second.status_code == 200
    assert second.json()["status"] == "approved"


def test_ac_230_approve_missing_link_404(client: TestClient, db: Session):
    """采纳不存在的边 → 404 `CHAPTER_LINK_NOT_FOUND`。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    response = client.post(
        f"{_url(project, document, version)}/999999/approve", headers=headers
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "CHAPTER_LINK_NOT_FOUND"


# ------------------------------------------------------------ 批量采纳


def test_ac_230_approve_batch_endpoint(client: TestClient, db: Session, provider):
    """批量采纳 → 200 + `approved_count`，全部变 `approved`。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    _analyze(
        client,
        provider,
        project,
        document,
        version,
        headers,
        _ref(rows[0].id, rows[1].id),
        _ref(rows[1].id, rows[2].id),
    )
    link_ids = [row.id for row in _ai_rows(db, version)]
    assert len(link_ids) == 2

    response = client.post(
        f"{_url(project, document, version)}/approve-batch",
        json={"link_ids": link_ids},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["approved_count"] == 2
    assert all(row.status == "approved" for row in _ai_rows(db, version))


def test_ac_230_approve_batch_atomic_on_missing(
    client: TestClient, db: Session, provider
):
    """批量里有一个不存在的 id → 整批 404，一条都不改。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    _analyze(
        client, provider, project, document, version, headers, _ref(rows[0].id, rows[1].id)
    )
    link_ids = [row.id for row in _ai_rows(db, version)]

    response = client.post(
        f"{_url(project, document, version)}/approve-batch",
        json={"link_ids": [*link_ids, 999999]},
        headers=headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "CHAPTER_LINK_NOT_FOUND"
    assert all(row.status == "pending" for row in _ai_rows(db, version))


def test_ac_230_approve_batch_empty_returns_400(client: TestClient, db: Session):
    """空数组 → 400 `INVALID_CHAPTER_LINK`（不是 422）。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    response = client.post(
        f"{_url(project, document, version)}/approve-batch",
        json={"link_ids": []},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_CHAPTER_LINK"


def test_ac_230_approve_batch_empty_link_ids_missing_field_422(
    client: TestClient, db: Session
):
    """缺 `link_ids` 字段 → 422（pydantic 结构校验，与业务 400 区分）。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    response = client.post(
        f"{_url(project, document, version)}/approve-batch",
        json={},
        headers=headers,
    )

    assert response.status_code == 422, response.text


# ------------------------------------------------------------ 权限


def test_ac_238_member_cannot_approve(client: TestClient, db: Session, provider):
    """普通成员可读不可采纳 → 403 `NOT_PROJECT_ADMIN`。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    _analyze(
        client, provider, project, document, version, headers, _ref(rows[0].id, rows[1].id)
    )
    link = _ai_rows(db, version)[0]

    member = helpers.make_user(db)
    helpers.add_member(db, project, member, "member")
    member_headers = helpers.login(client, member)

    response = client.post(
        f"{_url(project, document, version)}/{link.id}/approve", headers=member_headers
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_238_guest_cannot_batch_approve(client: TestClient, db: Session, provider):
    """访客可读不可批量采纳 → 403 `NOT_PROJECT_ADMIN`。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    _analyze(
        client, provider, project, document, version, headers, _ref(rows[0].id, rows[1].id)
    )
    link_ids = [row.id for row in _ai_rows(db, version)]

    guest = helpers.make_user(db)
    helpers.add_member(db, project, guest, "guest")
    guest_headers = helpers.login(client, guest)

    response = client.post(
        f"{_url(project, document, version)}/approve-batch",
        json={"link_ids": link_ids},
        headers=guest_headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_238_outsider_cannot_approve(client: TestClient, db: Session, provider):
    """非成员 → 403 `NOT_PROJECT_ADMIN`（与既有写接口同口径）。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    _analyze(
        client, provider, project, document, version, headers, _ref(rows[0].id, rows[1].id)
    )
    link = _ai_rows(db, version)[0]

    outsider = helpers.make_user(db)
    outsider_headers = helpers.login(client, outsider)

    response = client.post(
        f"{_url(project, document, version)}/{link.id}/approve",
        headers=outsider_headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_238_archived_project_returns_409(
    client: TestClient, db: Session, provider
):
    """归档项目 → 409 `PROJECT_ARCHIVED`。"""
    admin, project, document, version, rows = _chain(db, project_status="archived")
    headers = helpers.login(client, admin)

    response = client.post(
        f"{_url(project, document, version)}/999999/approve", headers=headers
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROJECT_ARCHIVED"


# ------------------------------------------------------------ 审计


def test_ac_230_approve_writes_audit(client: TestClient, db: Session, provider):
    """采纳写 `document.chapter_link.approve` 审计，带项目与操作者。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    _analyze(
        client, provider, project, document, version, headers, _ref(rows[0].id, rows[1].id)
    )
    link = _ai_rows(db, version)[0]

    client.post(f"{_url(project, document, version)}/{link.id}/approve", headers=headers)

    log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "document.chapter_link.approve",
            AuditLog.project_id == project.id,
        )
    )
    assert log is not None
    assert log.actor_id == admin.id
    assert log.target_type == "document_chapter_link"
    assert log.after_data["version_id"] == version.id
    assert log.after_data["approved_count"] == 1
