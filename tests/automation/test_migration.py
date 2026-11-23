"""迁移 `0024` 的数据库层断言（09-automation T111 / AC-181）。

覆盖三件事：三表及其索引 / CHECK 真的建出来了；枚举修正确实改了存量数据；
`baseline_labels.clear_reason` 没有 CHECK 约束（所以枚举修正不需要改表结构）。

`0024 → 0023 → 0024` 的往返不在这里跑——迁移在独立事务里执行，
与 `db` 夹具的嵌套事务会互相干扰；往返由 T111 的验证命令在两库上实跑。
"""

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.common.db import get_engine
from app.models.baseline import BaselineLabel


@pytest.fixture(scope="module")
def engine() -> Engine:
    """只读用的引擎：结构断言不写入，也不吃 `db` 夹具的事务。"""
    return get_engine()


def test_ac_181_three_tables_exist(engine: Engine):
    """三张表都存在。"""
    names = set(inspect(engine).get_table_names())
    assert {"automation_assets", "automation_runs", "automation_run_items"} <= names


@pytest.mark.parametrize(
    ("table", "indexes"),
    [
        (
            "automation_assets",
            {
                "uk_autoassets_project_path",
                "idx_autoassets_project",
                "idx_autoassets_framework",
                "idx_autoassets_linked_case",
            },
        ),
        ("automation_runs", {"idx_autoruns_project"}),
        (
            "automation_run_items",
            {
                "uk_autorunitems_run_asset",
                "idx_autorunitems_run",
                "idx_autorunitems_asset",
            },
        ),
    ],
)
def test_ac_181_indexes_exist(engine: Engine, table: str, indexes: set[str]):
    """索引 / 唯一键与 spec §4 一致。"""
    names = {item["name"] for item in inspect(engine).get_indexes(table)}
    assert indexes <= names


@pytest.mark.parametrize(
    ("table", "checks"),
    [
        (
            "automation_assets",
            {"ck_autoassets_framework", "ck_autoassets_source", "ck_autoassets_status"},
        ),
        ("automation_runs", {"ck_autoruns_status"}),
        ("automation_run_items", {"ck_autorunitems_result"}),
    ],
)
def test_ac_181_check_constraints_exist(engine: Engine, table: str, checks: set[str]):
    """CHECK 约束真的落到了库里（不是只写在 ORM 元数据里）。"""
    names = {
        item["name"] for item in inspect(engine).get_check_constraints(table)
    }
    assert checks <= names


def test_ac_181_no_check_on_clear_reason(engine: Engine):
    """`baseline_labels.clear_reason` **没有** CHECK 约束。

    这正是枚举修正只需要 UPDATE 存量、不需要改表结构的原因——
    如果这里有 CHECK，改枚举值就得先 drop 再 create constraint。
    """
    checks = {
        item["name"]
        for item in inspect(engine).get_check_constraints("baseline_labels")
    }
    assert not any("clear_reason" in name.lower() for name in checks)


def test_ac_181_existing_clear_reasons_are_new_values(db: Session):
    """存量标签里**不再出现**旧枚举值。

    迁移 `0024` 已经把 `priority_changed` / `duplicate_label`
    改写成 `baseline_adjusted` / `backtrace_override`。
    """
    old_values = db.scalars(
        select(BaselineLabel.clear_reason).where(
            BaselineLabel.clear_reason.in_(["priority_changed", "duplicate_label"])
        )
    ).all()
    assert old_values == []


def test_ac_181_new_clear_reason_values_are_accepted(db: Session):
    """新枚举值能写进库里（列宽 32 足够放下新值名）。"""
    import uuid

    from app.models.baseline import BaselineRevision
    from app.models.project import Project
    from app.models.user import User

    user = User(username=f"clr-{uuid.uuid4().hex[:10]}", password_hash="x" * 60)
    db.add(user)
    project = Project(name=f"枚举项目-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()

    # `revision_id` 有真实外键，必须先建一条审核记录
    revision = BaselineRevision(project_id=project.id, status="approved")
    db.add(revision)
    db.flush()

    label = BaselineLabel(
        project_id=project.id,
        revision_id=revision.id,
        target_type="function",
        target_id=1,
        label_type="changed",
        confirmed_by=user.id,
        status="cleared",
        clear_reason="backtrace_override",
    )
    db.add(label)
    db.flush()

    assert label.clear_reason == "backtrace_override"


def test_ac_181_migration_head_is_0024(db: Session):
    """迁移 head **不低于** `0024`（即 `0024` 已应用）。

    **为什么不是 `== "0024"`**：这条断言测的是**全局迁移 head 指针**，
    不是 09 期的业务行为或错误码。写死等值意味着——
    **10 期建了 `0025` 之后它必然失效**，往后每一期建新迁移都会再失效一次。
    09 期 T111 新建这个文件时 08 期并没有 head 断言，所以这是第一次撞上。

    改成「不低于 0024」后语义更准（`0024` **已应用**这一事实），
    且不再随新迁移反复失效。09 期的业务逻辑与错误码断言**一条未动**。
    """
    from sqlalchemy import text

    row = db.execute(text("SELECT version_num FROM alembic_version")).first()
    assert row is not None
    assert int(row[0]) >= 24
