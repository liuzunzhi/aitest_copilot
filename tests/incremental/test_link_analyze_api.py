"""AI 分析引用关系的接口层（12-chapter-link-ai T132 / AC-220 / AC-224 / AC-226 / AC-227）。

覆盖：成功落库、幂等、人工边与规则边不受影响、AI 边命中人工边时跳过、
越界 id 丢弃、模板缺失、权限矩阵、审计与运行留痕。
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chapter_link import DocumentChapterLink
from app.models.llm import LLMRunLog
from app.models.system import AuditLog
from tests.incremental import helpers

LINKS = (
    "/api/projects/{project_id}/documents/{document_id}"
    "/versions/{version_id}/links"
)

CHAPTERS = [
    # 第 1 章含「详见第 2 章」→ 规则抽取能命中 references 边
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


def _ref(from_id: int, to_id: int, **overrides) -> dict:
    item = {
        "from_chapter_id": from_id,
        "to_chapter_id": to_id,
        "link_type": "references",
        "confidence": 0.9,
        "rationale": "提到",
    }
    item.update(overrides)
    return item


def _queue(*payloads: dict) -> str:
    """把多条模型响应排成队列（整篇路径只用到第一条）。"""
    return json.dumps(list(payloads), ensure_ascii=False)


# ------------------------------------------------------------ 成功与幂等


def test_ac_220_analyze_success(client: TestClient, db: Session, provider):
    """AI 分析成功 → 200，边落库为 `source='ai'`，带统计。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    provider.queue.append(json.dumps({"references": [_ref(rows[0].id, rows[1].id)]}))

    response = client.post(f"{_url(project, document, version)}/analyze", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analyzed_count"] == 1
    assert body["chapter_count"] == 3
    assert body["discarded_count"] == 0
    assert body["mode"] == "full"
    assert body["provider"] == "mock"

    ai_rows = _ai_rows(db, version)
    assert len(ai_rows) == 1
    assert ai_rows[0].source == "ai"
    assert ai_rows[0].from_chapter_id == rows[0].id
    assert ai_rows[0].to_chapter_id == rows[1].id
    assert float(ai_rows[0].confidence) == pytest.approx(0.9)

    # 响应里的 links 是**全量**引用图（不只是 AI 边）
    assert any(item["source"] == "ai" for item in body["links"])


def test_ac_220_analyze_is_idempotent(client: TestClient, db: Session, provider):
    """重复调用不累加（`source='ai'` 先删后插）。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = f"{_url(project, document, version)}/analyze"

    provider.queue.append(json.dumps({"references": [_ref(rows[0].id, rows[1].id)]}))
    assert client.post(url, headers=headers).status_code == 200
    provider.queue.append(json.dumps({"references": [_ref(rows[0].id, rows[1].id)]}))
    assert client.post(url, headers=headers).status_code == 200

    assert len(_ai_rows(db, version)) == 1


def test_ac_220_no_reference_is_not_an_error(client: TestClient, db: Session, provider):
    """模型没找到引用 → 200 + 0 条，不是错误。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    response = client.post(
        f"{_url(project, document, version)}/analyze", headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analyzed_count"] == 0
    assert body["links"] == []
    assert _ai_rows(db, version) == []


# ------------------------------------------------------------ 越界即丢


def test_ac_224_out_of_scope_id_is_discarded(client: TestClient, db: Session, provider):
    """模型编造的 id 越界 → 丢弃，不落脏数据。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    provider.queue.append(
        json.dumps({"references": [_ref(rows[0].id, rows[1].id), _ref(rows[0].id, 999999)]})
    )

    response = client.post(
        f"{_url(project, document, version)}/analyze", headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analyzed_count"] == 1
    assert body["discarded_count"] == 1
    assert len(_ai_rows(db, version)) == 1


# ------------------------------------------------------------ 三种来源互不覆盖


def test_ac_226_manual_and_rule_links_survive_analysis(
    client: TestClient, db: Session, provider
):
    """AI 分析**不破坏**人工边与规则边。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    # 人工边
    manual = client.post(
        url,
        json={
            "from_chapter_id": rows[0].id,
            "link_type": "mentions_entity",
            "entity": "退款审核",
        },
        headers=headers,
    )
    assert manual.status_code == 201, manual.text

    # 规则边（规则能命中「详见第 2 章」）
    assert client.post(f"{url}/extract", headers=headers).status_code == 200
    rule_count = db.scalar(
        select(func.count())
        .select_from(DocumentChapterLink)
        .where(
            DocumentChapterLink.version_id == version.id,
            DocumentChapterLink.source == "rule",
        )
    )
    assert rule_count and rule_count > 0

    provider.queue.append(json.dumps({"references": [_ref(rows[1].id, rows[2].id)]}))
    assert client.post(f"{url}/analyze", headers=headers).status_code == 200

    sources = {
        row.source
        for row in db.scalars(
            select(DocumentChapterLink).where(
                DocumentChapterLink.version_id == version.id
            )
        ).all()
    }
    assert {"manual", "rule", "ai"} <= sources


def test_ac_226_ai_edge_conflicting_manual_is_skipped(
    client: TestClient, db: Session, provider
):
    """AI 边命中人工边同一条 → 跳过（不撞唯一键）。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)
    url = _url(project, document, version)

    manual = client.post(
        url,
        json={
            "from_chapter_id": rows[0].id,
            "link_type": "references",
            "to_chapter_id": rows[1].id,
        },
        headers=headers,
    )
    assert manual.status_code == 201, manual.text

    provider.queue.append(json.dumps({"references": [_ref(rows[0].id, rows[1].id)]}))
    response = client.post(f"{url}/analyze", headers=headers)

    assert response.status_code == 200, response.text
    # AI 边没插进去（人工边占了唯一键）
    assert _ai_rows(db, version) == []
    # 人工边还在
    manual_rows = db.scalars(
        select(DocumentChapterLink).where(
            DocumentChapterLink.version_id == version.id,
            DocumentChapterLink.source == "manual",
        )
    ).all()
    assert len(manual_rows) == 1


# ------------------------------------------------------------ 模板缺失


def test_ac_220_disabled_template_returns_409(client: TestClient, db: Session, provider):
    """模板被停用 → 409 `TEMPLATE_DISABLED`（不静默降级）。

    模板**缺失**与模板**被停用**是两个不同的运维动作，
    用户要知道的也不同：一个是「没建」，一个是「建了但关了」。
    """
    from app.models.incremental import PromptTemplate

    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "chapter_link_analyze"
        )
    )
    assert template is not None
    template.status = "disabled"
    db.flush()

    response = client.post(
        f"{_url(project, document, version)}/analyze", headers=headers
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "TEMPLATE_DISABLED"


def test_ac_220_missing_template_returns_404(client: TestClient, db: Session, provider):
    """模板行不存在 → 404 `TEMPLATE_NOT_FOUND`。"""
    from sqlalchemy import delete as sa_delete

    from app.models.incremental import PromptTemplate

    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    db.execute(
        sa_delete(PromptTemplate).where(
            PromptTemplate.task_type == "chapter_link_analyze"
        )
    )
    db.flush()

    response = client.post(
        f"{_url(project, document, version)}/analyze", headers=headers
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "TEMPLATE_NOT_FOUND"


# ------------------------------------------------------------ 权限


def test_ac_227_guest_cannot_analyze(client: TestClient, db: Session, provider):
    """访客可读不可分析 → 403 `NOT_PROJECT_ADMIN`。"""
    admin, project, document, version, rows = _chain(db)
    guest = helpers.make_user(db)
    helpers.add_member(db, project, guest, "guest")
    guest_headers = helpers.login(client, guest)

    response = client.post(
        f"{_url(project, document, version)}/analyze", headers=guest_headers
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_227_member_cannot_analyze(client: TestClient, db: Session, provider):
    """普通成员可读不可分析 → 403 `NOT_PROJECT_ADMIN`。"""
    admin, project, document, version, rows = _chain(db)
    member = helpers.make_user(db)
    helpers.add_member(db, project, member, "member")
    member_headers = helpers.login(client, member)

    response = client.post(
        f"{_url(project, document, version)}/analyze", headers=member_headers
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_227_outsider_cannot_analyze(client: TestClient, db: Session, provider):
    """非成员 → 403 `NOT_PROJECT_ADMIN`。

    **与既有 `create_link` 同一口径**：写接口统一用
    `ensure_writable_admin`，非成员与角色不符**都是** `NOT_PROJECT_ADMIN`
    ——区分会泄露项目是否存在（见 `app/common/permissions.py` 的注释）。
    """
    admin, project, document, version, rows = _chain(db)
    outsider = helpers.make_user(db)
    outsider_headers = helpers.login(client, outsider)

    response = client.post(
        f"{_url(project, document, version)}/analyze", headers=outsider_headers
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_227_archived_project_returns_409(client: TestClient, db: Session, provider):
    """归档项目 → 409 `PROJECT_ARCHIVED`。"""
    admin, project, document, version, rows = _chain(db, project_status="archived")
    headers = helpers.login(client, admin)

    response = client.post(
        f"{_url(project, document, version)}/analyze", headers=headers
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROJECT_ARCHIVED"


# ------------------------------------------------------------ 审计与留痕


def test_ac_220_analyze_writes_audit(client: TestClient, db: Session, provider):
    """AI 分析写 `document.chapter_link.analyze` 审计，带项目与操作者。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    assert client.post(
        f"{_url(project, document, version)}/analyze", headers=headers
    ).status_code == 200

    log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "document.chapter_link.analyze",
            AuditLog.project_id == project.id,
        )
    )
    assert log is not None
    assert log.actor_id == admin.id
    assert log.target_type == "document_chapter_link"
    assert log.after_data["version_id"] == version.id


def test_ac_220_analyze_writes_run_log(client: TestClient, db: Session, provider):
    """AI 分析写模型运行留痕（`task_type='chapter_link_analyze'`）。

    真实模型调用耗时且可能失败，没留痕就无法排查。
    """
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    assert client.post(
        f"{_url(project, document, version)}/analyze", headers=headers
    ).status_code == 200

    log = db.scalar(
        select(LLMRunLog).where(
            LLMRunLog.task_type == "chapter_link_analyze",
            LLMRunLog.project_id == project.id,
        )
    )
    assert log is not None
    assert log.status == "succeeded"
    assert log.call_count >= 1
    assert log.provider_name == "mock"


def test_ac_220_analyze_failure_writes_failed_run_log(
    client: TestClient, db: Session, provider
):
    """分析失败 → 502 `LLM_CALL_FAILED`，且留痕记为 failed。"""
    admin, project, document, version, rows = _chain(db)
    headers = helpers.login(client, admin)

    # 让模型返回坏 JSON（整篇路径 → 根结构校验失败 → 502）
    provider.queue.append("这不是 JSON")

    response = client.post(
        f"{_url(project, document, version)}/analyze", headers=headers
    )

    assert response.status_code == 502, response.text
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"

    log = db.scalar(
        select(LLMRunLog).where(
            LLMRunLog.task_type == "chapter_link_analyze",
            LLMRunLog.project_id == project.id,
        )
    )
    assert log is not None
    assert log.status == "failed"
    assert log.error_code == "LLM_OUTPUT_INVALID"
