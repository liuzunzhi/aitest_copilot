"""源测试点内容指纹（08-test-case-analysis）。

**用途**：判断一条已生成的用例，其源测试点是否发生了「值得复核」的变化。

**为什么不用 `updated_at`**：`test_points.updated_at` 在迁移 0022 里只有
`server_default`，MySQL 方言下 SQLAlchemy 的 `server_onupdate` 不会渲染成
`ON UPDATE`，应用代码也从不赋值——拿它比对永远不触发。

**口径**：
- 对 `_FIELDS` 列出的字段做规范化后取 SHA-256；
- `needs_review` 取 `0/1`：07 因标签清除把测试点置为待复核，同样算「源变更」；
- `None` 与 `""` 统一成 `""`（展示口径一致）；
- 指纹写入 `test_cases.source_point_fingerprint`；**NULL 表示源已删除并已确认**。

**字段清单只有一个出处**：生成 / 读时派生 / 确认复核三处共用 `_FIELDS`，
漏一项就会漏一种「改了但不提示」（测试逐字段断言）。
"""

import hashlib
import json
from typing import Any

__all__ = ["FIELDS", "derive_needs_review", "fingerprint_point"]

# 参与指纹的字段。顺序固定，序列化时 `sort_keys` 再兜一层。
FIELDS = (
    "name",
    "target_type",
    "target_id",
    "target_name",
    "priority",
    "precondition",
    "verification",
    "chapter_id",
    "chapter_title",
    "needs_review",
)


def _normalize(value: Any) -> Any:
    """规范化：`None` → `""`；数字保持数字；布尔压成 0/1。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    return value


def fingerprint_point(point: Any) -> str:
    """一条测试点的内容指纹（64 位小写十六进制）。"""
    payload = {
        field: _normalize(getattr(point, field, None)) for field in FIELDS
    }
    # `needs_review` 统一成 0/1（07 用整数列，模型/展示层可能给布尔）。
    payload["needs_review"] = 1 if bool(getattr(point, "needs_review", 0)) else 0
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_needs_review(
    case: Any, point: Any, current_fingerprint: str | None = None
) -> tuple[bool, str | None]:
    """读时派生「是否待复核」与原因。**不改任何数据**。

    - 源测试点不存在：
      - 快照非 NULL → `(True, "source_point_deleted")`（源被删，还没确认过）
      - 快照为 NULL → `(False, None)`（人工确认过源已删除，不再提示）
    - 源测试点存在：
      - 快照为 NULL，或当前指纹 ≠ 快照 → `(True, "source_point_changed")`
      - 否则 `(False, None)`
    """
    if point is None:
        return (case.source_point_fingerprint is not None, "source_point_deleted")

    if current_fingerprint is None:
        current_fingerprint = fingerprint_point(point)

    if (
        case.source_point_fingerprint is None
        or case.source_point_fingerprint != current_fingerprint
    ):
        return True, "source_point_changed"
    return False, None
