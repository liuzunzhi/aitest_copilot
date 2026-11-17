"""LLM 抽象层（T68）。

Mock 的可观察契约：`calls` 记录请求、`queue` 依次返回、`raw` 回带请求。
AC-84 的静态部分：本期代码里不存在真实网络调用。
"""

import json
import re
from pathlib import Path

from app.llm import MockProvider, get_provider
from app.llm.schemas import LLMRequest

ROOT = Path(__file__).resolve().parents[2]


def test_ac_84_mock_default_and_calls():
    """默认返回空结论，`calls` 与 `raw` 能拿到收到的 Prompt。"""
    provider = MockProvider()

    response = provider.chat(LLMRequest(system="系统提示词", user="用户提示词"))

    assert json.loads(response.content) == {"conclusions": []}
    assert provider.calls == [LLMRequest(system="系统提示词", user="用户提示词")]
    assert response.raw["request"]["system"] == "系统提示词"
    assert response.raw["request"]["user"] == "用户提示词"
    assert response.raw["index"] == 0
    assert response.model == "mock"


def test_ac_84_queue_preset_order_and_fallback():
    """`queue` 先入先出，用尽后回落到默认返回；index 逐次递增。"""
    provider = MockProvider(
        queue=['{"conclusions": [{"target_id": 1}]}', '{"conclusions": [{"target_id": 2}]}']
    )

    first = provider.chat(LLMRequest(system="s", user="u1"))
    second = provider.chat(LLMRequest(system="s", user="u2"))
    third = provider.chat(LLMRequest(system="s", user="u3"))

    assert json.loads(first.content)["conclusions"][0]["target_id"] == 1
    assert json.loads(second.content)["conclusions"][0]["target_id"] == 2
    assert json.loads(third.content) == {"conclusions": []}
    assert [call.user for call in provider.calls] == ["u1", "u2", "u3"]
    assert [resp.raw["index"] for resp in (first, second, third)] == [0, 1, 2]


def test_ac_84_get_provider_is_mock_singleton():
    """工厂当前只产出 Mock，且同进程内复用同一实例。"""
    provider = get_provider()

    assert provider is get_provider()
    assert provider.name == "mock"
    assert isinstance(provider, MockProvider)


def test_ac_84_no_real_network_code():
    """本期代码里不出现真实模型 / HTTP 客户端调用。"""
    pattern = re.compile(r"\b(httpx|requests|openai)\b")
    roots = (ROOT / "app" / "llm", ROOT / "app" / "incremental")
    offenders = [
        str(path.relative_to(ROOT))
        for root in roots
        for path in root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
