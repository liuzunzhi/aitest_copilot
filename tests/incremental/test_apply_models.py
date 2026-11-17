"""产出段落库结构（T79）。

验证 0016：`incremental_labels` 可写入、唯一键 / CHECK 生效、外键级联规则正确；
`incremental_analyses` 的 `apply_*` 列默认 NULL，状态 CHECK 只收 running / succeeded / failed。

红线：用例只读断言 `baseline_labels` 的结构与外键规则，不物理删除任何标签行。
"""

import pytest
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models import target_metadata
from app.models.baseline import BaselineLabel
from app.models.incremental import (
    APPLIED_LABEL_TYPES,
    APPLY_STATUSES,
    IncrementalAnalysis,
    IncrementalLabel,
)
from tests.incremental import helpers


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


def _baseline_label(
    db: Session,
    chain: dict,
    *,
    label_type: str = "changed",
    target_type: str = "function",
    target_id: int | None = None,
) -> BaselineLabel:
    """04 的标签行：产出段只引用它，用例不删除它。"""
    label = BaselineLabel(
        project_id=chain["project"].id,
        revision_id=chain["revision"].id,
        target_type=target_type,
        target_id=target_id or chain["structure"]["function"].id,
        label_type=label_type,
        confirmed_by=chain["admin"].id,
    )
    db.add(label)
    db.flush()
    return label


def _mapping(
    db: Session,
    analysis: IncrementalAnalysis,
    label: BaselineLabel,
    **overrides,
) -> IncrementalLabel:
    values = {
        "analysis_id": analysis.id,
        "baseline_label_id": label.id,
        "revision_id": label.revision_id,
        "target_type": label.target_type,
        "target_id": label.target_id,
        "label_type": label.label_type,
    }
    values.update(overrides)
    row = IncrementalLabel(**values)
    db.add(row)
    db.flush()
    return row


def test_apply_constants():
    """产出状态与可落标签类型限定在 spec 范围内。"""
    assert APPLY_STATUSES == ("running", "succeeded", "failed")
    assert APPLIED_LABEL_TYPES == ("changed", "affected")


def test_apply_columns_default_to_null(db: Session):
    """未应用过：7 个 apply_* 列全为 NULL。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)

    db.refresh(analysis)
    assert analysis.apply_status is None
    assert analysis.apply_stats is None
    assert analysis.apply_revision_id is None
    assert analysis.apply_error_code is None
    assert analysis.apply_error_message is None
    assert analysis.apply_started_at is None
    assert analysis.apply_finished_at is None


@pytest.mark.parametrize("status", APPLY_STATUSES)
def test_apply_status_accepts_running_states(db: Session, status: str):
    """running / succeeded / failed 都可写入。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain, apply_status=status)

    db.refresh(analysis)
    assert analysis.apply_status == status


def test_apply_status_check(db: Session):
    """产出状态只接受 running / succeeded / failed（NULL 表示未应用）。"""
    chain = helpers.build_chain(db)

    with pytest.raises(OperationalError) as exc:
        _analysis(db, chain, apply_status="done")
    assert exc.value.orig.args[0] == 3819
    assert "ck_ianalyses_apply_status" in str(exc.value.orig.args[1])


def test_mapping_row_writable(db: Session):
    """映射行可写入，created_at 走 server default，revision 与标签一致。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)
    label = _baseline_label(db, chain)
    row = _mapping(db, analysis, label)

    db.refresh(row)
    assert row.created_at is not None
    assert row.revision_id == label.revision_id
    assert row.target_type == "function"
    assert row.target_id == chain["structure"]["function"].id
    assert row.label_type == "changed"


def test_mapping_unique_per_baseline_label(db: Session):
    """一个标签只能被一条映射行指向：重跑要新增映射行，不能复用旧行。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)
    label = _baseline_label(db, chain)
    _mapping(db, analysis, label)
    db.commit()

    with pytest.raises(IntegrityError) as exc:
        _mapping(db, analysis, label)
    assert exc.value.orig.args[0] == 1062
    assert "uk_ilabels_analysis_label" in str(exc.value.orig.args[1])


def test_mapping_allows_same_target_across_labels(db: Session):
    """同一分析、同一目标、不同标签类型各有一条映射——证明唯一键没有按目标建。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)
    changed = _baseline_label(db, chain, label_type="changed")
    affected = _baseline_label(db, chain, label_type="affected")

    _mapping(db, analysis, changed)
    _mapping(db, analysis, affected)

    count = db.scalar(
        select(func.count())
        .select_from(IncrementalLabel)
        .where(IncrementalLabel.analysis_id == analysis.id)
    )
    assert count == 2


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"label_type": "unchanged"}, "ck_ilabels_label_type"),
        ({"target_type": "module"}, "ck_ilabels_target_type"),
    ],
)
def test_mapping_check_constraints(
    db: Session, overrides: dict, constraint: str
):
    """不落 unchanged 标签；目标只允许功能 / 功能点。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)
    label = _baseline_label(db, chain)

    with pytest.raises(OperationalError) as exc:
        _mapping(db, analysis, label, **overrides)
    assert exc.value.orig.args[0] == 3819
    assert constraint in str(exc.value.orig.args[1])


def test_mapping_cascades_with_analysis(db: Session):
    """分析记录删除时映射行级联清空（标签行本身不动）。"""
    chain = helpers.build_chain(db)
    analysis = _analysis(db, chain)
    label = _baseline_label(db, chain)
    _mapping(db, analysis, label)
    db.commit()

    db.execute(delete(IncrementalAnalysis).where(IncrementalAnalysis.id == analysis.id))
    db.flush()

    remaining = db.scalar(
        select(func.count())
        .select_from(IncrementalLabel)
        .where(IncrementalLabel.analysis_id == analysis.id)
    )
    assert remaining == 0
    assert db.get(BaselineLabel, label.id) is not None


def test_mapping_foreign_key_rules(db: Session):
    """外键规则：分析 / 标签删除级联映射；快照不级联（标签本身不删）。"""
    rows = db.execute(
        text(
            "SELECT constraint_name, delete_rule"
            " FROM information_schema.referential_constraints"
            " WHERE constraint_schema = DATABASE()"
            " AND table_name = 'incremental_labels'"
        )
    ).all()
    rules = {name: rule for name, rule in rows}

    assert rules["fk_ilabels_analysis"] == "CASCADE"
    assert rules["fk_ilabels_label"] == "CASCADE"
    assert rules["fk_ilabels_revision"] in ("NO ACTION", "RESTRICT")


def test_mapping_indexes(db: Session):
    """唯一键是 (analysis_id, baseline_label_id)，目标索引只做查询。"""
    indexes = {
        item["name"]: item
        for item in inspect(db.get_bind()).get_indexes("incremental_labels")
    }

    unique = indexes["uk_ilabels_analysis_label"]
    assert unique["unique"] is True
    assert unique["column_names"] == ["analysis_id", "baseline_label_id"]

    target = indexes["idx_ilabels_target"]
    assert target["unique"] is False
    assert target["column_names"] == [
        "analysis_id",
        "target_type",
        "target_id",
        "label_type",
    ]


def test_apply_models_registered():
    """模型集中注册：Alembic 能发现新表，__all__ 可导入。"""
    from app.models import __all__ as registered

    assert "IncrementalLabel" in registered
    assert "incremental_labels" in target_metadata.tables
