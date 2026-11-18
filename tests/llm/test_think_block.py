"""AC-121 · 推理模型思考块容错（L2 真实联调暴露）。

带推理能力的模型（MiniMax-M3 / DeepSeek-R1 / Qwen3 等）会在 `content` 里
先给一段 `<think>…</think>` 推理过程，再给答案。

**关键坑**：推理过程里经常出现 JSON 片段（模型自问自答「输出
`{"conclusions":[]}` 行不行」），所以「取第一个 `{` 到最后一个 `}`」的兜底
会从**思考块内部**的花括号起算，截出一堆垃圾。

这是纯函数，可以脱离数据库单测。
"""

import pytest

from app.common.errors import LLMOutputInvalid
from app.llm.json_utils import parse_llm_json, strip_think_block

# 真实 MiniMax-M3 响应形态（已脱敏）：思考块里含 JSON 片段
REAL_SHAPE = (
    "<think>We need compare baseline, but user didn't include baseline explicitly. "
    "Could give no conclusions? {\"conclusions\":[]} perhaps because no baseline available.\n\n"
    "Need obey schema target id number. Could use function 1.</think>\n\n"
    '{"conclusions":[{"target_type":"function","target_id":10096,'
    '"label_type":"changed","confidence":0.86,"rationale":"新增登录失败次数限制"}]}'
)


def test_ac_121_real_think_shape_parses():
    """真实响应形态：思考块 + 裸 JSON。"""
    result = parse_llm_json(REAL_SHAPE)

    assert result["conclusions"][0]["target_id"] == 10096


def test_ac_121_think_block_with_json_fragment():
    """思考块里的 JSON 片段不能被当成答案。

    这条是核心：没有「先剥思考块」的话，兜底会从思考块内部的花括号起算。
    """
    raw = (
        '<think>Could output {"conclusions":[]} perhaps.</think>\n'
        '{"conclusions":[{"target_id":7}]}'
    )

    result = parse_llm_json(raw)

    assert result["conclusions"][0]["target_id"] == 7


def test_ac_121_think_block_with_fence():
    """思考块 + Markdown 围栏。"""
    raw = '<think>先想一下 {"x":1}</think>\n```json\n{"a":1}\n```'

    assert parse_llm_json(raw) == {"a": 1}


def test_ac_121_think_and_fence_nested():
    """围栏里还有思考块。"""
    raw = '```json\n<think>推理 {"y":2}</think>\n{"a":1}\n```'

    assert parse_llm_json(raw) == {"a": 1}


def test_ac_121_think_is_case_insensitive():
    """标签大小写不敏感。"""
    raw = '<THINK>推理 {"z":3}</think>\n{"a":1}'

    assert parse_llm_json(raw) == {"a": 1}


def test_ac_121_unclosed_think_keeps_content():
    """未闭合的思考块**不剥**——剥了可能把答案一起丢掉。

    未闭合说明模型把内容都塞在 `<think>` 之后，交给围栏 / 括号兜底去试。
    """
    raw = '<think>还没说完 {"a":1}'

    # 未闭合时内容保留，括号兜底仍能读出来
    assert parse_llm_json(raw) == {"a": 1}


def test_ac_121_plain_json_unchanged():
    """裸 JSON 行为不变（无思考块时不做多余处理）。"""
    assert parse_llm_json('{"a":1}') == {"a": 1}


def test_ac_121_strip_think_block_helper():
    """剥思考块这个动作本身是纯文本操作。"""
    stripped = strip_think_block('<think>reasoning</think>\n{"a":1}')

    assert stripped.strip() == '{"a":1}'


def test_ac_121_strip_think_block_keeps_plain_text():
    """没有思考块时原样返回。"""
    assert strip_think_block('{"a":1}') == '{"a":1}'


def test_ac_121_strip_think_block_removes_multiple():
    """多个思考块都剥掉（思考块之间的普通文本保留）。"""
    raw = '<think>一</think>中间<think>二</think>{"a":1}'

    assert strip_think_block(raw).strip() == '中间{"a":1}'


def test_ac_121_invalid_message_excludes_body():
    """错误消息不含原始响应正文（模型输出可能夹带敏感内容）。"""
    body = "<think>secret-model-output-xyz</think>"

    with pytest.raises(LLMOutputInvalid) as exc:
        parse_llm_json(body)

    assert "secret-model-output-xyz" not in str(exc.value)
