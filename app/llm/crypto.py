"""大模型 API Key 的加密与掩码。

用 **Fernet**（`cryptography` 库的对称加密），不自造 AES——
自己写加密是自造漏洞，成熟库的边界情况已经被审过。

主密钥来自环境变量 `LLM_SECRET_KEY`（**必填**），由 `sha256` 派生 Fernet 密钥：

    base64.urlsafe_b64encode(sha256(secret_key.encode()).digest())

这样**任意长度**的字符串都能当主密钥，用户不必手工生成 32 字节。

明文边界（硬约束，见 spec §5.3）：数据库只存密文；响应只给掩码；
审计 / 日志 / 异常 / 运行日志里都不出现明文。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.common.config import get_settings
from app.common.errors import LLMConfigInvalid


def _fernet() -> Fernet:
    """由主密钥派生 Fernet 实例。"""
    raw = get_settings().llm_secret_key.encode("utf-8")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))


def encrypt(plain: str) -> str:
    """加密，返回可安全落库的密文字符串。"""
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(cipher: str) -> str:
    """解密。失败抛 `LLMConfigInvalid`。

    错误消息**固定**、不含密文也不含明文——Fernet 的原始异常里
    可能带密文片段，直接透出去就等于把密文写进了日志。
    """
    try:
        return _fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")
    except (InvalidToken, TypeError, ValueError) as exc:
        raise LLMConfigInvalid("大模型配置无法解密，请检查 LLM_SECRET_KEY") from exc


def mask(plain: str) -> str:
    """掩码：`sk-****abcd`。

    长度 ≤ 4 时只给 `****`——末 4 位就是全部，掩掉等于没掩。
    """
    if len(plain) <= 4:
        return "****"
    return f"{plain[:3]}****{plain[-4:]}"


__all__ = ["decrypt", "encrypt", "mask"]
