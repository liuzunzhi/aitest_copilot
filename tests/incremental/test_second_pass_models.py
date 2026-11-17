"""第二遍落库结构（T72）。

验证：第二遍模板种子、两表可写入、唯一键 / CHECK 生效、随分析级联删除、
老记录 `second_pass_status IS NULL` 且接口响应字段向后兼容。
"""

from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.incremental.schemas import AnalysisOut
from app.incremental.service import _analysis_item
from app.models.incremental import (
    IncrementalAnalysis,
    IncrementalConflict,
    IncrementalDecision,
    PromptTemplate,
)
from tests.incremental import helpers

SECOND_PASS_TEMPLATE = "增量分析·第二遍·按点分治"


def _second_pass_template(db: Session) -> PromptTemplate:
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.name == SECOND_PASS_TEMPLATE)
    )
    assert template is not None, "迁移 0015 应播种一条第二遍模板"
    return template


def _analysis(db: Session, chain: dict, **overrides) -> IncrementalAnalysis:
    values = {
        "project_id": chain["project"].id,
        "template_id": chain["template"].id,
        "template_version": chain["template"].version_no,
        "baseline_revision_id": chain["revision"].id,
        "document_id": chain["document"].id,
        "document_version_id": chain["version"].id,
        "status": "succeeded",
        "created_by": chain["admin"].id,
    }
    values.update(overrides)
    analysis = IncrementalAnalysis(**values)
    db.add(analysis)
    db.flush()
    return analysis


def _decision(db: Session, analysis: IncrementalAnalysis, **overrides) -> IncrementalDecision:
    values = {
        "analysis_id": analysis.id,
        "target_type": "function",
        "target_id": 1,
        "target_name": "下单",
        "decision": "changed",
        "confidence": Decimal("0.80"),
        "rationale": "接口新增字段",
        "evidence": {"chapter_ids": [1], "conclusion_ids": [1], "propagated_from": []},
    }
    values.update(overrides)
    row = IncrementalDecision(**values)
    db.add(row)
    db.flush()
    return row


def _conflict(db: Session, analysis: IncrementalAnalysis, **overrides) -> IncrementalConflict:
    values = {
        "analysis_id": analysis.id,
        "target_type": "feature_point",
        "target_id": 7,
        "target_name": "登录流程",
        "conflict_type": "conflict",
        "candidates": [{"label_type": "changed", "source": "point_pass"}],
    }
    values.update(overrides)
    row = IncrementalConflict(**values)
    db.add(row)
    db.flush()
    return row


def test_2b_seed_template_exists(db: Session):
    """第二遍模板由迁移播种：前缀可识别、active、与第一遍模板并存。"""
    template = _second_pass_template(db)

    assert template.task_type == "incremental"
    assert template.status == "active"
    assert template.version_no == 1
    assert template.system_prompt.startswith("[INCREMENTAL_2B_SYSTEM]")
    assert template.user_prompt.startswith("[INCREMENTAL_2B_USER]")
    assert helpers.seed_template(db).name == "增量分析·第一遍·章节局部"
    assert (
        db.execute(
            select(func.count())
            .select_from(PromptTemplate)
            .where(PromptTemplate.name.like("增量分析·第二遍%"))
        ).scalar_one()
        == 1
    )


def test_analysis_second_pass_defaults_and_response(db: Session):
    """未跑第二遍：列全为 NULL；`AnalysisOut` 仍是合法响应（向后兼容）。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)

    db.refresh(analysis)
    assert analysis.second_pass_status is None
    assert analysis.second_pass_template_id is None
    assert analysis.second_pass_stats is None
    assert analysis.second_pass_error_code is None

    payload = AnalysisOut(**_analysis_item(db, analysis))
    assert payload.status == "succeeded"
    assert payload.second_pass_status is None
    assert payload.second_pass_finished_at is None


def test_second_pass_status_check(db: Session):
    """第二遍状态只接受 running / succeeded / failed（NULL 表示未跑）。"""
    chain = helpers.build_chain(db)

    with pytest.raises(OperationalError) as exc:
        _analysis(db, chain, second_pass_status="done")
    assert exc.value.orig.args[0] == 3819
    assert "ck_ianalyses_2b_status" in str(exc.value.orig.args[1])


def test_decision_unique_per_target(db: Session):
    """同一分析、同一目标只允许一条裁决。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)
    decision = _decision(db, analysis)
    db.commit()

    with pytest.raises(IntegrityError) as exc:
        _decision(db, analysis, target_type=decision.target_type)
    assert exc.value.orig.args[0] == 1062
    assert "uk_idecisions_target" in str(exc.value.orig.args[1])


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("target_type", "module", "ck_idecisions_target_type"),
        ("decision", "new", "ck_idecisions_decision"),
    ],
)
def test_decision_check_constraints(
    db: Session, field: str, value: str, constraint: str
):
    """裁决的 target_type 只允许两级，decision 不含 new。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)

    with pytest.raises(OperationalError) as exc:
        _decision(db, analysis, **{field: value})
    assert exc.value.orig.args[0] == 3819
    assert constraint in str(exc.value.orig.args[1])


def test_conflict_new_has_no_target_id(db: Session):
    """new 没有 target_id，默认状态 pending、未裁决。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)

    fresh = _conflict(
        db,
        analysis,
        conflict_type="new",
        target_id=None,
        target_type="feature_point",
        target_name="退款审核",
    )
    assert fresh.status == "pending"
    assert fresh.resolved_at is None
    assert fresh.resolved_label_type is None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"conflict_type": "new", "target_id": 9, "target_name": "退款审核"}, "ck_iconflicts_target"),
        ({"conflict_type": "possible_impact", "target_id": None}, "ck_iconflicts_target"),
        ({"status": "done"}, "ck_iconflicts_status"),
        ({"resolved_label_type": "new"}, "ck_iconflicts_resolved_label"),
    ],
)
def test_conflict_check_constraints(db: Session, overrides: dict, constraint: str):
    """冲突目标组合、状态、裁决标签的 CHECK 约束。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)

    with pytest.raises(OperationalError) as exc:
        _conflict(db, analysis, **overrides)
    assert exc.value.orig.args[0] == 3819
    assert constraint in str(exc.value.orig.args[1])


def test_second_pass_rows_cascade_with_analysis(db: Session):
    """裁决与冲突都随分析记录级联删除。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)
    _decision(db, analysis)
    _conflict(db, analysis)
    db.commit()

    db.execute(delete(IncrementalAnalysis).where(IncrementalAnalysis.id == analysis.id))
    db.flush()

    for model in (IncrementalDecision, IncrementalConflict):
        remaining = db.scalar(
            select(func.count()).select_from(model).where(model.analysis_id == analysis.id)
        )
        assert remaining == 0
