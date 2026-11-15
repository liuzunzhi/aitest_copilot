"""可注入时钟。

所有「当前时间」统一从这里取，禁止直接调 `datetime.now()`：
锁定、冷却、令牌过期都必须能在测试里注入固定时间，不靠 sleep。

时间一律 UTC，不读任何时区配置——`DATETIME(3)` 字段不带时区。
"""

from datetime import datetime, timedelta, timezone


class Clock:
    """默认时钟：返回 UTC 当前时间。"""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock(Clock):
    """测试用固定时钟，可手动推进。"""

    def __init__(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("FixedClock 必须是带时区的时间（UTC）")
        self._value = value

    def now(self) -> datetime:
        return self._value

    def advance(self, delta: timedelta) -> None:
        self._value += delta


# 进程级单例。测试通过 monkeypatch 替换为 FixedClock。
clock: Clock = Clock()


def now() -> datetime:
    """当前 UTC 时间。"""
    return clock.now()


__all__ = ["Clock", "FixedClock", "clock", "now"]
