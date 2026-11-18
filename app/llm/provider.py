"""模型供应商工厂。

解析顺序（spec §6.1）：

    get_provider(session)
      1. 查 `llm_providers`：`status='active'` AND `is_default=1`（最多一条）
      2. 查不到 → 返回进程内 MockProvider 单例（**行为与改造前完全一致**）
      3. 查到 → 解密 Key → OpenAICompatProvider

**先降级、后接真**不是妥协，而是**安全阀**：没有配置、用户没配就发分析，
平台仍然能跑（和今天一模一样），不会因为新功能把 05 打挂。

**配置读取不缓存**：每次 `get_provider` 都查一次库。单表 + 唯一索引，
查询成本可忽略；换来的是「管理员改完配置立即生效」，不用处理缓存一致性。

**解密失败不降级**：抛 `LLMConfigInvalid`（500）——配置坏了必须让人知道，
否则线上会用 Mock 跑出一堆空结论却没人发现。

`get_provider` 一直是 FastAPI 依赖，测试通过
`dependency_overrides[get_provider] = lambda: mock` 覆盖它。
覆盖后 FastAPI **不会执行原函数体**，所以签名变化对现有用例零影响。
"""

from typing import TYPE_CHECKING, Protocol

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.llm.crypto import decrypt
from app.llm.schemas import LLMRequest, LLMResponse

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型
    from app.llm.mock import MockProvider


class LLMProvider(Protocol):
    """供应商协议：一个名字 + 一次对话。"""

    name: str

    def chat(self, req: LLMRequest) -> LLMResponse: ...


_default_provider: "MockProvider | None" = None


def load_default_config(session: Session):
    """取默认配置行（`active` + `is_default=1`），没有则返回 None。

    由唯一索引 `uk_llmprov_default` 保证最多一条。
    """
    from app.models.llm import LLMProviderConfig

    return session.scalar(
        select(LLMProviderConfig)
        .where(
            LLMProviderConfig.status == "active",
            LLMProviderConfig.is_default == 1,
        )
        .limit(1)
    )


def _mock_singleton() -> "MockProvider":
    """进程内 Mock 单例。

    同进程复用同一实例：现有测试 `test_ac_84_get_provider_is_mock_singleton`
    依赖这一点，且排查问题时 `calls` 持续累积更好用。
    """
    global _default_provider
    if _default_provider is None:
        from app.llm.mock import MockProvider

        _default_provider = MockProvider()
    return _default_provider


def get_provider(session: Session = Depends(get_db)) -> LLMProvider:
    """获取当前供应商。

    无默认配置 → Mock；解密失败 → 抛 `LLMConfigInvalid`（**不降级**）。
    """
    config = load_default_config(session)
    if config is None:
        return _mock_singleton()

    from app.llm.openai_compat import OpenAICompatProvider

    api_key = decrypt(config.api_key_ciphertext)
    return OpenAICompatProvider.from_config(config, api_key)


__all__ = ["LLMProvider", "get_provider", "load_default_config"]
