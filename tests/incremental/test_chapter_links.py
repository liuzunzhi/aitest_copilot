"""T71 · 章节引用图：规则抽取、幂等、手动补链与权限（AC-86 / AC-87 / AC-96）。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
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
    ("2 登录", "账号密码登录，依赖 2.1。"),
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


def _rule_rows(db: Session, version) -> list[DocumentChapterLink]:
    return list(
        db.scalars(
            select(DocumentChapterLink)
            .where(
                DocumentChapterLink.version_id == version.id,
                DocumentChapterLink.source == "rule",
            )
            .order_by(DocumentChapterLink.id)
        ).all()
    )


# ------------------------------------------------------------ AC-86


def test_ac_86_extract_rules_and_idempotent(client: TestClient, db: Session):
    """规则抽取出 references / depends_on；重抽不累加，人工边不丢。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    response = client.post(f"{url}/extract", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    by_type = {item["link_type"]: item for item in body}
    assert by_type["references"]["from_chapter_id"] == rows[0].id
    assert by_type["references"]["to_chapter_id"] == rows[1].id
    assert by_type["references"]["source"] == "rule"
    assert by_type["references"]["confidence"] == pytest.approx(0.8)
    assert by_type["depends_on"]["from_chapter_id"] == rows[1].id
    assert by_type["depends_on"]["to_chapter_id"] == rows[2].id
    assert by_type["references"]["to_chapter_title"] == "2 登录"

    # 人工边先插一条，重抽后必须还在
    manual = client.post(
        url,
        json={"from_chapter_id": rows[0].id, "link_type": "references", "to_chapter_id": rows[2].id},
        headers=headers,
    )
    assert manual.status_code == 201, manual.text

    first_count = len(_rule_rows(db, version))
    assert client.post(f"{url}/extract", headers=headers).status_code == 200
    assert len(_rule_rows(db, version)) == first_count == 2
    assert (
        db.execute(
            select(func.count())
            .select_from(DocumentChapterLink)
            .where(
                DocumentChapterLink.version_id == version.id,
                DocumentChapterLink.source == "manual",
            )
        ).scalar_one()
        == 1
    )

    filtered = client.get(url, params={"link_type": "references"}, headers=headers)
    assert filtered.status_code == 200, filtered.text
    assert {item["link_type"] for item in filtered.json()} == {"references"}
    assert len(filtered.json()) == 2


def test_ac_86_unresolvable_and_self_reference_dropped(client: TestClient, db: Session):
    """解析不到的序号、指向自身的引用都丢弃，不报错。"""
    chapters = [
        ("1 概述", "详见第 9 章；另见第 1 章。"),
        ("2 登录", "无引用。"),
    ]
    admin, project, document, version, _ = _chain(db, chapters=chapters)
    headers = helpers.login(client, admin)

    response = client.post(f"{_url(project, document, version)}/extract", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_ac_86_mentions_feature_point_entity(client: TestClient, db: Session):
    """正文命中功能点名称 → mentions_entity，名称按去空白比较。"""
    admin, project, document, version, rows = _chain(
        db, chapters=[("1 支付", "本章讲退款审核的规则。")]
    )
    helpers.make_function(db, project, admin, function_name="退款", point_name="退款 审核")
    headers = helpers.login(client, admin)

    response = client.post(f"{_url(project, document, version)}/extract", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["link_type"] == "mentions_entity"
    assert body[0]["entity"] == "退款审核"
    assert body[0]["to_chapter_id"] is None
    assert body[0]["confidence"] == pytest.approx(0.6)


# ------------------------------------------------------------ AC-87


def test_ac_87_manual_create_and_duplicate(client: TestClient, db: Session):
    """手动补链 → 201 / source=manual / 无置信度；重复 → 409。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)
    payload = {
        "from_chapter_id": rows[0].id,
        "link_type": "references",
        "to_chapter_id": rows[2].id,
    }

    response = client.post(url, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "manual"
    assert body["confidence"] is None
    assert body["from_chapter_title"] == "1 概述"
    assert body["to_chapter_title"] == "2.1 登录流程"

    again = client.post(url, json=payload, headers=headers)
    assert again.status_code == 409
    assert again.json()["code"] == "DUPLICATE_CHAPTER_LINK"


@pytest.mark.parametrize(
    "payload",
    [
        {"from_chapter_id": 0, "link_type": "references", "to_chapter_id": 0, "entity": "退款"},
        {"from_chapter_id": 0, "link_type": "references"},
        {"from_chapter_id": 0, "link_type": "unknown_type", "entity": "退款"},
        {"from_chapter_id": 0, "link_type": "references", "to_chapter_id": "self"},
        {"from_chapter_id": 0, "link_type": "references", "to_chapter_id": "other_version"},
    ],
)
def test_ac_87_invalid_payloads(client: TestClient, db: Session, payload: dict):
    """目标二选一 / 类型 / 章节归属 / 自引用不合法 → 400 INVALID_CHAPTER_LINK。"""
    admin, project, document, version, rows = _chain(db)
    _, _, other_rows = helpers.make_document_version(
        db, project, admin, chapters=[("1 其他", "别的版本")]
    )
    headers = helpers.login(client, admin)

    concrete = dict(payload)
    concrete["from_chapter_id"] = rows[0].id
    if concrete.get("to_chapter_id") == "self":
        concrete["to_chapter_id"] = rows[0].id
    elif concrete.get("to_chapter_id") == "other_version":
        concrete["to_chapter_id"] = other_rows[0].id

    response = client.post(
        _url(project, document, version), json=concrete, headers=headers
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_CHAPTER_LINK"


def test_ac_87_permissions_and_archive(client: TestClient, db: Session):
    """访客可读不可写；非成员不可读；归档项目写 → 409。"""
    admin, project, document, version, rows = _chain(db)
    guest = helpers.make_user(db)
    helpers.add_member(db, project, guest, "guest")
    outsider = helpers.make_user(db)
    url = _url(project, document, version)

    guest_headers = helpers.login(client, guest)
    assert client.get(url, headers=guest_headers).status_code == 200
    forbidden = client.post(
        url,
        json={"from_chapter_id": rows[0].id, "link_type": "references", "to_chapter_id": rows[1].id},
        headers=guest_headers,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "NOT_PROJECT_ADMIN"

    outsider_headers = helpers.login(client, outsider)
    blocked = client.get(url, headers=outsider_headers)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "NOT_PROJECT_MEMBER"

    archived_admin, archived_project, archived_doc, archived_version, archived_rows = _chain(
        db, project_status="archived"
    )
    archived_headers = helpers.login(client, archived_admin)
    response = client.post(
        _url(archived_project, archived_doc, archived_version),
        json={
            "from_chapter_id": archived_rows[0].id,
            "link_type": "references",
            "to_chapter_id": archived_rows[1].id,
        },
        headers=archived_headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


# ------------------------------------------------------------ AC-96


def test_ac_96_manual_link_writes_audit(client: TestClient, db: Session):
    """手动补链写 `document.chapter_link.create`，带项目与目标标识；抽取不写。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    assert client.post(f"{url}/extract", headers=headers).status_code == 200
    response = client.post(
        url,
        json={"from_chapter_id": rows[0].id, "link_type": "mentions_entity", "entity": "退款"},
        headers=headers,
    )
    assert response.status_code == 201, response.text

    log = db.scalar(
        select(AuditLog).where(AuditLog.action == "document.chapter_link.create")
    )
    assert log is not None
    assert log.project_id == project.id
    assert log.actor_id == admin.id
    assert log.target_type == "document_chapter_link"
    assert log.target_id == str(response.json()["id"])
