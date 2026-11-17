"""模型供应商抽象。

本期只有 `MockProvider` 一个实现，**不写任何真实网络调用**。
后续接真实模型时新增一个实现类，并只在 `get_provider()` 里分支，
第一遍引擎（`app/incremental/engine.py`）不需要改动。
"""

from typing import TYPE_CHECKING, Protocol

from app.llm.schemas import LLMRequest, LLMResponse

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型
    from app.llm.mock import MockProvider


class LLMProvider(Protocol):
    """供应商协议：一个名字 + 一次对话。"""

    name: str

    def chat(self, req: LLMRequest) -> LLMResponse: ...


_default_provider: "MockProvider | None" = None


def get_provider() -> LLMProvider:
    """获取当前供应商（本期固定 Mock）。

    单例返回：同一进程内 `calls` 持续累积，便于排查；
    测试通过 `app.dependency_overrides[get_provider]` 换成自己的实例。
    """
    global _default_provider
    if _default_provider is None:
        from app.llm.mock import MockProvider

        _default_provider = MockProvider()
    return _default_provider


__all__ = ["LLMProvider", "get_provider"]
