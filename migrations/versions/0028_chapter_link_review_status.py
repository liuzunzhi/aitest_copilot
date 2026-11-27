"""章节引用图 · 待评审状态与分析理由（12.5-chapter-link-review T137）

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-26

给 `document_chapter_links` 加两列：

1. `status`（`pending` 待评审 / `approved` 已生效）——AI 分析产出的边
   **先落待评审区**，人工采纳后才生效；
2. `rationale`——AI 给出的分析理由，供「详情」弹窗展示。

**为什么不复用 `source` 表达「待评审」**（12.5 期裁决）：
`source` 回答的是「这条边**谁产生的**」（rule / manual / ai），
「待评审」回答的是「这条边**人认可了没**」——两者正交。
若用 `source='ai_pending'`：
① 12 期的幂等口径「删 `(version_id, source='ai')` 再插」会变成只删待评审那批，
   **用户刚采纳的边在重新分析后凭空消失**；
② 采纳后 `source` 就不能再改，改了会丢掉「这条边是 AI 认出来的」这个信息
   （而这正是详情弹窗的可解释性基础）；
③ 下游过滤要写成 `source IN ('rule','manual','ai_approved')` 这样的白名单，
   每加一个来源都得记得补进去，漏一个就静默少传播一条边。
而唯一键 `uk_chlinks_to_chapter` 既不含 `source` 也不含 `status`——
用 `source` 一点迁移成本都省不下来。

**upgrade 的四步顺序不能换**（都是踩过坑的）：

1. **先加可空列 + `server_default`**：`server_default` 会把**存量行**填成
   `'approved'`——12 期已落库的 AI 边本来就是生效边（05 期的规则边、
   人工边同理），不该因为加了一列就倒退成「待评审」。
2. **再加 `rationale`**：可空列，直接加。
3. **然后加 CHECK**：`status` 只允许两个值。
4. **最后收紧成 NOT NULL**：此时列里已经没有 NULL（server_default 已回填），
   收紧是安全的。

**为什么不能一步加 NOT NULL 列**：MySQL 上把列改成 NOT NULL 时，
若表里有 NULL 行会直接报错 1138。所以必须「先加可空 → 回填 → 再收紧」。

**downgrade 的三步顺序**（严格反序）：

1. **必须先删 `status='pending'` 的行**——它们是本期独有的语义（待评审的 AI 边），
   降级后用户已经没法区分；留着还会变成 `status IS NULL` 的孤儿行。
   （与 `0026` / `0027` 的 downgrade 口径一致：都先删残留行再动结构。）
2. 再删 CHECK。
3. 最后删两列。

**踩坑记录（12.5 期 T137 实跑）**：

- **`alter_column` 必须显式给 `existing_type`**：MySQL 的 CHANGE/MODIFY COLUMN
  要求带上已有类型，alembic 不会自动推断。不写会报
  `All MySQL CHANGE/MODIFY COLUMN operations require the existing type`，
  而且**此时前 3 步已经执行完了**（MySQL DDL 非事务，不会回滚）——
  库处于「列和 CHECK 都在、版本号没升」的半成品状态，
  必须手工把列与 CHECK 删掉、把版本号改回 `0027`，再重跑。
- **`server_default` 回填的是「新增时刻的行」**：加列时 MySQL 会用
  `server_default` 填**当时已有的所有行**，所以存量行拿到的正是 `'approved'`。
  加列之后新插入的行如果不显式给 `status`，拿到的也是 `'approved'`——
  这正是我们要的默认（人工边 / 规则边天然已生效）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 存量行的回填值：全部已生效（12 期的 AI 边 / 05 期的规则边与人工边）。
LEGACY_STATUS = "approved"
# 本期新增的枚举值。
CHAPTER_LINK_STATUSES = ("pending", LEGACY_STATUS)


def _enum_sql(values: tuple[str, ...]) -> str:
    joined = ",".join(f"'{value}'" for value in values)
    return f"IN ({joined})"


def upgrade() -> None:
    # ① 先加可空列 + server_default —— 存量行被回填成 'approved'
    op.add_column(
        "document_chapter_links",
        sa.Column(
            "status",
            sa.String(16),
            nullable=True,
            server_default=sa.text(f"'{LEGACY_STATUS}'"),
        ),
    )

    # ② rationale：AI 的分析理由（详情弹窗要展示），可空
    op.add_column(
        "document_chapter_links",
        sa.Column("rationale", sa.String(1000), nullable=True),
    )

    # ③ 加 CHECK：只允许两个值
    op.create_check_constraint(
        "ck_chlinks_status",
        "document_chapter_links",
        f"status {_enum_sql(CHAPTER_LINK_STATUSES)}",
    )

    # ④ 收紧成 NOT NULL（此时列里已无 NULL）
    #    **`existing_type` 必须显式给出**：MySQL 的 CHANGE/MODIFY COLUMN
    #    要求带上已有类型，alembic 不会自动推断（不写会报
    #    "All MySQL CHANGE/MODIFY COLUMN operations require the existing type"）。
    op.alter_column(
        "document_chapter_links",
        "status",
        existing_type=sa.String(16),
        nullable=False,
        server_default=sa.text(f"'{LEGACY_STATUS}'"),
    )


def downgrade() -> None:
    # ① 先删残留的 pending 行——它们是本期独有的状态值，
    #    留着会变成 status IS NULL 的孤儿行（降级后用户没法区分）
    op.execute(
        sa.text("DELETE FROM document_chapter_links WHERE status = 'pending'")
    )

    # ② 删 CHECK
    op.drop_constraint("ck_chlinks_status", "document_chapter_links", type_="check")

    # ③ 删两列
    op.drop_column("document_chapter_links", "rationale")
    op.drop_column("document_chapter_links", "status")
