"""大模型配置与运行留痕模型（06-real-llm T84）。

两张表：

- `llm_providers` 全局大模型配置。API Key **只存密文**
  （`api_key_ciphertext`），明文只以末 4 位（`api_key_last4`）留在库里供 UI 掩码。
  `default_key` 是 STORED 生成列：仅当 `is_default = 1` 时等于 1，
  配合唯一索引保证**全局只有一个默认配置**——MySQL 唯一索引允许多个 NULL，
  所以非默认行不占位。
- `llm_run_logs` 模型运行留痕。**只记次数、耗时、状态、错误**，
  不记 Prompt 正文、不记模型原文、不记 token 金额。
  `analysis_id` / `provider_id` **不建外键**：配置被停用、记录被删
  都不该让日志丢失。

**不提供物理删除**：停用即 `status='disabled'`，历史与审计保留。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER, TEXT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

PROVIDER_TYPES = ("openai_compat",)
PROVIDER_STATUSES = ("active", "disabled")
RUN_LOG_TASK_TYPES = (
    "incremental_first",
    "incremental_second",
    "provider_test",
    "test_point",
    # 08 期（0023）扩的 `test_case`——当时只改了迁移，模型里漏了，
    # 这里补齐（模型与库必须一致，否则 ORM 写入会被 CHECK 拒）。
    "test_case",
    # 12 期（0027）扩的 `chapter_link_analyze`：章节引用图的 AI 分析。
    "chapter_link_analyze",
)
RUN_LOG_STATUSES = ("succeeded", "failed")

# 生成列：默认行取 1，其余取 NULL。
# 唯一索引挂在它上面 → 两条默认行不可能同时存在（MySQL 层面直接报错）。
DEFAULT_KEY_EXPR = "IF(is_default = 1, 1, NULL)"


class LLMProviderConfig(Base):
    """一条大模型配置。全局唯一默认，不绑项目。"""

    __tablename__ = "llm_providers"
    __table_args__ = (
        Index("uk_llmprov_name", "name", unique=True),
        Index("uk_llmprov_default", "default_key", unique=True),
        Index("idx_llmprov_status", "status"),
        CheckConstraint(
            "provider_type IN ('openai_compat')", name="ck_llmprov_type"
        ),
        CheckConstraint(
            "status IN ('active','disabled')", name="ck_llmprov_status"
        ),
        CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 300",
            name="ck_llmprov_timeout",
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'openai_compat'")
    )
    base_url: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="OpenAI 兼容端点，末尾不带 /"
    )
    api_key_ciphertext: Mapped[str] = mapped_column(
        TEXT, nullable=False, comment="Fernet 密文，绝不存明文"
    )
    api_key_last4: Mapped[str] = mapped_column(
        String(8), nullable=False, comment="明文末 4 位，供 UI 掩码"
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("60")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    is_default: Mapped[int] = mapped_column(
        TINYINT(unsigned=True), nullable=False, server_default=text("0")
    )
    default_key: Mapped[int | None] = mapped_column(
        TINYINT(unsigned=True),
        Computed(DEFAULT_KEY_EXPR, persisted=True),
        comment="生成列：默认行取 1，其余为 NULL（配合唯一索引保证唯一默认）",
    )
    last_test_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="已脱敏，不含 API Key"
    )
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        server_onupdate=text("CURRENT_TIMESTAMP(3)"),
    )


class LLMRunLog(Base):
    """一次模型任务的运行留痕。

    一条记录 = **一次任务**（一次分析的第一遍 / 第二遍 / 一次连通性测试），
    不是一次 HTTP 调用；`call_count` 记该任务内调用了几次。
    """

    __tablename__ = "llm_run_logs"
    __table_args__ = (
        Index("idx_llmlogs_analysis", "analysis_id"),
        Index("idx_llmlogs_created", "created_at"),
        Index("idx_llmlogs_status", "status", "created_at"),
        CheckConstraint(
            "task_type IN "
            "('incremental_first','incremental_second','provider_test',"
            "'test_point','test_case','chapter_link_analyze')",
            name="ck_llmlogs_task_type",
        ),
        CheckConstraint(
            "status IN ('succeeded','failed')", name="ck_llmlogs_status"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    project_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    # 快照引用，不建外键：配置停用、记录删除都不该让日志丢失
    analysis_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    provider_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    template_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    template_version: Mapped[int | None] = mapped_column(
        INTEGER(unsigned=True), nullable=True
    )
    call_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    latency_ms: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="已脱敏，不含 API Key"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = [
    "DEFAULT_KEY_EXPR",
    "LLMProviderConfig",
    "LLMRunLog",
    "PROVIDER_STATUSES",
    "PROVIDER_TYPES",
    "RUN_LOG_STATUSES",
    "RUN_LOG_TASK_TYPES",
]
