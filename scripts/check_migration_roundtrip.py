"""09 期收尾：两库迁移往返 `0024 → 0023 → 0024` + 枚举还原断言（T116）。

**为什么不能只看 alembic 版本号**：迁移「跑通了」不等于「数据还原了」。
`0024` 的另一半是**清除原因枚举修正**（`priority_changed` → `baseline_adjusted`、
`duplicate_label` → `backtrace_override`）——
`downgrade` 必须把存量值**逐字节**改回旧名，否则降级后
04 的清除标签接口会把历史数据判成非法原因（`INVALID_CLEAR_REASON`）。

所以这个脚本**造存量数据**（用旧枚举名写两行标签），
跑往返，然后逐字节比对：

- 升级后：只剩新值；
- 降级后：**逐字节还原**为旧值。

两库都跑：开发库 `aitest_copilot_v2` 与 e2e 库 `aitest_copilot_e2e`。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dev_check import e2e_dsn, migration_head, read_env  # noqa: E402

ALEMBIC = str(ROOT / ".venv" / "Scripts" / "alembic.exe")
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")

# 当前的迁移 head —— **动态取**，不硬编码。
# 这个脚本做的是「降到 0023 → 升回最新」，每加一个迁移都要跟着改版本号
# 是最容易漏的那类维护负担（12.5 期加 0028 时就在这里红过）。
HEAD = migration_head()

# 旧枚举名 → 新枚举名（与 `migrations/versions/0024_automation.py` 同源）
LEGACY_VALUES = ("priority_changed", "duplicate_label")
NEW_VALUES = ("baseline_adjusted", "backtrace_override")

# 造的存量标签用的 target_id（高位，避开真实数据）
SEED_TARGET_IDS = (900000, 900001)

# 临时项目名——收尾时按它识别并删除
PLACEHOLDER_PROJECT_NAME = "迁移往返临时项目"

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


def distinct_clear_reasons(dsn: str) -> list[str]:
    """库里 `baseline_labels.clear_reason` 的所有不同值。"""
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT clear_reason FROM baseline_labels "
                    "WHERE clear_reason IS NOT NULL"
                )
            ).scalars()
            return sorted(rows.all())
    finally:
        engine.dispose()


def seed_legacy_labels(dsn: str, project_id: int, user_id: int) -> int:
    """造两行**旧枚举名**的标签（升级前该有的存量形态）。

    只需要 `clear_reason` 对得上；其它列给最小合法值。
    `revision_id` 必须指向**真实存在的**基线版本（有外键），
    `project_id` / `target_id` 用高位 id 避开真实数据。
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    inserted = 0
    try:
        with engine.begin() as conn:
            revision_id = conn.execute(
                text("SELECT id FROM baseline_revisions WHERE project_id = :p LIMIT 1"),
                {"p": project_id},
            ).scalar()
            if revision_id is None:
                raise RuntimeError("该项目没有基线版本，造不了标签（外键要指向它）")
            for index, reason in enumerate(LEGACY_VALUES):
                conn.execute(
                    text(
                        "INSERT INTO baseline_labels (project_id, revision_id, target_type,"
                        " target_id, label_type, status, confirmed_by, confirmed_at,"
                        " clear_reason) VALUES (:project_id, :revision_id, 'function',"
                        " :target_id, 'changed', 'cleared', :user_id, NOW(3), :reason)"
                    ),
                    {
                        "project_id": project_id,
                        "revision_id": int(revision_id),
                        "target_id": 900000 + index,
                        "user_id": user_id,
                        "reason": reason,
                    },
                )
                inserted += 1
    finally:
        engine.dispose()
    return inserted


def find_admin(dsn: str) -> tuple[int, int]:
    """取 admin 用户 id 与一个有基线版本的项目 id（造标签要用）。

    **e2e 库可能一个项目都没有**（前台用例跑完会按 `e2e-` 前缀清干净），
    这时自己造最小的前置数据：一个项目 + 一个基线版本。
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    try:
        with engine.begin() as conn:
            user_id = conn.execute(
                text("SELECT id FROM users WHERE username = 'admin'")
            ).scalar()
            if user_id is None:
                raise RuntimeError("库里没有 admin 用户")
            project_id = conn.execute(
                text(
                    "SELECT DISTINCT p.id FROM projects p "
                    "JOIN baseline_revisions r ON r.project_id = p.id LIMIT 1"
                )
            ).scalar()
            if project_id is None:
                project_id = _create_placeholder_revision(conn)
            return int(user_id), int(project_id)
    finally:
        engine.dispose()


def _create_placeholder_revision(conn) -> int:
    """造最小的前置数据：一个项目 + 一个基线版本。

    e2e 库跑完前台用例会被清空，`baseline_labels.revision_id` 有外键，
    没有基线版本就造不出标签——所以这里补一行最小数据。
    收尾时会被 `cleanup_seeded_labels` 一起删掉。
    """
    from sqlalchemy import text

    project_id = conn.execute(
        text(
            "INSERT INTO projects (name, description, status, created_at) "
            "VALUES (:name, NULL, 'active', NOW(3))"
        ),
        {"name": PLACEHOLDER_PROJECT_NAME},
    ).lastrowid
    conn.execute(
        text(
            "INSERT INTO baseline_revisions (project_id, status, structure_json,"
            " module_count, function_count, feature_point_count, label_count, created_at)"
            " VALUES (:project_id, 'submitted', NULL, 0, 0, 0, 0, NOW(3))"
        ),
        {"project_id": int(project_id)},
    )
    return int(project_id)


def cleanup_seeded_labels(dsn: str, project_id: int) -> int:
    """删掉本次造的标签（不留垃圾在开发库）。

    如果这个项目是本脚本造的临时项目（「迁移往返临时项目」），
    连项目与基线版本一起删掉。
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn, pool_pre_ping=True, future=True)
    removed = 0
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM baseline_labels WHERE project_id = :p "
                    "AND target_id IN (900000, 900001)"
                ),
                {"p": project_id},
            )
            removed = result.rowcount or 0
            # 临时项目连同基线版本一起清掉——不留垃圾在 e2e 库。
            is_temp = conn.execute(
                text("SELECT COUNT(*) FROM projects WHERE id = :p AND name = :n"),
                {"p": project_id, "n": PLACEHOLDER_PROJECT_NAME},
            ).scalar()
            if is_temp:
                conn.execute(
                    text("DELETE FROM baseline_revisions WHERE project_id = :p"),
                    {"p": project_id},
                )
                conn.execute(
                    text("DELETE FROM projects WHERE id = :p"), {"p": project_id}
                )
    finally:
        engine.dispose()
    return removed


def check_roundtrip(label: str, dsn: str) -> None:
    """对一个库跑完整往返 + 断言。"""
    print(f"\n===== {label} 库 =====")
    user_id, project_id = find_admin(dsn)

    # ---- 造存量数据（旧枚举名） ----
    seeded = seed_legacy_labels(dsn, project_id, user_id)
    ok(f"造了 {seeded} 行旧枚举名标签（{', '.join(LEGACY_VALUES)}）")

    try:
        # ---- 降级到 0023 ----
        run_alembic(dsn, "downgrade", "0023")
        version = current_version(dsn)
        if version != "0023":
            fail(f"降级后版本是 {version}，应为 0023")
        else:
            ok("降级到 0023")

        # ---- 降级后：枚举必须逐字节还原，且三张表已删 ----
        reasons = distinct_clear_reasons(dsn)
        restored = sorted(set(LEGACY_VALUES) & set(reasons))
        if restored == sorted(LEGACY_VALUES):
            ok(f"降级后 clear_reason 逐字节还原：{restored}")
        else:
            fail(
                f"降级后 clear_reason 应只剩旧值 {sorted(LEGACY_VALUES)}，实际 {reasons}"
            )

        for table in ("automation_assets", "automation_runs", "automation_run_items"):
            if table_exists(dsn, table):
                fail(f"降级后表 {table} 还在")
            else:
                ok(f"降级后表 {table} 已删")

        # ---- 升回当前 head ----
        run_alembic(dsn, "upgrade", "head")
        version = current_version(dsn)
        if version != HEAD:
            fail(f"升级后版本是 {version}，应为 {HEAD}")
        else:
            ok(f"升级回 {HEAD}")

        # ---- 升级后：枚举应只剩新值 ----
        reasons = distinct_clear_reasons(dsn)
        remaining_legacy = sorted(set(LEGACY_VALUES) & set(reasons))
        if remaining_legacy:
            fail(f"升级后仍有旧枚举值 {remaining_legacy}（应已被改写为新值）")
        else:
            ok(f"升级后旧枚举值已清空，现存值：{reasons}")

        for table in ("automation_assets", "automation_runs", "automation_run_items"):
            if not table_exists(dsn, table):
                fail(f"升级后表 {table} 缺失")
            else:
                ok(f"升级后表 {table} 已建")
    finally:
        # 收尾必须把造的存量数据删掉——开发库是长期资产，不能留垃圾。
        removed = cleanup_seeded_labels(dsn, project_id)
        ok(f"清理了 {removed} 行造的存量标签")


def main() -> int:
    env = read_env()
    dev_dsn = env.get("DB_DSN", "")
    if not dev_dsn:
        print("[FAIL] .env 里没有 DB_DSN")
        return 1

    print(f"=== 09 期迁移往返（0023 → head {HEAD}）+ 枚举还原 ===")
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
    print("结论：两库迁移往返干净，枚举还原彻底")
    return 0


if __name__ == "__main__":
    sys.exit(main())
