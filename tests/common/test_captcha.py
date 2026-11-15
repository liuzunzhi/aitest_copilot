"""验证码与 Redis（T10）。

两类验证码都在 Redis 里，必须真连 Redis 跑，不能 mock——
这里要守的正是 TTL、一次性消费、限流键的行为。
"""

import uuid

import pytest

from app.common.captcha import (
    CAPTCHA_TTL_SECONDS,
    RESET_CODE_TTL_SECONDS,
    RESET_RATE_LIMIT_SECONDS,
    RateLimited,
    create_captcha,
    get_redis,
    send_reset_code,
    verify_captcha,
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


def test_captcha_success_then_consumed(client):
    """校验通过后同一个 captcha 不能再用第二次。"""
    captcha = create_captcha()

    assert verify_captcha(captcha.id, captcha.code) is True
    assert verify_captcha(captcha.id, captcha.code) is False
    assert client.exists(f"captcha:{captcha.id}") == 0


def test_captcha_answer_is_case_insensitive():
    captcha = create_captcha()

    assert verify_captcha(captcha.id, captcha.code.lower()) is True


def test_captcha_wrong_answer_still_consumed(client):
    """答错也作废，避免 4 位码被逐次枚举。"""
    captcha = create_captcha()
    wrong = "XXXX" if captcha.code != "XXXX" else "YYYY"

    assert verify_captcha(captcha.id, wrong) is False
    assert verify_captcha(captcha.id, captcha.code) is False
    assert client.exists(f"captcha:{captcha.id}") == 0


def test_captcha_unknown_or_missing():
    assert verify_captcha("no-such-captcha-id", "ABCD") is False
    assert verify_captcha(None, "ABCD") is False
    assert verify_captcha("some-id", None) is False


def test_captcha_ttl(client):
    """图形验证码 TTL 300s（允许几秒的建立延迟）。"""
    captcha = create_captcha()
    ttl = client.ttl(f"captcha:{captcha.id}")
    client.delete(f"captcha:{captcha.id}")

    assert 0 < ttl <= CAPTCHA_TTL_SECONDS
    assert ttl > CAPTCHA_TTL_SECONDS - 10


def test_reset_code_success_then_consumed(client, contact):
    """重置验证码校验成功后立即失效。"""
    code = send_reset_code(contact)

    assert verify_reset_code(contact, code) is True
    assert verify_reset_code(contact, code) is False
    assert client.exists(f"pwdreset:code:{contact}") == 0


def test_reset_code_format(contact):
    code = send_reset_code(contact)

    assert len(code) == 6
    assert code.isdigit()


def test_reset_code_wrong_keeps_validity(contact):
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
