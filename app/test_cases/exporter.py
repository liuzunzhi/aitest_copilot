"""测试用例导出 Excel（08-test-case-analysis T108 / AC-177）。

**一步一行**：用例元数据在每行重复——这样在 Excel 里筛「优先级=高」
或做数据透视时不用先合并单元格。

列顺序与中文状态见 spec §6.6。中文映射来自 `app/test_cases/labels.py`，
与前端 `testCaseMeta.tsx` 同源（两边都断言同一组中文，防漂移）。

导出是**读操作**：不写审计、不改库。
"""

from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from app.test_cases.labels import (
    case_type_label,
    priority_label,
    source_label,
    status_label,
)

__all__ = ["COLUMNS", "COLUMN_WIDTHS", "build_workbook", "export_bytes", "filename_for"]

COLUMNS = (
    "用例ID",
    "用例名称",
    "用例类型",
    "优先级",
    "所属测试点ID",
    "所属测试点",
    "功能或功能点",
    "前置条件",
    "步骤序号",
    "操作步骤",
    "预期结果",
    "状态",
    "来源",
    "创建时间",
)

COLUMN_WIDTHS = (10, 32, 10, 8, 12, 28, 20, 24, 10, 36, 36, 10, 10, 20)


def filename_for(project_id: int, moment: Any) -> str:
    """文件名：`test-cases-{project_id}-{yyyymmdd}.xlsx`。"""
    return f"test-cases-{project_id}-{moment.strftime('%Y%m%d')}.xlsx"


def _rows(cases: list[dict]) -> list[tuple]:
    """把用例列表摊成「一步一行」。"""
    rows: list[tuple] = []
    for case in cases:
        steps = case.get("steps") or []
        base = (
            case["id"],
            case["title"],
            case_type_label(case.get("case_type")),
            priority_label(case.get("priority")),
            case.get("test_point_id"),
            case.get("test_point_name"),
            case.get("target_name"),
            case.get("precondition") or "",
        )
        tail = (
            status_label(case.get("status")),
            source_label(case.get("source_type")),
            case["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
        )
        if not steps:
            rows.append(base + (None, "", "") + tail)
            continue
        for step in steps:
            rows.append(
                base
                + (
                    step["step_no"],
                    step.get("action") or "",
                    step.get("expected") or "",
                )
                + tail
            )
    return rows


def build_workbook(cases: list[dict]) -> Workbook:
    """造工作簿：首行加粗 + 冻结 + 固定列宽。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "测试用例"

    sheet.append(list(COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center")

    for row in _rows(cases):
        sheet.append(list(row))

    for index, width in enumerate(COLUMN_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    return workbook


def export_bytes(cases: list[dict]) -> bytes:
    """导出成 `.xlsx` 字节流（不落临时文件）。"""
    workbook = build_workbook(cases)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
