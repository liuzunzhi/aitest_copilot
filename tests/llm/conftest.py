"""06 期（T84）用例的公共夹具。

**断网红线**：任何一条测试都不允许产生真实 socket。
所有要造 HTTP 行为的用例一律用 `httpx.MockTransport`。
"""

import pytest
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.llm.crypto import encrypt
from app.llm.mock import MockProvider
from app.llm.provider import get_provider
from app.main import app as fastapi_app
from app.models.llm import LLMProviderConfig

# 假的 API Key——测试里出现它是安全的（不会真发出去），
# 但**不要**把它写进任何断言失败信息里。
FAKE_KEY = "sk-test-supersecret-1234"


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """用例结束后清掉 `get_settings` 缓存。

    改主密钥的用例会动这个缓存；不清的话会漏给后面的用例。
    """
    yield
    get_settings.cache_clear()


@pytest.fixture
def provider() -> MockProvider:
    """测试专用 Mock 供应商。

    与 `tests/incremental/conftest.py` 同款：把 `get_provider` 依赖
    换成可编程的 Mock，让用例能控制模型返回。
    """
    mock = MockProvider()
    fastapi_app.dependency_overrides[get_provider] = lambda: mock
    try:
        yield mock
    finally:
        fastapi_app.dependency_overrides.pop(get_provider, None)


@pytest.fixture
def make_provider(db: Session):
    """在库里造一条大模型配置，返回造出来的行。

    默认 `is_default=1`、`status='active'`，正好是工厂认的那条。
    API Key 只以**密文**落库——这是 AC-105 的前提。
    """

    def _make(
        *,
        name: str = "测试配置",
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        api_key: str = FAKE_KEY,
        timeout_seconds: int = 60,
        status: str = "active",
        is_default: int = 1,
    ) -> LLMProviderConfig:
        row = LLMProviderConfig(
            name=name,
            provider_type="openai_compat",
            base_url=base_url,
            api_key_ciphertext=encrypt(api_key),
            api_key_last4=api_key[-4:],
            model=model,
            timeout_seconds=timeout_seconds,
            status=status,
            is_default=is_default,
            created_by=1,
        )
        db.add(row)
        db.flush()
        return row

    return _make
