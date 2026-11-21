"""Mock Provider 的测试用例前缀分支（08-test-case-analysis T105 / AC-179）。

08 期给 Mock 加了 `[TEST_CASE_SYSTEM]` 分支——**只影响这一个前缀**，
既有五个分支（第一遍 / 第二遍 / 文档推导 / 测试点 / 默认）的行为一个字节没变。
第二条用例把「既有分支不受影响」钉死，这是断网红线的一部分：
全量套件不产生任何真实 socket，靠的就是 Mock 的确定性返回。
"""

import json

from app.llm.mock import (
    DEFAULT_RESPONSE,
    DERIVE_DEFAULT_RESPONSE,
    DERIVE_SYSTEM_PREFIX,
    SECOND_PASS_DEFAULT_RESPONSE,
    SECOND_PASS_SYSTEM_PREFIX,
    TEST_CASE_DEFAULT_RESPONSE,
    TEST_CASE_SYSTEM_PREFIX,
    TEST_POINT_DEFAULT_RESPONSE,
    TEST_POINT_SYSTEM_PREFIX,
    MockProvider,
)
from app.llm.schemas import LLMRequest


def test_ac_179_test_case_prefix_returns_cases_payload():
    """`[TEST_CASE_SYSTEM]` 前缀 → 返回用例结构的 JSON，且带步骤。"""
    provider = MockProvider()

    response = provider.chat(
        LLMRequest(system=f"{TEST_CASE_SYSTEM_PREFIX} 你是用例设计助手。", user="u")
    )

    payload = json.loads(response.content)
    assert len(payload["cases"]) == 1
    case = payload["cases"][0]
    assert case["title"]
    assert case["case_type"] == "functional"
    assert len(case["steps"]) == 2
    # 输出契约里没有测试点 id：绑定由服务端完成
    assert "test_point_id" not in case


def test_ac_179_existing_prefixes_are_unchanged():
    """既有分支的行为**一个字节没变**（08 期只加新分支）。"""
    provider = MockProvider()

    first = provider.chat(LLMRequest(system="随便什么 system", user="u"))
    second = provider.chat(
        LLMRequest(system=f"{SECOND_PASS_SYSTEM_PREFIX} x", user="u")
    )
    third = provider.chat(LLMRequest(system=f"{DERIVE_SYSTEM_PREFIX} x", user="u"))
    fourth = provider.chat(
        LLMRequest(system=f"{TEST_POINT_SYSTEM_PREFIX} x", user="u")
    )

    assert first.content == DEFAULT_RESPONSE
    assert second.content == SECOND_PASS_DEFAULT_RESPONSE
    assert third.content == DERIVE_DEFAULT_RESPONSE
    assert fourth.content == TEST_POINT_DEFAULT_RESPONSE


def test_ac_179_queue_takes_precedence_over_prefix():
    """显式给的 `queue` 优先于前缀分支——用例可以精确控制模型输出。"""
    provider = MockProvider(queue=['{"cases": []}'])

    response = provider.chat(
        LLMRequest(system=f"{TEST_CASE_SYSTEM_PREFIX} x", user="u")
    )

    assert json.loads(response.content) == {"cases": []}
    assert provider.calls, "每次 chat 都要留下一条请求，供 Prompt 断言"


def test_ac_179_test_case_default_response_is_valid_json():
    """默认响应必须是合法 JSON，且字段都能通过服务端校验（不靠容错解析兜底）。"""
    payload = json.loads(TEST_CASE_DEFAULT_RESPONSE)
    assert isinstance(payload["cases"], list)
    assert payload["cases"]

    case = payload["cases"][0]
    assert case["priority"] in {"high", "medium", "low"}
    assert case["case_type"] in {"functional", "api", "ui"}
    assert case["steps"]
    for step in case["steps"]:
        assert step["action"]
        assert step["expected"]
