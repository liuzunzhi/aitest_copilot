"""数据库引擎与会话管理。

所有物理连接建立后强制切换到 UTC，避免 DATETIME 字段写进本地时间。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.common.config import get_settings

UTC_SQL = "SET time_zone = '+00:00'"

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """ORM 基类。所有模型继承它。"""


@event.listens_for(Engine, "connect")
def _force_utc(dbapi_connection: Any, connection_record: Any) -> None:
    """每条物理连接建立后立即设置会话时区。

    容器默认时区恰好是 UTC，但这是巧合：一旦镜像或部署环境改了 TZ，
    NOW() 写入的时间会整体偏移且不会报错。所以这里显式设置，
    不依赖任何外部时区配置。
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(UTC_SQL)
    finally:
        cursor.close()


def get_engine() -> Engine:
    """获取引擎单例。"""
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().db_dsn,
            pool_pre_ping=True,
            pool_recycle=3600,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """获取会话工厂单例。"""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务上下文：正常提交，异常回滚。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话。事务由 service 层控制。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    """测试用：释放连接池并清空单例。"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
