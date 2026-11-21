"""清除标签原因的枚举修正（09-automation T111 / AC-181）。

**背景**：PRD 2.4.2 规定的 6 类清除原因是「误判 / 基线已调整 / 回溯覆盖 /
需求撤销 / 需求已完成 / 其他」，而代码里原本是
`priority_changed`（优先级变化）/ `duplicate_label`（标签重复）——
这两个值**在 PRD 里根本不存在**，而 PRD 要求的两类**无法表达**。
这是能力缺失，不是命名风格问题。

本文件钉住四件事：
1. 枚举的 6 个值与 PRD 一一对应；
2. **只有一处定义**（service 与 schemas 不再各写一份）；
3. 前端类型与中文文案同步；
4. 既有测试**零期望值改动**（被改的两个值原本就没被任何用例用到）。
"""

import ast
import pathlib
import re

import pytest

from app.baselines import constants, schemas, service


def _strip_ts_comments(source: str) -> str:
    """去掉 TS 的行注释与块注释，只留代码。

    注释里保留「旧值叫 priority_changed」的说明是有价值的，
    检查代码时不该被这些说明文字干扰。
    """
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//.*", "", without_block)


# PRD 2.4.2「人工清除」的 6 类原因，逐条对应。
PRD_CLEAR_REASONS = {
    "misjudged": "误判",
    "baseline_adjusted": "基线已调整",
    "backtrace_override": "回溯覆盖",
    "requirement_cancelled": "需求撤销",
    "requirement_done": "需求已完成（变更已纳入基线）",
    "other": "其他（备注必填）",
}

# 被 09 期 T111 移除的两个旧值——PRD 里没有它们。
REMOVED_REASONS = ("priority_changed", "duplicate_label")


def test_ac_181_clear_reasons_match_prd():
    """枚举的 6 个值与 PRD 一一对应。"""
    assert set(constants.CLEAR_REASONS) == set(PRD_CLEAR_REASONS)
    assert len(constants.CLEAR_REASONS) == 6


@pytest.mark.parametrize("removed", REMOVED_REASONS)
def test_ac_181_removed_reasons_are_gone(removed: str):
    """旧值不再出现在枚举里。"""
    assert removed not in constants.CLEAR_REASONS


def test_ac_181_enum_has_single_definition():
    """**只有一处定义**：service 与 schemas 都从 `constants` 导入。

    两处各写一份迟早漂移——这正是 09 期开工前发现的真实问题。

    **不能**让 `schemas.py` 直接 import `service.py`：
    `service.py` 已经 import 了 `schemas.py`（取 `trace_fields_in`），
    反向依赖会形成循环导入。所以常量放在无依赖的 `constants.py`。
    """
    assert schemas.CLEAR_REASONS is constants.CLEAR_REASONS
    assert service.CLEAR_REASONS is constants.CLEAR_REASONS


def test_ac_181_constants_module_has_no_heavy_dependencies():
    """`constants.py` 不 import 任何模块——它必须能被别人安全地导入。

    用 AST 检查**有没有 import 语句**（不是全文扫 "import" 字符串——
    那样会命中 docstring 里的说明文字）。
    """
    tree = ast.parse(pathlib.Path(constants.__file__).read_text(encoding="utf-8"))
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert imports == [], f"constants.py 不该有 import：{[ast.dump(i) for i in imports]}"


def test_ac_181_no_duplicate_literal_in_schemas():
    """`schemas.py` 里没有字面量枚举定义。

    用 AST 找「赋值给 CLEAR_REASONS 的元组字面量」——
    全文扫字符串会命中注释里的说明文字（那正是本文件想留下的说明）。
    """
    tree = ast.parse(pathlib.Path(schemas.__file__).read_text(encoding="utf-8"))
    literals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "CLEAR_REASONS"
            for target in node.targets
        )
        and isinstance(node.value, (ast.Tuple, ast.List, ast.Set))
    ]
    assert literals == [], "schemas.py 不该再定义 CLEAR_REASONS 字面量"


def test_ac_181_service_keeps_literal_definition():
    """定义落在 `constants.py`（唯一出处），service 只 import。"""
    tree = ast.parse(pathlib.Path(constants.__file__).read_text(encoding="utf-8"))
    literals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "CLEAR_REASONS"
            for target in node.targets
        )
        and isinstance(node.value, (ast.Tuple, ast.List, ast.Set))
    ]
    assert len(literals) == 1, "constants.py 应有且只有一处 CLEAR_REASONS 字面量定义"

    service_tree = ast.parse(pathlib.Path(service.__file__).read_text(encoding="utf-8"))
    service_literals = [
        node
        for node in ast.walk(service_tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "CLEAR_REASONS"
            for target in node.targets
        )
        and isinstance(node.value, (ast.Tuple, ast.List, ast.Set))
    ]
    assert service_literals == [], "service.py 不该再有 CLEAR_REASONS 字面量定义"


def test_ac_181_cascade_clear_reason_untouched():
    """`CASCADE_CLEAR_REASON` 不动。

    它是服务层内部写入的级联标记，不经人工清除接口，不在 PRD 的 6 类里。
    """
    assert service.CASCADE_CLEAR_REASON == "target_deleted"


def test_ac_181_incremental_auto_clear_reason_untouched():
    """05 的自动清除仍写 `misjudged`（该值未改名）。"""
    from app.incremental import apply

    assert apply.CLEAR_REASON == "misjudged"


def test_ac_181_frontend_type_and_labels_synced():
    """前端类型与中文文案同步改了。

    前端是 TS，用**剔除注释后的代码**做检查——
    注释里保留「旧值叫 priority_changed」的说明是有价值的，
    不该让这条断言把注释也一起禁掉。
    """
    root = pathlib.Path(__file__).resolve().parents[2] / "web" / "src"

    api_source = _strip_ts_comments(
        (root / "api" / "index.ts").read_text(encoding="utf-8")
    )
    assert "'baseline_adjusted'" in api_source
    assert "'backtrace_override'" in api_source
    assert "'priority_changed'" not in api_source
    assert "'duplicate_label'" not in api_source

    meta_source = _strip_ts_comments(
        (root / "pages" / "baselineMeta.ts").read_text(encoding="utf-8")
    )
    assert "baseline_adjusted" in meta_source
    assert "backtrace_override" in meta_source
    assert "priority_changed" not in meta_source
    assert "duplicate_label" not in meta_source
    # 中文文案也要跟着改
    assert "基线已调整" in meta_source
    assert "回溯覆盖" in meta_source


def test_ac_181_existing_tests_never_used_removed_values():
    """既有测试**一条都没用到**被改的两个值。

    所以枚举改名**不需要改任何既有期望值**——这是 AC-181 的「零期望值改动」断言。

    **只扫字符串字面量**（AST 层面）：全文扫会误报——
    `tests/baselines/test_labels.py::test_ac_66_duplicate_label` 里的
    `duplicate_label` 是**测试函数名**（对应错误码 `DUPLICATE_LABEL`），
    与清除原因枚举毫无关系。

    排除 `tests/automation/` 整个目录：09 期自己的用例会提到这两个旧值
    （`test_migration.py` 就是要断言「存量里不再出现旧值」，
    本文件则是守着这次改名的测试）。
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in root.rglob("*.py"):
        if "automation" in path.parts:
            continue
        # 用 utf-8-sig 读：仓库里有带 BOM 的文件，
        # ast.parse 遇到 U+FEFF 会直接 SyntaxError。
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for removed in REMOVED_REASONS:
            assert removed not in literals, (
                f"{path.name} 的字符串字面量里仍出现旧枚举值 {removed}"
            )
