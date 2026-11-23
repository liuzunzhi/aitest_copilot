"""流程基线四张表的模型层校验（10-process-baseline T117 / AC-197）。

钉住数据库层保障：四表可写入、默认值正确、CHECK / 唯一键 / 级联删除生效、
`process_baseline_links.target_id` **不建外键**（04 物理删功能不能变 500）、
以及**两套基线的版本号互不干扰**。
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.baseline import BaselineRevision
from app.models.process_baseline import (
    ProcessBaseline,
    ProcessBaselineLink,
    ProcessBaselineRevision,
    ProcessBaselineStep,
)
from app.models.project import Project
from app.models.user import User


def _user(db: Session) -> User:
    user = User(username=f"pb-{uuid.uuid4().hex[:10]}", password_hash="x" * 60)
    db.add(user)
    db.flush()
    return user


def _chain(db: Session) -> dict:
    user = _user(db)
    project = Project(name=f"流程基线项目-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    return {"user": user, "project": project}


def _scenario(db: Session, chain: dict, **overrides) -> ProcessBaseline:
    payload = {
        "project_id": chain["project"].id,
        "name": "扫码登录连续失败 5 次后锁定",
        "description": "账号已存在且未锁定时，连续输错密码达阈值后账号被锁定",
        "precondition": "账号已注册且处于未锁定状态",
        "source_type": "manual",
        "created_by": chain["user"].id,
    }
    payload.update(overrides)
    row = ProcessBaseline(**payload)
    db.add(row)
    db.flush()
    return row


def _step(db: Session, scenario: ProcessBaseline, **overrides) -> ProcessBaselineStep:
    payload = {
        "baseline_id": scenario.id,
        "step_no": 1,
        "action": "打开登录页并选择「扫码登录」",
        "expected": "展示扫码二维码",
    }
    payload.update(overrides)
    row = ProcessBaselineStep(**payload)
    db.add(row)
    db.flush()
    return row


def _link(db: Session, scenario: ProcessBaseline, **overrides) -> ProcessBaselineLink:
    payload = {
        "baseline_id": scenario.id,
        "target_type": "function",
        "target_id": 10096,
        "target_name": "用户扫码登录",
    }
    payload.update(overrides)
    row = ProcessBaselineLink(**payload)
    db.add(row)
    db.flush()
    return row


# --------------------------------------------------------------- 场景行


def test_ac_197_scenario_is_writable(db: Session):
    """场景行可写入，默认值与 spec §4.1 一致。"""
    chain = _chain(db)
    scenario = _scenario(db, chain)

    assert scenario.id is not None
    assert scenario.source_type == "manual"
    assert scenario.status == "active"
    # 场景自身的修订次数从 1 起
    assert scenario.version_no == 1
    # 手工添加：六列来源追溯字段全为 NULL（PRD：手工添加不做追溯要求）
    assert scenario.source_document_id is None
    assert scenario.source_version_id is None
    assert scenario.source_chapter_id is None
    assert scenario.source_chapter_title is None
    assert scenario.source_method is None
    assert scenario.source_analysis_id is None


def test_ac_197_scenario_rejects_unknown_source_type(db: Session):
    """CHECK 真的在拦非法来源值（不是只写在 ORM 元数据里）。"""
    chain = _chain(db)
    db.add(
        ProcessBaseline(
            project_id=chain["project"].id,
            name="非法来源场景",
            source_type="incremental_new",
            created_by=chain["user"].id,
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_pbaselines_source" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_197_scenario_rejects_unknown_status(db: Session):
    """非法状态被 CHECK 拒绝。"""
    chain = _chain(db)
    db.add(
        ProcessBaseline(
            project_id=chain["project"].id,
            name="非法状态场景",
            status="deleted",
            created_by=chain["user"].id,
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_pbaselines_status" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_197_scenario_name_unique_per_project(db: Session):
    """同项目同名只允许一条；不同项目可以各有一条。"""
    chain = _chain(db)
    _scenario(db, chain)

    db.add(
        ProcessBaseline(
            project_id=chain["project"].id,
            name="扫码登录连续失败 5 次后锁定",
            created_by=chain["user"].id,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# --------------------------------------------------------------- 步骤行


def test_ac_197_step_is_writable(db: Session):
    """步骤行可写入，默认值与 spec §4.2 一致。"""
    chain = _chain(db)
    scenario = _scenario(db, chain)
    step = _step(db, scenario)

    assert step.id is not None
    assert step.step_no == 1
    assert step.expected != ""


def test_ac_197_step_rejects_non_positive_step_no(db: Session):
    """`step_no >= 1` 的 CHECK 生效（序号从 1 起）。"""
    chain = _chain(db)
    scenario = _scenario(db, chain)
    db.add(
        ProcessBaselineStep(
            baseline_id=scenario.id,
            step_no=0,
            action="非法序号",
            expected="",
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_pbsteps_no_positive" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_197_step_no_unique_per_scenario(db: Session):
    """同场景同序号只允许一条。"""
    chain = _chain(db)
    scenario = _scenario(db, chain)
    _step(db, scenario, step_no=1)

    db.add(
        ProcessBaselineStep(
            baseline_id=scenario.id,
            step_no=1,
            action="重复序号",
            expected="",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ac_197_steps_are_cascade_deleted_with_scenario(db: Session):
    """删场景 → 步骤行被数据库级 CASCADE 清理，不留孤儿。"""
    chain = _chain(db)
    scenario = _scenario(db, chain)
    _step(db, scenario, step_no=1)
    _step(db, scenario, step_no=2)
    scenario_id = scenario.id

    db.delete(scenario)
    db.flush()

    remaining = db.scalars(
        select(ProcessBaselineStep).where(ProcessBaselineStep.baseline_id == scenario_id)
    ).all()
    assert remaining == []


# --------------------------------------------------------------- 关联行


def test_ac_197_link_is_writable(db: Session):
    """关联行可写入。"""
    chain = _chain(db)
    scenario = _scenario(db, chain)
    link = _link(db, scenario)

    assert link.id is not None
    assert link.target_type == "function"
    assert link.target_name == "用户扫码登录"


def test_ac_197_link_rejects_unknown_target_type(db: Session):
    """`target_type` 只接受功能 / 功能点。"""
    chain = _chain(db)
    scenario = _scenario(db, chain)
    db.add(
        ProcessBaselineLink(
            baseline_id=scenario.id,
            target_type="module",
            target_id=1,
            target_name="非法层级",
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_pblinks_target_type" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_197_link_target_has_no_foreign_key(db: Session):
    """**关联目标不建外键**——这是 04 物理删功能不变成 500 的前提。

    `target_id` 指向 `baseline_functions.id` / `baseline_feature_points.id`，
    但**不是外键**：04 的 `delete_function` 是物理删除，
    建了 FK 的话 04 的既有删除行为会直接 500（IntegrityError）。
    """
    from sqlalchemy import inspect

    from app.common.db import get_engine

    inspector = inspect(get_engine())
    fks = inspector.get_foreign_keys("process_baseline_links")
    referred = {
        column
        for fk in fks
        for column in fk.get("referred_table", "") and [fk["referred_table"]] or []
    }
    # 唯一的 FK 是 baseline_id → process_baselines.id（CASCADE）
    assert "baseline_functions" not in referred
    assert "baseline_feature_points" not in referred
    # baseline_id 确实有 FK
    assert "process_baselines" in referred


def test_ac_197_link_target_unique_per_scenario(db: Session):
    """同场景同目标只允许一条。"""
    chain = _chain(db)
    scenario = _scenario(db, chain)
    _link(db, scenario)

    db.add(
        ProcessBaselineLink(
            baseline_id=scenario.id,
            target_type="function",
            target_id=10096,
            target_name="用户扫码登录",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ac_197_links_are_cascade_deleted_with_scenario(db: Session):
    """删场景 → 关联行被 CASCADE 清理。"""
    chain = _chain(db)
    scenario = _scenario(db, chain)
    _link(db, scenario)
    scenario_id = scenario.id

    db.delete(scenario)
    db.flush()

    remaining = db.scalars(
        select(ProcessBaselineLink).where(ProcessBaselineLink.baseline_id == scenario_id)
    ).all()
    assert remaining == []


def test_ac_197_link_survives_target_deletion(db: Session):
    """04 物理删掉目标功能后，**链接行仍在**、名称快照仍可读。

    这是「不建外键 + 名称快照」这条设计的核心价值（spec §3.4）。
    """
    from app.models.baseline import BaselineFunction, BaselineModule

    chain = _chain(db)
    scenario = _scenario(db, chain)

    module = BaselineModule(
        project_id=chain["project"].id, name="登录模块", created_by=chain["user"].id
    )
    db.add(module)
    db.flush()
    function = BaselineFunction(
        project_id=chain["project"].id,
        module_id=module.id,
        name="用户扫码登录",
        created_by=chain["user"].id,
    )
    db.add(function)
    db.flush()

    _link(db, scenario, target_id=function.id, target_name=function.name)
    function_id = function.id

    # 04 的物理删除（`app/baselines/service.py:678` 的 delete_function 同一语义）
    db.delete(function)
    db.flush()

    links = db.scalars(
        select(ProcessBaselineLink).where(
            ProcessBaselineLink.baseline_id == scenario.id,
            ProcessBaselineLink.target_id == function_id,
        )
    ).all()
    assert len(links) == 1
    # 名称快照仍在——目标被删后仍能显示「原本关联的是谁」
    assert links[0].target_name == "用户扫码登录"


# ----------------------------------------------------------- 快照 / 审核


def test_ac_197_revision_is_writable(db: Session):
    """快照行可写入；提交态的 `version_no` 为 NULL。"""
    chain = _chain(db)
    revision = ProcessBaselineRevision(
        project_id=chain["project"].id,
        status="submitted",
        draft_snapshot='{"scenarios":[],"counts":{"scenarios":0,"steps":0,"links":0}}',
        scenario_count=0,
        step_count=0,
        link_count=0,
        submitted_by=chain["user"].id,
    )
    db.add(revision)
    db.flush()

    assert revision.id is not None
    assert revision.version_no is None
    assert revision.structure_json is None
    assert revision.scenario_count == 0


def test_ac_197_revision_rejects_unknown_status(db: Session):
    """快照状态只接受三种。"""
    chain = _chain(db)
    db.add(
        ProcessBaselineRevision(
            project_id=chain["project"].id,
            status="draft",
            submitted_by=chain["user"].id,
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_pbrevisions_status" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_197_version_no_unique_per_project(db: Session):
    """同项目同版本号只允许一份。"""
    chain = _chain(db)
    db.add(
        ProcessBaselineRevision(
            project_id=chain["project"].id,
            version_no=0,
            status="approved",
            submitted_by=chain["user"].id,
        )
    )
    db.flush()

    db.add(
        ProcessBaselineRevision(
            project_id=chain["project"].id,
            version_no=0,
            status="approved",
            submitted_by=chain["user"].id,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ac_197_multiple_null_version_no_allowed(db: Session):
    """多份「未分配版本号」的快照可以共存（MySQL 唯一索引允许多个 NULL）。

    这是「审核中 / 已驳回的记录不占版本号」的实现基础——
    没有它，项目里同时有两份待审快照就会撞唯一键。
    """
    chain = _chain(db)
    for _ in range(3):
        db.add(
            ProcessBaselineRevision(
                project_id=chain["project"].id,
                status="submitted",
                submitted_by=chain["user"].id,
            )
        )
        db.flush()

    count = db.scalar(
        select(func.count()).where(
            ProcessBaselineRevision.project_id == chain["project"].id
        )
    )
    assert count == 3


def test_ac_197_version_numbers_are_independent_between_baselines(db: Session):
    """**两套基线的版本号互不干扰**（AC-197 的核心断言）。

    功能基线发 `v1.0` 之后，流程基线**仍然发 `v1.0`**——
    两套快照分表存储，不抢同一个版本号序列。
    """
    chain = _chain(db)

    # 功能基线发 v1.0（04 的表，本期零改动）
    baseline_rev = BaselineRevision(
        project_id=chain["project"].id, status="approved", version_no=0
    )
    db.add(baseline_rev)
    db.flush()

    # 流程基线发 v1.0——**没有被功能基线挤走**
    process_rev = ProcessBaselineRevision(
        project_id=chain["project"].id,
        version_no=0,
        status="approved",
        submitted_by=chain["user"].id,
    )
    db.add(process_rev)
    db.flush()

    assert baseline_rev.version_no == 0
    assert process_rev.version_no == 0

    # 再各发一份，两边都递增到 1，互不影响
    db.add(
        BaselineRevision(
            project_id=chain["project"].id, status="approved", version_no=1
        )
    )
    db.add(
        ProcessBaselineRevision(
            project_id=chain["project"].id,
            version_no=1,
            status="approved",
            submitted_by=chain["user"].id,
        )
    )
    db.flush()

    assert db.scalar(
        select(func.count()).where(
            BaselineRevision.project_id == chain["project"].id,
            BaselineRevision.version_no == 1,
        )
    ) == 1
    assert db.scalar(
        select(func.count()).where(
            ProcessBaselineRevision.project_id == chain["project"].id,
            ProcessBaselineRevision.version_no == 1,
        )
    ) == 1


# --------------------------------------------------------------- 元数据


def test_ac_197_metadata_uses_mysql_engine():
    """四表都是 InnoDB + utf8mb4（迁移里显式声明，不靠服务器默认值）。"""
    for model in (
        ProcessBaseline,
        ProcessBaselineStep,
        ProcessBaselineLink,
        ProcessBaselineRevision,
    ):
        opts = model.__table__.dialect_kwargs
        assert opts["mysql_engine"] == "InnoDB"
        assert opts["mysql_default_charset"] == "utf8mb4"


def test_ac_197_models_are_not_collected_by_pytest():
    """四个模型都写了 `__test__ = False`。

    pytest 会把 `Test*` 开头的类当成测试类收集——
    `ProcessBaseline*` 不撞这个规则，但统一加上更省心
    （08 的 `TestCase*`、09 的 `Automation*` 都有先例）。
    """
    for model in (
        ProcessBaseline,
        ProcessBaselineStep,
        ProcessBaselineLink,
        ProcessBaselineRevision,
    ):
        assert model.__test__ is False
