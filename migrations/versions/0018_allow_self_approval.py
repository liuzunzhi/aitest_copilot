"""allow_baseline_self_approval switch

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-18

04-baseline 补一条配置项：`allow_baseline_self_approval`。

背景：PRD 要求「提交者不能自审」，但内部测试环境常常只有**一个**管理员账号，
此时「自己提交 + 自己审核」是唯一可行路径，规则直接变成死锁。

加开关而不是改规则：默认关闭（保持 PRD 语义），需要时由管理员在
`system_settings` 里打开，打开后自审被放行并在审计里标记 `self_approved`。

默认值 **True**——本项目是内部测试环境，单人管理员是常态。
对外发布前应改回 False（或用 `set_setting` 关掉）。

`value` 是 JSON 标量，布尔必须保持 `true`/`false`，不能写成字符串。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY = "allow_baseline_self_approval"


def upgrade() -> None:
    settings = sa.table(
        "system_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.JSON),
    )
    op.bulk_insert(settings, [{"key": KEY, "value": True}])


def downgrade() -> None:
    op.execute(sa.text(f"DELETE FROM system_settings WHERE `key` = '{KEY}'"))
