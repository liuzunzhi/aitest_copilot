"""测试公共夹具。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import get_db, get_engine
from app.main import app as fastapi_app
from app.models.llm import LLMProviderConfig


@pytest.fixture
def db() -> Iterator[Session]:
    """绑定在外层事务上的会话。

    用例内的写入通过 savepoint 提交，用例结束后外层事务整体回滚，
    不会污染开发库中已提交的数据。
    """
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _isolate_llm_providers(db: Session):
    """用例期间**屏蔽** `llm_providers` 里的真实配置。

    **断网红线**：任何一条测试都不允许产生真实 socket。

    开发库里可能配着真的 MiniMax / DeepSeek 配置（管理员在系统设置页
    存进去的）。`get_provider` 查库拿到它就会真的发 HTTP 请求——
    既慢又不确定，还可能把测试数据发到外部服务。

    所以每个用例开始前把默认配置行临时摘掉：需要测真实 Provider 的用例
    自己用 `make_provider` 夹具造一条（密文 + 假 Key），不依赖开发库。
    用例结束后外层事务回滚，配置自动还原。
    """
    rows = db.scalars(
        select(LLMProviderConfig).where(LLMProviderConfig.is_default == 1)
    ).all()
    if not rows:
        yield
        return

    for row in rows:
        db.delete(row)
    db.flush()
    yield


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """走真实 HTTP 栈的客户端，数据库依赖指向用例会话。"""
    fastapi_app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(fastapi_app) as test_client:
            yield test_client
    finally:
        fastapi_app.dependency_overrides.clear()
