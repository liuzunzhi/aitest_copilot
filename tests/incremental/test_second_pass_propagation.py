"""T74 · 2b-3 图传播（AC-92）。

传播只做一跳；结果一律进人工队列；命中已裁决目标时删除裁决并并入候选，
保证同一目标只出现在 `decisions` / `conflicts` 之一。
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.incremental.second_pass import (
    build_point_index,
    propagate_impacts,
    run_point_pass,
)
from app.llm.mock import MockProvider
from app.models.chapter_link import DocumentChapterLink
from tests.incremental import helpers


def _link(
    db: Session, chain: dict, from_chapter, to_chapter, link_type: str = "references"
) -> None:
    db.add(
        DocumentChapterLink(
            version_id=chain["version"].id,
            from_chapter_id=from_chapter.id,
            to_chapter_id=to_chapter.id,
            link_type=link_type,
            confidence=Decimal("0.80"),
            source="rule",
            created_by=chain["admin"].id,
        )
    )
    db.flush()


def _setup(db: Session):
    """C1 命中功能点 F，C2 命中功能点 G，C1 → C2 有引用边。"""
    chain = helpers.build_chain(
        db,
        chapters=[("1 下单", "下单流程改动"), ("2 退款", "退款流程说明")],
        with_function=False,
    )
    first_chapter, second_chapter = chain["chapters"]
    order = helpers.make_function(
        db, chain["project"], chain["admin"], function_name="下单", point_name="提交订单"
    )
    refund = helpers.make_function(
        db,
        chain["project"],
        chain["admin"],
        module_name="售后模块",
        function_name="退款",
        point_name="退款审核",
    )
    return chain, first_chapter, second_chapter, order, refund


def test_ac_92_propagation_goes_to_conflict_queue(db: Session):
    """C1 的功能点 changed → C2 的功能点只进 possible_impact，不进 decisions。"""
    chain, first_chapter, second_chapter, order, refund = _setup(db)
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=first_chapter.id,
        target_type="feature_point",
        target_id=order["point"].id,
        label_type="changed",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second_chapter.id,
        target_type="feature_point",
        target_id=refund["point"].id,
        label_type="unchanged",
    )
    _link(db, chain, first_chapter, second_chapter)
    db.flush()

    index = build_point_index(db, analysis)
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)

    decisions = {(item.target_type, item.target_id) for item in result.decisions}
    assert ("feature_point", order["point"].id) in decisions
    assert ("feature_point", refund["point"].id) not in decisions

    impact = [
        item
        for item in result.conflicts
        if item.target_id == refund["point"].id
    ]
    assert len(impact) == 1
    assert impact[0].conflict_type == "possible_impact"
    sources = {candidate["source"] for candidate in impact[0].candidates}
    assert f"chapter:{first_chapter.id}" in sources
    assert result.propagated_count == 1


def test_ac_92_propagation_removes_existing_decision(db: Session):
    """传播命中已裁决目标 → 删除该裁决，原标签并入候选。"""
    chain, first_chapter, second_chapter, order, refund = _setup(db)
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=first_chapter.id,
        target_type="feature_point",
        target_id=order["point"].id,
        label_type="changed",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second_chapter.id,
        target_type="feature_point",
        target_id=refund["point"].id,
        label_type="unchanged",
    )
    _link(db, chain, first_chapter, second_chapter)
    db.flush()

    index = build_point_index(db, analysis)
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    # 2b-2 阶段 G 已有一条裁决
    assert ("feature_point", refund["point"].id) in {
        (item.target_type, item.target_id) for item in result.decisions
    }

    propagate_impacts(index, result)

    decisions = {(item.target_type, item.target_id) for item in result.decisions}
    assert ("feature_point", refund["point"].id) not in decisions

    impact = [item for item in result.conflicts if item.target_id == refund["point"].id]
    assert len(impact) == 1
    labels = {candidate["label_type"] for candidate in impact[0].candidates}
    assert "affected" in labels
    assert "unchanged" in labels  # 原裁决标签并入候选
    assert "point_pass" in {candidate["source"] for candidate in impact[0].candidates}


def test_ac_92_mentions_entity_does_not_propagate(db: Session):
    """`mentions_entity` 边不参与传播。"""
    chain, first_chapter, second_chapter, order, refund = _setup(db)
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=first_chapter.id,
        target_type="feature_point",
        target_id=order["point"].id,
        label_type="changed",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second_chapter.id,
        target_type="feature_point",
        target_id=refund["point"].id,
        label_type="unchanged",
    )
    _link(db, chain, first_chapter, second_chapter, link_type="mentions_entity")
    db.flush()

    index = build_point_index(db, analysis)
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)

    assert result.propagated_count == 0
    assert result.conflicts == []
    assert ("feature_point", refund["point"].id) in {
        (item.target_type, item.target_id) for item in result.decisions
    }


def test_ac_92_weak_source_does_not_propagate(db: Session):
    """源章节只有 `unchanged` → 不触发传播。"""
    chain, first_chapter, second_chapter, order, refund = _setup(db)
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=first_chapter.id,
        target_type="feature_point",
        target_id=order["point"].id,
        label_type="unchanged",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second_chapter.id,
        target_type="feature_point",
        target_id=refund["point"].id,
        label_type="unchanged",
    )
    _link(db, chain, first_chapter, second_chapter)
    db.flush()

    index = build_point_index(db, analysis)
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)

    assert result.propagated_count == 0
    assert result.conflicts == []


def test_ac_92_only_one_hop(db: Session):
    """只走一跳：C1 → C2 → C3，C3 不再传播。"""
    chain = helpers.build_chain(
        db,
        chapters=[("1 A", "A 改动"), ("2 B", "B 说明"), ("3 C", "C 说明")],
        with_function=False,
    )
    first, second, third = chain["chapters"]
    a = helpers.make_function(
        db, chain["project"], chain["admin"], function_name="甲", point_name="甲点"
    )
    b = helpers.make_function(
        db,
        chain["project"],
        chain["admin"],
        module_name="模块二",
        function_name="乙",
        point_name="乙点",
    )
    c = helpers.make_function(
        db,
        chain["project"],
        chain["admin"],
        module_name="模块三",
        function_name="丙",
        point_name="丙点",
    )
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=first.id,
        target_type="feature_point",
        target_id=a["point"].id,
        label_type="changed",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second.id,
        target_type="feature_point",
        target_id=b["point"].id,
        label_type="unchanged",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=third.id,
        target_type="feature_point",
        target_id=c["point"].id,
        label_type="unchanged",
    )
    _link(db, chain, first, second)
    _link(db, chain, second, third)
    db.flush()

    index = build_point_index(db, analysis)
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)

    impacted = {item.target_id for item in result.conflicts}
    assert b["point"].id in impacted
    assert c["point"].id not in impacted
    assert result.propagated_count == 1


def test_ac_92_conflict_wins_over_possible_impact(db: Session):
    """同目标既有 conflict 又有 possible_impact → 合并为一条 conflict。"""
    chain = helpers.build_chain(
        db,
        chapters=[("1 下单", "下单改动"), ("2 退款", "退款说明"), ("3 售后", "售后补充")],
        with_function=False,
    )
    first_chapter, second_chapter, third_chapter = chain["chapters"]
    order = helpers.make_function(
        db, chain["project"], chain["admin"], function_name="下单", point_name="提交订单"
    )
    refund = helpers.make_function(
        db,
        chain["project"],
        chain["admin"],
        module_name="售后模块",
        function_name="退款",
        point_name="退款审核",
    )
    analysis = helpers.make_analysis(db, chain)
    # F 在 C1 变更 → 触发向 C2 传播
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=first_chapter.id,
        target_type="feature_point",
        target_id=order["point"].id,
        label_type="changed",
    )
    # G 在 C2 / C3 标签不一致 → 2b-2 直接产 conflict
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second_chapter.id,
        target_type="feature_point",
        target_id=refund["point"].id,
        label_type="changed",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=third_chapter.id,
        target_type="feature_point",
        target_id=refund["point"].id,
        label_type="unchanged",
    )
    _link(db, chain, first_chapter, second_chapter)
    db.flush()

    index = build_point_index(db, analysis)
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)

    merged = [item for item in result.conflicts if item.target_id == refund["point"].id]
    assert len(merged) == 1
    assert merged[0].conflict_type == "conflict"
    labels = {candidate["label_type"] for candidate in merged[0].candidates}
    assert {"changed", "unchanged"} <= labels
    assert "affected" in labels  # 传播候选并入同一条
    assert result.propagated_count == 1


def test_propagate_is_idempotent(db: Session):
    """同一份结果重复传播不会产生重复冲突。"""
    chain, first_chapter, second_chapter, order, refund = _setup(db)
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=first_chapter.id,
        target_type="feature_point",
        target_id=order["point"].id,
        label_type="changed",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second_chapter.id,
        target_type="feature_point",
        target_id=refund["point"].id,
        label_type="unchanged",
    )
    _link(db, chain, first_chapter, second_chapter)
    db.flush()

    index = build_point_index(db, analysis)
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)
    count = len(result.conflicts)
    propagate_impacts(index, result)

    assert len(result.conflicts) == count
    assert result.propagated_count == 1


def test_propagate_with_empty_index_is_noop(db: Session):
    """没有结论也没有引用边时，传播不产生任何冲突。"""
    chain = helpers.build_chain(db, chapters=[("1 下单", "下单改动")], with_function=False)
    analysis = helpers.make_analysis(db, chain)

    index = build_point_index(db, analysis)
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)

    assert result.point_count == 0
    assert result.conflicts == []
    assert result.propagated_count == 0
