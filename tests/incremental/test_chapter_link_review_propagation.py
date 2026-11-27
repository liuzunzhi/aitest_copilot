"""12.5 期 · 待评审边不参与图传播（T138 / AC-231）。

**这一条是「待评审」能不能在语义上成立的关键**：
边「生效」在本仓库里的唯一含义，就是**能参与 05 期第二遍的图传播**
（`second_pass.build_point_index` 读引用图，沿 `references` / `depends_on`
边走一跳，把源章节的 `changed` / `affected` 结论传播成 `possible_impact` 冲突）。

如果 `pending` 的边照样参与传播，那「待评审」就只是前端的一个分区标签，
语义上等于没做——用户以为「还没确认，不会影响分析」，实际已经影响了。

所以 `build_point_index` 的链接查询必须过滤 `status='approved'`，
本文件逐条钉住这件事。
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
    db: Session,
    chain: dict,
    from_chapter,
    to_chapter,
    *,
    status: str = "approved",
    source: str = "ai",
    link_type: str = "references",
) -> DocumentChapterLink:
    """插一条引用边。`status` 显式给，避免依赖 server_default 而掩盖真实意图。"""
    link = DocumentChapterLink(
        version_id=chain["version"].id,
        from_chapter_id=from_chapter.id,
        to_chapter_id=to_chapter.id,
        link_type=link_type,
        confidence=Decimal("0.80"),
        source=source,
        status=status,
        created_by=chain["admin"].id,
    )
    db.add(link)
    db.flush()
    return link


def _setup(db: Session):
    """C1 命中功能点 F（changed），C2 命中功能点 G（unchanged），C1 → C2 有边。"""
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


def _seed_conclusions(db: Session, chain: dict, order, refund):
    """在 C1 写 F=changed、在 C2 写 G=unchanged（传播的触发条件）。返回该分析记录。"""
    first_chapter, second_chapter = chain["chapters"]
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
    return analysis


def _propagated_targets(db: Session, analysis) -> list:
    """对**同一个分析**跑索引 + 2b-2 + 传播，返回 possible_impact 的目标 id。"""
    index = build_point_index(db, analysis)
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)
    return [
        item.target_id
        for item in result.conflicts
        if item.conflict_type == "possible_impact"
    ]


def test_ac_231_pending_link_does_not_propagate(db: Session):
    """`status='pending'` 的 `references` 边**不产生** `possible_impact`。"""
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
    _link(db, chain, first_chapter, second_chapter, status="pending")

    index = build_point_index(db, analysis)
    # 索引层面就已经看不到这条边（不是等到传播才过滤）
    assert index.chapter_links == {}

    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)

    assert result.propagated_count == 0
    assert [item for item in result.conflicts if item.conflict_type == "possible_impact"] == []
    # G 原样留在裁决里，没有被传播改成冲突
    assert ("feature_point", refund["point"].id) in {
        (item.target_type, item.target_id) for item in result.decisions
    }


def test_ac_231_approved_link_propagates(db: Session):
    """同一条边改成 `approved` 后就**产生** `possible_impact`（对照组）。"""
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
    _link(db, chain, first_chapter, second_chapter, status="approved")

    index = build_point_index(db, analysis)
    assert index.chapter_links == {first_chapter.id: [second_chapter.id]}

    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)

    assert result.propagated_count == 1
    impacts = [
        item for item in result.conflicts if item.conflict_type == "possible_impact"
    ]
    assert len(impacts) == 1
    assert impacts[0].target_id == refund["point"].id


def test_ac_231_review_then_approve_produces_impact(db: Session):
    """「分析落 pending → 人工采纳 → 才产生传播」的完整链路。

    **同一个库、同一个分析**，只改边的 `status`，传播结果从「无」变成「有」——
    这正是 AC-231 要钉住的语义：状态是唯一的开关。
    """
    chain, first_chapter, second_chapter, order, refund = _setup(db)
    analysis = _seed_conclusions(db, chain, order, refund)
    link = _link(db, chain, first_chapter, second_chapter, status="pending")

    assert _propagated_targets(db, analysis) == []

    link.status = "approved"
    db.flush()

    assert _propagated_targets(db, analysis) == [refund["point"].id]


def test_ac_231_approved_and_pending_coexist(db: Session):
    """同版本同时有 approved 与 pending 边：只走 approved 那条。

    三条章节：C1 命中 F（changed）；C1→C2 是待评审、C1→C3 是已生效。
    传播结果应只有 C3 的功能点，C2 的保持原裁决。
    """
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
        db, analysis, chapter_id=first.id, target_type="feature_point",
        target_id=a["point"].id, label_type="changed",
    )
    helpers.make_conclusion(
        db, analysis, chapter_id=second.id, target_type="feature_point",
        target_id=b["point"].id, label_type="unchanged",
    )
    helpers.make_conclusion(
        db, analysis, chapter_id=third.id, target_type="feature_point",
        target_id=c["point"].id, label_type="unchanged",
    )
    _link(db, chain, first, second, status="pending")
    _link(db, chain, first, third, status="approved")

    index = build_point_index(db, analysis)
    # 只有 approved 的那条进了索引
    assert index.chapter_links == {first.id: [third.id]}

    result = run_point_pass(
        db,
        analysis=analysis,
        provider=MockProvider(),
        template=helpers.second_pass_template(db),
        index=index,
    )
    propagate_impacts(index, result)

    impacted = {
        item.target_id
        for item in result.conflicts
        if item.conflict_type == "possible_impact"
    }
    assert impacted == {c["point"].id}
    assert b["point"].id not in impacted
    assert result.propagated_count == 1


def test_ac_231_rule_link_defaults_to_approved(db: Session):
    """规则边（不显式给 status）走 server_default → `approved` → 照常传播。

    这是**零回归**的保障：05 期既有的规则边没写 `status`，
    加列后必须仍然参与传播，否则 05 期的图传播会静默失效。
    """
    chain, first_chapter, second_chapter, order, refund = _setup(db)
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db, analysis, chapter_id=first_chapter.id, target_type="feature_point",
        target_id=order["point"].id, label_type="changed",
    )
    helpers.make_conclusion(
        db, analysis, chapter_id=second_chapter.id, target_type="feature_point",
        target_id=refund["point"].id, label_type="unchanged",
    )
    # 不传 status（走 server_default）
    db.add(
        DocumentChapterLink(
            version_id=chain["version"].id,
            from_chapter_id=first_chapter.id,
            to_chapter_id=second_chapter.id,
            link_type="references",
            confidence=Decimal("0.80"),
            source="rule",
            created_by=chain["admin"].id,
        )
    )
    db.flush()

    index = build_point_index(db, analysis)
    assert index.chapter_links == {first_chapter.id: [second_chapter.id]}
