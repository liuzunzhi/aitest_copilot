"""自动化执行与测试报告的三张表（09-automation T111）。

- `automation_assets`：扫描进来的自动化资产（Pytest / Playwright），
  可关联一条测试用例。
- `automation_runs`：一次执行任务的记录（状态、退出码、统计、日志）。
- `automation_run_items`：这次执行里每个资产的结果。

三条刻意的设计：

1. `linked_case_id` **不建外键**：08 的 `delete_case` 是**物理删除**，
   建外键会把 08 的既有行为变成 500（`IntegrityError`）。
   这里用逻辑引用 + 落库快照（`case_title`），
   与 08 的 `test_point_id` 同一思路。
2. `file_path` 存**相对路径**，不存绝对路径：绝对路径会随部署环境漂移，
   且泄露服务器目录结构。绝对路径由服务端在执行时用 `AUTOMATION_ROOT` 拼出来。
3. 明细的粒度是**资产**，不是 pytest 的测试函数：一个文件里有 N 个测试函数，
   一次执行会产生 N 条结果，本期按文件聚合（见 spec §4.3）。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, DECIMAL, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

FRAMEWORKS = ("pytest", "playwright")
ASSET_SOURCES = ("scanned", "manual")
ASSET_STATUSES = ("active", "archived")
RUN_STATUSES = ("running", "succeeded", "failed")
RUN_RESULTS = ("passed", "failed", "skipped")


class AutomationAsset(Base):
    """一个自动化资产（一个测试脚本文件）。"""

    __tablename__ = "automation_assets"
    # pytest 会把 `Test*` 开头的类当成测试类收集——显式关掉。
    # `Automation*` 本身不撞这个规则，但统一加上更省心
    # （08 的 `TestCase*` 已有先例，见 `app/models/test_case.py`）。
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_autoassets_project"),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_autoassets_creator"),
        Index("uk_autoassets_project_path", "project_id", "file_path", unique=True),
        Index("idx_autoassets_project", "project_id"),
        Index("idx_autoassets_framework", "framework"),
        Index("idx_autoassets_linked_case", "linked_case_id"),
        CheckConstraint(
            "framework IN ('pytest','playwright')", name="ck_autoassets_framework"
        ),
        CheckConstraint(
            "source IN ('scanned','manual')", name="ck_autoassets_source"
        ),
        CheckConstraint(
            "status IN ('active','archived')", name="ck_autoassets_status"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="相对 AUTOMATION_ROOT 的相对路径；512 上限是为了让 "
        "(project_id, file_path) 唯一索引落在 InnoDB 的 3072 字节键长内",
    )
    framework: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'scanned'")
    )
    parse_confidence: Mapped[float | None] = mapped_column(
        DECIMAL(3, 2), nullable=True, comment="识别置信度 0.60 ~ 0.95"
    )
    detected_cases: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    linked_case_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        nullable=True,
        comment="关联的测试用例；逻辑引用，不建外键（08 是物理删除）",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class AutomationRun(Base):
    """一次执行任务。

    `status` 的语义是「系统是否正常完成执行」——
    `succeeded` = pytest 进程**正常跑完**（哪怕退出码是 1，测试失败也是正常业务结果）；
    `failed` = 跑不起来（超时 / 启动失败）。两者靠 `error` 字段区分。
    """

    __tablename__ = "automation_runs"
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_autoruns_project"),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_autoruns_creator"),
        Index("idx_autoruns_project", "project_id"),
        CheckConstraint("status IN ('running','succeeded','failed')", name="ck_autoruns_status"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    framework: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="本次执行涉及的框架；本期固定 pytest"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'running'")
    )
    exit_code: Mapped[int | None] = mapped_column(
        INTEGER(), nullable=True, comment="pytest 的退出码；1 表示有测试失败"
    )
    stats: Mapped[dict | None] = mapped_column(
        JSON(), nullable=True, comment="{total, passed, failed, skipped}，按资产维度"
    )
    log: Mapped[str | None] = mapped_column(
        Text(), nullable=True, comment="执行输出，上限 100KB"
    )
    error: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="跑不起来的原因（超时 / 启动失败）"
    )
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class AutomationRunItem(Base):
    """这次执行里一个资产的结果。

    `case_title` 是**执行时的用例名称快照**：08 删用例是物理删除，
    资产关联的用例被删后，报告必须仍能显示「当时关联的是哪条用例」。
    """

    __tablename__ = "automation_run_items"
    __test__ = False
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_autorunitems_project"),
        ForeignKeyConstraint(
            ["run_id"],
            ["automation_runs.id"],
            name="fk_autorunitems_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["asset_id"],
            ["automation_assets.id"],
            name="fk_autorunitems_asset",
            ondelete="CASCADE",
        ),
        Index("uk_autorunitems_run_asset", "run_id", "asset_id", unique=True),
        Index("idx_autorunitems_run", "run_id"),
        Index("idx_autorunitems_asset", "asset_id"),
        CheckConstraint(
            "result IN ('passed','failed','skipped')", name="ck_autorunitems_result"
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    run_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    asset_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    linked_case_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="逻辑引用，不建外键"
    )
    case_title: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="执行时的用例名称快照"
    )
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(INTEGER(), nullable=True)


__all__ = [
    "ASSET_SOURCES",
    "ASSET_STATUSES",
    "FRAMEWORKS",
    "RUN_RESULTS",
    "RUN_STATUSES",
    "AutomationAsset",
    "AutomationRun",
    "AutomationRunItem",
]
