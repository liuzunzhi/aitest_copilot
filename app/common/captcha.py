"""密码重置验证码。

只存 Redis，不落库：
- `pwdreset:code:{contact}` TTL 600s  重置验证码
- `pwdreset:rate:{contact}` TTL 60s   发送频率限制

作废策略：重置验证码校验成功才作废，6 位码由发送限流约束尝试次数。

**图形验证码已于 2026-11-18 移除**（内部测试环境，注册入口不对外开放）。
对外发布前需要补回图形验证码，见 `specs/01-auth/tasks.md` 的待办记录。
"""

import secrets
from functools import lru_cache

import redis

from app.common.config import get_settings

RESET_CODE_TTL_SECONDS = 600
RESET_CODE_LENGTH = 6
RESET_RATE_LIMIT_SECONDS = 60


class RateLimited(Exception):
    """距上次发送不足 `RESET_RATE_LIMIT_SECONDS`，由上层映射为 429。"""


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Redis 客户端单例。"""
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


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
    key = f"pwdreset:code:{contact}"
    client = get_redis()
    stored = client.get(key)
    if stored is None or stored != code.strip():
        return False

    client.delete(key)
    return True


__all__ = [
    "RESET_CODE_TTL_SECONDS",
    "RESET_RATE_LIMIT_SECONDS",
    "RateLimited",
    "get_redis",
    "send_reset_code",
    "verify_reset_code",
]
