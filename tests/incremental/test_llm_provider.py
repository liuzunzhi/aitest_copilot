"""LLM 抽象层（T68 / 06-T84）。

Mock 的可观察契约：`calls` 记录请求、`queue` 依次返回、`raw` 回带请求。

06 期（T84）后这里多了两件事：

- `get_provider` 改成查库工厂（无配置 → Mock 单例；有配置 → 真实 Provider）；
- 原来「代码里不出现 httpx」这条静态守卫**改写**为「真实 Provider 必须走
  `transport` 注入」——06 期引入了真实供应商，但**断网可跑**的守卫意图
  不能丢：真实网络调用只允许发生在注入了 `transport` 的实例上，
  测试层一律 `httpx.MockTransport`，零真实 socket。
"""

import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

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


def test_ac_84_get_provider_is_mock_singleton(db: Session):
    """工厂无默认配置时返回 Mock 单例（06 期 T84 后要传 session）。

    `llm_providers` 表为空 → 降级 Mock，且同进程复用同一实例。
    """
    provider = get_provider(db)

    assert provider is get_provider(db)
    assert provider.name == "mock"
    assert isinstance(provider, MockProvider)


def test_ac_84_no_real_network_code():
    """真实 Provider 必须走 `transport` 注入，测试层零真实 socket。

    06 期引入了真实大模型供应商，但**断网可跑**是本期红线。这条守卫
    改写成两条可执行的断言：

    1. `OpenAICompatProvider` 的构造函数**强制要求** `transport` 可注入，
       且不注入时也不会被测试意外调用——生产路径由工厂注入配置，
       测试路径一律 `httpx.MockTransport`；
    2. `app/` 下**除** `openai_compat.py` 外不出现任何真实网络客户端
       （`requests` / `openai` SDK / 裸 `urlopen`），
       `app/incremental/` 更是完全不碰 HTTP。
    """
    source = (ROOT / "app" / "llm" / "openai_compat.py").read_text(encoding="utf-8")

    # 1) Provider 必须支持注入 transport，且真实调用点走的就是它
    assert "transport: httpx.BaseTransport | None = None" in source
    assert "httpx.Client(timeout=timeout, transport=self._transport)" in source

    # 2) 其余代码零真实网络客户端
    pattern = re.compile(r"\b(requests|openai|urlopen)\b")
    roots = (ROOT / "app" / "llm", ROOT / "app" / "incremental")
    offenders = [
        str(path.relative_to(ROOT))
        for root in roots
        for path in root.rglob("*.py")
        if path.name != "openai_compat.py"
        and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_ac_84_tests_never_use_real_socket():
    """测试目录里不许出现真实 HTTP 客户端——全部用 `httpx.MockTransport`。

    这是「任何一条测试都不允许产生真实 socket」这条红线的守卫：
    测试要造 HTTP 行为，只能走 MockTransport。
    """
    pattern = re.compile(r"\b(requests\.|urlopen\(|aiohttp|socket\.socket)")
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests").rglob("*.py")
        # 本文件自己带着这些字面量（正则），扫自己会误报
        if path.name != "test_llm_provider.py"
        and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
