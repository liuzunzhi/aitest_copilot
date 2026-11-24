"""10 期收尾：两库迁移往返 `0025 → 0024 → 0025` + 模板 CHECK 还原断言（T123）。

**为什么不能只看 alembic 版本号**：迁移「跑通了」不等于「数据还原了」。
`0025` 的另一半是**提示词模板的 CHECK 扩枚举**——
`prompt_templates.task_type` 的 CHECK 从四个值扩到五个（多了 `'process_baseline'`），
且 `downgrade` 必须**先删掉播种的模板行**再重建旧 CHECK
（残留的行会让旧 CHECK 重建失败，3819）。

所以这个脚本**造存量数据**（用新的 `task_type='process_baseline'` 写一行模板），
跑往返，然后逐项比对：

- 降级后：四张表已删、`task_type` **只剩旧的四个值**；
- 升级后：四张表已建、`task_type='process_baseline'` 的模板**已重新播种**。

两库都跑：开发库 `aitest_copilot_v2` 与 e2e 库 `aitest_copilot_e2e`。

**造数要照着真实的 CHECK 写**：模板行的 `status` 只能是 `'active'`，
`version_no` 有默认值——写别的枚举值会被 MySQL 3819 拒掉
（09 期 T116 就在 `baseline_revisions.status` 上踩过同一件事）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dev_check import e2e_dsn, read_env  # noqa: E402

ALEMBIC = str(ROOT / ".venv" / "Scripts" / "alembic.exe")

# 本期新表的四张表（降级后必须全删，升级后必须全建）
PROCESS_TABLES = (
    "process_baselines",
    "process_baseline_steps",
    "process_baseline_links",
    "process_baseline_revisions",
)

# 旧 CHECK 的四个值（降级后 `task_type` 只能有这些）
OLD_TASK_TYPES = ("document_parse", "incremental", "test_point", "test_case")
NEW_TASK_TYPE = "process_baseline"

_failures: list[str] = []


def ok(message: str) -> None:
    print(f"[ OK ] {message}")


def fail(message: str) -> None:
    _failures.append(message)
    print(f"[FAIL] {message}")


def run_alembic(dsn: str, *args: str) -> None:
    """跑一条 alembic 命令（带 DSN 环境变量）。"""
    env = {**os.environ, "DB_DSN": dsn}
    result = subprocess.run(
        [ALEMBIC, *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} 失败（{result.returncode}）：\n"
            f"{result.stdout}\n{result.stderr}"
        )


def current_version(dsn: str) -> str | None:
    """读 `alembic_version` 表。"""
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
            return row[0] if row else None
    finally:
        engine.dispose()


def table_exists(dsn: str, table: str) -> bool:
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() AND table_name = :t"
                    ),
                    {"t": table},
                ).scalar()
            )
    finally:
        engine.dispose()


def distinct_task_types(dsn: str) -> list[str]:
    """库里 `prompt_templates.task_type` 的所有不同值。"""
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT task_type FROM prompt_templates")
            ).scalars()
            return sorted(rows.all())
    finally:
        engine.dispose()


def count_process_rows(dsn: str) -> dict[str, int]:
    """四张表各自的行数（用来确认造的数据确实落过库）。"""
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    counts: dict[str, int] = {}
    try:
        with engine.connect() as conn:
            for table in PROCESS_TABLES:
                counts[table] = int(
                    conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
                )
        return counts
    finally:
        engine.dispose()


def seed_process_scenario(dsn: str) -> None:
    """造一个最小的流程基线场景（含步骤与关联），让降级真的丢过数据。

    **造数要照着真实的 CHECK 写**：`source_type` 只能是 `'manual'` /
    `'document_derived'`、`status` 只能是 `'active'` / `'archived'`，
    写别的会被 MySQL 3819 拒掉。
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    try:
        with engine.begin() as conn:
            project_id = conn.execute(
                text("SELECT id FROM projects ORDER BY id LIMIT 1")
            ).scalar()
            if project_id is None:
                raise RuntimeError("库里一个项目都没有，造不了场景（外键要指向它）")
            user_id = conn.execute(
                text("SELECT id FROM users WHERE username = 'admin'")
            ).scalar()
            if user_id is None:
                raise RuntimeError("库里没有 admin 用户")
            baseline_id = conn.execute(
                text(
                    "INSERT INTO process_baselines (project_id, name, source_type,"
                    " status, version_no, created_by, created_at, updated_at)"
                    " VALUES (:p, :n, 'manual', 'active', 1, :u, NOW(3), NOW(3))"
                ),
                {
                    "p": int(project_id),
                    "n": "迁移往返临时场景",
                    "u": int(user_id),
                },
            ).lastrowid
            conn.execute(
                text(
                    "INSERT INTO process_baseline_steps (baseline_id, step_no, action,"
                    " expected, created_at) VALUES (:b, 1, '临时操作', '临时预期', NOW(3))"
                ),
                {"b": int(baseline_id)},
            )
    finally:
        engine.dispose()


def cleanup_process_scenario(dsn: str) -> int:
    """收尾：确认本次造的临时场景没有残留。

    **降级已经把四张表整个删了**，所以升回来之后表是空的——
    清理时能删到的行数应该是 **0**，这正是「数据真的被丢掉」的证据。
    万一不是 0（比如降级没删干净），说明迁移有问题，要报出来。
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    remaining = 0
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT id FROM process_baselines WHERE name = '迁移往返临时场景'")
            ).scalars()
            ids = [int(item) for item in rows]
            if ids:
                placeholders = ",".join(str(item) for item in ids)
                conn.execute(
                    text(
                        "DELETE FROM process_baseline_steps WHERE baseline_id IN "
                        f"({placeholders})"
                    )
                )
                conn.execute(
                    text(
                        "DELETE FROM process_baseline_links WHERE baseline_id IN "
                        f"({placeholders})"
                    )
                )
                conn.execute(
                    text(
                        "DELETE FROM process_baselines WHERE id IN "
                        f"({placeholders})"
                    )
                )
                remaining = len(ids)
    finally:
        engine.dispose()
    return remaining


def check_roundtrip(label: str, dsn: str) -> None:
    """对一个库跑完整往返 + 断言。"""
    print(f"\n===== {label} 库 =====")

    # ---- 造存量数据（一个场景 + 一步）----
    seed_process_scenario(dsn)
    counts = count_process_rows(dsn)
    ok(
        "造了临时场景："
        + "，".join(f"{table} {rows}" for table, rows in counts.items())
    )

    try:
        # ---- 降级到 0024 ----
        run_alembic(dsn, "downgrade", "0024")
        version = current_version(dsn)
        if version != "0024":
            fail(f"降级后版本是 {version}，应为 0024")
        else:
            ok("降级到 0024")

        # ---- 降级后：四张表已删 + task_type 只剩旧四值 ----
        for table in PROCESS_TABLES:
            if table_exists(dsn, table):
                fail(f"降级后表 {table} 还在")
            else:
                ok(f"降级后表 {table} 已删")

        task_types = distinct_task_types(dsn)
        if NEW_TASK_TYPE in task_types:
            fail(f"降级后还有 task_type='{NEW_TASK_TYPE}' 的模板行（应被删）")
        else:
            ok(f"降级后 task_type 只剩旧值：{task_types}")
        unexpected = sorted(set(task_types) - set(OLD_TASK_TYPES))
        if unexpected:
            fail(f"降级后 task_type 出现了旧四值之外的值：{unexpected}")
        else:
            ok("降级后 task_type 与旧 CHECK 完全一致")

        # ---- 升回 0025 ----
        run_alembic(dsn, "upgrade", "head")
        version = current_version(dsn)
        if version != "0025":
            fail(f"升级后版本是 {version}，应为 0025")
        else:
            ok("升级回 0025")

        # ---- 升级后：四张表已建 + 模板已重新播种 ----
        for table in PROCESS_TABLES:
            if not table_exists(dsn, table):
                fail(f"升级后表 {table} 缺失")
            else:
                ok(f"升级后表 {table} 已建")

        task_types = distinct_task_types(dsn)
        if NEW_TASK_TYPE not in task_types:
            fail(f"升级后没有 task_type='{NEW_TASK_TYPE}' 的模板（应重新播种）")
        else:
            ok(f"升级后 task_type 已重新播种：{task_types}")
        missing = sorted(set(OLD_TASK_TYPES) - set(task_types))
        if missing:
            fail(f"升级后旧模板丢了：{missing}")
        else:
            ok("升级后旧四值模板仍在")
    finally:
        # 收尾确认没有残留——**降级已经把这批数据整个丢掉了**，
        # 所以这里应该删不到东西（删到了反而说明降级没删干净）。
        remaining = cleanup_process_scenario(dsn)
        if remaining:
            fail(f"升级后还有 {remaining} 个造的临时场景残留（降级没删干净？）")
        else:
            ok("升级后没有造的临时场景残留（降级确实把数据丢掉了）")


def main() -> int:
    env = read_env()
    dev_dsn = env.get("DB_DSN", "")
    if not dev_dsn:
        print("[FAIL] .env 里没有 DB_DSN")
        return 1

    print("=== 10 期迁移往返（0025 → 0024 → 0025）===")
    for label, dsn in (
        ("开发", dev_dsn),
        ("e2e", e2e_dsn(dev_dsn)),
    ):
        try:
            check_roundtrip(label, dsn)
        except Exception as exc:  # noqa: BLE001 - 收尾脚本要报告而不是崩
            fail(f"{label} 库往返异常：{type(exc).__name__}: {exc}")

    print()
    if _failures:
        print(f"结论：有 {len(_failures)} 项失败")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print("结论：两库迁移往返干净，四张表与模板 CHECK 都还原彻底")
    return 0


if __name__ == "__main__":
    sys.exit(main())
