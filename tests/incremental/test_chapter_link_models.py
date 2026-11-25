"""章节引用图模型层（12-chapter-link-ai T129 / AC-224）。

验证 `document_chapter_links.source` 扩 `'ai'` 后的数据库层保障：
`source='ai'` 可写、非法值仍被 CHECK 拒（3819）、目标二选一的 CHECK 仍生效。
"""

import pytest
from decimal import Decimal
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.chapter_link import DocumentChapterLink
from tests.incremental import helpers


def _chain(db: Session):
    """造一条章节引用边所需的完整外键链。"""
    admin = helpers.make_user(db)
    project = helpers.make_project(db)
    helpers.add_member(db, project, admin, "project_admin")
    document, version, rows = helpers.make_document_version(
        db, project, admin, chapters=[("1 概述", "总览"), ("2 登录", "登录流程")]
    )
    return admin, version, rows


def _link(db: Session, version, rows, admin, *, source: str, **overrides) -> DocumentChapterLink:
    """插入一条边（不 commit，交由 db 夹具回滚）。"""
    params = {
        "version_id": version.id,
        "from_chapter_id": rows[0].id,
        "to_chapter_id": rows[1].id,
        "link_type": "references",
        "entity": None,
        "confidence": None,
        "source": source,
        "created_by": admin.id,
    }
    params.update(overrides)
    link = DocumentChapterLink(**params)
    db.add(link)
    db.flush()
    return link


def test_source_ai_is_accepted(db: Session):
    """`source='ai'` 可写入（0026 扩了 ck_chlinks_source）。"""
    admin, version, rows = _chain(db)

    link = _link(db, version, rows, admin, source="ai")

    assert link.id is not None
    assert link.source == "ai"


def test_source_rule_and_manual_still_accepted(db: Session):
    """既有 `rule` / `manual` 不受影响。

    注意：`uk_chlinks_to_chapter` 唯一键不含 `source`，同源同类型同目标
    的两条边（无论来源）不能共存——所以这里用不同 `link_type` 区分。
    """
    admin, version, rows = _chain(db)

    assert _link(db, version, rows, admin, source="rule", link_type="references").source == "rule"
    assert _link(db, version, rows, admin, source="manual", link_type="depends_on").source == "manual"


def test_unknown_source_rejected(db: Session):
    """扩枚举不是放开口子：非法 source 仍被 CHECK 拒（3819）。"""
    admin, version, rows = _chain(db)

    with pytest.raises(OperationalError) as exc:
        _link(db, version, rows, admin, source="bogus")
    assert exc.value.orig.args[0] == 3819
    assert "ck_chlinks_source" in str(exc.value.orig.args[1])
    db.rollback()


def test_target_check_still_enforced(db: Session):
    """`ck_chlinks_target` 二选一仍生效：同时给 to_chapter_id 与 entity 被拒。"""
    admin, version, rows = _chain(db)

    with pytest.raises(OperationalError) as exc:
        _link(db, version, rows, admin, source="ai", entity="退款")
    assert exc.value.orig.args[0] == 3819
    assert "ck_chlinks_target" in str(exc.value.orig.args[1])
    db.rollback()


def test_ai_edge_can_carry_confidence(db: Session):
    """AI 边可带置信度（人工边是 NULL，AI 边是模型给的值）。"""
    admin, version, rows = _chain(db)

    link = _link(db, version, rows, admin, source="ai", confidence=Decimal("0.85"))

    assert link.confidence == Decimal("0.85")
