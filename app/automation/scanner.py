"""自动化资产扫描器（09-automation T112）。

**纯函数**：不碰数据库、不碰配置、不写文件。所以规则匹配与置信度可以
纯函数级测试，不必起 HTTP、不必起数据库（与 06 / 07 / 08 的引擎同一思路）。

三条设计：

1. **路径安全是第一位的**。`POST /scan` 是外部输入驱动的文件读取，
   判定基准是 `resolve()` 后的**实际路径**是否落在 `AUTOMATION_ROOT` 内，
   不是字符串里有没有 `..`——`sub/../sub2` 解析后仍在 root 内，应放行；
   `../../etc` 解析后越界，应拒绝。
2. **绝对路径显式拒绝**。`root / "C:\\Windows"` 在 Windows 上会变成
   `root/C:\\Windows`（仍在 root 内），`is_relative_to` 挡不住它，
   所以必须单独判 `Path(directory).is_absolute()`。
3. **置信度是规则命中分**，不是模型判断（本期不调模型）。
   规则分可解释、可测试、零成本。真正的语义解析留后续期。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.common.errors import AutomationScanPathInvalid, AutomationScanTooLarge

__all__ = [
    "DEFAULT_SCAN_LIMIT",
    "LOW_CONFIDENCE_THRESHOLD",
    "PLAYWRIGHT_CALL_RE",
    "PLAYWRIGHT_NAME_RE",
    "PYTEST_FUNC_RE",
    "PYTEST_NAME_RE",
    "SKIP_DIRS",
    "ScanResult",
    "ScannedAsset",
    "match_file",
    "resolve_scan_dir",
    "resolve_scan_path",
    "scan_dir",
]

# 跳过目录——**硬编码常量**，不接受用户输入。
# `.git` / `.venv` / `node_modules` 这些目录里全是依赖代码，扫进去既慢又没意义。
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".next",
    "coverage",
    ".cache",
}

# 单文件最多读 64KB 用于规则匹配——不把整个文件读进内存。
READ_LIMIT_BYTES = 64 * 1024

# 单次扫描的文件数上限。超出直接拒绝，避免误扫整个磁盘。
DEFAULT_SCAN_LIMIT = 2000

# 置信度低于此值 → 前端默认不勾选，标「低置信度，请人工确认」。
LOW_CONFIDENCE_THRESHOLD = 0.7

PYTEST_NAME_RE = re.compile(r"^(test_.*|.*_test)\.py$")
PLAYWRIGHT_NAME_RE = re.compile(r"^.*\.(spec|test)\.(ts|js)$")
PYTEST_FUNC_RE = re.compile(r"^\s*(async\s+)?def\s+(test_\w+)", re.MULTILINE)
PLAYWRIGHT_CALL_RE = re.compile(r"\btest\s*\(")

# 命中文件名的基础置信度；文件内再命中内容规则则升到 0.95。
_CONTENT_CONFIDENCE = 0.95
_NAME_ONLY_CONFIDENCE = 0.60


@dataclass(frozen=True)
class ScannedAsset:
    """扫描识别出来的一个自动化资产（**还没入库**）。

    `file_path` 是**相对 root 的 POSIX 路径**（统一用 `/`）——
    Windows 上 `Path` 的反斜杠会让同一份文件在不同系统上路径不一样，
    而 `file_path` 是要进库并参与唯一索引的。
    """

    file_path: str
    name: str
    framework: str
    parse_confidence: float
    detected_cases: int

    @property
    def low_confidence(self) -> bool:
        """置信度偏低 → 前端默认不勾选，标「低置信度，请人工确认」。"""
        return self.parse_confidence < LOW_CONFIDENCE_THRESHOLD


@dataclass(frozen=True)
class ScanResult:
    """一次扫描的结果。

    - `assets`：识别到的资产（`file_path` 相对 root）
    - `scanned_files`：遍历到的文件总数（**含**未识别的）
    - `matched`：`len(assets)`
    - `skipped`：扫到了但没认出来的文件数
    """

    assets: list[ScannedAsset]
    scanned_files: int
    skipped: int

    @property
    def matched(self) -> int:
        return len(self.assets)


def _resolve_within_root(root: Path, relative: str) -> tuple[Path, Path]:
    """把一个相对路径解析到 root 内，返回 `(base, candidate)`。

    越界 / 绝对路径 → `AutomationScanPathInvalid`。

    **判定基准是 `resolve()` 后的实际路径**，不是字符串里有没有 `..`：
    `sub/../sub2` 解析后仍在 root 内，应放行；`../../etc` 解析后越界，应拒绝。

    `root` 也先 `resolve()` 一次——配置里写的是相对路径（`var/automation`），
    不 resolve 的话 `is_relative_to` 拿相对根去比绝对路径，永远不成立。
    """
    raw = (relative or "").strip()
    if not raw:
        raise AutomationScanPathInvalid("路径不能为空")

    # 绝对路径显式拒绝：`root / abs` 在 Windows 上会退化成 root 内的相对拼接，
    # `is_relative_to` 挡不住，必须单独判。
    if Path(raw).is_absolute():
        raise AutomationScanPathInvalid("路径必须是相对路径")

    base = Path(root).resolve()
    candidate = (base / raw).resolve()
    if not candidate.is_relative_to(base):
        raise AutomationScanPathInvalid("路径超出允许范围")
    return base, candidate


def resolve_scan_dir(root: Path, directory: str) -> Path:
    """把用户传入的相对目录解析到 root 内。

    越界 / 绝对路径 / 目录不存在 → `AutomationScanPathInvalid`。

    空目录名 = 扫整个 root（仍然是 root 之内）。
    """
    raw = (directory or "").strip()
    if not raw:
        return Path(root).resolve()
    base, candidate = _resolve_within_root(root, raw)
    if not candidate.exists() or not candidate.is_dir():
        raise AutomationScanPathInvalid("扫描目录不存在")
    return candidate


def resolve_scan_path(root: Path, relative: str) -> Path:
    """把一个资产的相对路径解析成 root 内的绝对路径（**文件**）。

    与 `resolve_scan_dir` 同一套安全判定（越界 / 绝对路径 → 400），
    但不要求存在——入库时文件可能已经被删了。
    """
    _, candidate = _resolve_within_root(root, relative)
    return candidate


def _read_head(path: Path) -> str:
    """只读文件前 64KB。读不到（编码 / 权限）就当空内容，不让扫描整体失败。"""
    try:
        with path.open("rb") as handle:
            chunk = handle.read(READ_LIMIT_BYTES)
    except OSError:
        return ""
    return chunk.decode("utf-8", errors="ignore")


def match_file(path: Path, relative_path: str) -> ScannedAsset | None:
    """按规则判断一个文件是不是自动化资产。

    规则（spec §3.2）：

    | 命中情况 | framework | 置信度 | detected_cases |
    |---|---|---|---|
    | pytest 文件名 + 有 `def test_` | pytest | 0.95 | 函数计数 |
    | pytest 文件名 + 无 | pytest | 0.60 | 0 |
    | playwright 文件名 + 有 `test(` | playwright | 0.95 | 匹配计数 |
    | playwright 文件名 + 无 | playwright | 0.60 | 0 |
    | 都不匹配 | — | — | `None`（进 skipped） |

    只读文件**前 64KB**——不把整个文件读进内存。
    """
    name = path.name
    is_pytest = bool(PYTEST_NAME_RE.match(name))
    is_playwright = bool(PLAYWRIGHT_NAME_RE.match(name))
    if not is_pytest and not is_playwright:
        return None

    content = _read_head(path)

    if is_pytest:
        count = len(PYTEST_FUNC_RE.findall(content))
        framework = "pytest"
    else:
        count = len(PLAYWRIGHT_CALL_RE.findall(content))
        framework = "playwright"

    confidence = _CONTENT_CONFIDENCE if count else _NAME_ONLY_CONFIDENCE
    return ScannedAsset(
        file_path=relative_path,
        name=name,
        framework=framework,
        parse_confidence=confidence,
        detected_cases=count,
    )


def scan_dir(
    root: Path, directory: str, limit: int = DEFAULT_SCAN_LIMIT
) -> ScanResult:
    """遍历目录并产出资产清单。

    `directory` 的合法性由 `resolve_scan_dir` 判定（越界 → 400）；
    这里接收的是**已经解析过**的绝对路径。

    遍历规则：

    - 递归，跳过 `SKIP_DIRS` 与隐藏目录（`.` 开头）；
    - 隐藏文件（`.` 开头）跳过；
    - 文件数超 `limit` → `AutomationScanTooLarge`；
    - 未识别的文件计入 `skipped`（用户要知道「扫到了但没认出来」）。
    """
    base = Path(root).resolve()
    target = Path(directory).resolve()
    assets: list[ScannedAsset] = []
    scanned = 0

    for current, _dir_names, file_names in _walk(target):
        for file_name in sorted(file_names):
            if file_name.startswith("."):
                continue
            path = current / file_name
            if not path.is_file():
                continue
            scanned += 1
            if scanned > limit:
                raise AutomationScanTooLarge(
                    f"扫描文件数超过上限（{limit}），请缩小目录范围"
                )
            relative = path.relative_to(base).as_posix()
            asset = match_file(path, relative)
            if asset is None:
                continue
            assets.append(asset)

    return ScanResult(assets=assets, scanned_files=scanned, skipped=scanned - len(assets))


def _walk(target: Path):
    """自己实现遍历，而不是 `Path.rglob`：要**在遍历时就剪掉**跳过目录，
    否则 `node_modules` 里的文件也会被计数（进而撞上文件数上限）。

    `rglob` 不支持按目录剪枝，`os.walk` 支持——这里用 `os.walk` + `dirnames` 原地裁剪。
    """
    for current_dir, dir_names, file_names in os.walk(target):
        dir_names[:] = sorted(
            name
            for name in dir_names
            if name not in SKIP_DIRS and not name.startswith(".")
        )
        yield Path(current_dir), dir_names, file_names
