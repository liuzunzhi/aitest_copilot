"""密码哈希。

只做 bcrypt 封装，不涉及业务校验（强度规则在注册服务里）。
"""

import bcrypt

from app.common.config import get_settings

# 登录时「用户不存在」分支要空跑一次校验，让耗时与「密码错误」一致。
# 否则攻击者能用响应时间探测账号是否存在（AC-02）。
# 成本必须与 BCRYPT_COST 默认值一致，否则空跑与真实校验的耗时会被区分。
DUMMY_HASH = bcrypt.hashpw(
    b"dummy-password-for-timing", bcrypt.gensalt(rounds=12)
).decode()


def hash_password(password: str) -> str:
    """生成 bcrypt 哈希，成本取自配置。"""
    return bcrypt.hashpw(
        password.encode(), bcrypt.gensalt(rounds=get_settings().bcrypt_cost)
    ).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码。哈希格式非法时返回 False 而不是抛异常。"""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


__all__ = ["DUMMY_HASH", "hash_password", "verify_password"]
