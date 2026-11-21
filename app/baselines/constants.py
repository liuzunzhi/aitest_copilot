"""功能基线的共享常量。

**为什么单独一个模块**：清除原因枚举原先在 `service.py` 与 `schemas.py`
各写一份，两处迟早漂移。09 期 T111 把它们收敛成一处——
但不能简单地让 `schemas.py` 反向 import `service.py`：
`service.py` 已经 import 了 `schemas.py`（取 `trace_fields_in`），
反向依赖会形成**循环导入**（`ImportError: partially initialized module`）。

所以枚举放在这个**不依赖任何其他模块**的常量文件里，
`service.py` 与 `schemas.py` 都从这里导入——单一出处，且无循环。
"""

# 清除原因 6 类（PRD 2.4.2「人工清除」）——**全项目只有这一处定义**。
#
# 09 期 T111 修正：原值 `priority_changed`（优先级变化）与 `duplicate_label`
# （标签重复）**在 PRD 里根本不存在**，而 PRD 要求的「基线已调整」「回溯覆盖」
# 两类**无法表达**——这是能力缺失，不是命名风格问题。
#
#   priority_changed  → baseline_adjusted  （PRD：基线已调整）
#   duplicate_label   → backtrace_override （PRD：回溯覆盖）
CLEAR_REASONS = (
    "requirement_done",
    "requirement_cancelled",
    "misjudged",
    "baseline_adjusted",
    "backtrace_override",
    "other",
)

# 标签类型 4 类：新增 / 变更 / 受影响 / 无变化
LABEL_TYPES = ("new", "changed", "affected", "unchanged")

__all__ = ["CLEAR_REASONS", "LABEL_TYPES"]
