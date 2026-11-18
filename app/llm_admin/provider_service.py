"""大模型配置的服务层（T85 · AC-113 / AC-114）。

三条硬规矩：

1. **明文边界**：API Key 只以密文落库，响应只给掩码，
   审计 / 日志 / 异常里**既没有明文也没有密文**；
2. **默认互斥必须「先清后置」**：`default_key` 是**即时计算**的生成列，
   把新行 `is_default` 置 1 的那一刻它的 `default_key` 立刻落成 1，
   而老默认行还没清、`default_key` 还是 1 → 唯一索引**当场报错**。
   所以顺序是死的：**先清其余行，再置目标行**（同一事务）；
3. **连通性测试失败不抛异常**：仍返回 200 + `ok=false`，
   让前端能在表单里内联展示错误。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.clock import utcnow_naive
from app.common.errors import (
    LLMConfigInvalid,
    LLMProviderInvalid,
    LLMProviderNameTaken,
    LLMProviderNotFound,
)
from app.llm.crypto import decrypt, encrypt, mask
from app.llm.schemas import LLMRequest
from app.models.llm import LLMProviderConfig, LLMRunLog
from app.models.user import User

__all__ = [
    "create_provider",
    "list_providers",
    "test_provider",
    "to_out",
    "update_provider",
]

# 连通性测试用的固定 ping prompt——不涉及业务数据
PING_SYSTEM = "ping"
PING_USER = "ping"

NAME_MAX = 64
MODEL_MAX = 128
TIMEOUT_MIN = 1
TIMEOUT_MAX = 300


# ------------------------------------------------------------ 校验


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise LLMProviderInvalid("配置名不能为空")
    if len(name) > NAME_MAX:
        raise LLMProviderInvalid(f"配置名不能超过 {NAME_MAX} 个字符")
    return name


def _validate_base_url(base_url: str) -> str:
    """只允许 http / https，入库前去掉尾部 `/`。"""
    url = (base_url or "").strip()
    if not url:
        raise LLMProviderInvalid("Base URL 不能为空")
    if not url.startswith(("http://", "https://")):
        raise LLMProviderInvalid("Base URL 必须以 http:// 或 https:// 开头")
    return url.rstrip("/")


def _validate_model(model: str) -> str:
    name = (model or "").strip()
    if not name:
        raise LLMProviderInvalid("模型名不能为空")
    if len(name) > MODEL_MAX:
        raise LLMProviderInvalid(f"模型名不能超过 {MODEL_MAX} 个字符")
    return name


def _validate_timeout(timeout: int) -> int:
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise LLMProviderInvalid("超时必须是整数秒")
    if timeout < TIMEOUT_MIN or timeout > TIMEOUT_MAX:
        raise LLMProviderInvalid(f"超时必须在 {TIMEOUT_MIN}~{TIMEOUT_MAX} 秒之间")
    return timeout


def _validate_api_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        raise LLMProviderInvalid("API Key 不能为空")
    return key


def _validate_status(status: str) -> str:
    if status not in ("active", "disabled"):
        raise LLMProviderInvalid("状态只能是 active 或 disabled")
    return status


# ------------------------------------------------------------ 默认互斥


def _clear_other_defaults(session: Session, keep_id: int | None = None) -> None:
    """把除 `keep_id` 外的所有配置行的 `is_default` 置 0。

    **必须先做这一步**。生成列即时计算——目标行还没置 1 之前，
    老默认行必须已经让位（`default_key` 落成 NULL）。

    用 ORM 逐行改而不是批量 `UPDATE`：
    批量更新绕过了 ORM 的脏检查，内存里的对象会留着旧的 `is_default`，
    后面 flush 时可能被写回，把刚清掉的老默认行又立起来。
    配置表只有几行，逐行改的开销可以忽略。
    """
    rows = session.scalars(
        select(LLMProviderConfig).where(LLMProviderConfig.is_default == 1)
    ).all()
    for row in rows:
        if keep_id is None or row.id != keep_id:
            row.is_default = 0
    session.flush()


# ------------------------------------------------------------ 读取


def list_providers(session: Session) -> list[LLMProviderConfig]:
    """配置列表（不分页，数量极少）。"""
    return list(
        session.scalars(
            select(LLMProviderConfig).order_by(
                LLMProviderConfig.is_default.desc(), LLMProviderConfig.id
            )
        ).all()
    )


def get_provider_row(session: Session, provider_id: int) -> LLMProviderConfig:
    """取一行，不存在抛 404。"""
    row = session.get(LLMProviderConfig, provider_id)
    if row is None:
        raise LLMProviderNotFound("大模型配置不存在")
    return row


def to_out(row: LLMProviderConfig) -> dict[str, Any]:
    """模型行 → 响应字典。

    **只给掩码**：`api_key_masked` 形如 `sk-****1234`。
    密文与明文都不出现在响应里。
    """
    return {
        "id": row.id,
        "name": row.name,
        "provider_type": row.provider_type,
        "base_url": row.base_url,
        "model": row.model,
        "api_key_masked": masked_of(row),
        "timeout_seconds": row.timeout_seconds,
        "status": row.status,
        "is_default": bool(row.is_default),
        "last_test_status": row.last_test_status,
        "last_test_at": row.last_test_at,
        "last_test_error": row.last_test_error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def masked_of(row: LLMProviderConfig) -> str:
    """掩码展示：`sk-****1234`。

    库里只有密文与末 4 位，要还原 `sk-` 前缀就得解密一次。
    解密失败（主密钥换过）时退化成 `****{last4}`——
    掩码拿不到就少给几个字符，绝不因此让整个列表挂掉。
    """
    try:
        return mask(decrypt(row.api_key_ciphertext))
    except LLMConfigInvalid:
        last4 = row.api_key_last4 or ""
        return f"****{last4}" if last4 else "****"


def _audit_snapshot(row: LLMProviderConfig) -> dict[str, Any]:
    """审计里记的字段集。**不含密文，也不含明文。**"""
    return {
        "name": row.name,
        "base_url": row.base_url,
        "model": row.model,
        "timeout_seconds": row.timeout_seconds,
        "status": row.status,
        "is_default": bool(row.is_default),
        "api_key_last4": row.api_key_last4,
    }


# ------------------------------------------------------------ 写


def create_provider(
    session: Session,
    *,
    actor: User,
    name: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: int = 60,
    is_default: bool = False,
) -> LLMProviderConfig:
    """新建配置。"""
    clean_name = _validate_name(name)
    clean_url = _validate_base_url(base_url)
    clean_model = _validate_model(model)
    clean_timeout = _validate_timeout(timeout_seconds)
    clean_key = _validate_api_key(api_key)

    duplicate = session.scalar(
        select(LLMProviderConfig).where(LLMProviderConfig.name == clean_name)
    )
    if duplicate is not None:
        raise LLMProviderNameTaken("配置名已存在")

    row = LLMProviderConfig(
        name=clean_name,
        provider_type="openai_compat",
        base_url=clean_url,
        api_key_ciphertext=encrypt(clean_key),
        api_key_last4=clean_key[-4:],
        model=clean_model,
        timeout_seconds=clean_timeout,
        status="active",
        is_default=0,
        created_by=actor.id,
        updated_by=actor.id,
    )
    session.add(row)
    session.flush()

    if is_default:
        # 先清后置——顺序不能反
        _clear_other_defaults(session, keep_id=row.id)
        row.is_default = 1
        session.flush()

    write_audit(
        session,
        "llm.provider.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        target_type="llm_provider",
        target_id=row.id,
        after_data=_audit_snapshot(row),
    )
    session.commit()
    return row


def update_provider(
    session: Session,
    *,
    actor: User,
    provider_id: int,
    payload: dict[str, Any],
) -> LLMProviderConfig:
    """更新配置。

    - `api_key` 为 `None` / 不传 → **原密文与 `last4` 不变**；
    - `status='disabled'` 且是默认行 → `is_default` 一并置 0
      （可能最终没有默认配置 → 降级 Mock，这是期望行为）；
    - `is_default=True` → **先清后置**。
    """
    row = get_provider_row(session, provider_id)
    before = _audit_snapshot(row)

    if payload.get("name") is not None:
        clean_name = _validate_name(payload["name"])
        if clean_name != row.name:
            duplicate = session.scalar(
                select(LLMProviderConfig).where(
                    LLMProviderConfig.name == clean_name,
                    LLMProviderConfig.id != row.id,
                )
            )
            if duplicate is not None:
                raise LLMProviderNameTaken("配置名已存在")
            row.name = clean_name

    if payload.get("base_url") is not None:
        row.base_url = _validate_base_url(payload["base_url"])

    if payload.get("model") is not None:
        row.model = _validate_model(payload["model"])

    if payload.get("timeout_seconds") is not None:
        row.timeout_seconds = _validate_timeout(payload["timeout_seconds"])

    if payload.get("status") is not None:
        row.status = _validate_status(payload["status"])

    api_key = payload.get("api_key")
    if api_key:
        # 传了新 Key → 重新加密，密文与 last4 一起变
        clean_key = _validate_api_key(api_key)
        row.api_key_ciphertext = encrypt(clean_key)
        row.api_key_last4 = clean_key[-4:]

    # 停用默认行 → 一并清掉默认标记
    if row.status == "disabled" and row.is_default == 1:
        row.is_default = 0
        session.flush()

    if payload.get("is_default") is True and row.is_default != 1:
        # 先清后置：先让所有行（含自己）落成 0，再置这一行
        _clear_other_defaults(session, keep_id=row.id)
        row.is_default = 1
        session.flush()

    row.updated_by = actor.id
    session.flush()

    write_audit(
        session,
        "llm.provider.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        target_type="llm_provider",
        target_id=row.id,
        before_data=before,
        after_data=_audit_snapshot(row),
    )
    session.commit()
    return row


# ------------------------------------------------------------ 连通性测试


def test_provider(
    session: Session,
    *,
    actor: User,
    provider_id: int,
    transport: Any = None,
) -> dict[str, Any]:
    """连通性测试。

    **失败也返回 200** + `ok=false` + 可读 `message`——
    它不是业务异常，是「这个配置连不通」的正常反馈。
    无论成败都写一条 `llm_run_logs(task_type='provider_test')`。
    """
    row = get_provider_row(session, provider_id)

    # 解密失败 → 配置坏了，必须让人知道（500），不降级
    try:
        api_key = decrypt(row.api_key_ciphertext)
    except LLMConfigInvalid:
        raise

    from app.llm.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider.from_config(row, api_key, transport=transport)

    started = time.monotonic()
    ok = True
    message = "连通正常"
    try:
        provider.chat(LLMRequest(system=PING_SYSTEM, user=PING_USER))
    except Exception as exc:  # noqa: BLE001 - 连通性失败不抛业务异常
        ok = False
        message = _safe_message(exc)
    latency_ms = int((time.monotonic() - started) * 1000)

    row.last_test_status = "succeeded" if ok else "failed"
    row.last_test_at = utcnow_naive()
    row.last_test_error = None if ok else message[:500]
    row.updated_by = actor.id
    session.flush()

    session.add(
        LLMRunLog(
            task_type="provider_test",
            provider_id=row.id,
            provider_name=row.name,
            model=row.model,
            call_count=1,
            latency_ms=latency_ms,
            status="succeeded" if ok else "failed",
            error_code=None if ok else "LLM_CALL_FAILED",
            error_message=None if ok else message[:500],
        )
    )
    session.commit()

    return {
        "ok": ok,
        "latency_ms": latency_ms,
        "model": row.model if ok else None,
        "message": message,
    }


def _safe_message(exc: Exception) -> str:
    """把异常变成可读消息。

    `LLMCallFailed` 的消息已经不含 Key；其它异常只取**类型名**，
    不取 `str(exc)`——原始异常里可能带 URL、请求头等敏感片段。
    """
    from app.common.errors import LLMCallFailed

    if isinstance(exc, LLMCallFailed):
        return exc.message
    return f"调用失败：{type(exc).__name__}"
