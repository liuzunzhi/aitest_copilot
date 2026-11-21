"""扫描器的纯函数断言（09-automation T112 / AC-182 / AC-183）。

扫描器**不碰数据库、不碰配置**，所以这些用例既不起 HTTP 也不起数据库——
与 06 / 07 / 08 的引擎同一思路：规则与路径安全可以脱离运行时验证。

三组关注点：

1. **路径安全**（AC-182）：越界 / 绝对路径 → 400；`..` 但仍在 root 内 → 放行。
2. **规则匹配与置信度**（AC-183）：文件名 + 内容规则 → 置信度与用例数。
3. **遍历边界**：跳过目录 / 隐藏文件不扫；文件数上限。
"""

from pathlib import Path

import pytest

from app.automation import scanner
from app.common.errors import AutomationScanPathInvalid, AutomationScanTooLarge


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """扫描根目录（`tmp_path` 内的子目录，模拟 `var/automation`）。"""
    target = tmp_path / "automation"
    target.mkdir()
    return target


def _write(root: Path, relative: str, content: str = "") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ------------------------------------------------------------- 路径安全


def test_ac_182_relative_path_is_allowed(root: Path):
    """相对路径正常放行。"""
    (root / "web-tests").mkdir()
    assert scanner.resolve_scan_dir(root, "web-tests") == (root / "web-tests").resolve()


def test_ac_182_traversal_outside_root_is_rejected(root: Path):
    """`../../etc` 越界 → 400 `AUTOMATION_SCAN_PATH_INVALID`。"""
    with pytest.raises(AutomationScanPathInvalid) as exc:
        scanner.resolve_scan_dir(root, "../../etc")
    assert exc.value.code == "AUTOMATION_SCAN_PATH_INVALID"


def test_ac_182_absolute_path_is_rejected(root: Path, tmp_path: Path):
    """**绝对路径**显式拒绝。

    `root / "C:\\Windows"` 在 Windows 上会退化成 root 内的相对拼接，
    `is_relative_to` 挡不住——所以必须单独判 `is_absolute()`。
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(AutomationScanPathInvalid):
        scanner.resolve_scan_dir(root, str(outside))
    with pytest.raises(AutomationScanPathInvalid):
        scanner.resolve_scan_dir(root, "C:\\Windows")


def test_ac_182_dotdot_inside_root_is_allowed(root: Path):
    """`sub/../sub2` 解析后仍在 root 内 → **放行**。

    判定基准是 `resolve()` 后的实际路径，不是字符串里有没有 `..`。
    """
    (root / "sub").mkdir()
    (root / "sub2").mkdir()
    assert scanner.resolve_scan_dir(root, "sub/../sub2") == (root / "sub2").resolve()


def test_ac_182_empty_directory_scans_the_whole_root(root: Path):
    """空目录名 = 扫整个 root（仍然是 root 之内）。

    上限（2000 文件）仍然保护着「误扫整个磁盘」这种情形。
    """
    _write(root, "test_a.py", "def test_one():\n    pass\n")

    assert scanner.resolve_scan_dir(root, "") == root.resolve()
    result = scanner.scan_dir(root, scanner.resolve_scan_dir(root, ""))
    assert result.matched == 1


def test_ac_182_missing_directory_is_rejected(root: Path):
    """目录不存在 → 400。"""
    with pytest.raises(AutomationScanPathInvalid):
        scanner.resolve_scan_dir(root, "not-exist")


def test_ac_182_scan_dir_takes_no_session():
    """扫描器是**纯函数**——签名里根本没有 `session` / `db`。

    这条断言钉住「扫描不写表」的结构性保证：
    只要 `scan_dir` 拿不到 Session，它就**不可能**写表。
    行数不变的服务层断言在 `test_assets.py`。
    """
    import inspect

    parameters = list(inspect.signature(scanner.scan_dir).parameters)
    assert parameters == ["root", "directory", "limit"]
    parameters = list(inspect.signature(scanner.resolve_scan_dir).parameters)
    assert parameters == ["root", "directory"]


# ------------------------------------------------------------- 规则匹配


def test_ac_183_pytest_file_with_test_functions(root: Path):
    """pytest 文件名 + 有 `def test_` → 置信度 0.95，用例数 = 函数个数。"""
    _write(
        root,
        "test_a.py",
        "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n",
    )
    result = scanner.scan_dir(root, root)

    assert result.matched == 1
    asset = result.assets[0]
    assert asset.framework == "pytest"
    assert asset.parse_confidence == 0.95
    assert asset.detected_cases == 2
    assert asset.file_path == "test_a.py"
    assert asset.name == "test_a.py"


def test_ac_183_pytest_file_without_test_functions(root: Path):
    """pytest 文件名 + **无** `def test_` → 置信度 0.60，用例数 0。"""
    _write(root, "b_test.py", "def helper():\n    pass\n")
    result = scanner.scan_dir(root, root)

    assert result.matched == 1
    asset = result.assets[0]
    assert asset.framework == "pytest"
    assert asset.parse_confidence == 0.60
    assert asset.detected_cases == 0
    assert asset.low_confidence is True


def test_ac_183_playwright_file_with_test_call(root: Path):
    """playwright 文件名 + 有 `test(` → 置信度 0.95。"""
    _write(root, "c.spec.ts", "test('login', async () => {});\n")
    result = scanner.scan_dir(root, root)

    assert result.matched == 1
    asset = result.assets[0]
    assert asset.framework == "playwright"
    assert asset.parse_confidence == 0.95
    assert asset.detected_cases == 1


def test_ac_183_playwright_file_without_test_call(root: Path):
    """playwright 文件名 + 无 `test(` → 置信度 0.60。"""
    _write(root, "d.test.ts", "export const helper = 1;\n")
    result = scanner.scan_dir(root, root)

    assert result.matched == 1
    asset = result.assets[0]
    assert asset.framework == "playwright"
    assert asset.parse_confidence == 0.60
    assert asset.detected_cases == 0


def test_ac_183_unrecognized_file_goes_to_skipped(root: Path):
    """`readme.md` 不进清单，但计入 `skipped`（用户要知道「扫到了但没认出来」）。"""
    _write(root, "readme.md", "# 说明\n")
    _write(root, "test_a.py", "def test_one():\n    pass\n")
    result = scanner.scan_dir(root, root)

    assert result.scanned_files == 2
    assert result.matched == 1
    assert result.skipped == 1
    assert [asset.file_path for asset in result.assets] == ["test_a.py"]


def test_ac_183_both_frameworks_in_one_scan(root: Path):
    """pytest 与 playwright 可以在同一次扫描里共存。"""
    _write(root, "web-tests/test_login.py", "def test_login():\n    pass\n")
    _write(root, "web-tests/login.spec.ts", "test('login', async () => {});\n")
    result = scanner.scan_dir(root, root)

    frameworks = sorted(asset.framework for asset in result.assets)
    assert frameworks == ["playwright", "pytest"]
    assert result.matched == 2


def test_ac_183_detected_cases_counts_playwright_calls(root: Path):
    """playwright 的 `detected_cases` 是 `test(` 的匹配计数。"""
    _write(
        root,
        "multi.spec.ts",
        "test('a', async () => {});\ntest('b', async () => {});\ntest.describe('c', () => {});\n",
    )
    result = scanner.scan_dir(root, root)

    assert result.assets[0].detected_cases == 2


# ------------------------------------------------------------- 遍历边界


def test_ac_183_skip_dirs_are_not_scanned(root: Path):
    """`__pycache__` / `node_modules` / 隐藏目录**不被扫描**。"""
    _write(root, "test_ok.py", "def test_one():\n    pass\n")
    _write(root, "__pycache__/test_cached.py", "def test_cached():\n    pass\n")
    _write(root, "node_modules/pkg/test_pkg.py", "def test_pkg():\n    pass\n")
    _write(root, ".hidden/test_hidden.py", "def test_hidden():\n    pass\n")
    _write(root, ".venv/test_venv.py", "def test_venv():\n    pass\n")

    result = scanner.scan_dir(root, root)

    assert result.scanned_files == 1
    assert [asset.file_path for asset in result.assets] == ["test_ok.py"]


def test_ac_183_hidden_files_are_not_scanned(root: Path):
    """隐藏文件（`.` 开头）跳过。"""
    _write(root, ".hidden_test.py", "def test_one():\n    pass\n")
    _write(root, "test_visible.py", "def test_one():\n    pass\n")

    result = scanner.scan_dir(root, root)

    assert result.scanned_files == 1
    assert [asset.file_path for asset in result.assets] == ["test_visible.py"]


def test_ac_183_too_many_files_is_rejected(root: Path):
    """文件数超上限 → 400 `AUTOMATION_SCAN_TOO_LARGE`。"""
    for index in range(5):
        _write(root, f"test_{index}.py", "def test_one():\n    pass\n")

    with pytest.raises(AutomationScanTooLarge) as exc:
        scanner.scan_dir(root, root, limit=3)
    assert exc.value.code == "AUTOMATION_SCAN_TOO_LARGE"


def test_ac_183_scan_is_recursive(root: Path):
    """递归遍历子目录。"""
    _write(root, "a/b/c/test_deep.py", "def test_one():\n    pass\n")

    result = scanner.scan_dir(root, root)

    assert [asset.file_path for asset in result.assets] == ["a/b/c/test_deep.py"]


def test_ac_183_file_path_uses_posix_separator(root: Path):
    """`file_path` 统一用 `/`——要进库并参与唯一索引。"""
    _write(root, "web-tests/test_login.py", "def test_one():\n    pass\n")

    result = scanner.scan_dir(root, root)

    assert result.assets[0].file_path == "web-tests/test_login.py"


def test_ac_183_only_first_64kb_is_read(root: Path):
    """单文件只读前 64KB——后面的内容不参与匹配。"""
    padding = "# " + "x" * 200 + "\n"
    _write(root, "test_big.py", padding * 400 + "def test_one():\n    pass\n")

    result = scanner.scan_dir(root, root)

    # 测试函数在 64KB 之外 → 识别不到用例 → 置信度 0.60
    assert result.assets[0].parse_confidence == 0.60
    assert result.assets[0].detected_cases == 0
