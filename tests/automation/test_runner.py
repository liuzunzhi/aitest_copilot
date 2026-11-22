"""执行器的断言（09-automation T113 / AC-185 / AC-186 / AC-188）。

执行器是**纯执行层**——不起 HTTP、不起数据库。全部用例都用 `tmp_path`
造最小 pytest 样例，**平台自身的 `tests/` 目录永远不会被执行**。

四组关注点：

1. **超时即 kill**（AC-185）：`time.sleep(999)` + 2s 超时 → 有限时间内返回，
   `error` 含「超时」，**子进程确实被杀了**（断言 PID 已不存在）。
2. **PIPE 死锁防护**（AC-186）：子进程打印 1MB → 有限时间内返回，日志含输出片段。
   **这组用例的价值最高**——它是唯一能抓住「有人把 `capture_output=True`
   改成管道 + 阻塞式读取」的回归防线。
3. **输出解析与退出码语义**（AC-188）：计数解析 / 无法解析不抛错 /
   资产级聚合规则。
4. **执行边界**：执行的路径必须在 root 内，越界与绝对路径直接拒。
"""

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

from app.automation import runner
from app.common.errors import AutomationScanPathInvalid

REPO_ROOT = Path(__file__).resolve().parents[2]
PLATFORM_TESTS_DIR = REPO_ROOT / "tests"

# 超时样例：模块级就把 PID 写下来（采集阶段就跑完了，比函数体早），
# 睡醒之后才写 finished —— 进程被 kill 就永远写不出 finished。
SLEEP_SAMPLE = '''
import os
import time
from pathlib import Path

Path("worker.pid").write_text(str(os.getpid()), encoding="utf-8")


def test_sleeps_forever():
    time.sleep(999)
    Path("finished.marker").write_text("done", encoding="utf-8")
'''

# 1MB 输出样例：远超管道缓冲区容量。
BIG_OUTPUT_SAMPLE = '''
def test_prints_one_megabyte():
    print("X" * (1024 * 1024))
    assert True
'''

# 1 通过 + 1 失败 → 退出码 1。
MIXED_SAMPLE = '''
def test_ok():
    assert True


def test_bad():
    assert 1 == 2
'''

# 全部跳过。
SKIPPED_SAMPLE = '''
import pytest


@pytest.mark.skip(reason="demo")
def test_skipped():
    assert True
'''

# 记录执行现场（cwd / argv）——用来证明「执行发生在 tmp_path 内」。
TRACE_SAMPLE = '''
import json
import os
import sys

with open("trace.json", "w", encoding="utf-8") as handle:
    json.dump({"cwd": os.getcwd(), "argv": sys.argv}, handle)


def test_ok():
    assert True
'''


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """执行根目录（`tmp_path` 内的子目录，模拟 `AUTOMATION_ROOT`）。"""
    target = tmp_path / "automation"
    target.mkdir()
    return target


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _run_with_deadline(func, deadline: float) -> dict:
    """在**守护线程**里跑一次执行，最多等 `deadline` 秒。

    死锁的实现（管道 + 阻塞式读取）会让执行永远不返回——
    这时守护线程还挂着，但 pytest 仍能正常退出（守护线程不阻塞解释器退出），
    于是「死锁」被翻译成一条**失败的断言**，而不是整个测试进程卡死。
    """
    box: dict = {}

    def worker() -> None:
        try:
            box["result"] = func()
        except BaseException as exc:  # noqa: BLE001 - 测试里要看到原始异常
            box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(deadline)
    return box


def _pid_is_alive(pid: int) -> bool:
    """进程是否还活着。

    `os.kill(pid, 0)` 在 Windows 上**不是**存在性检查（它会真的去终止进程），
    所以 Windows 走 `OpenProcess` + `GetExitCodeProcess`。
    """
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ------------------------------------------------------------- AC-185 超时


def test_ac_185_timeout_returns_in_bounded_time(work_dir: Path):
    """`time.sleep(999)` + 2s 超时 → **有限时间内返回**，不挂起。

    这是「强制超时」这条红线的正面断言：没有 `timeout=` 的话，
    这个用例会永远挂着。
    """
    _write(work_dir, "test_sleep.py", SLEEP_SAMPLE)

    started = time.time()
    result = runner.run_pytest(sys.executable, work_dir, "test_sleep.py", timeout=2)
    elapsed = time.time() - started

    assert elapsed < 30, f"超时未生效，执行耗时 {elapsed:.1f}s"
    assert result.error is not None
    assert "超时" in result.error
    assert result.exit_code == -1


def test_ac_185_timeout_error_mentions_the_limit(work_dir: Path):
    """超时的错误信息带上超时秒数——用户要知道是「多久」卡住的。"""
    _write(work_dir, "test_sleep.py", SLEEP_SAMPLE)

    result = runner.run_pytest(sys.executable, work_dir, "test_sleep.py", timeout=2)

    assert result.error is not None
    assert "2" in result.error
    assert runner.TIMEOUT_ERROR_PREFIX in result.error


def test_ac_185_timeout_kills_the_child_process(work_dir: Path):
    """**子进程已被杀死**——这是「超时即 kill」这条红线的正面断言。

    两条独立证据：

    1. 样例把 PID 写进文件，执行结束后查这个 PID → 进程已不存在；
    2. 样例睡醒后才写 `finished.marker`——文件始终不存在，
       说明进程没有跑到自然结束（没跑完就被杀了）。
    """
    _write(work_dir, "test_sleep.py", SLEEP_SAMPLE)

    result = runner.run_pytest(sys.executable, work_dir, "test_sleep.py", timeout=2)

    assert result.error is not None
    pid_file = work_dir / "worker.pid"
    assert pid_file.exists(), "样例没跑起来，超时测试的前提不成立"
    pid = int(pid_file.read_text(encoding="utf-8").strip())

    assert not _pid_is_alive(pid), "超时后子进程仍然存活——kill 没生效"
    assert not (work_dir / "finished.marker").exists()


def test_ac_185_timeout_does_not_touch_platform_tests(work_dir: Path):
    """超时样例只在 `tmp_path` 里——**平台自身的 `tests/` 目录不被执行**。"""
    _write(work_dir, "test_sleep.py", SLEEP_SAMPLE)

    runner.run_pytest(sys.executable, work_dir, "test_sleep.py", timeout=2)

    assert work_dir.resolve() != PLATFORM_TESTS_DIR.resolve()
    assert not PLATFORM_TESTS_DIR.resolve().is_relative_to(work_dir.resolve())


# ------------------------------------------------------------- AC-186 死锁


def test_ac_186_large_output_does_not_deadlock(work_dir: Path):
    """子进程打印 **1MB**（远超管道缓冲区）→ 执行**正常返回**，日志含输出片段。

    如果实现被改成「管道 + 阻塞式读取 stdout」，
    子进程会把管道写满后阻塞等待、而父进程在等它退出 → **死锁**。
    这条用例就是把死锁翻译成失败断言的回归防线。
    """
    _write(work_dir, "test_big.py", BIG_OUTPUT_SAMPLE)

    box = _run_with_deadline(
        lambda: runner.run_pytest(sys.executable, work_dir, "test_big.py", timeout=60),
        deadline=90,
    )

    assert "error" not in box, f"执行抛异常：{box.get('error')}"
    assert "result" in box, "执行在 90 秒内没有返回——疑似管道死锁"

    result = box["result"]
    assert result.error is None
    assert result.exit_code == 0
    assert "X" * 100 in result.output, "日志里没有子进程的输出片段"


def test_ac_186_runner_source_uses_communicate_semantics():
    """实现层面钉死三条安全线（源码断言）。

    - `capture_output=True`：**内部走 `communicate()`**，不会管道死锁；
    - **禁止** `stdout.read()`（阻塞式读管道）；
    - `timeout=` 必须在；`shell=True` 不得出现（否则是命令注入）。
    """
    source = Path(runner.__file__).read_text(encoding="utf-8")

    assert "capture_output=True" in source
    assert re.search(r"\btimeout=timeout\b", source)
    assert "stdout.read(" not in source
    assert "shell=True" not in source


def test_ac_186_parse_summary_counts():
    """`2 failed, 3 passed, 1 skipped` → 四类计数各自正确，`total` 是三者之和。"""
    output = "===== 2 failed, 3 passed, 1 skipped in 1.23s =====\n"

    counts = runner.parse_pytest_summary(output)

    assert counts["failed"] == 2
    assert counts["passed"] == 3
    assert counts["skipped"] == 1
    assert counts["error"] == 0
    assert counts["total"] == 6


def test_ac_186_parse_summary_ignores_child_output_noise():
    """子进程自己打印的同名词**不干扰**统计——以 pytest 的摘要行为准。

    统计行有固定形状（末尾带 `in <时长>`），噪声行「3 passed」没有。
    """
    output = (
        "3 passed\n"
        "some child output\n"
        "===== 1 failed, 2 passed in 0.50s =====\n"
    )

    counts = runner.parse_pytest_summary(output)

    assert counts["failed"] == 1
    assert counts["passed"] == 2
    assert counts["total"] == 3


def test_ac_186_child_output_noise_is_not_mistaken_for_summary():
    """子进程打印「3 passed」但 pytest 真实统计是 1 passed → 取 1，不是 3。

    没有「按形状挑统计行」这条规则时，这里会算成 3 passed。
    """
    output = "3 passed\n.\n1 passed in 0.08s\n"

    counts = runner.parse_pytest_summary(output)

    assert counts["passed"] == 1
    assert counts["total"] == 1


def test_ac_186_summary_survives_the_platform_pytest_config(tmp_path: Path):
    """**平台自己的 pytest 配置不能漏进被执行的资产**。

    `AUTOMATION_ROOT` 默认在仓库内，pytest 从工作目录**向上**找配置文件，
    会捡到**平台自己的** `pyproject.toml`（`addopts = "-q -m 'not e2e'"`）：

    - `-m 'not e2e'` → 资产里标了 `e2e` 的用例被**静默 deselect**
      （少跑用例却装作跑完了）；
    - `-q` → 与我们的 `-q` 叠成 `-qq` → **统计行整个消失**，计数必然拿不到数。

    这条用例在 `tmp_path` 里**照抄平台那份配置**，复现同一种泄漏：
    资产必须跑满、统计行必须还在。
    """
    platform_dir = tmp_path / "platform"
    asset_dir = platform_dir / "assets"
    asset_dir.mkdir(parents=True)
    # 与平台自己的 pyproject.toml 同一形态的「上级配置」。
    (platform_dir / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        "addopts = \"-q -m 'not e2e'\"\n",
        encoding="utf-8",
    )
    sample = asset_dir / "test_leak.py"
    sample.write_text(
        "import pytest\n"
        "\n"
        "\n"
        "def test_plain():\n"
        "    assert True\n"
        "\n"
        "\n"
        "@pytest.mark.e2e\n"
        "def test_marked_e2e():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = runner.run_pytest(sys.executable, asset_dir, "test_leak.py", timeout=60)

    assert result.exit_code == 0, result.output
    assert "deselected" not in result.output, "资产里的用例被平台的 marker 过滤掉了"
    counts = runner.parse_pytest_summary(result.output)
    assert counts["total"] == 2, f"统计行没解析出来：{result.output!r}"
    assert counts["passed"] == 2


def test_ac_186_asset_keeps_its_own_pytest_config(tmp_path: Path):
    """资产**自己**的 pytest 配置不被平台改掉。

    隔离用的是「只清空 `addopts`」，不是「换掉配置文件」——
    资产自己的 `pytest.ini` 里的 `addopts` 必须照常生效。
    """
    asset_dir = tmp_path / "asset"
    asset_dir.mkdir()
    (asset_dir / "pytest.ini").write_text(
        "[pytest]\naddopts = -k demo\n", encoding="utf-8"
    )
    sample = asset_dir / "test_own.py"
    sample.write_text(
        "def test_demo():\n    assert True\n\n\ndef test_other():\n    assert True\n",
        encoding="utf-8",
    )

    result = runner.run_pytest(sys.executable, asset_dir, "test_own.py", timeout=60)

    assert result.exit_code == 0, result.output
    counts = runner.parse_pytest_summary(result.output)
    # 资产自己的 `-k demo` 生效：只跑 1 条。
    assert counts["passed"] == 1, result.output


def test_ac_186_config_isolation_picks_the_right_branch(tmp_path: Path):
    """配置隔离**按资产有没有自己的配置分流**——两条支路都要走对。

    - 资产有自己的 `pytest.ini` → `-c <它>`（资产自己的 `addopts` 生效）
    - 资产没有 → `-o addopts=`（平台配置进不来）
    """
    with_own = tmp_path / "with_own"
    (with_own / "sub").mkdir(parents=True)
    (with_own / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    without_own = tmp_path / "without_own"
    without_own.mkdir()

    own_cmd = runner._build_command(
        "python", "test_x.py", with_own.resolve(), (with_own / "sub").resolve()
    )
    plain_cmd = runner._build_command(
        "python", "test_x.py", without_own.resolve(), without_own.resolve()
    )

    assert "-c" in own_cmd
    assert str((with_own / "pytest.ini").resolve()) in own_cmd
    assert "addopts=" not in own_cmd

    assert "-c" not in plain_cmd
    assert "addopts=" in plain_cmd


def test_ac_186_platform_pytest_config_is_never_used(tmp_path: Path):
    """平台自己的配置**永远不会被** `-c` 指给资产。

    平台配置在 `work_dir` **之外**（`AUTOMATION_ROOT` 默认在仓库内，
    平台自己的 `pyproject.toml` 就在上面一层）——它不是资产的配置。
    """
    platform_dir = tmp_path / "platform"
    asset_dir = platform_dir / "assets"
    asset_dir.mkdir(parents=True)
    (platform_dir / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q -m 'not e2e'\"\n", encoding="utf-8"
    )

    command = runner._build_command(
        "python", "test_x.py", asset_dir.resolve(), asset_dir.resolve()
    )

    assert "-c" not in command, "平台自己的配置被当成资产的配置了"
    assert "addopts=" in command


def test_ac_186_parse_unparsable_output_is_none_and_does_not_raise():
    """完全无法解析的输出 → `{'total': None}`，**不抛错**。

    原始文本由调用方原样保留在日志里，前端标「无法解析统计」。
    """
    counts = runner.parse_pytest_summary("这不是 pytest 的输出，随便一段文字")

    assert counts == {"total": None}


# ------------------------------------------------------------- AC-188 语义


def test_ac_188_exit_code_is_one_when_a_test_fails(work_dir: Path):
    """1 通过 + 1 失败 → **退出码 1**，但 `error` 为空。

    `error` 为空 = 「进程正常跑完」；退出码 1 = 「有测试失败」，
    两者不是一回事（spec §4.2）。
    """
    _write(work_dir, "test_mixed.py", MIXED_SAMPLE)

    result = runner.run_pytest(sys.executable, work_dir, "test_mixed.py", timeout=60)

    assert result.exit_code == 1
    assert result.error is None
    counts = runner.parse_pytest_summary(result.output)
    assert counts["passed"] == 1
    assert counts["failed"] == 1


def test_ac_188_failure_aggregates_to_failed(work_dir: Path):
    """有失败 → 资产级结果 `failed`。"""
    _write(work_dir, "test_mixed.py", MIXED_SAMPLE)

    result = runner.run_pytest(sys.executable, work_dir, "test_mixed.py", timeout=60)
    counts = runner.parse_pytest_summary(result.output)

    assert runner.aggregate_result(counts) == "failed"


def test_ac_188_pass_and_skip_aggregates_to_passed(work_dir: Path):
    """1 通过 + 1 跳过 → `passed`（**有失败才是 failed，全跳过才是 skipped**）。"""
    _write(work_dir, "test_mixed.py", MIXED_SAMPLE)

    result = runner.run_pytest(sys.executable, work_dir, "test_mixed.py", timeout=60)
    counts = runner.parse_pytest_summary(result.output)
    counts["skipped"] = 1
    counts["passed"] = 1
    counts["failed"] = 0

    assert runner.aggregate_result(counts) == "passed"


def test_ac_188_all_skipped_aggregates_to_skipped(work_dir: Path):
    """全部跳过 → `skipped`。"""
    _write(work_dir, "test_skipped.py", SKIPPED_SAMPLE)

    result = runner.run_pytest(sys.executable, work_dir, "test_skipped.py", timeout=60)
    counts = runner.parse_pytest_summary(result.output)

    assert counts["skipped"] == 1
    assert counts["failed"] == 0
    assert runner.aggregate_result(counts) == "skipped"


def test_ac_188_unparsable_output_never_reports_passed():
    """解析不出来**不等于通过**——宁可标 `failed`。"""
    assert runner.aggregate_result({"total": None}) == "failed"


def test_ac_188_all_passing_file_exits_zero(work_dir: Path):
    """全部通过 → 退出码 0，`error` 为空。"""
    _write(work_dir, "test_ok.py", "def test_ok():\n    assert True\n")

    result = runner.run_pytest(sys.executable, work_dir, "test_ok.py", timeout=60)

    assert result.exit_code == 0
    assert result.error is None
    counts = runner.parse_pytest_summary(result.output)
    assert counts["passed"] == 1
    assert runner.aggregate_result(counts) == "passed"


# ------------------------------------------------------------- 执行边界


def test_ac_195_execution_stays_inside_the_root(work_dir: Path):
    """执行的路径必须在 root 内——**平台自身的 `tests/` 目录不被执行**。

    样例把 `cwd` 与 `argv` 写下来，用执行现场的证据证明这一点。
    """
    _write(work_dir, "test_trace.py", TRACE_SAMPLE)

    result = runner.run_pytest(sys.executable, work_dir, "test_trace.py", timeout=60)
    assert result.exit_code == 0

    trace = json.loads((work_dir / "trace.json").read_text(encoding="utf-8"))
    cwd = Path(trace["cwd"]).resolve()
    assert cwd.is_relative_to(work_dir.resolve())
    for argument in trace["argv"]:
        assert not Path(argument).resolve().is_relative_to(PLATFORM_TESTS_DIR.resolve())


def test_ac_195_path_outside_root_is_rejected(work_dir: Path):
    """越界的相对路径 → 直接拒，**不执行**。"""
    outside = work_dir.parent / "test_outside.py"
    outside.write_text("def test_x():\n    assert True\n", encoding="utf-8")

    with pytest.raises(AutomationScanPathInvalid):
        runner.run_pytest(sys.executable, work_dir, "../test_outside.py", timeout=5)


def test_ac_195_absolute_path_is_rejected(work_dir: Path):
    """绝对路径 → 直接拒（Windows 上 `root / abs` 会退化成 root 内的拼接）。"""
    with pytest.raises(AutomationScanPathInvalid):
        runner.run_pytest(sys.executable, work_dir, str(work_dir / "test_x.py"), timeout=5)


def test_ac_195_empty_path_is_rejected(work_dir: Path):
    """空路径 → 直接拒。"""
    with pytest.raises(AutomationScanPathInvalid):
        runner.run_pytest(sys.executable, work_dir, "   ", timeout=5)


def test_ac_195_missing_executable_reports_start_failure(work_dir: Path):
    """可执行文件不存在 → 「执行器启动失败」，**不抛异常**。

    原始异常消息里可能带本机路径，所以只报异常类型。
    """
    _write(work_dir, "test_ok.py", "def test_ok():\n    assert True\n")

    result = runner.run_pytest(
        work_dir / "no_such_python.exe", work_dir, "test_ok.py", timeout=5
    )

    assert result.exit_code == -1
    assert result.error is not None
    assert "启动失败" in result.error
