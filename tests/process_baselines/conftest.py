"""流程基线的测试夹具（10-process-baseline）。

`engine` 夹具是**只读**的结构检查用引擎：断言「某表有没有某道外键」
不该占用 `db` 夹具的嵌套事务（写操作才有事务可言）。
"""

import pytest
from sqlalchemy.engine import Engine

from app.common.db import get_engine


@pytest.fixture(scope="module")
def engine() -> Engine:
    """只读用的引擎：结构断言不写入，也不吃 `db` 夹具的事务。"""
    return get_engine()
