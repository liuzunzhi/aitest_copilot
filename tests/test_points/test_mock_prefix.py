"""Mock Provider 的测试点前缀分支（07-test-points T100）。

07 期给 Mock 加了 `[TEST_POINT_SYSTEM]` 分支——**只影响这一个前缀**，
既有三个分支（第一遍 / 第二遍 / 文档推导）的行为一个字节没变。
这条用例把「既有分支不受影响」钉死。
"""

import json

from app.llm.mock import (
    DEFAULT_RESPONSE,
    DERIVE_DEFAULT_RESPONSE,
    DERIVE_SYSTEM_PREFIX,
    SECOND_PASS_DEFAULT_RESPONSE,
    SECOND_PASS_SYSTEM_PREFIX,
    TEST_POINT_DEFAULT_RESPONSE,
    TEST_POINT_SYSTEM_PREFIX,
    MockProvider,
)
from app.llm.schemas import LLMRequest


def test_ac_146_test_point_prefix_returns_test_point_payload():
    """`[TEST_POINT_SYSTEM]` 前缀 → 返回测试点结构的 JSON。"""
    provider = MockProvider()

    response = provider.chat(
        LLMRequest(system=f"{TEST_POINT_SYSTEM_PREFIX} 你是测试设计助手。", user="u")
    )

    payload = json.loads(response.content)
    assert "test_points" in payload
    assert payload["test_points"][0]["target_type"] == "function"
    # 占位符 id：真实 id 由 Prompt 里的清单给出
    assert payload["test_points"][0]["target_id"] == 123


def test_ac_146_existing_prefixes_are_unchanged():
    """既有三个分支的行为**一个字节没变**（07 期只加新分支）。"""
    provider = MockProvider()

    first = provider.chat(LLMRequest(system="随便什么 system", user="u"))
    second = provider.chat(
        LLMRequest(system=f"{SECOND_PASS_SYSTEM_PREFIX} x", user="u")
    )
    third = provider.chat(
        LLMRequest(system=f"{DERIVE_SYSTEM_PREFIX} x", user="u")
    )

    assert first.content == DEFAULT_RESPONSE
    assert second.content == SECOND_PASS_DEFAULT_RESPONSE
    assert third.content == DERIVE_DEFAULT_RESPONSE


def test_ac_146_queue_takes_precedence_over_prefix():
    """显式给的 `queue` 优先于前缀分支——用例可以精确控制模型输出。"""
    provider = MockProvider(queue=['{"test_points": []}'])

    response = provider.chat(
        LLMRequest(system=f"{TEST_POINT_SYSTEM_PREFIX} x", user="u")
    )

    assert json.loads(response.content) == {"test_points": []}


def test_ac_146_test_point_default_response_is_valid_json():
    """默认响应必须是合法 JSON（否则引擎的容错解析也救不了它）。"""
    payload = json.loads(TEST_POINT_DEFAULT_RESPONSE)
    assert isinstance(payload["test_points"], list)
    assert payload["test_points"]
