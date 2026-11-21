"""测试用例夹具：把 LLM 供应商换成可编程的 Mock。"""

import pytest

from app.llm.mock import MockProvider
from app.llm.provider import get_provider
from app.main import app as fastapi_app


@pytest.fixture
def provider() -> MockProvider:
    """测试专用 Mock；`client` 夹具收尾时会清空所有依赖覆盖。

    **注意**：Mock 的默认用例响应是固定的一条「mock 生成用例」，
    不会命中任何测试点 id——但 08 的输出契约里本来就没有 id，
    服务端按「当前测试点」绑定，默认响应可直接用。
    需要多条 / 特定字段时显式给 `queue`。
    """
    mock = MockProvider()
    fastapi_app.dependency_overrides[get_provider] = lambda: mock
    return mock
