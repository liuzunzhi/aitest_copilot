"""测试点生成引擎（07-test-points T100）。

**全部用例显式给 `MockProvider(queue=[...])`**——
Mock 默认响应的 `target_id=123` 不在真实清单里，会被当越界全丢。
这是 06 期「Mock 通过 ≠ 真实模型能跑」的同一个坑。

覆盖点：

- 坏 JSON / 缺字段 / 非数组 → **整次失败**；
- 带 Markdown 围栏的 JSON → **照常落库**（证明走 `parse_llm_json`）；
- `target_id` 越界 → **整条丢弃**并记 `TEST_POINT_TARGET_OUT_OF_BASELINE`；
- `name` 缺失 / `target_type` 非法 → **整条丢弃**并记 `TEST_POINT_INVALID`；
- `priority` 非法 → **归一到 medium**（不丢）；
- `precondition` / `verification` 缺失 → **存空串**（不丢）；
- 空章节跳过；单章失败不续跑。
"""

import json

import pytest
from sqlalchemy.orm import Session

from app.common.errors import LLMCallFailed, TestPointInvalid
from app.llm.mock import MockProvider
from app.models.document import DocumentChapter
from app.test_points.context import active_label_context, conclusion_context
from app.test_points.engine import INVALID, OUT_OF_BASELINE, run_generate
from tests.test_points.helpers import (
    build_chain,
    fenced_response,
    make_analysis,
    make_conclusion,
    make_label,
    point_response,
)


def _labels(db: Session, chain: dict) -> active_label_context:
    """给链上的功能打一条生效标签，返回标签上下文。"""
    function = chain["structure"]["function"]
    make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
    )
    return active_label_context(db, project_id=chain["project"].id)


def _run(
    db: Session,
    chain: dict,
    provider: MockProvider,
    *,
    labels=None,
    conclusions=None,
    chapters=None,
):
    return run_generate(
        db,
        provider=provider,
        template=chain["template"],
        chapters=chapters if chapters is not None else chain["chapters"],
        labels=labels if labels is not None else _labels(db, chain),
        conclusions=conclusions,
    )


# --------------------------------------------------------------- 正常路径


def test_ac_141_valid_point_is_produced(db: Session):
    """合法响应 → 产出待落库的测试点，带齐来源。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    provider = MockProvider(queue=[point_response(target_id=function.id)])
    result = _run(db, chain, provider, labels=labels)

    assert len(result.points) == 1
    point = result.points[0]
    assert point.name == "扫码登录连续失败 5 次后锁定"
    assert point.target_type == "function"
    assert point.target_id == function.id
    assert point.target_name == function.name
    assert point.priority == "high"
    assert point.chapter_id == chain["chapters"][0].id
    assert point.source_label_id is not None


def test_ac_146_fenced_json_is_accepted(db: Session):
    """带 Markdown 围栏的 JSON → 照常产出（证明走的是 `parse_llm_json`）。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    provider = MockProvider(
        queue=[fenced_response(point_response(target_id=function.id))]
    )
    result = _run(db, chain, provider, labels=labels)

    assert len(result.points) == 1
    assert result.discarded == []


def test_ac_156_prompt_contains_target_list(db: Session):
    """Prompt 里必须带清单与标签依据——不给清单模型只能瞎猜。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    provider = MockProvider(queue=[point_response(target_id=function.id)])
    _run(db, chain, provider, labels=labels)

    sent = provider.calls[0]
    assert sent.system == chain["template"].system_prompt
    assert sent.user.startswith(chain["template"].user_prompt)
    assert "## 可对照的基线目标" in sent.user
    assert f"功能#{function.id}" in sent.user
    assert "## 标签依据" in sent.user
    assert "## 章节：" in sent.user


# --------------------------------------------------------------- 整次失败


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        ("not json at all", "返回不是合法 JSON"),
        (json.dumps({"points": []}), "缺少 test_points 字段"),
        (json.dumps({"test_points": "nope"}), "test_points 必须是数组"),
    ],
)
def test_ac_145_bad_output_fails_whole_run(
    db: Session, content: str, detail: str
):
    """坏输出 → **整次失败**（抛 `TestPointInvalid`），不产出任何测试点。"""
    chain = build_chain(db)
    labels = _labels(db, chain)

    provider = MockProvider(queue=[content])
    with pytest.raises(TestPointInvalid) as exc:
        _run(db, chain, provider, labels=labels)

    assert detail in str(exc.value)


def test_ac_145_provider_error_fails_whole_run(db: Session):
    """Provider 抛错 → `LLMCallFailed`，不静默吞异常。"""
    chain = build_chain(db)
    labels = _labels(db, chain)

    class Boom(MockProvider):
        def chat(self, req):  # type: ignore[override]
            raise RuntimeError("网络断了")

    provider = Boom()
    with pytest.raises(LLMCallFailed):
        _run(db, chain, provider, labels=labels)


def test_ac_145_single_chapter_failure_stops_run(db: Session):
    """单章失败即中止，不续跑后续章节。"""
    chain = build_chain(
        db, chapters=[("第一章", "内容一"), ("第二章", "内容二")]
    )
    labels = _labels(db, chain)

    provider = MockProvider(queue=["not json"])
    with pytest.raises(TestPointInvalid):
        _run(db, chain, provider, labels=labels)

    assert len(provider.calls) == 1


# --------------------------------------------------------------- 逐条丢弃


def test_ac_144_out_of_baseline_target_is_dropped(db: Session):
    """`target_id` 不在清单 → **整条丢弃**并记越界码。"""
    chain = build_chain(db)
    labels = _labels(db, chain)

    provider = MockProvider(queue=[point_response(target_id=999999)])
    result = _run(db, chain, provider, labels=labels)

    assert result.points == []
    assert len(result.discarded) == 1
    assert result.discarded[0]["code"] == OUT_OF_BASELINE
    assert result.discarded[0]["target_id"] == 999999


def test_ac_144_only_out_of_baseline_entry_is_dropped(db: Session):
    """清单外的丢、清单内的留——逐条判定，不是整次否决。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    provider = MockProvider(
        queue=[
            point_response(
                target_id=function.id,
                extra=[{"name": "越界的", "target_type": "function", "target_id": 888888}],
            )
        ]
    )
    result = _run(db, chain, provider, labels=labels)

    assert len(result.points) == 1
    assert result.points[0].target_id == function.id
    assert len(result.discarded) == 1
    assert result.discarded[0]["code"] == OUT_OF_BASELINE


@pytest.mark.parametrize(
    "item",
    [
        {"target_type": "function", "target_id": 1},
        {"name": "", "target_type": "function", "target_id": 1},
        {"name": "缺类型", "target_id": 1},
        {"name": "类型非法", "target_type": "module", "target_id": 1},
        {"name": "缺 id", "target_type": "function"},
        {"name": "id 非数字", "target_type": "function", "target_id": "abc"},
    ],
)
def test_ac_145_invalid_entry_is_dropped(db: Session, item: dict):
    """字段不合契约 → **整条丢弃**并记 `TEST_POINT_INVALID`。"""
    chain = build_chain(db)
    labels = _labels(db, chain)

    provider = MockProvider(
        queue=[json.dumps({"test_points": [item]}, ensure_ascii=False)]
    )
    result = _run(db, chain, provider, labels=labels)

    assert result.points == []
    assert len(result.discarded) == 1
    assert result.discarded[0]["code"] == INVALID


# --------------------------------------------------------------- 归一


def test_ac_145_invalid_priority_is_normalized(db: Session):
    """`priority` 非法 → **归一到 medium**，不丢整条测试点。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    provider = MockProvider(
        queue=[point_response(target_id=function.id, priority="urgent")]
    )
    result = _run(db, chain, provider, labels=labels)

    assert len(result.points) == 1
    assert result.points[0].priority == "medium"
    assert result.discarded == []


def test_ac_145_missing_precondition_and_verification_are_emptied(db: Session):
    """缺前置条件 / 验证要点 → **存空串**，不丢。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    provider = MockProvider(
        queue=[
            json.dumps(
                {
                    "test_points": [
                        {
                            "name": "只有名字",
                            "target_type": "function",
                            "target_id": function.id,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )
    result = _run(db, chain, provider, labels=labels)

    assert len(result.points) == 1
    assert result.points[0].precondition == ""
    assert result.points[0].verification == ""
    assert result.points[0].priority == "medium"


def test_ac_145_string_target_id_is_normalized(db: Session):
    """模型把 id 写成字符串 → **归一成整数**，不丢。

    真实模型经常给 `"10096"`（带引号）。这是格式噪声，
    还原成整数就是原文——不是猜测性修复。
    """
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    provider = MockProvider(
        queue=[
            json.dumps(
                {
                    "test_points": [
                        {
                            "name": "字符串 id",
                            "target_type": "function",
                            "target_id": str(function.id),
                        }
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )
    result = _run(db, chain, provider, labels=labels)

    assert len(result.points) == 1
    assert result.points[0].target_id == function.id


# --------------------------------------------------------------- 遍历


def test_ac_141_empty_chapter_is_skipped(db: Session):
    """`char_count == 0` 的章节**不调模型**。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    empty = DocumentChapter(
        version_id=chain["version"].id,
        parent_id=None,
        seq=9,
        level=1,
        title="空章节",
        content="",
        char_count=0,
    )
    db.add(empty)
    db.flush()

    provider = MockProvider(queue=[point_response(target_id=function.id)])
    result = _run(
        db,
        chain,
        provider,
        labels=labels,
        chapters=[empty, *chain["chapters"]],
    )

    assert len(provider.calls) == 1
    assert result.skipped_empty == 1
    assert result.chapter_count == 2


def test_ac_141_duplicate_target_keeps_first(db: Session):
    """模型重复输出同一目标 → 只留第一条。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    provider = MockProvider(
        queue=[
            point_response(
                target_id=function.id,
                extra=[
                    {
                        "name": "重复的",
                        "target_type": "function",
                        "target_id": function.id,
                    }
                ],
            )
        ]
    )
    result = _run(db, chain, provider, labels=labels)

    assert len(result.points) == 1
    assert result.points[0].name == "扫码登录连续失败 5 次后锁定"


def test_ac_143_conclusion_source_is_recorded(db: Session):
    """来源增量结论会被记进测试点（可追溯）。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    analysis = make_analysis(db, chain)
    conclusion = make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="function",
        target_id=function.id,
    )
    conclusions = conclusion_context(db, analysis_id=analysis.id)

    provider = MockProvider(queue=[point_response(target_id=function.id)])
    result = _run(db, chain, provider, labels=labels, conclusions=conclusions)

    assert len(result.points) == 1
    assert result.points[0].source_conclusion_id == conclusion.id


def test_ac_143_conclusion_brief_reaches_prompt(db: Session):
    """增量结论进 Prompt 的「增量结论」段。"""
    chain = build_chain(db)
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    analysis = make_analysis(db, chain)
    make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="function",
        target_id=function.id,
    )
    conclusions = conclusion_context(db, analysis_id=analysis.id)

    provider = MockProvider(queue=[point_response(target_id=function.id)])
    _run(db, chain, provider, labels=labels, conclusions=conclusions)

    assert "## 增量结论" in provider.calls[0].user


def test_ac_145_on_chapter_callback_receives_each_chapter(db: Session):
    """`on_chapter` 每章调一次（服务层靠它逐章落库）。"""
    chain = build_chain(db, chapters=[("第一章", "内容一"), ("第二章", "内容二")])
    labels = _labels(db, chain)
    function = chain["structure"]["function"]

    seen: list[str] = []
    provider = MockProvider(
        queue=[
            point_response(target_id=function.id),
            point_response(target_id=function.id, name="第二条"),
        ]
    )
    run_generate(
        db,
        provider=provider,
        template=chain["template"],
        chapters=chain["chapters"],
        labels=labels,
        on_chapter=lambda result: seen.append(result.chapter.title),
    )

    assert seen == ["第一章", "第二章"]
