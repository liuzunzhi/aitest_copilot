"""时钟与密码哈希（T09）。

耗时对齐的用例是 AC-02 的前提：若「用户不存在」分支不跑 bcrypt，
攻击者能用响应时间区分账号是否存在，三种失败响应一致就名存实亡。
"""

import time
from datetime import datetime, timedelta, timezone

import pytest

from app.common import clock as clock_module
from app.common.clock import Clock, FixedClock
from app.common.config import get_settings
from app.common.security import DUMMY_HASH, hash_password, verify_password

ROUNDS = 3
# bcrypt 单次校验耗时存在小幅抖动，同机器上 35% 的相对误差足够稳定
TIMING_TOLERANCE = 0.35


def test_clock_returns_utc():
    """默认时钟必须带 UTC 时区，且接近系统当前时间。"""
    current = Clock().now()

    assert current.tzinfo is not None
    assert current.utcoffset() == timedelta(0)
    assert abs((clock_module.now() - current).total_seconds()) < 5


def test_fixed_clock(monkeypatch):
    """注入固定时钟后可推进，业务侧只认 clock.now()。"""
    fixed = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(clock_module, "clock", fixed)

    assert clock_module.now() == datetime(2026, 1, 1, tzinfo=timezone.utc)

    fixed.advance(timedelta(minutes=30))
    assert clock_module.now() == datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)


def test_fixed_clock_rejects_naive_datetime():
    """不带时区的时间一律拒绝，避免本地时间混进 UTC 字段。"""
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 1))


def test_hash_format():
    """产出 bcrypt 哈希，成本与配置一致。"""
    hashed = hash_password("Passw0rd!")

    assert isinstance(hashed, str)
    assert hashed.startswith("$2b$")
    assert len(hashed) == 60
    assert hashed.split("$")[2] == f"{get_settings().bcrypt_cost:02d}"


def test_hash_is_salted():
    """同一密码两次哈希不同，说明每次生成新盐。"""
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_password():
    hashed = hash_password("correct horse battery")

    assert verify_password("correct horse battery", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_verify_password_malformed_hash():
    """库里存了非法哈希也不能抛出去，按校验失败处理。"""
    assert verify_password("whatever", "not-a-bcrypt-hash") is False


def test_dummy_hash_rejects_password():
    """DUMMY_HASH 只用于对齐耗时，不是任何真实密码。"""
    assert verify_password("some-other-password", DUMMY_HASH) is False


def _best_verify_time(password_hash: str) -> float:
    """跑若干次取最小值，抵消系统调度抖动。"""
    samples = []
    for _ in range(ROUNDS):
        start = time.perf_counter()
        verify_password("wrong-password", password_hash)
        samples.append(time.perf_counter() - start)
    return min(samples)


def test_unknown_user_timing_close():
    """用户不存在时空跑 DUMMY_HASH，耗时与密码错误接近（AC-02）。"""
    real_hash = hash_password("right-password")
    # 预热，排除首次调用的额外开销
    verify_password("warmup", real_hash)
    verify_password("warmup", DUMMY_HASH)

    real = _best_verify_time(real_hash)
    dummy = _best_verify_time(DUMMY_HASH)

    assert abs(real - dummy) <= max(real, dummy) * TIMING_TOLERANCE
