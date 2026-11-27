"""迁移 `0028` 的数据库层断言（12.5-chapter-link-review T137 / AC-229）。

覆盖：`document_chapter_links` 加了两列（`status` / `rationale`）、
`ck_chlinks_status` 的 CHECK 只有 `pending` / `approved` 两个值、
存量行回填 `'approved'`、迁移 head 是 `0028`。

`0028 → 0027 → 0028` 的往返不在这里跑——迁移在独立事务里执行，
与 `db` 夹具的嵌套事务会互相干扰；往返由 T137 的验证命令在两库上实跑。
"""

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.common.db import get_engine
from app.models.chapter_link import DocumentChapterLink


@pytest.fixture(scope="module")
def engine() -> Engine:
    """只读用的引擎：结构断言不写入，也不吃 `db` 夹具的事务。"""
    return get_engine()


def _checks(engine: Engine) -> dict[str, str]:
    return {
        item["name"]: str(item["sqltext"]).lower()
        for item in inspect(engine).get_check_constraints("document_chapter_links")
    }


def _columns(engine: Engine) -> dict[str, dict]:
    return {item["name"]: item for item in inspect(engine).get_columns("document_chapter_links")}


def test_ac_229_status_check_has_only_two_values(engine: Engine):
    """`ck_chlinks_status` 只允许 `pending` / `approved`，**没有** `rejected`。

    用户原话「错的直接删除」——不做 `rejected` 态（删除会写审计，历史可追）。
    """
    checks = _checks(engine)
    assert "ck_chlinks_status" in checks
    sqltext = checks["ck_chlinks_status"]
    assert "'pending'" in sqltext
    assert "'approved'" in sqltext
    assert "'rejected'" not in sqltext


def test_ac_229_status_column_exists_and_not_nullable(engine: Engine):
    """`status` 列存在、非空、默认 `'approved'`。"""
    columns = _columns(engine)
    assert "status" in columns
    assert columns["status"]["nullable"] is False
    default = columns["status"].get("default")
    assert default is not None
    assert "'approved'" in str(default)


def test_ac_229_rationale_column_exists_and_nullable(engine: Engine):
    """`rationale` 列存在、可空、长度 1000。"""
    columns = _columns(engine)
    assert "rationale" in columns
    assert columns["rationale"]["nullable"] is True
    # 长度对齐 incremental_conclusions.rationale / test_points 的 1000
    assert "1000" in str(columns["rationale"]["type"])


def test_ac_229_table_has_exactly_12_columns(engine: Engine):
    """表结构 = 10 列 + 本期新增 2 列（`status` / `rationale`）。"""
    columns = _columns(engine)
    assert set(columns) == {
        "id",
        "version_id",
        "from_chapter_id",
        "to_chapter_id",
        "link_type",
        "entity",
        "confidence",
        "source",
        "created_by",
        "created_at",
        "status",
        "rationale",
    }


def test_ac_229_legacy_rows_backfilled_as_approved(db: Session):
    """存量行（任何来源）迁移后 `status` 回填 `'approved'`，**不是** `pending`。

    12 期已落库的 AI 边、05 期的规则边与人工边都已经是生效边，
    不该因为加了一列就倒退成「待评审」。
    """
    # 直接写一条不带 status 的边（走 server_default），模拟「存量行」。
    from tests.incremental import helpers

    admin = helpers.make_user(db)
    project = helpers.make_project(db)
    helpers.add_member(db, project, admin, "project_admin")
    document, version, rows = helpers.make_document_version(
        db, project, admin, chapters=[("1 概述", "总览"), ("2 登录", "登录流程")]
    )
    link = DocumentChapterLink(
        version_id=version.id,
        from_chapter_id=rows[0].id,
        to_chapter_id=rows[1].id,
        link_type="references",
        entity=None,
        confidence=None,
        source="ai",
        created_by=admin.id,
    )
    db.add(link)
    db.flush()

    # server_default 把 status 填成 approved
    assert link.status == "approved"
    assert link.rationale is None


def test_ac_229_status_unknown_value_rejected(db: Session):
    """`ck_chlinks_status` 会拒绝非法值（3819），不是「只写 ORM 不管库」。"""
    import pytest as _pytest
    from sqlalchemy.exc import OperationalError

    from tests.incremental import helpers

    admin = helpers.make_user(db)
    project = helpers.make_project(db)
    helpers.add_member(db, project, admin, "project_admin")
    document, version, rows = helpers.make_document_version(
        db, project, admin, chapters=[("1 概述", "总览"), ("2 登录", "登录流程")]
    )
    link = DocumentChapterLink(
        version_id=version.id,
        from_chapter_id=rows[0].id,
        to_chapter_id=rows[1].id,
        link_type="references",
        entity=None,
        source="manual",
        status="rejected",  # 非法值
        created_by=admin.id,
    )
    db.add(link)
    with _pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_chlinks_status" in str(exc.value.orig.args[1])
    db.rollback()


def test_migration_head_is_0028(db: Session):
    """迁移 head 是 `0028`（0026 数据层 + 0027 模板层 + 0028 评审状态层）。"""
    row = db.execute(text("SELECT version_num FROM alembic_version")).first()
    assert row is not None
    assert row[0] == "0028"
