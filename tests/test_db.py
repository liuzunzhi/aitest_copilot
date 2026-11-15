"""数据库引擎与 UTC 强制（T03）。

核心断言：任何一条物理连接的会话时区都是 +00:00。
这是 AC-04 账号锁定、AC-22 驳回冷却正确性的前提。
"""

import pytest
from sqlalchemy import text

from app.common.db import get_engine, reset_engine, session_scope


@pytest.fixture(autouse=True)
def _clean_engine():
    reset_engine()
    yield
    reset_engine()


def test_session_timezone():
    """会话时区必须是 +00:00。"""
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT @@session.time_zone")).scalar() == "+00:00"


def test_now_equals_utc_timestamp():
    """比时区字符串更直接的判断：数据库当前时间就是 UTC 时间。"""
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT NOW(3) = UTC_TIMESTAMP(3)")).scalar() == 1


def test_new_physical_connection_also_utc():
    """监听器要挂在每次连接建立上，不只是第一条。"""
    engine = get_engine()
    with engine.connect():
        pass
    engine.dispose()  # 丢弃池中连接，下一次必然新建物理连接

    with engine.connect() as conn:
        assert conn.execute(text("SELECT @@session.time_zone")).scalar() == "+00:00"


def test_session_scope_commits():
    with session_scope() as session:
        assert session.execute(text("SELECT 1")).scalar() == 1


def test_pool_pre_ping_enabled():
    assert get_engine().pool._pre_ping is True
