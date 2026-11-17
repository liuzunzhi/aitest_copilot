"""T80 · 产出引擎（AC-98 / AC-100）。

覆盖：

- `collect_labelable` 的 spec §5.1 规则表（纯函数，不碰库）；
- `resolve_revision` 复用 / 新建 submitted 快照（AC-99 的快照语义）；
- `write_labels` 写标签 + 映射、跳过已删除 / 归档模块下的目标；
- `clear_previous` 逻辑清除：行不删、置 cleared、留清除人 / 时间 / 原因，
  连续两次产出后生效标签数不累加（AC-100）。
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.errors import DuplicateLabel
from app.incremental import apply
from app.models.baseline import BaselineLabel, BaselineRevision
from app.models.incremental import (
    IncrementalAnalysis,
    IncrementalConflict,
    IncrementalDecision,
    IncrementalLabel,
)
from app.models.system import AuditLog
from tests.incremental import helpers


def _decision(
    db: Session,
    analysis: IncrementalAnalysis,
    *,
    target_type: str = "function",
    target_id: int,
    target_name: str = "下单",
    decision: str = "changed",
) -> IncrementalDecision:
    row = IncrementalDecision(
        analysis_id=analysis.id,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        decision=decision,
    )
    db.add(row)
    db.flush()
    return row


def _conflict(
    db: Session,
    analysis: IncrementalAnalysis,
    *,
    target_type: str = "function",
    target_id: int | None,
    target_name: str = "下单",
    conflict_type: str = "conflict",
    status: str = "confirmed",
    resolved_label_type: str | None = "changed",
) -> IncrementalConflict:
    row = IncrementalConflict(
        analysis_id=analysis.id,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        conflict_type=conflict_type,
        candidates=[{"label_type": "changed"}],
        status=status,
        resolved_label_type=resolved_label_type,
        resolved_by=analysis.created_by if status != "pending" else None,
    )
    db.add(row)
    db.flush()
    return row


def _label_count(db: Session, analysis: IncrementalAnalysis, *, status: str | None = None) -> int:
    query = (
        select(func.count())
        .select_from(BaselineLabel)
        .where(BaselineLabel.source_analysis_id == analysis.id)
    )
    if status is not None:
        query = query.where(BaselineLabel.status == status)
    return int(db.scalar(query) or 0)


# ------------------------------------------------------------ 收集规则


def test_collect_decisions_only_changed_and_affected():
    """裁决只收 changed / affected，unchanged 不落标签。"""
    decisions = [
        SimpleNamespace(
            id=1, decision="changed", target_type="function", target_id=7, target_name="下单"
        ),
        SimpleNamespace(
            id=2, decision="affected", target_type="feature_point", target_id=9, target_name="确认"
        ),
        SimpleNamespace(
            id=3, decision="unchanged", target_type="function", target_id=8, target_name="退款"
        ),
    ]

    targets = apply.collect_labelable(decisions, [])

    assert [(t.target_type, t.target_id, t.label_type) for t in targets] == [
        ("function", 7, "changed"),
        ("feature_point", 9, "affected"),
    ]
    assert all(t.source == "decision" for t in targets)


def test_collect_conflicts_only_confirmed_labelable():
    """冲突只收已确认且裁决为变更类、且有基线实体的。"""
    conflicts = [
        SimpleNamespace(
            id=11,
            status="confirmed",
            resolved_label_type="affected",
            target_type="function",
            target_id=7,
            target_name="下单",
        ),
        SimpleNamespace(
            id=12,
            status="confirmed",
            resolved_label_type="unchanged",
            target_type="function",
            target_id=8,
            target_name="退款",
        ),
        SimpleNamespace(
            id=13,
            status="rejected",
            resolved_label_type=None,
            target_type="function",
            target_id=9,
            target_name="取消",
        ),
        SimpleNamespace(
            id=14,
            status="pending",
            resolved_label_type=None,
            target_type="function",
            target_id=10,
            target_name="查询",
        ),
        # new 冲突：没有基线实体
        SimpleNamespace(
            id=15,
            status="confirmed",
            resolved_label_type="changed",
            target_type="function",
            target_id=None,
            target_name="新增：开票",
        ),
    ]

    targets = apply.collect_labelable([], conflicts)

    assert len(targets) == 1
    assert targets[0].target_id == 7
    assert targets[0].label_type == "affected"
    assert targets[0].source == "conflict"
    assert targets[0].source_id == 11


def test_collect_dedupes_same_target_decision_first():
    """同一目标只留一条：裁决优先，避免写两条标签。"""
    decisions = [
        SimpleNamespace(
            id=1, decision="changed", target_type="function", target_id=7, target_name="下单"
        )
    ]
    conflicts = [
        SimpleNamespace(
            id=2,
            status="confirmed",
            resolved_label_type="affected",
            target_type="function",
            target_id=7,
            target_name="下单",
        )
    ]

    targets = apply.collect_labelable(decisions, conflicts)

    assert len(targets) == 1
    assert targets[0].source == "decision"
    assert targets[0].label_type == "changed"


def test_collect_removes_new_conflict_but_keeps_others(db: Session):
    """真实冲突行：新增无 target_id 被丢弃；普通冲突确认后保留。"""
    chain = helpers.build_chain(db)
    analysis = helpers.make_analysis(db, chain)
    function = chain["structure"]["function"]

    normal = _conflict(db, analysis, target_id=function.id, resolved_label_type="changed")
    new = _conflict(
        db,
        analysis,
        target_id=None,
        target_name="新增：开票",
        conflict_type="new",
        resolved_label_type="changed",
    )

    targets = apply.collect_labelable([], [normal, new])

    assert [t.target_id for t in targets] == [function.id]


# ------------------------------------------------------------ 快照（AC-99 语义）


def test_resolve_revision_creates_submitted_without_version(db: Session):
    """没有待审核记录时新建：submitted、version_no 为空、备注记来源分析。"""
    chain = helpers.build_chain(db)
    analysis = helpers.make_analysis(db, chain)

    revision = apply.resolve_revision(
        db,
        project_id=chain["project"].id,
        actor=chain["admin"],
        analysis=analysis,
    )

    db.refresh(revision)
    assert revision.status == "submitted"
    assert revision.version_no is None
    assert revision.submitted_by == chain["admin"].id
    assert revision.submitted_at is not None
    assert str(analysis.id) in (revision.review_comment or "")


def test_resolve_revision_reuses_existing_submitted(db: Session):
    """项目内已有 submitted 记录时复用，不新建第二条。"""
    chain = helpers.build_chain(db)
    analysis = helpers.make_analysis(db, chain)
    existing = helpers.make_revision(
        db, chain["project"], status="submitted", version_no=None
    )

    revision = apply.resolve_revision(
        db,
        project_id=chain["project"].id,
        actor=chain["admin"],
        analysis=analysis,
    )

    assert revision.id == existing.id
    total = db.scalar(
        select(func.count())
        .select_from(BaselineRevision)
        .where(
            BaselineRevision.project_id == chain["project"].id,
            BaselineRevision.status == "submitted",
        )
    )
    assert total == 1


# ------------------------------------------------------------ 写标签（AC-98）


def test_write_labels_creates_rows_and_mapping(db: Session):
    """AC-98：标签带 revision / 目标 / 类型 / 来源分析，映射行同步落库。"""
    chain = helpers.build_chain(db)
    analysis = helpers.make_analysis(db, chain)
    function = chain["structure"]["function"]
    extra = helpers.make_function(
        db,
        chain["project"],
        chain["admin"],
        module_name="会员模块",
        function_name="开通会员",
        point_name="支付会费",
    )
    decisions = [
        _decision(db, analysis, target_id=function.id, decision="changed"),
        _decision(
            db,
            analysis,
            target_type="feature_point",
            target_id=extra["point"].id,
            target_name="支付会费",
            decision="affected",
        ),
    ]
    revision = apply.resolve_revision(
        db, project_id=chain["project"].id, actor=chain["admin"], analysis=analysis
    )

    targets = apply.collect_labelable(decisions, [])
    result = apply.write_labels(
        db,
        analysis=analysis,
        revision_id=revision.id,
        targets=targets,
        actor=chain["admin"],
    )
    db.commit()

    assert result.label_count == 2
    assert result.skipped_missing == []
    by_target = {(label.target_type, label.target_id): label for label in result.labels}
    assert by_target[("function", function.id)].label_type == "changed"
    assert by_target[("feature_point", extra["point"].id)].label_type == "affected"
    for label in result.labels:
        assert label.revision_id == revision.id
        assert label.source_analysis_id == analysis.id
        assert label.status == "active"
        assert label.confirmed_by == chain["admin"].id
        assert label.active_key is not None

    mappings = db.scalars(
        select(IncrementalLabel).where(IncrementalLabel.analysis_id == analysis.id)
    ).all()
    assert len(mappings) == 2
    assert {row.baseline_label_id for row in mappings} == {
        label.id for label in result.labels
    }
    assert {row.revision_id for row in mappings} == {revision.id}


def test_write_labels_skips_missing_and_archived_targets(db: Session):
    """目标不存在或所属模块已归档 → 跳过并计入 skipped_missing，不报错。"""
    chain = helpers.build_chain(db)
    analysis = helpers.make_analysis(db, chain)
    archived = helpers.make_function(
        db,
        chain["project"],
        chain["admin"],
        module_name="历史模块",
        function_name="已归档功能",
    )
    archived["module"].status = "archived"
    db.flush()

    targets = [
        apply.LabelableTarget(
            target_type="function",
            target_id=chain["structure"]["function"].id,
            target_name="下单",
            label_type="changed",
            source="decision",
        ),
        apply.LabelableTarget(
            target_type="function",
            target_id=archived["function"].id,
            target_name="已归档功能",
            label_type="changed",
            source="decision",
        ),
        apply.LabelableTarget(
            target_type="function",
            target_id=999999,
            target_name="已删除功能",
            label_type="affected",
            source="conflict",
        ),
    ]
    revision = apply.resolve_revision(
        db, project_id=chain["project"].id, actor=chain["admin"], analysis=analysis
    )

    result = apply.write_labels(
        db,
        analysis=analysis,
        revision_id=revision.id,
        targets=targets,
        actor=chain["admin"],
    )

    assert result.label_count == 1
    assert {item.target_id for item in result.skipped_missing} == {
        archived["function"].id,
        999999,
    }
    assert _label_count(db, analysis) == 1


def test_write_labels_detects_duplicate_active_label(db: Session):
    """同一快照同目标同类型已有生效标签 → 抛 04 的 DUPLICATE_LABEL。"""
    chain = helpers.build_chain(db)
    analysis = helpers.make_analysis(db, chain)
    function = chain["structure"]["function"]
    revision = apply.resolve_revision(
        db, project_id=chain["project"].id, actor=chain["admin"], analysis=analysis
    )
    db.add(
        BaselineLabel(
            project_id=chain["project"].id,
            revision_id=revision.id,
            target_type="function",
            target_id=function.id,
            label_type="changed",
            confirmed_by=chain["admin"].id,
        )
    )
    db.flush()

    with pytest.raises(DuplicateLabel):
        apply.write_labels(
            db,
            analysis=analysis,
            revision_id=revision.id,
            targets=[
                apply.LabelableTarget(
                    target_type="function",
                    target_id=function.id,
                    target_name="下单",
                    label_type="changed",
                    source="decision",
                )
            ],
            actor=chain["admin"],
        )


# ------------------------------------------------------------ 重跑（AC-100）


def test_apply_twice_clears_previous_without_deleting(db: Session):
    """AC-100：连跑两次，生效标签不累加；旧行保留并标记 cleared。"""
    chain = helpers.build_chain(db)
    extra = helpers.make_function(
        db,
        chain["project"],
        chain["admin"],
        module_name="会员模块",
        function_name="开通会员",
        point_name="支付会费",
    )
    analysis = helpers.make_analysis(db, chain)
    decisions = [
        _decision(db, analysis, target_id=chain["structure"]["function"].id),
        _decision(
            db,
            analysis,
            target_type="feature_point",
            target_id=extra["point"].id,
            target_name="支付会费",
            decision="affected",
        ),
    ]
    targets = apply.collect_labelable(decisions, [])
    revision = apply.resolve_revision(
        db, project_id=chain["project"].id, actor=chain["admin"], analysis=analysis
    )

    # 第一轮
    assert apply.clear_previous(db, analysis=analysis, actor=chain["admin"]) == 0
    first = apply.write_labels(
        db,
        analysis=analysis,
        revision_id=revision.id,
        targets=targets,
        actor=chain["admin"],
    )
    db.commit()
    first_ids = [label.id for label in first.labels]
    assert _label_count(db, analysis, status="active") == 2

    # 第二轮：逻辑清除旧标签后重建
    assert apply.clear_previous(db, analysis=analysis, actor=chain["admin"]) == 2
    second = apply.write_labels(
        db,
        analysis=analysis,
        revision_id=revision.id,
        targets=targets,
        actor=chain["admin"],
    )
    db.commit()
    second_ids = [label.id for label in second.labels]

    # 生效标签数不变，旧行仍在库里
    assert _label_count(db, analysis, status="active") == 2
    assert _label_count(db, analysis) == 4
    assert set(first_ids).isdisjoint(second_ids)
    for label_id in first_ids:
        row = db.get(BaselineLabel, label_id)
        assert row is not None, "旧标签行不允许被物理删除"
        assert row.status == "cleared"
        assert row.cleared_by == chain["admin"].id
        assert row.cleared_at is not None
        assert row.clear_reason == apply.CLEAR_REASON

    # 映射行同样保留：新旧各一条，历史可追溯
    mapping_count = int(
        db.scalar(
            select(func.count())
            .select_from(IncrementalLabel)
            .where(IncrementalLabel.analysis_id == analysis.id)
        )
        or 0
    )
    assert mapping_count == 4
    assert len(second.labels) == len(first.labels) == 2


def test_clear_previous_writes_clear_audit(db: Session):
    """逻辑清除走 04 的 clear_label，会留下 baseline.label.clear 审计。"""
    chain = helpers.build_chain(db)
    analysis = helpers.make_analysis(db, chain)
    decisions = [
        _decision(db, analysis, target_id=chain["structure"]["function"].id)
    ]
    revision = apply.resolve_revision(
        db, project_id=chain["project"].id, actor=chain["admin"], analysis=analysis
    )
    apply.write_labels(
        db,
        analysis=analysis,
        revision_id=revision.id,
        targets=apply.collect_labelable(decisions, []),
        actor=chain["admin"],
    )
    db.commit()

    apply.clear_previous(db, analysis=analysis, actor=chain["admin"])
    db.commit()

    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "baseline.label.clear",
            AuditLog.project_id == chain["project"].id,
        )
    ).all()
    assert len(audits) == 1
    assert audits[0].reason == apply.CLEAR_REASON
    assert audits[0].actor_id == chain["admin"].id
