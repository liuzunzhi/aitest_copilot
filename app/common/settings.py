"""system_settings 读取与写入。

配置是「高频读、极少写」，所以进程内缓存 60s；
写入后立即失效缓存，管理员改开关不需要等 TTL 到点。

缓存是进程内的：多进程部署时其他进程最多滞后 60s，这是明确接受的代价，
换来的是一次读配置不进数据库。
"""

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import session_scope
from app.models.system import SystemSetting

CACHE_TTL_SECONDS = 60

# key -> (过期时刻 monotonic, 值)
_cache: dict[str, tuple[float, Any]] = {}


def get_setting(key: str, session: Session | None = None) -> Any:
    """读取配置项。

    传入 `session` 时复用调用方事务；不传则自建短会话。
    配置项缺失抛 `KeyError`——种子迁移保证 6 个键一定存在，
    读到空值说明库结构或种子被破坏，不能静默返回 None。
    """
    cached = _cache.get(key)
    now = time.monotonic()
    if cached is not None and cached[0] > now:
        return cached[1]

    if session is None:
        with session_scope() as own_session:
            value = _read(own_session, key)
    else:
        value = _read(session, key)

    _cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, value)
    return value


def set_setting(
    session: Session, key: str, value: Any, updated_by: int | None = None
) -> None:
    """写入配置并立即失效缓存。事务由调用方控制。"""
    setting = session.get(SystemSetting, key)
    if setting is None:
        session.add(SystemSetting(key=key, value=value, updated_by=updated_by))
    else:
        setting.value = value
        setting.updated_by = updated_by

    session.flush()
    invalidate(key)


def invalidate(key: str) -> None:
    """失效单个配置项的缓存。"""
    _cache.pop(key, None)


def cache_clear() -> None:
    """清空全部缓存。进程启动与测试用。"""
    _cache.clear()


def _read(session: Session, key: str) -> Any:
    value = session.execute(
        select(SystemSetting.value).where(SystemSetting.key == key)
    ).scalar_one_or_none()
    if value is None:
        raise KeyError(f"system_settings 缺少配置项：{key}")
    return value


__all__ = [
    "CACHE_TTL_SECONDS",
    "cache_clear",
    "get_setting",
    "invalidate",
    "set_setting",
]
