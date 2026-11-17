"""T73 · 2b-2 按点分治（AC-89 / AC-90 / AC-91）。

全部走 `MockProvider`：不预设队列时第二遍默认返回 `unchanged`，
需要特定返回（新增功能点、非法输出）时用 `queue` 预设。
"""

import json
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.common.errors import LLMCallFailed, LLMOutputInvalid
from app.incremental.second_pass import run_point_pass
from app.llm.mock import (
    DEFAULT_RESPONSE,
    SECOND_PASS_DEFAULT_RESPONSE,
    MockProvider,
)
from app.llm.schemas import LLMRequest
from tests.incremental import helpers


class _BrokenProvider:
    """模拟供应商异常，用于断言 LLM_CALL_FAILED。"""

    name = "broken"

    def chat(self, req: LLMRequest):
        raise RuntimeError("连接被拒绝")


def _chain(db: Session, chapters=None):
    return helpers.build_chain(
        db,
        chapters=chapters or [("1 下单", "下单流程改动"), ("2 退款", "退款说明")],
        with_function=False,
    )


def _consistent_point(db: Session, chain: dict) -> dict:
    structure = helpers.make_function(
        db, chain["project"], chain["admin"], function_name="下单", point_name="提交订单"
    )
    return structure


def test_ac_89_small_input_and_call_count(db: Session):
    """只有证据一致的目标调模型；Prompt 只带当前目标的局部结论。"""
    chain = _chain(db)
    first_chapter, second_chapter = chain["chapters"]
    with_point = _consistent_point(db, chain)
    other = helpers.make_function(
        db, chain["project"], chain["admin"], module_name="售后模块", function_name="退款"
    )
    analysis = helpers.make_analysis(db, chain)

    # P1 两章结论一致 → 调模型
    for chapter in (first_chapter, second_chapter):
        helpers.make_conclusion(
            db,
            analysis,
            chapter_id=chapter.id,
            target_type="feature_point",
            target_id=with_point["point"].id,
            label_type="changed",
        )
    # F2 两章结论矛盾 → 不调模型
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=first_chapter.id,
        target_type="function",
        target_id=other["function"].id,
        label_type="changed",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=second_chapter.id,
        target_type="function",
        target_id=other["function"].id,
        label_type="unchanged",
    )
    db.flush()

    provider = MockProvider()
    template = helpers.second_pass_template(db)
    result = run_point_pass(db, analysis=analysis, provider=provider, template=template)

    assert result.point_count == 2
    assert result.prompted_count == 1
    assert len(provider.calls) == 1

    call = provider.calls[0]
    assert call.system == template.system_prompt
    assert call.user.startswith(template.user_prompt)
    assert "## 功能点：提交订单" in call.user
    assert "1 下单" in call.user and "2 退款" in call.user
    # 不带其他目标：不出现另一个目标的锚点与 id
    assert "## 功能：退款" not in call.user
    assert str(other["function"].id) not in call.user

    assert len(result.decisions) == 1
    decision = result.decisions[0]
    assert decision.target_type == "feature_point"
    assert decision.target_id == with_point["point"].id
    assert decision.decision == "unchanged"
    assert decision.confidence == Decimal("0.5")
    assert decision.evidence["propagated_from"] == []
    assert len(decision.evidence["chapter_ids"]) == 2
    assert len(decision.evidence["conclusion_ids"]) == 2

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.conflict_type == "conflict"
    assert conflict.target_id == other["function"].id
    assert {item["label_type"] for item in conflict.candidates} == {"changed", "unchanged"}


def test_ac_91_function_level_evidence_exposes_conflict(db: Session):
    """功能级 changed + 点级 unchanged → 点作用域内直接冲突，不调模型。"""
    chain = _chain(db)
    with_point = _consistent_point(db, chain)
    analysis = helpers.make_analysis(db, chain)

    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="function",
        target_id=with_point["function"].id,
        label_type="changed",
        rationale="功能整体改写",
    )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][1].id,
        target_type="feature_point",
        target_id=with_point["point"].id,
        label_type="unchanged",
        rationale="流程未变",
    )
    db.flush()

    provider = MockProvider()
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=provider,
        template=helpers.second_pass_template(db),
    )

    assert provider.calls == []
    assert result.decisions == []
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.target_type == "feature_point"
    assert conflict.target_id == with_point["point"].id
    assert conflict.conflict_type == "conflict"
    labels = {item["label_type"]: item for item in conflict.candidates}
    assert set(labels) == {"changed", "unchanged"}
    assert labels["changed"]["source"] == "point_pass"


def test_ac_90_new_points_only_in_conflicts(db: Session):
    """new_points 只进 `new` 冲突：无 target_id，候选带 new 标签。"""
    chain = _chain(db)
    with_point = _consistent_point(db, chain)
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="feature_point",
        target_id=with_point["point"].id,
    )
    db.flush()

    provider = MockProvider(
        queue=[
            json.dumps(
                {
                    "decision": "changed",
                    "confidence": 0.9,
                    "rationale": "新增了退款审核",
                    "new_points": [{"name": "退款审核", "rationale": "文档新增"}],
                },
                ensure_ascii=False,
            )
        ]
    )
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=provider,
        template=helpers.second_pass_template(db),
    )

    assert [item.decision for item in result.decisions] == ["changed"]
    assert len(result.conflicts) == 1
    new_conflict = result.conflicts[0]
    assert new_conflict.conflict_type == "new"
    assert new_conflict.target_type == "feature_point"
    assert new_conflict.target_id is None
    assert new_conflict.target_name == "退款审核"
    assert new_conflict.candidates[0]["label_type"] == "new"


def test_ac_90_new_points_deduped_across_targets(db: Session):
    """不同目标报出同名新增 → 只留一条，理由合并。"""
    chain = _chain(db)
    with_point = _consistent_point(db, chain)
    other = helpers.make_function(
        db, chain["project"], chain["admin"], module_name="售后模块", function_name="退款"
    )
    analysis = helpers.make_analysis(db, chain)
    for chapter in chain["chapters"]:
        helpers.make_conclusion(
            db,
            analysis,
            chapter_id=chapter.id,
            target_type="feature_point",
            target_id=with_point["point"].id,
        )
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="function",
        target_id=other["function"].id,
        label_type="affected",
    )
    db.flush()

    provider = MockProvider(
        queue=[
            json.dumps(
                {
                    "decision": "changed",
                    "new_points": [{"name": "退款审核", "rationale": "来自下单"}],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "decision": "affected",
                    "new_points": [{"name": "退款审核", "rationale": "来自退款"}],
                },
                ensure_ascii=False,
            ),
        ]
    )
    result = run_point_pass(
        db,
        analysis=analysis,
        provider=provider,
        template=helpers.second_pass_template(db),
    )

    assert result.prompted_count == 2
    assert len(result.conflicts) == 1
    assert len(result.conflicts[0].candidates) == 2


def test_second_pass_invalid_output_fails(db: Session):
    """decision 不在三值内 → LLM_OUTPUT_INVALID。"""
    chain = _chain(db)
    with_point = _consistent_point(db, chain)
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="feature_point",
        target_id=with_point["point"].id,
    )
    db.flush()

    provider = MockProvider(queue=[json.dumps({"decision": "new"})])
    with pytest.raises(LLMOutputInvalid) as exc:
        run_point_pass(
            db,
            analysis=analysis,
            provider=provider,
            template=helpers.second_pass_template(db),
        )
    assert exc.value.code == "LLM_OUTPUT_INVALID"


def test_second_pass_provider_error_is_call_failed(db: Session):
    """供应商抛错 → LLM_CALL_FAILED。"""
    chain = _chain(db)
    with_point = _consistent_point(db, chain)
    analysis = helpers.make_analysis(db, chain)
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="feature_point",
        target_id=with_point["point"].id,
    )
    db.flush()

    with pytest.raises(LLMCallFailed):
        run_point_pass(
            db,
            analysis=analysis,
            provider=_BrokenProvider(),
            template=helpers.second_pass_template(db),
        )


def test_mock_default_responses_split_by_prompt_type():
    """Mock 默认响应按 system 前缀区分：第一遍空结论，第二遍 unchanged。"""
    provider = MockProvider()

    first = provider.chat(LLMRequest(system="[INCREMENTAL_SYSTEM] 第一遍", user="章节"))
    assert first.content == DEFAULT_RESPONSE

    second = provider.chat(LLMRequest(system="[INCREMENTAL_2B_SYSTEM] 第二遍", user="目标"))
    assert second.content == SECOND_PASS_DEFAULT_RESPONSE
    assert json.loads(second.content)["decision"] == "unchanged"
