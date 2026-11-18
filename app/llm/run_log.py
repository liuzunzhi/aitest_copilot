"""模型运行留痕（06-real-llm T86 · AC-112）。

一条记录 = **一次任务**（一次分析的第一遍 / 第二遍、一次连通性测试），
**不是**一次 HTTP 调用；`call_count` 记该任务内调了几次。

**记什么**：次数、耗时、状态、错误。
**不记什么**：Prompt 正文、模型原文、token 金额——表里根本没有这些列。

调用次数的口径：`provider.calls` 是**累计**的（Mock 与真实 Provider 同契约），
所以要「跑前记基线，跑完相减」——直接取 `len(calls)` 会把历史调用也算进来。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.models.llm import LLMRunLog

__all__ = [
    "call_count",
    "provider_identity",
    "record_run",
]


def call_count(provider: Any) -> int:
    """当前累计调用次数。

    Mock 与真实 Provider 都有 `calls: list[LLMRequest]`，口径一致。
    没有 `calls` 的供应商一律按 0 算。
    """
    calls = getattr(provider, "calls", None)
    if not calls:
        return 0
    return len(calls)


def provider_identity(provider: Any) -> tuple[str, str]:
    """取 (provider_name, model) 快照。

    有配置时 `provider_name` 是**配置名**（如「DeepSeek 生产」），
    没有配置（Mock 降级）时退化成供应商类型（`mock`）。
    `model` 同理：真实 Provider 带配置里的模型名，Mock 是 `mock`。
    """
    name = getattr(provider, "provider_name", None) or provider.name
    model = getattr(provider, "model", None) or provider.name
    return str(name), str(model)


def record_run(
    session: Session,
    *,
    task_type: str,
    provider: Any,
    calls: int,
    started_at: float,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    project_id: int | None = None,
    analysis_id: int | None = None,
    template_id: int | None = None,
    template_version: int | None = None,
) -> LLMRunLog:
    """写一条运行留痕（**只 add + flush**，不 commit）。

    事务边界由调用方控制——业务失败要回滚时，留痕一起回滚，
    不允许出现「业务没成但留痕说成功」。
    """
    provider_name, model = provider_identity(provider)
    latency_ms = max(1, int((time.monotonic() - started_at) * 1000))

    log = LLMRunLog(
        task_type=task_type,
        project_id=project_id,
        analysis_id=analysis_id,
        provider_id=getattr(provider, "provider_id", None),
        provider_name=provider_name[:64],
        model=model[:128],
        template_id=template_id,
        template_version=template_version,
        call_count=max(0, calls),
        latency_ms=latency_ms,
        status=status,
        error_code=None if error_code is None else error_code[:64],
        error_message=None if error_message is None else error_message[:500],
    )
    session.add(log)
    session.flush()
    return log
