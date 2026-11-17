"""T73 · 2b-1 功能点索引（AC-89 的索引一边）。

覆盖：结论聚合、功能→功能点、章节引用图、参与目标集合与作用域边界。
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.incremental.second_pass import (
    build_point_index,
    participating_targets,
    scoped_conclusions,
)
from app.models.chapter_link import DocumentChapterLink
from tests.incremental import helpers


def _setup_structure(db: Session, chain: dict) -> tuple[dict, dict]:
    """功能 F1 带功能点 P1，功能 F2 没有功能点。"""
    with_point = helpers.make_function(
        db, chain["project"], chain["admin"], function_name="下单", point_name="提交订单"
    )
    without_point = helpers.make_function(
        db,
        chain["project"],
        chain["admin"],
        module_name="售后模块",
        function_name="退款",
    )
    return with_point, without_point


def test_ac_89_index_shapes(db: Session):
    """索引按目标聚合，功能点表与引用图都齐。"""
    chain = helpers.build_chain(
        db, chapters=[("1 下单", "下单流程改动"), ("2 退款", "退款说明")], with_function=False
    )
    first_chapter, second_chapter = chain["chapters"]
    with_point, without_point = _setup_structure(db, chain)
    point = with_point["point"]
    analysis = helpers.make_analysis(db, chain)

    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=first_chapter.id,
        target_type="feature_point",
        target_id=point.id,
        label_type="changed",
        rationale="新增字段",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second_chapter.id,
        target_type="function",
        target_id=with_point["function"].id,
        label_type="unchanged",
        rationale="功能级无变化",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second_chapter.id,
        target_type="function",
        target_id=without_point["function"].id,
        label_type="affected",
        rationale="被退款流程牵连",
    )
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

    assert index.names[("feature_point", point.id)] == "提交订单"
    assert index.names[("function", without_point["function"].id)] == "退款"
    assert index.function_points[with_point["function"].id] == [point.id]
    assert index.chapter_links[first_chapter.id] == [second_chapter.id]

    # F1 有功能点，不单独参与；F2 没有功能点，必须参与
    assert participating_targets(index) == [
        ("function", without_point["function"].id),
        ("feature_point", point.id),
    ]

    # 功能点作用域 = 点自身结论 + 所辖功能的结论（AC-91 的证据来源）
    scoped = scoped_conclusions(index, "feature_point", point.id)
    assert {(item.target_type, item.target_id) for item in scoped} == {
        ("feature_point", point.id),
        ("function", with_point["function"].id),
    }
    assert {item.chapter_title for item in scoped} == {"1 下单", "2 退款"}

    # 没有功能点的功能只看自己
    only_function = scoped_conclusions(index, "function", without_point["function"].id)
    assert len(only_function) == 1
    assert only_function[0].label_type == "affected"


def test_ac_89_index_ignores_archived_targets(db: Session):
    """第一遍落库后目标被归档：索引里直接忽略，不参与第二遍。"""
    chain = helpers.build_chain(db, chapters=[("1 下单", "下单改动")], with_function=False)
    chapter = chain["chapters"][0]
    with_point, _ = _setup_structure(db, chain)
    analysis = helpers.make_analysis(db, chain)

    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=chapter.id,
        target_type="feature_point",
        target_id=with_point["point"].id,
    )
    with_point["module"].status = "archived"
    db.flush()

    index = build_point_index(db, analysis)

    assert index.conclusions == {}
    assert participating_targets(index) == []
