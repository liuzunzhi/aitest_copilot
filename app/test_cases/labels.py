"""测试用例的枚举中文标签（08-test-case-analysis T108）。

**为什么单独一个模块**：导出 Excel 需要中文，前端也要中文。
后端放一份、前端手抄一份——两份会漂移，所以两边都断言同一组中文
（后端 `tests/test_cases/test_export.py`，前端 T109 的 `testCaseMeta.tsx`）。

**口径**：只做展示映射，不参与判定。库里存的永远是英文枚举
（`pending` / `functional` / `high`），中文只出现在响应展示与导出文件里。
"""

CASE_STATUS_LABELS = {
    "pending": "待评审",
    "approved": "已通过",
    "rejected": "已驳回",
}

CASE_TYPE_LABELS = {
    "functional": "功能",
    "api": "接口",
    "ui": "UI",
}

CASE_PRIORITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

CASE_SOURCE_LABELS = {
    "llm": "AI 生成",
    "manual": "手工新增",
}

TARGET_TYPE_LABELS = {
    "function": "功能",
    "feature_point": "功能点",
}

NEEDS_REVIEW_REASON_LABELS = {
    "source_point_changed": "所属测试点已变更",
    "source_point_deleted": "所属测试点已删除",
}


def status_label(value: str | None) -> str:
    """评审状态 → 中文；未知值原样返回（不吞掉问题）。"""
    return CASE_STATUS_LABELS.get(value or "", value or "")


def case_type_label(value: str | None) -> str:
    return CASE_TYPE_LABELS.get(value or "", value or "")


def priority_label(value: str | None) -> str:
    return CASE_PRIORITY_LABELS.get(value or "", value or "")


def source_label(value: str | None) -> str:
    return CASE_SOURCE_LABELS.get(value or "", value or "")


def target_type_label(value: str | None) -> str:
    return TARGET_TYPE_LABELS.get(value or "", value or "")


def needs_review_reason_label(value: str | None) -> str:
    return NEEDS_REVIEW_REASON_LABELS.get(value or "", value or "")


__all__ = [
    "CASE_PRIORITY_LABELS",
    "CASE_SOURCE_LABELS",
    "CASE_STATUS_LABELS",
    "CASE_TYPE_LABELS",
    "NEEDS_REVIEW_REASON_LABELS",
    "TARGET_TYPE_LABELS",
    "case_type_label",
    "needs_review_reason_label",
    "priority_label",
    "source_label",
    "status_label",
    "target_type_label",
]
