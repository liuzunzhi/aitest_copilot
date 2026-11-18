"""开发/联调环境一键自检。

解决的问题：8001 端口被连「别的库」的旧后端占住时，前端和 e2e 看起来都通，
但数据写进了错误的库（本轮 T65 踩过一次，污染了开发库）。

用法（用项目自己的虚拟环境跑）：

    .\\.venv\\Scripts\\python.exe scripts\\dev_check.py
    .\\.venv\\Scripts\\python.exe scripts\\dev_check.py --expect-db e2e

检查项：
    1. 开发库 / e2e 库是否存在，alembic 版本是否等于迁移 head，04 基线表是否齐
    2. 8000 / 8001 / 5173 / 5174 的监听者（PID、进程名、命令行、绑定地址）
    3. 后端 /health 与前端代理链路
    4. 每个在跑的后端实际连的是哪个库（用 admin 参与的 /api/projects 与两库比对）

`--expect-db e2e` 会额外断言 8001 连的是 `aitest_copilot_e2e`（`dev` 则断言 8000）。

只读：不写任何数据，可以随时跑。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations" / "versions"
# dev 后端 8000 / e2e 后端 8001；前端 5173 代理到 8000，5174 代理到 8001
BACKEND_PORTS = (8000, 8001)
FRONTEND_PORTS = (5173, 5174)
FRONTEND_TARGETS = {5173: 8000, 5174: 8001}
E2E_DATABASE = "aitest_copilot_e2e"
BASELINE_TABLES = (
    "baseline_modules",
    "baseline_functions",
    "baseline_feature_points",
    "baseline_labels",
    "baseline_revisions",
)

_ok = True
_process_cache: dict[int, tuple[str, str]] = {}


def ok(message: str) -> None:
    print(f"[ OK ] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    global _ok
    _ok = False
    print(f"[FAIL] {message}")


def info(message: str) -> None:
    print(f"       {message}")


# --------------------------------------------------------------------------- #
# .env 与 DSN
# --------------------------------------------------------------------------- #
def read_env() -> dict[str, str]:
    env_file = ROOT / ".env"
    if not env_file.exists():
        fail("找不到 .env，无法确定开发库 DSN")
        return {}
    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def parse_dsn(dsn: str) -> dict:
    """mysql+pymysql://user:pass@host:port/db?charset=utf8mb4 → 连接参数。"""
    parsed = urllib.parse.urlparse(dsn.replace("mysql+pymysql://", "mysql://", 1))
    return {
        "user": urllib.parse.unquote(parsed.username or ""),
        "password": urllib.parse.unquote(parsed.password or ""),
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "database": (parsed.path or "/").lstrip("/"),
    }


def e2e_dsn(dev_dsn: str) -> str:
    """e2e 库固定是 `aitest_copilot_e2e`（与 tests/e2e/support.py 保持一致）。

    注意不是简单加 `_e2e` 后缀：开发库是 `aitest_copilot_v2`，e2e 库不带 `_v2`。
    """
    explicit = os.getenv("E2E_DB_DSN")
    if explicit:
        return explicit
    params = parse_dsn(dev_dsn)
    return dev_dsn.replace(f"/{params['database']}", f"/{E2E_DATABASE}", 1)


# --------------------------------------------------------------------------- #
# 库检查
# --------------------------------------------------------------------------- #
def migration_head() -> str | None:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in MIGRATIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revisions.update(re.findall(r"^revision\s*(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", text, re.M))
        for line in re.findall(r"^down_revision[^=]*=\s*(.+)$", text, re.M):
            parents.update(re.findall(r"[\"']([^\"']+)[\"']", line))
    heads = revisions - parents
    return heads.pop() if len(heads) == 1 else None


def check_database(label: str, dsn: str, head: str | None) -> dict | None:
    try:
        import pymysql
    except ImportError:
        fail("当前 Python 没有 pymysql，请用 .venv\\Scripts\\python.exe 运行")
        return None

    params = parse_dsn(dsn)
    try:
        conn = pymysql.connect(
            host=params["host"],
            port=params["port"],
            user=params["user"],
            password=params["password"],
            database=params["database"],
            connect_timeout=3,
        )
    except Exception as exc:  # noqa: BLE001 - 自检脚本要报告而不是抛栈
        fail(f"{label} 库连不上（{params['database']}）：{exc}")
        return None

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            row = cur.fetchone()
            version = row[0] if row else None
            cur.execute("SHOW TABLES LIKE 'baseline%%'")
            tables = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT id FROM users WHERE username = %s", ("admin",))
            admin_row = cur.fetchone()
            admin_id = admin_row[0] if admin_row else None
            # 与 GET /api/projects 同口径：admin 参与的项目
            cur.execute(
                "SELECT DISTINCT pm.project_id FROM project_members pm "
                "JOIN users u ON u.id = pm.user_id WHERE u.username = %s "
                "ORDER BY pm.project_id",
                ("admin",),
            )
            admin_projects = {row[0] for row in cur.fetchall()}

        if version != head:
            fail(f"{label} 库 alembic 是 {version}，迁移 head 是 {head}")
        else:
            ok(f"{label} 库 {params['database']} 迁移在 {version}")

        missing = [t for t in BASELINE_TABLES if t not in tables]
        if missing:
            fail(f"{label} 库缺表：{', '.join(missing)}")
        else:
            ok(f"{label} 库 04 基线表齐（{len(BASELINE_TABLES)} 张）")

        return {
            "database": params["database"],
            "admin_id": admin_id,
            "admin_projects": admin_projects,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 端口检查
# --------------------------------------------------------------------------- #
def listening_ports() -> dict[int, list[str]]:
    """端口 → 监听地址列表。"""
    try:
        output = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="ignore",
            check=False,
        ).stdout
    except OSError as exc:
        fail(f"调不动 netstat：{exc}")
        return {}

    ports: dict[int, list[str]] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        address, port_text = parts[1].rsplit(":", 1)
        if not port_text.isdigit():
            continue
        port = int(port_text)
        if port in BACKEND_PORTS or port in FRONTEND_PORTS:
            ports.setdefault(port, []).append(f"{address} (pid {parts[4]})")
    return ports


def process_detail(pid: int) -> tuple[str, str]:
    """PID → (进程名, 命令行)。"""
    if pid in _process_cache:
        return _process_cache[pid]
    name = "unknown"
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="ignore",
            check=False,
        ).stdout.strip()
        if out.startswith('"'):
            name = out.split('","')[0].strip('"')
    except OSError:
        pass

    command = ""
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        ).stdout.strip()
        command = out.splitlines()[0] if out else ""
    except OSError:
        pass

    _process_cache[pid] = (name, command)
    return name, command


def check_ports() -> dict[int, list[str]]:
    ports = listening_ports()

    for port in BACKEND_PORTS:
        if port not in ports:
            warn(f"后端端口 {port} 没人监听（这一套环境没起）")
            continue
        for entry in ports[port]:
            pid = int(entry.rsplit("pid ", 1)[1].rstrip(")"))
            name, command = process_detail(pid)
            ok(f"后端 {port} ← {entry}，{name}")
            if command:
                info(command)

    for port in FRONTEND_PORTS:
        if port not in ports:
            warn(f"前端端口 {port} 没人监听（这一套环境没起）")
            continue
        target = FRONTEND_TARGETS[port]
        for entry in ports[port]:
            pid = int(entry.rsplit("pid ", 1)[1].rstrip(")"))
            name, _ = process_detail(pid)
            ok(f"前端 {port} ← {entry}，{name}（应代理到 {target}）")
            if entry.startswith("::1") and "127.0.0.1" not in entry:
                fail(
                    f"前端 {port} 只绑了 IPv6 ::1，Chromium 解析 localhost→127.0.0.1 会连不上；"
                    f"重启时加 --host 127.0.0.1"
                )
    return ports


# --------------------------------------------------------------------------- #
# HTTP 检查
# --------------------------------------------------------------------------- #
def http_json(
    url: str,
    *,
    data: dict | None = None,
    json_data: dict | None = None,
    token: str | None = None,
    timeout: float = 4.0,
):
    headers = {"Accept": "application/json"}
    body = None
    if json_data is not None:
        body = json.dumps(json_data).encode()
        headers["Content-Type"] = "application/json"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read() or b"null")


def check_backend_api(base: str, dbs: dict[str, dict | None]) -> str | None:
    """返回后端实际在用的库名（判定不出来时返回 None）。"""
    try:
        status, body = http_json(f"{base}/health")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        fail(f"后端 {base} /health 不通：{exc}")
        return None
    if status == 200 and body.get("status") == "ok":
        ok(f"后端 {base} /health 正常")
    else:
        fail(f"后端 {base} /health 异常：{status} {body}")
        return None

    username = os.getenv("E2E_ADMIN_USERNAME", "admin")
    password = os.getenv("E2E_ADMIN_PASSWORD", "Admin12345")
    try:
        _, auth = http_json(
            f"{base}/api/auth/login",
            json_data={"username": username, "password": password},
        )
        token = auth["access_token"]
    except urllib.error.HTTPError as exc:
        warn(f"后端 {base} 登录 {username} 失败（HTTP {exc.code}），无法判定连的是哪个库")
        return None
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        warn(f"后端 {base} 登录 {username} 失败，无法判定连的是哪个库：{exc}")
        return None

    try:
        _, me = http_json(f"{base}/api/auth/me", token=token)
        _, projects = http_json(f"{base}/api/projects", token=token)
        # 用「admin 的 id + 参与的项目集合」认库：只看项目集合时，两库都空就会判定不出来
        api_fingerprint = (me["id"], frozenset(item["id"] for item in projects))
    except (urllib.error.URLError, OSError, ValueError, TypeError, KeyError) as exc:
        warn(f"后端 {base} 取项目列表失败，无法判定连的是哪个库：{exc}")
        return None

    matches = [
        label
        for label, db in dbs.items()
        if db is not None
        and (db["admin_id"], frozenset(db["admin_projects"])) == api_fingerprint
    ]
    if len(matches) == 1:
        label = matches[0]
        ok(
            f"后端 {base} 实际连的是【{dbs[label]['database']}】"
            f"（{label}，admin id={api_fingerprint[0]}，"
            f"{len(api_fingerprint[1])} 个参与项目）"
        )
        return dbs[label]["database"]
    if len(matches) > 1:
        warn(f"后端 {base}：两个库的 admin 指纹一致，无法判定连接库")
    else:
        warn(f"后端 {base} 的 admin 指纹与两个库都不匹配，可能是第三种 DSN")
    return None


def check_frontend_proxy(
    base: str, target_port: int, ports: dict[int, list[str]]
) -> None:
    if target_port not in ports:
        warn(f"前端 {base} 的代理目标 {target_port} 没起，跳过代理检查")
        return
    try:
        http_json(f"{base}/api/projects")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            ok(f"前端 {base} → 后端 {target_port} 代理正常（未带 token 返回 {exc.code}）")
        else:
            fail(f"前端 {base} 代理异常：HTTP {exc.code}")
        return
    except (urllib.error.URLError, OSError, ValueError) as exc:
        fail(f"前端 {base} 代理不通：{exc}")
        return
    ok(f"前端 {base} → 后端 {target_port} 代理正常（匿名可访问）")


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="开发/联调环境自检")
    parser.add_argument(
        "--expect-db",
        choices=("dev", "e2e", "none"),
        default="none",
        help="断言后端连的库（e2e 跑前台用例前建议 --expect-db e2e）",
    )
    args = parser.parse_args()

    env = read_env()
    dev_dsn = env.get("DB_DSN", "")
    if not dev_dsn:
        fail(".env 里没有 DB_DSN")
        return 1

    # 06 期新增必填：大模型 API Key 的加密主密钥（缺失时后端启动即失败）
    if not env.get("LLM_SECRET_KEY", "").strip():
        fail(
            "LLM_SECRET_KEY 缺失：请在 .env 补一行 LLM_SECRET_KEY=<随机长字符串>"
            "（只加密本平台的供应商密钥，不是供应商 API Key）"
        )
    else:
        ok("LLM_SECRET_KEY 已配置")

    head = migration_head()
    if head is None:
        fail("算不出 alembic head（迁移图有多个 head 或解析失败）")
    else:
        info(f"迁移 head = {head}")

    dev_db = check_database("开发", dev_dsn, head)
    e2e_db = check_database("e2e", e2e_dsn(dev_dsn), head)
    dbs = {"dev": dev_db, "e2e": e2e_db}

    ports = check_ports()

    actual: dict[int, str | None] = {}
    for port in BACKEND_PORTS:
        if port in ports:
            actual[port] = check_backend_api(f"http://127.0.0.1:{port}", dbs)

    for port in FRONTEND_PORTS:
        if port in ports:
            check_frontend_proxy(f"http://127.0.0.1:{port}", FRONTEND_TARGETS[port], ports)

    if args.expect_db != "none":
        expected_port = 8001 if args.expect_db == "e2e" else 8000
        expected = dbs[args.expect_db]
        expected_name = expected["database"] if expected else f"{args.expect_db} 库"
        if expected_port not in ports:
            fail(f"要求 {expected_port} 连【{expected_name}】，但 {expected_port} 没人监听")
        elif actual.get(expected_port) is None:
            fail(f"要求 {expected_port} 连【{expected_name}】，但判定不出来")
        elif actual[expected_port] != expected_name:
            fail(f"要求 {expected_port} 连【{expected_name}】，实际连的是【{actual[expected_port]}】")
        else:
            ok(f"{expected_port} 连接库符合预期（{expected_name}）")

    print()
    if _ok:
        print("结论：环境自检通过")
        return 0
    print("结论：有检查项失败，见上面的 [FAIL]")
    return 1


if __name__ == "__main__":
    sys.exit(main())
