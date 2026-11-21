"""自动化执行三张表的模型层校验（09-automation T111 / AC-159 之后的 09 期 AC）。

钉住数据库层保障：三表可写入、默认值正确、CHECK / 唯一键 / 级联删除生效、
`linked_case_id` **不建外键**（08 物理删除不能变 500）。
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.automation import AutomationAsset, AutomationRun, AutomationRunItem
from app.models.project import Project
from app.models.user import User


def _user(db: Session) -> User:
    user = User(username=f"auto-{uuid.uuid4().hex[:10]}", password_hash="x" * 60)
    db.add(user)
    db.flush()
    return user


def _chain(db: Session) -> dict:
    user = _user(db)
    project = Project(name=f"自动化项目-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    return {"user": user, "project": project}


def _asset(db: Session, chain: dict, **overrides) -> AutomationAsset:
    payload = {
        "project_id": chain["project"].id,
        "name": "test_login.py",
        "file_path": "web-tests/test_login.py",
        "framework": "pytest",
        "parse_confidence": 0.95,
        "detected_cases": 3,
        "created_by": chain["user"].id,
    }
    payload.update(overrides)
    asset = AutomationAsset(**payload)
    db.add(asset)
    db.flush()
    return asset


def _run(db: Session, chain: dict, **overrides) -> AutomationRun:
    payload = {
        "project_id": chain["project"].id,
        "framework": "pytest",
        "status": "running",
        "created_by": chain["user"].id,
    }
    payload.update(overrides)
    run = AutomationRun(**payload)
    db.add(run)
    db.flush()
    return run


def test_ac_181_asset_is_writable(db: Session):
    """资产行可写入，默认值与 spec §4.1 一致。"""
    chain = _chain(db)
    asset = _asset(db, chain)

    assert asset.id is not None
    assert asset.source == "scanned"
    assert asset.status == "active"
    assert asset.linked_case_id is None


def test_ac_181_asset_rejects_unknown_framework(db: Session):
    """CHECK 真的在拦非法框架值（不是只写在 ORM 元数据里）。"""
    chain = _chain(db)
    db.add(
        AutomationAsset(
            project_id=chain["project"].id,
            name="x.py",
            file_path="x.py",
            framework="selenium",
            created_by=chain["user"].id,
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_autoassets_framework" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_181_asset_path_unique_per_project(db: Session):
    """同项目同路径只允许一条资产；不同项目可以各有一条。"""
    chain = _chain(db)
    _asset(db, chain)

    db.add(
        AutomationAsset(
            project_id=chain["project"].id,
            name="test_login.py",
            file_path="web-tests/test_login.py",
            framework="pytest",
            created_by=chain["user"].id,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    other = _chain(db)
    duplicate = _asset(db, other)
    assert duplicate.id is not None


def test_ac_181_asset_allows_playwright(db: Session):
    """Playwright 资产可入库（本期只读不执行，但允许扫描入库）。"""
    chain = _chain(db)
    asset = _asset(
        db,
        chain,
        name="login.spec.ts",
        file_path="web-tests/login.spec.ts",
        framework="playwright",
        parse_confidence=0.90,
        detected_cases=2,
    )
    assert asset.framework == "playwright"


def test_ac_181_run_is_writable(db: Session):
    """执行记录可写入。"""
    chain = _chain(db)
    run = _run(db, chain)

    assert run.id is not None
    assert run.status == "running"
    assert run.exit_code is None


def test_ac_181_run_rejects_unknown_status(db: Session):
    """执行状态只有三种。"""
    chain = _chain(db)
    db.add(
        AutomationRun(
            project_id=chain["project"].id,
            framework="pytest",
            status="bogus",
            created_by=chain["user"].id,
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_autoruns_status" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_181_run_item_is_writable(db: Session):
    """执行明细可写入，且 `case_title` 快照能存下来。"""
    chain = _chain(db)
    asset = _asset(db, chain)
    run = _run(db, chain)

    item = AutomationRunItem(
        project_id=chain["project"].id,
        run_id=run.id,
        asset_id=asset.id,
        linked_case_id=999,
        case_title="连续输错密码 5 次后账号锁定",
        result="passed",
        duration_ms=820,
    )
    db.add(item)
    db.flush()

    assert item.id is not None
    assert item.result == "passed"
    assert item.case_title == "连续输错密码 5 次后账号锁定"


def test_ac_181_run_item_rejects_unknown_result(db: Session):
    """明细结果只有三种。"""
    chain = _chain(db)
    asset = _asset(db, chain)
    run = _run(db, chain)

    db.add(
        AutomationRunItem(
            project_id=chain["project"].id,
            run_id=run.id,
            asset_id=asset.id,
            result="skipped_by_me",
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_autorunitems_result" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_181_run_item_unique_per_run_asset(db: Session):
    """一次执行里同一个资产只出现一行。"""
    chain = _chain(db)
    asset = _asset(db, chain)
    run = _run(db, chain)

    db.add(
        AutomationRunItem(
            project_id=chain["project"].id,
            run_id=run.id,
            asset_id=asset.id,
            result="passed",
        )
    )
    db.flush()

    db.add(
        AutomationRunItem(
            project_id=chain["project"].id,
            run_id=run.id,
            asset_id=asset.id,
            result="failed",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ac_181_linked_case_id_has_no_foreign_key(db: Session):
    """`linked_case_id` **不建外键**——08 的删用例是物理删除。

    建了 FK 的话，08 的 `delete_case` 会变成 500（IntegrityError）。
    这里直接塞一个不存在的用例 id，验证**能存进去**。
    """
    chain = _chain(db)
    asset = _asset(db, chain, linked_case_id=88888888)
    assert asset.linked_case_id == 88888888

    item = AutomationRunItem(
        project_id=chain["project"].id,
        run_id=_run(db, chain).id,
        asset_id=asset.id,
        linked_case_id=88888888,
        result="passed",
    )
    db.add(item)
    db.flush()
    assert item.linked_case_id == 88888888


def test_ac_181_run_items_cascade_on_run_delete(db: Session):
    """删执行记录 → 明细级联删除（数据库级 CASCADE）。"""
    chain = _chain(db)
    asset = _asset(db, chain)
    run = _run(db, chain)
    db.add(
        AutomationRunItem(
            project_id=chain["project"].id,
            run_id=run.id,
            asset_id=asset.id,
            result="passed",
        )
    )
    db.flush()

    db.delete(run)
    db.flush()

    remaining = db.scalars(
        select(AutomationRunItem).where(
            AutomationRunItem.run_id == run.id,
        )
    ).all()
    assert remaining == []


def test_ac_181_models_are_not_collected_as_tests():
    """三个模型类都要写 `__test__ = False`。

    `Automation*` 本身不撞 pytest 的 `Test*` 收集规则，但统一加上更省心
    （08 的 `TestCase*` 已有先例）。
    """
    for model in (AutomationAsset, AutomationRun, AutomationRunItem):
        assert model.__test__ is False


def test_ac_181_metadata_uses_mysql_engine():
    """三表都是 InnoDB + utf8mb4（迁移里显式声明，不靠服务器默认值）。"""
    for model in (AutomationAsset, AutomationRun, AutomationRunItem):
        opts = model.__table__.dialect_kwargs
        assert opts["mysql_engine"] == "InnoDB"
        assert opts["mysql_default_charset"] == "utf8mb4"
