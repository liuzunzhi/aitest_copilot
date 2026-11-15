"""测试公共夹具。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.db import get_db, get_engine
from app.main import app as fastapi_app


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


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """走真实 HTTP 栈的客户端，数据库依赖指向用例会话。"""
    fastapi_app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(fastapi_app) as test_client:
            yield test_client
    finally:
        fastapi_app.dependency_overrides.clear()
