"""章节引用图 AI 分析 · 数据层（12-chapter-link-ai T129）

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-25

把「章节引用图」从「纯手工 + 正则重抽」升级为「AI 一键分析」的第一步：
`document_chapter_links.source` 的 CHECK 扩一个 `'ai'`——AI 产出的边与
规则边（`'rule'`）、人工边（`'manual'`）并列，三种来源**各自独立重算**
（AI 分析只重算 `source='ai'` 的，规则重抽只重算 `source='rule'` 的，互不覆盖）。

**为什么不是新建一张 `document_chapter_references` 表**（用户拍板）：
复用现有表才能让既有数据、既有唯一键、既有列表接口、既有前端全部不受影响；
拆两张表意味着规则重抽、手工补链、AI 分析三套逻辑要维护两份。

**为什么 `source` 用 `'ai'` 而不是 `'ai_analyzed'`**：
`'rule'` 的语义已经等价于「正则抽取」，改它会破坏 05 期既有数据与断言；
只**新增**一个值是代价最小的做法。

**downgrade 的顺序约束**（踩过坑的）：MySQL 不允许直接改 CHECK，
必须先 `drop_constraint` 再 `create_check_constraint`；且 downgrade 必须先删
`source='ai'` 的残留行再重建旧 CHECK，否则撞 3819
（见 `0023_test_cases.py:321-322` 的同款注释）。

**表结构零改动**：`document_chapter_links` 的列、索引、唯一键一个都没动——
只扩了 `source` 的 CHECK 枚举。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_LINK_SOURCES = ("rule", "manual")
NEW_LINK_SOURCES = (*OLD_LINK_SOURCES, "ai")


def _enum_sql(values: tuple[str, ...]) -> str:
    joined = ",".join(f"'{value}'" for value in values)
    return f"IN ({joined})"


def upgrade() -> None:
    op.drop_constraint("ck_chlinks_source", "document_chapter_links", type_="check")
    op.create_check_constraint(
        "ck_chlinks_source",
        "document_chapter_links",
        f"source {_enum_sql(NEW_LINK_SOURCES)}",
    )


def downgrade() -> None:
    # 必须先删残留行，否则重建旧 CHECK 撞 3819（`source='ai'` 是旧 CHECK 不认的值）。
    op.execute(sa.text("DELETE FROM document_chapter_links WHERE source = 'ai'"))
    op.drop_constraint("ck_chlinks_source", "document_chapter_links", type_="check")
    op.create_check_constraint(
        "ck_chlinks_source",
        "document_chapter_links",
        f"source {_enum_sql(OLD_LINK_SOURCES)}",
    )
