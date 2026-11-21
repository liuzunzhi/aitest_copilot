"""测试用例三张表的模型层校验（08-test-case-analysis T105 / AC-159）。

钉住数据库层保障：三表可写入、默认值正确、CHECK / 唯一键 / 级联删除生效、
`test_point_id` 与 `test_point_analysis_id` **不建外键**（07 物理删除不能变 500）。
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.incremental import PromptTemplate
from app.models.project import Project
from app.models.test_case import TestCase, TestCaseAnalysis, TestCaseStep
from app.models.user import User


def _user(db: Session) -> User:
    user = User(username=f"tc-{uuid.uuid4().hex[:10]}", password_hash="x" * 60)
    db.add(user)
    db.flush()
    return user


def _chain(db: Session) -> dict:
    """用例只需要 用户 / 项目 / 模板——测试点与章节都是逻辑引用，不建外键。"""
    user = _user(db)
    project = Project(name=f"用例项目-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()

    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "test_case")
    )
    assert template is not None, "迁移 0023 应播种一条 test_case 模板"

    return {"user": user, "project": project, "template": template}


def _analysis(db: Session, chain: dict, *, status: str = "running") -> TestCaseAnalysis:
    analysis = TestCaseAnalysis(
        project_id=chain["project"].id,
        template_id=chain["template"].id,
        template_version=chain["template"].version_no,
        test_point_analysis_id=999,
        chapter_ids=[1, 2],
        status=status,
        created_by=chain["user"].id,
    )
    db.add(analysis)
    db.flush()
    return analysis


def _case(
    db: Session,
    chain: dict,
    analysis: TestCaseAnalysis | None = None,
    **overrides,
) -> TestCase:
    payload = {
        "project_id": chain["project"].id,
        "analysis_id": analysis.id if analysis is not None else None,
        "test_point_id": 10096,
        "test_point_name": "扫码登录连续失败 5 次后锁定",
        "title": "连续输错密码 5 次后账号锁定",
        "target_type": "function",
        "target_id": 10096,
        "target_name": "用户扫码登录",
        "created_by": chain["user"].id,
    }
    payload.update(overrides)
    case = TestCase(**payload)
    db.add(case)
    db.flush()
    return case


def _steps(db: Session, case: TestCase, actions: list[str]) -> list[TestCaseStep]:
    rows = [
        TestCaseStep(case_id=case.id, step_no=index, action=action, expected=f"{action}-预期")
        for index, action in enumerate(actions, start=1)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def test_ac_159_tables_are_registered():
    """三张表都进了 `Base.metadata`（Alembic / 测试共用同一份元数据）。"""
    from app.models import Base

    assert {
        "test_case_analyses",
        "test_cases",
        "test_case_steps",
    } <= set(Base.metadata.tables)


def test_ac_159_analysis_roundtrip(db: Session):
    """生成记录的默认值：`provider='mock'`、`status='pending'`、JSON 列可写。"""
    chain = _chain(db)
    analysis = _analysis(db, chain, status="pending")
    db.refresh(analysis)

    assert analysis.provider == "mock"
    assert analysis.status == "pending"
    assert analysis.chapter_ids == [1, 2]
    # 逻辑引用：批次记录来自 07，但不建外键
    assert analysis.test_point_analysis_id == 999
    assert analysis.created_at is not None


def test_ac_159_case_defaults_and_snapshot(db: Session):
    """用例默认值与落库快照：状态待评审、类型功能、优先级中、来源 llm。"""
    chain = _chain(db)
    analysis = _analysis(db, chain)
    case = _case(db, chain, analysis)
    db.refresh(case)

    assert case.status == "pending"
    assert case.case_type == "functional"
    assert case.priority == "medium"
    assert case.source_type == "llm"
    assert case.test_point_name == "扫码登录连续失败 5 次后锁定"
    assert case.target_name == "用户扫码登录"
    assert case.created_at is not None
    # MySQL 方言不渲染 ON UPDATE，updated_at 由服务层赋值——插入时至少有默认值
    assert case.updated_at is not None


def test_ac_159_manual_case_has_null_analysis(db: Session):
    """手工新增：`analysis_id` 为 NULL、`source_type='manual'`、指纹为 NULL。"""
    chain = _chain(db)
    case = _case(db, chain, None, source_type="manual")

    assert case.analysis_id is None
    assert case.source_type == "manual"
    assert case.source_point_fingerprint is None
    assert case.needs_review_ack_at is None


def test_ac_159_steps_roundtrip(db: Session):
    """步骤子表：`step_no` 从 1 起连续，`expected` 默认空串。"""
    chain = _chain(db)
    case = _case(db, chain)
    _steps(db, case, ["输入错误密码", "重复 4 次"])

    rows = db.scalars(
        select(TestCaseStep)
        .where(TestCaseStep.case_id == case.id)
        .order_by(TestCaseStep.step_no)
    ).all()
    assert [row.step_no for row in rows] == [1, 2]
    assert rows[0].action == "输入错误密码"
    assert rows[0].expected == "输入错误密码-预期"


def test_ac_159_steps_cascade_on_case_delete(db: Session):
    """删用例时步骤由数据库级 `ON DELETE CASCADE` 清理，不留孤儿行。"""
    chain = _chain(db)
    case = _case(db, chain)
    _steps(db, case, ["第一步", "第二步"])

    db.delete(case)
    db.flush()

    left = db.scalars(
        select(TestCaseStep).where(TestCaseStep.case_id == case.id)
    ).all()
    assert left == []


def test_ac_159_steps_unique_step_no(db: Session):
    """同一用例的 `step_no` 唯一：重复序号撞 `uk_tcsteps_case_no`（1062）。"""
    chain = _chain(db)
    case = _case(db, chain)
    db.add(TestCaseStep(case_id=case.id, step_no=1, action="第一步"))
    db.flush()

    with pytest.raises(IntegrityError) as exc:
        db.add(TestCaseStep(case_id=case.id, step_no=1, action="重复序号"))
        db.flush()
    assert exc.value.orig.args[0] == 1062
    assert "uk_tcsteps_case_no" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_159_steps_require_positive_step_no(db: Session):
    """`step_no` 必须 >= 1（CHECK `ck_tcsteps_no_positive`）。"""
    chain = _chain(db)
    case = _case(db, chain)

    with pytest.raises(OperationalError) as exc:
        db.add(TestCaseStep(case_id=case.id, step_no=0, action="第零步"))
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_tcsteps_no_positive" in str(exc.value.orig.args[1])
    db.rollback()


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("case_type", "perf", "ck_tcases_case_type"),
        ("priority", "urgent", "ck_tcases_priority"),
        ("status", "done", "ck_tcases_status"),
        ("source_type", "skill", "ck_tcases_source_type"),
    ],
)
def test_ac_159_case_check_constraints(
    db: Session, field: str, value: str, constraint: str
):
    """用例的四个 CHECK 约束都生效。"""
    chain = _chain(db)

    with pytest.raises(OperationalError) as exc:
        _case(db, chain, None, **{field: value})
    assert exc.value.orig.args[0] == 3819
    assert constraint in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_159_analysis_status_check(db: Session):
    """生成记录状态只接受四个枚举值。"""
    chain = _chain(db)

    with pytest.raises(OperationalError) as exc:
        _analysis(db, chain, status="done")
    assert exc.value.orig.args[0] == 3819
    assert "ck_tcanalyses_status" in str(exc.value.orig.args[1])
    db.rollback()
