"""测试点用例夹具：把 LLM 供应商换成可编程的 Mock。"""

import pytest

from app.llm.mock import MockProvider
from app.llm.provider import get_provider
from app.main import app as fastapi_app


@pytest.fixture
def provider() -> MockProvider:
    """测试专用 Mock；`client` 夹具收尾时会清空所有依赖覆盖。

    **注意**：Mock 的默认响应里 `target_id=123`，不在真实清单里，
    会被全被当越界丢弃。断言落库条数的用例必须显式给 `queue`
    （用 `helpers.point_response(target_id=真实id)`）。
    """
    mock = MockProvider()
    fastapi_app.dependency_overrides[get_provider] = lambda: mock
    return mock
