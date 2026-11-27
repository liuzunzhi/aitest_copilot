"""12.5 期 · 待评审落库与采纳服务层（T139 / AC-229 / AC-230 / AC-232）。

本文件**不经 HTTP**，直接调 `app.incremental.links` 的服务层函数——
接口层（参数校验、权限顺序、响应形状）由 T140 的
`test_chapter_link_review_api.py` 覆盖。

覆盖：

- AI 分析产出的边落库为 `status='pending'`，并带上 `rationale`；
- 人工补链 / 规则重抽的边默认 `approved`（天然已生效，不需要评审）；
- 采纳幂等（重复采纳不报错、不重复写审计）；
- 批量采纳整批原子（缺一个 id 就整批失败）；
- 重新分析**不冲掉已采纳的边**（AC-232）。
"""

import json
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.errors import ChapterLinkNotFound, InvalidChapterLink
from app.incremental import links as links_service
from app.llm.mock import MockProvider
from app.models.chapter_link import DocumentChapterLink
from app.models.document import DocumentVersion
from app.models.system import AuditLog
from tests.incremental import helpers

CHAPTERS = [
    ("1 概述", "总体说明，详见第 2 章。"),
    ("2 登录", "账号密码登录。"),
    ("3 支付", "支付回调说明。"),
]


def _chain(db: Session, *, project_status: str = "active"):
    """项目 + 管理员 + 文档版本（三个章节）。"""
    admin = helpers.make_user(db)
    project = helpers.make_project(db, status=project_status)
    helpers.add_member(db, project, admin, "project_admin")
    document, version, rows = helpers.make_document_version(
        db, project, admin, chapters=CHAPTERS
    )
    return admin, project, document, version, rows


def _ref(from_id: int, to_id: int, **overrides) -> dict:
    item = {
        "from_chapter_id": from_id,
        "to_chapter_id": to_id,
        "link_type": "references",
        "confidence": 0.9,
        "rationale": "1 节正文里提到「详见第 2 章」",
    }
    item.update(overrides)
    return item


def _analyze(db: Session, admin, project, document, version, *refs) -> dict:
    """跑一次 AI 分析（整篇路径：小文档只调 1 次模型）。"""
    provider = MockProvider(
        queue=[json.dumps({"references": list(refs)}, ensure_ascii=False)]
    )
    return links_service.analyze_links(
        db,
        project_id=project.id,
        document_id=document.id,
        version_id=version.id,
        actor=admin,
        provider=provider,
    )


def _rows(db: Session, version, **filters) -> list[DocumentChapterLink]:
    stmt = select(DocumentChapterLink).where(
        DocumentChapterLink.version_id == version.id
    )
    for key, value in filters.items():
        stmt = stmt.where(getattr(DocumentChapterLink, key) == value)
    return list(db.scalars(stmt.order_by(DocumentChapterLink.id)).all())


def _approve(db: Session, admin, project, document, version, link_id: int):
    return links_service.approve_link(
        db,
        project_id=project.id,
        document_id=document.id,
        version_id=version.id,
        actor=admin,
        link_id=link_id,
    )


def _approve_batch(db: Session, admin, project, document, version, link_ids: list[int]):
    return links_service.approve_links_batch(
        db,
        project_id=project.id,
        document_id=document.id,
        version_id=version.id,
        actor=admin,
        link_ids=link_ids,
    )


# ------------------------------------------------------------ 落库即待评审


def test_ac_229_analyze_persists_edges_as_pending(db: Session):
    """AI 分析 → 边落库 `status='pending'`，`rationale` / `confidence` 都有值。"""
    admin, project, document, version, rows = _chain(db)

    result = _analyze(db, admin, project, document, version, _ref(rows[0].id, rows[1].id))

    assert result["analyzed_count"] == 1
    ai_rows = _rows(db, version, source="ai")
    assert len(ai_rows) == 1
    assert ai_rows[0].status == "pending"
    assert ai_rows[0].rationale == "1 节正文里提到「详见第 2 章」"
    assert float(ai_rows[0].confidence) == pytest.approx(0.9)
    # 响应里的每条边也带 status / rationale（前端要按状态分区）
    assert result["links"][0]["status"] == "pending"
    assert result["links"][0]["rationale"] == "1 节正文里提到「详见第 2 章」"


def test_ac_229_manual_link_is_approved(db: Session):
    """人工补链的边**天然已生效**，不需要评审。"""
    admin, project, document, version, rows = _chain(db)

    link = links_service.create_link(
        db,
        project_id=project.id,
        document_id=document.id,
        version_id=version.id,
        actor=admin,
        from_chapter_id=rows[0].id,
        link_type="references",
        to_chapter_id=rows[1].id,
        entity=None,
    )

    assert link.status == "approved"
    assert link.rationale is None


def test_ac_229_rule_link_is_approved(db: Session):
    """规则重抽的边**天然已生效**，不进 AI 评审流程。"""
    admin, project, document, version, rows = _chain(db)

    created = links_service.extract_links(
        db,
        project_id=project.id,
        document_id=document.id,
        version_id=version.id,
        actor=admin,
    )

    assert created, "第一章正文含「详见第 2 章」，规则抽取应命中"
    assert all(row.status == "approved" for row in created)
    assert all(row.source == "rule" for row in created)


def test_ac_229_ai_edge_skips_existing_manual_edge(db: Session):
    """AI 边命中人工边同一条 → 跳过（不撞唯一键，也不重复建）。

    唯一键 `uk_chlinks_to_chapter` 不含 `source` / `status`，
    所以「已存在的边」不论来源都要跳过。
    """
    admin, project, document, version, rows = _chain(db)
    links_service.create_link(
        db,
        project_id=project.id,
        document_id=document.id,
        version_id=version.id,
        actor=admin,
        from_chapter_id=rows[0].id,
        link_type="references",
        to_chapter_id=rows[1].id,
        entity=None,
    )

    _analyze(db, admin, project, document, version, _ref(rows[0].id, rows[1].id))

    assert _rows(db, version, source="ai") == []
    assert len(_rows(db, version, source="manual")) == 1


# ------------------------------------------------------------ 采纳


def test_ac_230_approve_marks_link_approved(db: Session):
    """采纳 → `status='approved'`，并写一条 `document.chapter_link.approve` 审计。"""
    admin, project, document, version, rows = _chain(db)
    _analyze(db, admin, project, document, version, _ref(rows[0].id, rows[1].id))
    link = _rows(db, version, source="ai")[0]

    approved = _approve(db, admin, project, document, version, link.id)

    assert approved.status == "approved"
    assert _rows(db, version, id=link.id)[0].status == "approved"

    log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "document.chapter_link.approve",
            AuditLog.project_id == project.id,
        )
    )
    assert log is not None
    assert log.after_data["status"] == "approved"
    assert log.after_data["link_ids"] == [link.id]
    assert log.before_data["status"] == "pending"


def test_ac_230_approve_is_idempotent(db: Session):
    """重复采纳：返回 200 语义（不抛错），且**不重复写审计**。"""
    admin, project, document, version, rows = _chain(db)
    _analyze(db, admin, project, document, version, _ref(rows[0].id, rows[1].id))
    link = _rows(db, version, source="ai")[0]

    _approve(db, admin, project, document, version, link.id)
    again = _approve(db, admin, project, document, version, link.id)

    assert again.status == "approved"
    logs = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.action == "document.chapter_link.approve",
                AuditLog.project_id == project.id,
            )
        ).all()
    )
    assert len(logs) == 1, "状态没变就不该再写一条「采纳」审计"


def test_ac_230_approve_missing_link_returns_404(db: Session):
    """采纳不存在的边 → 404 `CHAPTER_LINK_NOT_FOUND`。"""
    admin, project, document, version, rows = _chain(db)

    with pytest.raises(ChapterLinkNotFound) as exc:
        _approve(db, admin, project, document, version, 999999)
    assert exc.value.code == "CHAPTER_LINK_NOT_FOUND"


def test_ac_230_approve_cross_version_returns_404(db: Session):
    """跨版本采纳 → 404（必须校验边归属该版本）。

    **必须是同一个文档下的第二个版本**：`make_document_version` 会新建文档，
    那样会先撞 `DOCUMENT_VERSION_NOT_FOUND`，测不到「边不属于该版本」这条线。
    """
    admin, project, document, version, rows = _chain(db)
    _analyze(db, admin, project, document, version, _ref(rows[0].id, rows[1].id))
    link = _rows(db, version, source="ai")[0]

    other_version = DocumentVersion(
        document_id=document.id,
        version_no=2,
        # `uk_versions_active` 保证一个文档只有一个 active 版本，这里用 pending
        status="pending",
        file_name=f"{document.name}.md",
        file_path=f"var/uploads/{project.id}/other.md",
        file_size=64,
        sha256="b" * 64,
        chapter_count=0,
        uploaded_by=admin.id,
    )
    db.add(other_version)
    db.flush()

    with pytest.raises(ChapterLinkNotFound):
        links_service.approve_link(
            db,
            project_id=project.id,
            document_id=document.id,
            version_id=other_version.id,
            actor=admin,
            link_id=link.id,
        )
    # 原边没被动过
    assert _rows(db, version, id=link.id)[0].status == "pending"


def test_ac_230_approve_batch_marks_all_approved(db: Session):
    """批量采纳 → 全部 `approved`，返回条数，写一条审计。"""
    admin, project, document, version, rows = _chain(db)
    _analyze(
        db,
        admin,
        project,
        document,
        version,
        _ref(rows[0].id, rows[1].id),
        _ref(rows[1].id, rows[2].id),
    )
    link_ids = [row.id for row in _rows(db, version, source="ai")]
    assert len(link_ids) == 2

    approved_count = _approve_batch(db, admin, project, document, version, link_ids)

    assert approved_count == 2
    assert all(row.status == "approved" for row in _rows(db, version, source="ai"))
    log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "document.chapter_link.approve",
            AuditLog.project_id == project.id,
        )
    )
    assert log is not None
    assert log.after_data["approved_count"] == 2
    assert log.after_data["link_ids"] == sorted(link_ids)


def test_ac_230_approve_batch_is_atomic_on_missing_id(db: Session):
    """批量里有一个 id 不存在 → **整批失败**，一条都不改。"""
    admin, project, document, version, rows = _chain(db)
    _analyze(
        db,
        admin,
        project,
        document,
        version,
        _ref(rows[0].id, rows[1].id),
        _ref(rows[1].id, rows[2].id),
    )
    link_ids = [row.id for row in _rows(db, version, source="ai")]

    with pytest.raises(ChapterLinkNotFound):
        _approve_batch(db, admin, project, document, version, [*link_ids, 999999])

    db.rollback()
    assert all(row.status == "pending" for row in _rows(db, version, source="ai"))


def test_ac_230_approve_batch_empty_raises_400(db: Session):
    """空数组 → 400 `INVALID_CHAPTER_LINK`（复用既有错误码，零新增）。"""
    admin, project, document, version, rows = _chain(db)

    with pytest.raises(InvalidChapterLink) as exc:
        _approve_batch(db, admin, project, document, version, [])
    assert exc.value.code == "INVALID_CHAPTER_LINK"


def test_ac_230_approve_batch_idempotent_counts_all(db: Session):
    """重复批量采纳：返回仍为全部条数，但不重复写审计。"""
    admin, project, document, version, rows = _chain(db)
    _analyze(
        db,
        admin,
        project,
        document,
        version,
        _ref(rows[0].id, rows[1].id),
        _ref(rows[1].id, rows[2].id),
    )
    link_ids = [row.id for row in _rows(db, version, source="ai")]

    assert _approve_batch(db, admin, project, document, version, link_ids) == 2
    assert _approve_batch(db, admin, project, document, version, link_ids) == 2

    logs = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.action == "document.chapter_link.approve",
                AuditLog.project_id == project.id,
            )
        ).all()
    )
    assert len(logs) == 1


# ------------------------------------------------------------ AC-232 重分析


def test_ac_232_reanalyze_keeps_approved_edges(db: Session):
    """分析 → 采纳 1 条 → 重新分析：已采纳的**仍是 approved**，不重复插入。

    这条是「人工评审不被重跑冲掉」的保证。
    """
    admin, project, document, version, rows = _chain(db)
    _analyze(db, admin, project, document, version, _ref(rows[0].id, rows[1].id))
    first = _rows(db, version, source="ai")[0]
    _approve(db, admin, project, document, version, first.id)

    # 重新分析，模型给出同一条 + 一条新的
    _analyze(
        db,
        admin,
        project,
        document,
        version,
        _ref(rows[0].id, rows[1].id),
        _ref(rows[1].id, rows[2].id),
    )

    ai_rows = _rows(db, version, source="ai")
    # 旧的已采纳那条原样保留（id 不变、状态不变）
    kept = [row for row in ai_rows if row.id == first.id]
    assert len(kept) == 1
    assert kept[0].status == "approved"
    # 新的一条以 pending 落库
    new_rows = [row for row in ai_rows if row.id != first.id]
    assert len(new_rows) == 1
    assert new_rows[0].status == "pending"
    assert (new_rows[0].from_chapter_id, new_rows[0].to_chapter_id) == (
        rows[1].id,
        rows[2].id,
    )


def test_ac_232_reanalyze_replaces_unapproved_pending(db: Session):
    """重新分析会**替换**上一轮没采纳的待评审边（不累加）。"""
    admin, project, document, version, rows = _chain(db)
    _analyze(db, admin, project, document, version, _ref(rows[0].id, rows[1].id))
    assert len(_rows(db, version, source="ai")) == 1

    # 第二轮换一条不同的边
    _analyze(db, admin, project, document, version, _ref(rows[1].id, rows[2].id))

    ai_rows = _rows(db, version, source="ai")
    assert len(ai_rows) == 1
    assert (ai_rows[0].from_chapter_id, ai_rows[0].to_chapter_id) == (
        rows[1].id,
        rows[2].id,
    )
    assert ai_rows[0].status == "pending"
