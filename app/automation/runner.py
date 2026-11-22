"""Pytest 执行器（09-automation T113）。

三条安全红线（用户 2026-11-21 拍板），**缺一条就可能把后端拖死**：

1. **强制超时**：`subprocess.run(..., timeout=timeout)`。
   没有超时的执行会让 HTTP 请求永久挂起——一次卡死的同步执行就够
   把整个后端的 worker 占满。
2. **超时直接 kill**：标准库在超时时**已经**杀掉子进程并 `wait()` 回收
   （CPython 的 `Popen.communicate` 就是这么做的），我们只需要捕获
   `TimeoutExpired` **不让它冒泡**。
3. **必须用 `communic()` 语义读输出**：`capture_output=True` 内部即
   `communicate()`；**禁止**「管道 + 阻塞式读取 stdout」——
   子进程输出塞满管道缓冲区时父进程阻塞等待退出 → **死锁**，
   表现是接口请求永久挂起。

第四条隐含红线：**不经 shell 解析**（参数以列表传入，`shell=False`），
文件名里的空格、`;`、`$` 不会变成命令注入。

`exe` / `root` / `timeout` / `cwd` **全部可注入**：测试用 `tmp_path` 造样例，
**平台自身的 `tests/` 目录永远不会被执行**。

另外三条实现决定（都是实测出来的，不是拍脑袋）：

- **带 `-s`**：pytest 默认会把子进程的 stdout 截获进自己的临时文件，
  父进程的管道里就什么都没有——那样既测不出死锁，报告日志里也只有一行摘要。
  `-s` 让输出真的流进管道，日志才拿得到执行现场。
- **配置隔离（`-c` / `-o addopts=` 二选一）**：这是实测踩到的**真坑**。
  `AUTOMATION_ROOT` 默认在仓库内（`var/automation`），pytest 会从工作目录
  **向上**找配置文件，捡到**平台自己的** `pyproject.toml`
  （`addopts = "-q -m 'not e2e'"`），于是被执行的资产**继承平台的两条配置**：
  ① `-m 'not e2e'` → 资产里标了 `e2e` 的用例被**静默 deselect**（少跑用例还装作跑完了）；
  ② `-q` → 与我们自己的 `-q` 叠成 `-qq` → **pytest 的统计行整个消失**
  （`-qq` 一行只输出进度点，没有 `N passed`），计数解析必然拿不到数。
  按「资产有没有自己的配置」分流：有自己的 → `-c <它>`（**它自己的 `addopts`
  照常生效**）；没有 → `-o addopts=`。详见 `_build_command`。
- **摘要行只认「pytest 自己的统计行」**：统计行有固定形状
  `N passed, M failed in 0.45s`（末尾带 `in <时长>`）。子进程自己打印的
  「3 passed」这种噪声行没有这个形状，按形状挑才不会把噪声当统计。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import NamedTuple

from app.common.errors import AutomationScanPathInvalid

__all__ = [
    "COUNT_PATTERNS",
    "ExecResult",
    "TIMEOUT_ERROR_PREFIX",
    "aggregate_result",
    "parse_pytest_summary",
    "run_pytest",
]


class ExecResult(NamedTuple):
    """一次执行的原始结果。

    - `exit_code`：pytest 的退出码；超时 / 启动失败统一用 `-1`。
    - `output`：stdout + stderr 的合并文本（**原样保留**）。
    - `error`：**非空**表示「跑不起来」（超时 / 启动失败），
      为空表示进程**正常跑完**——退出码非 0 只是「有测试失败」，
      那是业务结果，不是系统错误。
    """

    exit_code: int
    output: str
    error: str | None


# 超时的错误前缀——服务层靠它把「超时」与「有测试失败」区分开。
TIMEOUT_ERROR_PREFIX = "执行超时"

# pytest 摘要行里的四类计数。
COUNT_PATTERNS: dict[str, re.Pattern[str]] = {
    "passed": re.compile(r"(\d+)\s+passed"),
    "failed": re.compile(r"(\d+)\s+failed"),
    "skipped": re.compile(r"(\d+)\s+skipped"),
    "error": re.compile(r"(\d+)\s+error"),
}

# pytest 统计行的形状：末尾是「in <时长>」。
# `2 passed in 0.45s` / `1 failed, 2 passed in 1.23s` / `1 error in 0.55s`
# 子进程自己打印的「3 passed」**没有**这个形状 → 不会被误认成统计行。
_SUMMARY_SHAPE_RE = re.compile(r"in\s+\d+(\.\d+)?s\s*=*\s*$")


def _safe_text(value: object) -> str:
    """把子进程输出安全地转成文本。

    `TimeoutExpired.stdout` 可能是 `None`（超时发生在读到输出之前），
    也可能是 **bytes**（POSIX 下 `communicate` 把原始字节塞进异常），
    也可能是 `str`（Windows 下 `subprocess.run` 会重新 `communicate()` 一次）。
    三种都得兜住——直接 `.decode()` 会在 `None` 上抛 `AttributeError`，
    异常一旦冒泡，调用方连「超时了」这句话都看不到。
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _resolve_target(work_dir: Path, rel_path: str) -> Path:
    """把待执行的相对路径解析到 `work_dir` 内。

    越界 / 绝对路径 → `AutomationScanPathInvalid`（400）。
    判定基准是 `resolve()` 后的实际路径，与扫描器同一套口径。

    **为什么执行器要再校验一次**：上层服务层已经校验过资产路径，
    但执行器是**最后一道闸**——它直接决定「哪个文件会被当成代码跑起来」。
    边界判在底层，不依赖每一层调用方都记得判。
    """
    raw = (rel_path or "").strip()
    if not raw:
        raise AutomationScanPathInvalid("执行路径不能为空")
    if Path(raw).is_absolute():
        raise AutomationScanPathInvalid("执行路径必须是相对路径")
    resolved = (work_dir / raw).resolve()
    if not resolved.is_relative_to(work_dir):
        raise AutomationScanPathInvalid("执行路径超出允许范围")
    return resolved


# 资产自己的 pytest 配置文件候选（判定顺序与 pytest 的 rootdir 发现一致）。
_CONFIG_NAMES = ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")


def _is_asset_config(path: Path) -> bool:
    """这个文件是不是 pytest 会认的配置文件。

    `pyproject.toml` 必须含 `[tool.pytest.ini_options]` 才算——
    否则它只是普通项目描述文件（装了也没用）。
    """
    if not path.is_file():
        return False
    if path.name == "pyproject.toml":
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return "[tool.pytest.ini_options]" in content
    return True


def _find_asset_config(work_dir: Path, asset_dir: Path) -> Path | None:
    """找**资产自己**的 pytest 配置文件。

    从资产所在目录**向上**找（与 pytest 的 rootdir 发现一致），
    **最多找到 `work_dir` 为止**——再往上就是平台自己的配置了，
    那不是资产的配置。

    找不到 → `None`（资产没有自己的配置）。
    """
    current = asset_dir
    for _ in range(64):  # 上限防御：目录层级不可能这么深
        for name in _CONFIG_NAMES:
            candidate = current / name
            if _is_asset_config(candidate):
                return candidate
        if current == work_dir:
            break
        parent = current.parent
        if parent == current or not parent.is_relative_to(work_dir):
            break
        current = parent
    return None


def _build_command(
    exe: Path | str, rel_path: str, work_dir: Path, asset_dir: Path
) -> list[str]:
    """拼出 pytest 命令行。

    **配置隔离**（实测踩到的坑）：`AUTOMATION_ROOT` 默认在仓库内，
    pytest 会从工作目录**向上**找配置文件，捡到**平台自己的**
    `pyproject.toml`（`addopts = "-q -m 'not e2e'"`），于是被执行的资产
    继承平台的两条配置：

    ① `-m 'not e2e'` → 资产里标了 `e2e` 的用例被**静默 deselect**
       （少跑用例却装作跑完了）；
    ② `-q` → 与我们自己的 `-q` 叠成 `-qq` → **pytest 的统计行整个消失**
       （`-qq` 一行只输出进度点，没有 `N passed`），计数解析必然拿不到数。

    两种隔离方式，**按资产有没有自己的配置**分流：

    | 情况 | 做法 | 效果 |
    |---|---|---|
    | 资产**有自己的** pytest 配置 | `-c <资产自己的配置>` | 平台配置进不来，**资产自己的 `addopts` 照常生效** |
    | 资产**没有**自己的配置 | `-o addopts=` | 平台配置进不来，资产也没有配置可丢 |

    为什么不统一用 `-o addopts=`：它会**连资产自己的 `addopts` 一起清空**
    （资产写 `addopts = -k demo` 之类就会失效）。
    为什么不统一用 `-c`：资产没有配置文件时 `-c` 无从指起，
    平台的配置照样会被捡到。

    **为什么「有自己配置」那一支不加 `-q`**：资产自己的 `addopts` 里
    可能已经有 `-q`，两个 `-q` 叠成 `-qq` → 统计行又没了。
    那一支交给资产自己决定详细程度（默认详细度**本来就带统计行**）。
    """
    command = [str(exe), "-m", "pytest", rel_path, "-s"]
    asset_config = _find_asset_config(work_dir, asset_dir)
    if asset_config is not None:
        command += ["-c", str(asset_config)]
    else:
        command += ["-q", "-o", "addopts="]
    return command


def run_pytest(
    exe: Path | str,
    root: Path | str,
    rel_path: str,
    timeout: int,
    cwd: Path | str | None = None,
) -> ExecResult:
    """跑一次 pytest，返回 `(exit_code, output, error)`。

    参数：

    - `exe`：python 可执行文件路径（**注入点**——测试用当前解释器）。
    - `root`：`AUTOMATION_ROOT`，默认作为工作目录。
    - `rel_path`：相对 `root` 的待测文件路径（必须是 pytest 文件）。
    - `timeout`：**强制超时**秒数。
    - `cwd`：工作目录覆盖项（**注入点**，默认等于 `root`）。

    三条安全线都在 `subprocess.run` 那一行里：`timeout=` /
    `capture_output=True` / `shell=False`（默认，即显式不启用）。
    **禁止**改成管道 + 阻塞式读取——那会在子进程输出量大时死锁。
    """
    work_dir = Path(cwd).resolve() if cwd is not None else Path(root).resolve()
    # 越界路径直接拒（不执行）。
    target = _resolve_target(work_dir, rel_path)

    command = _build_command(exe, rel_path, work_dir, target.parent)
    try:
        proc = subprocess.run(
            command,
            cwd=str(work_dir),
            capture_output=True,  # ← 内部走 communicate()，防管道死锁
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,  # ← 强制超时
            check=False,
            shell=False,  # ← 参数以列表传入，不经 shell 解析
        )
    except subprocess.TimeoutExpired as exc:
        # 超时：标准库已经 kill + wait 回收了子进程，这里只把异常按住。
        output = _safe_text(exc.stdout) + _safe_text(exc.stderr)
        return ExecResult(-1, output, f"{TIMEOUT_ERROR_PREFIX}（超过 {timeout} 秒）")
    except (OSError, ValueError) as exc:
        # 进程拉不起来（可执行文件不存在 / 参数非法）——只报异常类型，
        # 原始异常消息里可能带本机路径，不往外透。
        return ExecResult(-1, "", f"执行器启动失败：{type(exc).__name__}")

    return ExecResult(proc.returncode, proc.stdout + proc.stderr, None)


def _find_summary_line(text: str) -> str | None:
    """找出 pytest 的统计行。

    **按形状挑**（末尾带 `in <时长>`），而不是「含 passed/failed 就算」——
    子进程自己打印的「3 passed」这种噪声行会被误认成统计行，
    导致计数把子进程的业务输出算进去。

    取**最后**一个符合条件的行：pytest 的统计行永远在输出末尾。
    """
    for line in reversed(text.splitlines()):
        if _SUMMARY_SHAPE_RE.search(line) and any(
            pattern.search(line) for pattern in COUNT_PATTERNS.values()
        ):
            return line
    return None


def parse_pytest_summary(output: str) -> dict[str, int | None]:
    """解析 pytest 摘要行，返回 `{total, passed, failed, skipped, error}`。

    - 四个计数逐个正则匹配（pytest 的统计行在一行里）。
    - `total` = 四类计数之和。
    - **找不到统计行** → 返回 `{'total': None}`（输出无法解析，
      原始文本由调用方原样保留在日志里，**不抛错**）。
    """
    text = output or ""
    summary = _find_summary_line(text)
    if summary is None:
        return {"total": None}

    counts: dict[str, int | None] = {}
    for key, pattern in COUNT_PATTERNS.items():
        found = pattern.search(summary)
        counts[key] = int(found.group(1)) if found is not None else 0

    total = sum(int(counts[key] or 0) for key in COUNT_PATTERNS)
    return {"total": total, **counts}


def aggregate_result(counts: dict[str, int | None]) -> str:
    """把一次执行的计数聚合成**资产级**结果。

    | 聚合规则 | result |
    |---|---|
    | 有任何失败 / error | `failed` |
    | 全部跳过（且无失败） | `skipped` |
    | 其余 | `passed` |

    **无法解析（`total` 为 None）→ `failed`**：解析不出来不等于通过，
    宁可标失败，也不要在报告里谎报「这条资产通过了」。
    """
    failed = int(counts.get("failed") or 0)
    error = int(counts.get("error") or 0)
    passed = int(counts.get("passed") or 0)
    skipped = int(counts.get("skipped") or 0)

    if failed > 0 or error > 0:
        return "failed"
    if counts.get("total") is None:
        return "failed"
    if skipped > 0 and passed == 0:
        return "skipped"
    return "passed"
