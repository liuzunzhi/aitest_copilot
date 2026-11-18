"""llm providers + run logs

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-17

06-real-llm（T84）：真实大模型接入的落库结构。

1. `llm_providers`：全局大模型配置。API Key 只存 Fernet 密文，
   明文只留末 4 位供 UI 掩码。`default_key` 用 STORED 生成列
   `IF(is_default = 1, 1, NULL)` + 唯一索引，保证全局只有一个默认配置
   （MySQL 无条件唯一索引，但允许多个 NULL，非默认行不占位）；
2. `llm_run_logs`：模型运行留痕。只记次数、耗时、状态、错误，
   **不记 Prompt 正文、不记模型原文、不记 token 金额**。
   `analysis_id` / `provider_id` 不建外键——记录必须能留存；
3. 无种子数据：`llm_providers` 空表 = 平台出厂即 Mock 降级。

`down_revision` 指向 0016（05 第三期产出段）。downgrade 反序直接删表
（沿用 04/05 的写法：不先删索引，避开 MySQL 1553 依赖错误）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

# 生成列：默认行取 1，其余取 NULL。唯一索引挂在它上面。
DEFAULT_KEY_EXPR = "IF(is_default = 1, 1, NULL)"


def upgrade() -> None:
    # 1) 大模型配置
    op.create_table(
        "llm_providers",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "provider_type",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'openai_compat'"),
        ),
        sa.Column(
            "base_url",
            sa.String(length=255),
            nullable=False,
            comment="OpenAI 兼容端点，末尾不带 /",
        ),
        sa.Column(
            "api_key_ciphertext",
            mysql.TEXT(),
            nullable=False,
            comment="Fernet 密文，绝不存明文",
        ),
        sa.Column(
            "api_key_last4",
            sa.String(length=8),
            nullable=False,
            comment="明文末 4 位，供 UI 掩码",
        ),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "timeout_seconds",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "is_default",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "default_key",
            mysql.TINYINT(unsigned=True),
            sa.Computed(DEFAULT_KEY_EXPR, persisted=True),
            comment="生成列：默认行取 1，其余为 NULL（配合唯一索引保证唯一默认）",
        ),
        sa.Column("last_test_status", sa.String(length=16), nullable=True),
        sa.Column("last_test_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "last_test_error",
            sa.String(length=500),
            nullable=True,
            comment="已脱敏，不含 API Key",
        ),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("updated_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "provider_type IN ('openai_compat')", name="ck_llmprov_type"
        ),
        sa.CheckConstraint(
            "status IN ('active','disabled')", name="ck_llmprov_status"
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 300",
            name="ck_llmprov_timeout",
        ),
        **TABLE_OPTS,
    )
    op.create_index("uk_llmprov_name", "llm_providers", ["name"], unique=True)
    op.create_index(
        "uk_llmprov_default", "llm_providers", ["default_key"], unique=True
    )
    op.create_index("idx_llmprov_status", "llm_providers", ["status"])

    # 2) 运行留痕
    op.create_table(
        "llm_run_logs",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("analysis_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("provider_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("template_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("template_version", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column(
            "call_count",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "latency_ms",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "error_message",
            sa.String(length=500),
            nullable=True,
            comment="已脱敏，不含 API Key",
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "task_type IN ('incremental_first','incremental_second','provider_test')",
            name="ck_llmlogs_task_type",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded','failed')", name="ck_llmlogs_status"
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_llmlogs_analysis", "llm_run_logs", ["analysis_id"])
    op.create_index("idx_llmlogs_created", "llm_run_logs", ["created_at"])
    op.create_index("idx_llmlogs_status", "llm_run_logs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("llm_run_logs")
    op.drop_table("llm_providers")
