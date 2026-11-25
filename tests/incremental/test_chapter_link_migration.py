"""迁移 `0026` 的数据库层断言（12-chapter-link-ai T129 / AC-224）。

覆盖：`document_chapter_links.source` 的 CHECK 真的扩了 `'ai'`（不是只写在 ORM
元数据里）；迁移 head 是 `0026`。

`0026 → 0025 → 0026` 的往返不在这里跑——迁移在独立事务里执行，与 `db` 夹具的
嵌套事务会互相干扰；往返由 T129 的验证命令在两库上实跑。
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.common.db import get_engine


@pytest.fixture(scope="module")
def engine() -> Engine:
    """只读用的引擎：结构断言不写入，也不吃 `db` 夹具的事务。"""
    return get_engine()


def test_ac_224_source_check_extended(engine: Engine):
    """`ck_chlinks_source` 的 CHECK 扩了 `'ai'`（真的落到库里）。"""
    checks = {
        item["name"]: str(item["sqltext"]).lower()
        for item in inspect(engine).get_check_constraints("document_chapter_links")
    }
    assert "ck_chlinks_source" in checks
    assert "'ai'" in checks["ck_chlinks_source"]


def test_ac_224_source_check_keeps_rule_and_manual(engine: Engine):
    """扩枚举不是重写：`'rule'` / `'manual'` 仍在 CHECK 里。"""
    checks = {
        item["name"]: str(item["sqltext"]).lower()
        for item in inspect(engine).get_check_constraints("document_chapter_links")
    }
    sqltext = checks["ck_chlinks_source"]
    assert "'rule'" in sqltext
    assert "'manual'" in sqltext


def test_migration_head_is_0026(db: Session):
    """迁移 head 是 `0026`。"""
    row = db.execute(text("SELECT version_num FROM alembic_version")).first()
    assert row is not None
    assert row[0] == "0026"


def test_chapter_links_table_has_no_new_column(engine: Engine):
    """表结构零改动：`document_chapter_links` 的列集合不变（只扩 CHECK）。"""
    columns = {item["name"] for item in inspect(engine).get_columns("document_chapter_links")}
    assert columns == {
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
    }
