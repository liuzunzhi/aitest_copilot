"""AC-120 · JSON 解析容错（Markdown 围栏）。

真实模型必然返回带围栏的 JSON。`parse_llm_json` 是**纯函数**，
可以脱离数据库单测。

三条边界：

1. 裸 JSON 行为不变；
2. 围栏（` ```json ` / ` ``` `，大小写不敏感）与前置说明都能读出来；
3. 读不出来时抛 `LLMOutputInvalid`，**消息不含原始响应正文**。
"""

import pytest

from app.common.errors import LLMOutputInvalid
from app.llm.json_utils import parse_llm_json


def test_ac_120_plain_json_unchanged():
    """裸 JSON 行为不变。"""
    assert parse_llm_json('{"a":1}') == {"a": 1}


def test_ac_120_plain_json_with_whitespace():
    """首尾空白不影响。"""
    assert parse_llm_json('  \n {"a":1}  \n ') == {"a": 1}


def test_ac_120_json_fence():
    """带 ```json 围栏。"""
    assert parse_llm_json('```json\n{"a":1}\n```') == {"a": 1}


def test_ac_120_plain_fence():
    """无语言标记的围栏。"""
    assert parse_llm_json('```\n{"a":1}\n```') == {"a": 1}


def test_ac_120_fence_is_case_insensitive():
    """语言标记大小写不敏感。"""
    assert parse_llm_json('```JSON\n{"a":1}\n```') == {"a": 1}
    assert parse_llm_json('```Json\n{"a":1}\n```') == {"a": 1}


def test_ac_120_fence_with_spaces():
    """围栏内侧有空格也能读出来。"""
    assert parse_llm_json('```json   {"a":1}   ```') == {"a": 1}


def test_ac_120_leading_explanation():
    """前面带一句说明文字（平衡括号兜底）。"""
    assert parse_llm_json('好的，结果如下：\n{"a":1}') == {"a": 1}


def test_ac_120_leading_explanation_inside_fence():
    """围栏里也带前置说明。"""
    assert parse_llm_json('```json\n好的，结果如下：{"a":1}\n```') == {"a": 1}


def test_ac_120_nested_braces():
    """嵌套括号不能被截断。"""
    payload = {"a": {"b": [1, 2, {"c": 3}]}}
    raw = '```json\n' + '{"a": {"b": [1, 2, {"c": 3}]}}' + '\n```'

    assert parse_llm_json(raw) == payload


def test_ac_120_non_dict_payload():
    """数组也能解析——容错入口不限定形状（形状校验在调用方）。"""
    assert parse_llm_json('```json\n[1,2,3]\n```') == [1, 2, 3]


def test_ac_120_invalid_raises():
    """不是 JSON → 抛 LLMOutputInvalid。"""
    with pytest.raises(LLMOutputInvalid):
        parse_llm_json("not a json")


def test_ac_120_invalid_message_excludes_body():
    """错误消息不含原始响应正文（模型输出可能夹带敏感内容）。"""
    body = "secret-model-output-xyz"

    with pytest.raises(LLMOutputInvalid) as exc:
        parse_llm_json(body)

    assert body not in str(exc.value)


def test_ac_120_invalid_message_excludes_body_with_fence():
    """带围栏的坏内容同样不外泄。"""
    body = "```json\nsecret-model-output-xyz\n```"

    with pytest.raises(LLMOutputInvalid) as exc:
        parse_llm_json(body)

    assert "secret-model-output-xyz" not in str(exc.value)


def test_ac_120_non_string_raises():
    """不是字符串 → 也抛 LLMOutputInvalid。"""
    with pytest.raises(LLMOutputInvalid):
        parse_llm_json(None)  # type: ignore[arg-type]


def test_ac_120_does_not_smart_repair():
    """**不做智能修复**：补引号是猜测，不做。

    真实模型返回坏 JSON 时，平台要报错而不是悄悄改对——
    否则「模型返回了坏 JSON」会变成「平台悄悄改对了」，排查更难。
    """
    with pytest.raises(LLMOutputInvalid):
        parse_llm_json("{'a':1}")  # 单引号不是合法 JSON


def test_ac_120_truncated_json_raises():
    """截断的 JSON 不补全。"""
    with pytest.raises(LLMOutputInvalid):
        parse_llm_json('```json\n{"a":1\n```')
