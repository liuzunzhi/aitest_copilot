"""AC-106 · 加解密往返与篡改检测。

三件事必须成立：

1. `encrypt` → `decrypt` 往返得到原文；
2. 密文被改一个字符 → 抛 `LLMConfigInvalid`，**消息不含密文也不含明文**；
3. 换一把主密钥解密旧密文 → 同样抛 `LLMConfigInvalid`。

外加掩码规则：4 位以内的 Key 只给 `****`。
"""

import pytest

from app.common.config import get_settings
from app.common.errors import LLMConfigInvalid
from app.llm.crypto import decrypt, encrypt, mask

PLAIN = "sk-supersecret-1234"


def test_ac_106_roundtrip():
    """加密再解密回到原文。"""
    cipher = encrypt(PLAIN)

    assert cipher != PLAIN
    assert decrypt(cipher) == PLAIN


def test_ac_106_ciphertext_hides_plaintext():
    """密文里不含明文片段——落库的是密文不是明文。"""
    cipher = encrypt(PLAIN)

    assert PLAIN not in cipher
    assert "supersecret" not in cipher


def test_ac_106_ciphertext_is_not_deterministic():
    """同一明文两次加密得到不同密文（Fernet 带随机 IV）。"""

    assert encrypt(PLAIN) != encrypt(PLAIN)


def test_ac_106_tampered_ciphertext_raises():
    """密文被改动一个字符 → 抛 LLMConfigInvalid。"""
    cipher = encrypt(PLAIN)
    # 改最后两个字符（Fernet 密文末段是签名，改了就验不过）
    tampered = cipher[:-2] + ("xy" if not cipher.endswith("xy") else "ab")

    with pytest.raises(LLMConfigInvalid):
        decrypt(tampered)


def test_ac_106_tampered_message_does_not_leak():
    """解密失败的错误消息里既没有密文也没有明文。"""
    cipher = encrypt(PLAIN)
    tampered = cipher[:-2] + ("xy" if not cipher.endswith("xy") else "ab")

    with pytest.raises(LLMConfigInvalid) as exc:
        decrypt(tampered)

    message = str(exc.value)
    assert PLAIN not in message
    assert cipher not in message
    assert tampered not in message


def test_ac_106_wrong_secret_key_raises(monkeypatch):
    """换一把主密钥解密旧密文 → 抛 LLMConfigInvalid。

    走**环境变量**换密钥而不是改 Settings 对象：`get_settings` 是
    `lru_cache` 单例，改对象属性后一 `cache_clear()` 就被 `.env` 重建回去了。
    """
    cipher = encrypt(PLAIN)

    monkeypatch.setenv("LLM_SECRET_KEY", "another-master-key")
    get_settings.cache_clear()

    with pytest.raises(LLMConfigInvalid) as exc:
        decrypt(cipher)

    assert PLAIN not in str(exc.value)


def test_ac_106_garbage_ciphertext_raises():
    """根本不是密文 → 也是 LLMConfigInvalid，不抛别的异常。"""
    with pytest.raises(LLMConfigInvalid):
        decrypt("not-a-fernet-token")


@pytest.mark.parametrize("secret", ["", "x"])
def test_ac_106_empty_or_tiny_plaintext(secret):
    """空串也能加密解密（边界不炸）。"""
    cipher = encrypt(secret)

    assert decrypt(cipher) == secret


def test_ac_106_mask_rules():
    """掩码只露头 3 尾 4；短 Key 只给 `****`。"""
    assert mask("sk-supersecret-1234") == "sk-****1234"
    assert mask("abcd") == "****"
    assert mask("abc") == "****"
    assert mask("") == "****"


def test_ac_106_mask_does_not_leak_middle():
    """掩码后中间部分必须看不到。"""
    masked = mask("sk-supersecret-1234")

    assert "supersecret" not in masked
    assert masked.endswith("1234")
