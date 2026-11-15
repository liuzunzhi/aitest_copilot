"""seed system_settings

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-15

6 个默认配置。`value` 是 JSON 标量：布尔与数字要保持原类型，
不要写成字符串，否则读侧比较 `value == 5` 会失败。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETTINGS: list[tuple[str, object]] = [
    ("enable_project_apply", True),
    ("token_ttl_seconds", 28800),
    ("remember_ttl_seconds", 2592000),
    ("max_login_failures", 5),
    ("lock_duration_minutes", 30),
    ("apply_cooldown_hours", 24),
]


def upgrade() -> None:
    settings = sa.table(
        "system_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.JSON),
    )
    op.bulk_insert(settings, [{"key": k, "value": v} for k, v in SETTINGS])


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k, _ in SETTINGS)
    op.execute(sa.text(f"DELETE FROM system_settings WHERE `key` IN ({keys})"))
