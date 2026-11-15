"""图形验证码与密码重置验证码。

两类验证码只存 Redis，不落库：
- `captcha:{id}`            TTL 300s  图形验证码
- `pwdreset:code:{contact}` TTL 600s  重置验证码
- `pwdreset:rate:{contact}` TTL 60s   发送频率限制

作废策略：
- 图形验证码一次校验无论对错都作废，防止 4 位码被逐次枚举；
- 重置验证码校验成功才作废，6 位码由发送限流约束尝试次数。
"""

import secrets
from dataclasses import dataclass
from functools import lru_cache

import redis

from app.common.config import get_settings

CAPTCHA_TTL_SECONDS = 300
CAPTCHA_LENGTH = 4
# 去掉 0/O/1/I/L 这类易混淆字符，降低误读
CAPTCHA_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

RESET_CODE_TTL_SECONDS = 600
RESET_CODE_LENGTH = 6
RESET_RATE_LIMIT_SECONDS = 60


class RateLimited(Exception):
    """距上次发送不足 `RESET_RATE_LIMIT_SECONDS`，由上层映射为 429。"""


@dataclass(frozen=True)
class Captcha:
    """图形验证码。`code` 交给图片渲染，`id` 给客户端带回提交。"""

    id: str
    code: str


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Redis 客户端单例。"""
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def create_captcha() -> Captcha:
    """生成图形验证码，5 分钟内有效。"""
    code = "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(CAPTCHA_LENGTH))
    captcha_id = secrets.token_urlsafe(16)
    get_redis().set(f"captcha:{captcha_id}", code, ex=CAPTCHA_TTL_SECONDS)
    return Captcha(id=captcha_id, code=code)


def verify_captcha(captcha_id: str | None, answer: str | None) -> bool:
    """校验图形验证码，一次校验后立即作废。"""
    if not captcha_id or not answer:
        return False

    stored = get_redis().getdel(f"captcha:{captcha_id}")
    return stored is not None and stored == answer.strip().upper()


def send_reset_code(contact: str) -> str:
    """生成密码重置验证码并写入 Redis，返回明文供上层发送。

    同一 contact 60s 内重复调用抛 `RateLimited`。
    """
    client = get_redis()
    rate_key = f"pwdreset:rate:{contact}"
    if not client.set(rate_key, "1", ex=RESET_RATE_LIMIT_SECONDS, nx=True):
        raise RateLimited(contact)

    code = f"{secrets.randbelow(10**RESET_CODE_LENGTH):0{RESET_CODE_LENGTH}d}"
    client.set(f"pwdreset:code:{contact}", code, ex=RESET_CODE_TTL_SECONDS)
    return code


def verify_reset_code(contact: str, code: str | None) -> bool:
    """校验重置验证码，成功即删除；失败保留，允许用户在有效期内重试。"""
    if not code:
        return False

    client = get_redis()
    key = f"pwdreset:code:{contact}"
    stored = client.get(key)
    if stored is None or stored != code.strip():
        return False

    client.delete(key)
    return True


__all__ = [
    "CAPTCHA_TTL_SECONDS",
    "RESET_CODE_TTL_SECONDS",
    "RESET_RATE_LIMIT_SECONDS",
    "Captcha",
    "RateLimited",
    "create_captcha",
    "get_redis",
    "send_reset_code",
    "verify_captcha",
    "verify_reset_code",
]
