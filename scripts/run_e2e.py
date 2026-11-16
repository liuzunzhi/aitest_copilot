"""一条命令跑完前台 e2e：自检 → 起 8001/5174 → 跑 tests/e2e → 收尾。

之前每个 task 都要手工开两个终端、记得加 `--host 127.0.0.1`、还要防着端口被
连开发库的旧后端占住。这个脚本把这几步串起来，端口上已经有服务就直接复用，
但必须先通过 `dev_check.py --expect-db e2e` 才允许开跑。

用法：

    .\\.venv\\Scripts\\python.exe scripts\\run_e2e.py
    .\\.venv\\Scripts\\python.exe scripts\\run_e2e.py --keep          # 跑完不杀进程
    .\\.venv\\Scripts\\python.exe scripts\\run_e2e.py --keep-data     # 保留造的数据
    .\\.venv\\Scripts\\python.exe scripts\\run_e2e.py -k bl-review    # 其余参数透传 pytest

约定（与 specs/验证约定.md §3 一致）：
    后端 127.0.0.1:8001，DB_DSN 指向 aitest_copilot_e2e
    前端 127.0.0.1:5174，VITE_API_TARGET 指向 8001，且必须 --host 127.0.0.1
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LOG_DIR = ROOT / "var"
BACKEND_URL = "http://127.0.0.1:8001"
FRONTEND_URL = "http://127.0.0.1:5174"
PYTHON = sys.executable

sys.path.insert(0, str(ROOT / "scripts"))


def _e2e_dsn() -> str:
    from dev_check import e2e_dsn, read_env

    env = read_env()
    if "DB_DSN" not in env:
        raise RuntimeError(".env 里没有 DB_DSN，无法定位 e2e 库")
    return e2e_dsn(env["DB_DSN"])


def _port_listening(port: int) -> bool:
    from dev_check import listening_ports

    return port in listening_ports()


def _wait_for(url: str, timeout: float, label: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError(f"{label} 在 {timeout:.0f}s 内没起来：{url}")


def _start(cmd: list[str], *, cwd: Path, env: dict[str, str], log_name: str):
    LOG_DIR.mkdir(exist_ok=True)
    handle = open(LOG_DIR / log_name, "w", encoding="utf-8")
    print(f"[ .. ] 启动 {' '.join(cmd)}（日志 var/{log_name}）")
    process = subprocess.Popen(
        cmd, cwd=str(cwd), env=env, stdout=handle, stderr=subprocess.STDOUT
    )
    return process, handle


def main() -> int:
    parser = argparse.ArgumentParser(description="一键跑前台 e2e")
    parser.add_argument("--keep", action="store_true", help="跑完不杀本次启动的后端/前端")
    parser.add_argument("--keep-data", action="store_true", help="跳过 e2e 数据清理")
    parser.add_argument("--timeout", type=float, default=90.0, help="等端口就绪的秒数")
    args, extra = parser.parse_known_args()
    if extra and extra[0] == "--":
        extra = extra[1:]

    dsn = _e2e_dsn()
    started: list[tuple[subprocess.Popen, object]] = []
    try:
        if _port_listening(8001):
            print("[ .. ] 8001 已有服务，复用（下面会校验它连的是 e2e 库）")
        else:
            started.append(
                _start(
                    [PYTHON, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001"],
                    cwd=ROOT,
                    env={**os.environ, "DB_DSN": dsn},
                    log_name="e2e_backend.log",
                )
            )
        _wait_for(f"{BACKEND_URL}/health", args.timeout, "后端 8001")

        if _port_listening(5174):
            print("[ .. ] 5174 已有服务，复用")
        else:
            npm = shutil.which("npm") or "npm"
            started.append(
                _start(
                    [npm, "run", "dev", "--", "--port", "5174", "--host", "127.0.0.1"],
                    cwd=WEB,
                    env={**os.environ, "VITE_API_TARGET": BACKEND_URL},
                    log_name="e2e_frontend.log",
                )
            )
        _wait_for(f"{FRONTEND_URL}/", args.timeout, "前端 5174")

        check = subprocess.run(
            [PYTHON, str(ROOT / "scripts" / "dev_check.py"), "--expect-db", "e2e"],
            cwd=str(ROOT),
        )
        if check.returncode != 0:
            print("\n环境自检没过，先按上面的 [FAIL] 修环境再跑用例。")
            return check.returncode

        cmd = [
            PYTHON, "-m", "pytest", "tests/e2e", "-m", "e2e",
            "--base-url", FRONTEND_URL, *extra,
        ]
        print(f"\n[ .. ] {' '.join(cmd)}")
        env = dict(os.environ)
        if args.keep_data:
            env["E2E_KEEP_DATA"] = "1"
        return subprocess.run(cmd, cwd=str(ROOT), env=env).returncode
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")
        return 1
    finally:
        for process, handle in started:
            if args.keep:
                print(f"[ .. ] --keep：保留 pid {process.pid}")
                continue
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            try:
                handle.close()
            except OSError:
                pass
        if started and not args.keep:
            print("[ .. ] 已停止本次启动的后端/前端")


if __name__ == "__main__":
    sys.exit(main())
