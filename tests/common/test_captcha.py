"""密码重置验证码与 Redis（T10）。

**图形验证码已于 2026-11-18 移除**（内部测试环境，注册不对外开放）。
这里只守剩下的重置验证码：TTL、一次性消费、限流键。

必须真连 Redis 跑，不能 mock——守的正是 TTL 与限流键的行为。
"""

import uuid

import pytest

from app.common.captcha import (
    RESET_CODE_TTL_SECONDS,
    RESET_RATE_LIMIT_SECONDS,
    RateLimited,
    get_redis,
    send_reset_code,
    verify_reset_code,
)


@pytest.fixture
def client():
    return get_redis()


@pytest.fixture
def contact(client):
    """每个用例独立的 contact，结束时清掉遗留键。"""
    value = f"t10-{uuid.uuid4().hex}@example.com"
    yield value
    client.delete(f"pwdreset:code:{value}", f"pwdreset:rate:{value}")


def test_reset_code_success_then_consumed(client, contact):
    """重置验证码校验成功后立即失效。"""
    code = send_reset_code(contact)

    assert verify_reset_code(contact, code) is True
    assert verify_reset_code(contact, code) is False
    assert client.exists(f"pwdreset:code:{contact}") == 0


def test_reset_code_format(client, contact):
    code = send_reset_code(contact)

    assert len(code) == 6
    assert code.isdigit()


def test_reset_code_wrong_keeps_validity(client, contact):
    """输错不消耗，用户可在 10 分钟内重试。"""
    code = send_reset_code(contact)

    assert verify_reset_code(contact, "000000" if code != "000000" else "111111") is False
    assert verify_reset_code(contact, code) is True


def test_reset_code_ttl(client, contact):
    send_reset_code(contact)
    ttl = client.ttl(f"pwdreset:code:{contact}")

    assert 0 < ttl <= RESET_CODE_TTL_SECONDS
    assert ttl > RESET_CODE_TTL_SECONDS - 10


def test_reset_send_rate_limited(client, contact):
    """60s 内重复发送抛 RateLimited，由上层映射为 429。"""
    send_reset_code(contact)

    with pytest.raises(RateLimited):
        send_reset_code(contact)

    ttl = client.ttl(f"pwdreset:rate:{contact}")
    assert 0 < ttl <= RESET_RATE_LIMIT_SECONDS


def test_verify_reset_code_missing_arguments(contact):
    assert verify_reset_code(contact, None) is False
    assert verify_reset_code("no-such-contact", "123456") is False
