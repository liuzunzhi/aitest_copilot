"""AC-107 / AC-108 / AC-109 · 动态 Provider 工厂。

三条语义：

- **AC-107** `llm_providers` 表为空 → 返回 MockProvider 单例
  （这是「断网全绿」的关键：没配配置就用 Mock，行为与改造前一致）；
- **AC-108** 存在 `status='active'` + `is_default=1` 的配置 → 返回
  `OpenAICompatProvider`；
- **AC-109** 默认唯一（库层唯一索引兜底）+ 停用默认行后降级 Mock。

另外断言「解密失败**不降级**」：配置坏了必须让人知道，
否则线上会用 Mock 跑出一堆空结论却没人发现。
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.errors import LLMConfigInvalid
from app.llm.mock import MockProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.provider import get_provider
from app.models.llm import LLMProviderConfig

from tests.llm.conftest import FAKE_KEY


# ------------------------------------------------------------ AC-107


def test_ac_107_no_config_falls_back_to_mock(db: Session):
    """表为空 → 返回 Mock。"""
    provider = get_provider(db)

    assert isinstance(provider, MockProvider)
    assert provider.name == "mock"


def test_ac_107_mock_is_process_singleton(db: Session):
    """Mock 单例进程级复用。"""
    first = get_provider(db)

    assert first is get_provider(db)


def test_ac_107_only_disabled_rows_still_falls_back_to_mock(db: Session, make_provider):
    """只有 disabled 的行 → 仍是 Mock（工厂认 active + default）。"""
    make_provider(name="停用的", status="disabled", is_default=0)

    assert isinstance(get_provider(db), MockProvider)


def test_ac_107_non_default_row_still_falls_back_to_mock(db: Session, make_provider):
    """有配置但不是默认行 → 仍是 Mock。"""
    make_provider(name="非默认", is_default=0)

    assert isinstance(get_provider(db), MockProvider)


# ------------------------------------------------------------ AC-108


def test_ac_108_default_config_uses_real_provider(db: Session, make_provider):
    """有默认配置 → 返回 OpenAICompatProvider。"""
    make_provider()

    provider = get_provider(db)

    assert isinstance(provider, OpenAICompatProvider)
    assert provider.name == "openai_compat"


def test_ac_108_real_provider_carries_config_fields(db: Session, make_provider):
    """真实 Provider 带上配置里的 base_url / model / timeout。"""
    make_provider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        timeout_seconds=30,
    )

    provider = get_provider(db)

    assert provider.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert provider.model == "qwen-plus"
    assert provider.timeout_seconds == 30


def test_ac_108_real_provider_carries_decrypted_key(db: Session, make_provider):
    """真实 Provider 拿到的是**解密后的**明文 Key。"""
    make_provider()

    provider = get_provider(db)

    assert provider.api_key == FAKE_KEY


def test_ac_108_config_change_takes_effect_immediately(db: Session, make_provider):
    """每次 `get_provider` 都查库——管理员改完配置立即生效，不做缓存。"""
    make_provider(name="原配置", model="deepseek-chat")

    assert get_provider(db).model == "deepseek-chat"

    row = db.scalar(
        select(LLMProviderConfig).where(LLMProviderConfig.name == "原配置")
    )
    row.model = "deepseek-reasoner"
    db.flush()

    assert get_provider(db).model == "deepseek-reasoner"


# ------------------------------------------------------------ AC-109


def test_ac_109_second_default_is_rejected_by_unique_index(db: Session):
    """两个默认行 → 库层唯一索引直接拦截（IntegrityError）。

    唯一索引挂在生成列 `default_key` 上，所以第二个默认行在 **INSERT 时刻**
    就被 MySQL 拒绝——这是 AC-109「不可能」的硬保证，绕不过去。
    """
    from app.llm.crypto import encrypt

    db.add(
        LLMProviderConfig(
            name="默认一",
            provider_type="openai_compat",
            base_url="https://api.deepseek.com/v1",
            api_key_ciphertext=encrypt(FAKE_KEY),
            api_key_last4=FAKE_KEY[-4:],
            model="deepseek-chat",
            timeout_seconds=60,
            status="active",
            is_default=1,
            created_by=1,
        )
    )
    db.flush()

    db.add(
        LLMProviderConfig(
            name="默认二",
            provider_type="openai_compat",
            base_url="https://api.deepseek.com/v1",
            api_key_ciphertext=encrypt(FAKE_KEY),
            api_key_last4=FAKE_KEY[-4:],
            model="deepseek-chat",
            timeout_seconds=60,
            status="active",
            is_default=1,
            created_by=1,
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()

    db.rollback()  # 回滚 savepoint，别把坏状态留给后续


def test_ac_109_disabled_default_row_falls_back_to_mock(db: Session, make_provider):
    """默认行被停用 → 降级 Mock。"""
    make_provider(name="默认配置", status="disabled", is_default=1)

    assert isinstance(get_provider(db), MockProvider)


def test_ac_109_only_one_default_is_picked(db: Session, make_provider):
    """存在多条配置时，工厂只认 `is_default=1` 的那一条。"""
    make_provider(name="非默认", is_default=0, model="wrong-model")
    make_provider(name="默认", is_default=1, model="right-model")

    provider = get_provider(db)

    assert isinstance(provider, OpenAICompatProvider)
    assert provider.model == "right-model"


def test_ac_109_switching_default_keeps_single_default(db: Session, make_provider):
    """把默认行清掉、另一行置默认 → 全局仍只有一个默认。

    **顺序很关键**：必须**先清后置**（同一事务内两次 UPDATE）。
    反过来做（先置 1 再清 0）会撞唯一索引——因为生成列是即时计算的，
    第二个默认行的 `default_key` 落成 1 的那一刻，第一个还没清掉，
    唯一索引立刻报错。这条用例把这个约束固定下来。
    """
    first = make_provider(name="配置一", is_default=1)
    second = make_provider(name="配置二", is_default=0)

    # 先清：老默认行的 default_key 落成 NULL
    first.is_default = 0
    db.flush()
    # 后置：新默认行的 default_key 落成 1（此时没人占位）
    second.is_default = 1
    db.flush()

    defaults = db.scalars(
        select(LLMProviderConfig).where(LLMProviderConfig.is_default == 1)
    ).all()
    assert len(defaults) == 1
    assert defaults[0].id == second.id


def test_ac_109_set_default_before_clear_hits_unique_index(db: Session, make_provider):
    """**先置后清**会撞唯一索引——这正是服务层必须「先清后置」的原因。

    生成列是即时计算的：把新行 `is_default` 置 1 的那一刻，
    它的 `default_key` 立刻落成 1；而老默认行还没清，`default_key` 还是 1。
    唯一索引当场报错——所以顺序不能反。
    """
    first = make_provider(name="配置一", is_default=1)
    second = make_provider(name="配置二", is_default=0)

    # 反序：先置后清 → 立刻撞唯一索引
    second.is_default = 1
    with pytest.raises(IntegrityError):
        db.flush()

    db.rollback()


# ------------------------------------------------------------ 解密失败


def test_broken_ciphertext_raises_instead_of_falling_back(db: Session, make_provider):
    """密文解不开 → 抛 LLMConfigInvalid，**不降级** Mock。"""
    row = make_provider()
    row.api_key_ciphertext = "tampered-not-a-fernet-token"
    db.flush()

    with pytest.raises(LLMConfigInvalid):
        get_provider(db)


def test_broken_ciphertext_error_has_no_plaintext(db: Session, make_provider):
    """解密失败的错误消息里没有明文、也没有密文。"""
    row = make_provider()
    row.api_key_ciphertext = "tampered-not-a-fernet-token"
    db.flush()

    with pytest.raises(LLMConfigInvalid) as exc:
        get_provider(db)

    message = str(exc.value)
    assert FAKE_KEY not in message
    assert "tampered-not-a-fernet-token" not in message
