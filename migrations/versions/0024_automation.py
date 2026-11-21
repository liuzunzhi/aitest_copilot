"""automation assets / runs / run items（09-automation T111）

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-21

09-automation T111：自动化执行与测试报告的三张新表 + **清除原因枚举修正**。

1. `automation_assets`：扫描进来的自动化资产，可关联一条测试用例；
2. `automation_runs`：一次执行任务的记录；
3. `automation_run_items`：这次执行里每个资产的结果。

**枚举修正（本迁移的另一半，也是唯一一处改动既有数据的地方）**：

PRD 2.4.2 规定清除标签有 6 类原因，而代码里原本是
`priority_changed`（优先级变化）/ `duplicate_label`（标签重复）——
这两个值**在 PRD 里根本不存在**，而 PRD 要求的「基线已调整」「回溯覆盖」
两类**无法表达**。这是能力缺失，不是命名风格问题。

    priority_changed  → baseline_adjusted  （PRD：基线已调整）
    duplicate_label   → backtrace_override （PRD：回溯覆盖）

存量数据用两条 UPDATE 就地改写。`downgrade` 必须**反向改回去**——
否则降级后代码只认旧枚举名，历史数据会被判成非法原因。

**为什么建表与枚举修正放在同一个迁移**：T111 同时要建三张表，
合成一个迁移少一次往返验证。代价是 `downgrade` 要同时处理两件事——
但它们互不依赖，写起来是直的。

**三条刻意的设计**：

- `linked_case_id` **不建外键**：08 的删用例是物理删除，建外键会把 08 的
  既有行为变成 500（IntegrityError）。用逻辑引用 + `case_title` 快照。
- `file_path` 存**相对路径**（不存绝对路径）：绝对路径随部署环境漂移，
  且泄露服务器目录结构。
- `baseline_labels.clear_reason` **没有 CHECK 约束**（`0012` 只对
  `target_type` / `label_type` / `status` 建了 CHECK），
  所以枚举修正**不需要改表结构**，只需要 UPDATE 存量。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}

# 清除原因的旧值 → 新值（PRD 2.4.2 的 6 类）。
# 写成映射而不是散落的常量：upgrade / downgrade 共用这一处，
# 避免两处各写一遍、改了一处忘了另一处。
CLEAR_REASON_RENAMES = (
    ("priority_changed", "baseline_adjusted"),
    ("duplicate_label", "backtrace_override"),
)


def _rename_clear_reasons() -> None:
    """把存量标签的清除原因从旧值改写成新值。"""
    for old_value, new_value in CLEAR_REASON_RENAMES:
        op.execute(
            sa.text(
                "UPDATE baseline_labels SET clear_reason = :new_value "
                "WHERE clear_reason = :old_value"
            ).bindparams(new_value=new_value, old_value=old_value)
        )


def _restore_clear_reasons() -> None:
    """反向改回旧值——`downgrade` 必须能把存量数据完全还原。"""
    for old_value, new_value in CLEAR_REASON_RENAMES:
        op.execute(
            sa.text(
                "UPDATE baseline_labels SET clear_reason = :old_value "
                "WHERE clear_reason = :new_value"
            ).bindparams(old_value=old_value, new_value=new_value)
        )


def upgrade() -> None:
    # 0) 枚举修正（先做，顺序上与建表无关）
    _rename_clear_reasons()

    # 1) 自动化资产
    op.create_table(
        "automation_assets",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "file_path",
            sa.String(length=512),
            nullable=False,
            comment="相对 AUTOMATION_ROOT 的相对路径",
        ),
        sa.Column("framework", sa.String(length=16), nullable=False),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'scanned'"),
        ),
        sa.Column(
            "parse_confidence",
            mysql.DECIMAL(precision=3, scale=2),
            nullable=True,
            comment="识别置信度 0.60 ~ 0.95",
        ),
        sa.Column(
            "detected_cases",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "linked_case_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="关联的测试用例；逻辑引用，不建外键（08 是物理删除）",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_autoassets_project"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_autoassets_creator"),
        sa.CheckConstraint(
            "framework IN ('pytest','playwright')", name="ck_autoassets_framework"
        ),
        sa.CheckConstraint(
            "source IN ('scanned','manual')", name="ck_autoassets_source"
        ),
        sa.CheckConstraint(
            "status IN ('active','archived')", name="ck_autoassets_status"
        ),
        **TABLE_OPTS,
    )
    op.create_index(
        "uk_autoassets_project_path", "automation_assets", ["project_id", "file_path"], unique=True
    )
    op.create_index("idx_autoassets_project", "automation_assets", ["project_id"])
    op.create_index("idx_autoassets_framework", "automation_assets", ["framework"])
    op.create_index("idx_autoassets_linked_case", "automation_assets", ["linked_case_id"])

    # 2) 执行记录
    op.create_table(
        "automation_runs",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "framework",
            sa.String(length=16),
            nullable=False,
            comment="本次执行涉及的框架；本期固定 pytest",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column(
            "exit_code",
            mysql.INTEGER(),
            nullable=True,
            comment="pytest 的退出码；1 表示有测试失败",
        ),
        sa.Column(
            "stats",
            mysql.JSON(),
            nullable=True,
            comment="{total, passed, failed, skipped}，按资产维度",
        ),
        sa.Column("log", sa.Text(), nullable=True, comment="执行输出，上限 100KB"),
        sa.Column(
            "error",
            sa.String(length=500),
            nullable=True,
            comment="跑不起来的原因（超时 / 启动失败）",
        ),
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_autoruns_project"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_autoruns_creator"),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_autoruns_status"
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_autoruns_project", "automation_runs", ["project_id"])

    # 3) 执行明细
    op.create_table(
        "automation_run_items",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("project_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("run_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("asset_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "linked_case_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="逻辑引用，不建外键",
        ),
        sa.Column(
            "case_title",
            sa.String(length=255),
            nullable=True,
            comment="执行时的用例名称快照",
        ),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("duration_ms", mysql.INTEGER(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_autorunitems_project"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["automation_runs.id"],
            name="fk_autorunitems_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["automation_assets.id"],
            name="fk_autorunitems_asset",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "asset_id", name="uk_autorunitems_run_asset"),
        sa.CheckConstraint(
            "result IN ('passed','failed','skipped')", name="ck_autorunitems_result"
        ),
        **TABLE_OPTS,
    )
    op.create_index("idx_autorunitems_run", "automation_run_items", ["run_id"])
    op.create_index("idx_autorunitems_asset", "automation_run_items", ["asset_id"])


def downgrade() -> None:
    op.drop_table("automation_run_items")
    op.drop_table("automation_runs")
    op.drop_table("automation_assets")

    # 枚举还原必须在删表**之后**也无妨（两张表互不相关），
    # 但**必须做**——否则降级后代码只认旧枚举名，
    # 存量数据会被 04 的清除标签接口判成非法原因。
    _restore_clear_reasons()
