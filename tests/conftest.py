"""测试公共夹具。"""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.common.db import get_engine


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
