"""测试用例生成引擎（08-test-case-analysis T106）。

**纯函数**：只把模型输出校验 / 归一成待落库的 `CaseDraft`，不写库。
写库在 `service.py`（T107），因此「丢弃 / 归一」可以不起 HTTP、不起数据库地逐条断言。

执行策略（与 07 同构，但**没有越界 id 这类脏数据**）：

- 逐测试点调用一次 `provider.chat`，一个测试点一次，产出 0..N 条用例；
- **整次失败**（抛 `TestCaseInvalid`，不落任何用例）：
  - `parse_llm_json` 解析失败；
  - 输出不是对象 / 缺 `cases` / `cases` 不是数组。
- **整条丢弃**（不中断，计入 `discarded`）：
  - 不是对象、`title` 缺失 / 空白；
  - `steps` 缺失 / 空数组 / 不是数组；
  - 任一步 `action` 缺失 / 空白；
  - 同测试点内 `title` 重复（保留第一条，顺序确定）。
- **归一**（不丢）：
  - `case_type` / `priority` 不在枚举 → `functional` / `medium`；
  - `expected` / `precondition` 缺失 → 空串；
  - `title` 截断到 255，`action` / `expected` / `precondition` 截断到 1000。

**为什么没有 `test_point_id` 校验**：输出契约里根本没有这个字段——
绑定哪个测试点由服务端按「当前正在处理的测试点」决定（spec §5.3）。
06 期「模型照抄示例 id」的坑从结构上消失。
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from app.common.errors import LLMCallFailed, LLMOutputInvalid, TestCaseInvalid
from app.llm.json_utils import parse_llm_json
from app.llm.provider import LLMProvider
from app.llm.schemas import LLMRequest
from app.models.test_case import CASE_PRIORITIES, CASE_TYPES

logger = logging.getLogger(__name__)

# 丢弃码：写进 `stats.discarded`，不是 HTTP 错误。
INVALID = "TEST_CASE_INVALID"

DEFAULT_CASE_TYPE = "functional"
DEFAULT_PRIORITY = "medium"

# 列宽（与 0023 的建表一致）。
MAX_TITLE = 255
MAX_TEXT = 1000


@dataclass
class CaseDraft:
    """待落库的一条用例（尚未绑定测试点与 `analysis_id`）。"""

    title: str
    case_type: str = DEFAULT_CASE_TYPE
    priority: str = DEFAULT_PRIORITY
    precondition: str = ""
    # (action, expected)；序号由服务端按数组顺序重排为 1..n
    steps: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class CaseAnalysis:
    """单个测试点的解析结果。"""

    cases: list[CaseDraft] = field(default_factory=list)
    discarded: list[dict[str, Any]] = field(default_factory=list)


def _clean_text(value: Any) -> str:
    """取文本字段；缺失 / 类型不对都退化成空串（不丢整条用例）。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip()


def _enum(value: Any, allowed: tuple[str, ...]) -> str | None:
    """枚举字段归一：不在枚举就返回 None，由调用方退回默认值（不丢整条用例）。"""
    return value if value in allowed else None


def _parse_steps(value: Any) -> list[tuple[str, str]] | None:
    """解析步骤数组；结构不合法返回 None，由调用方整条丢弃。

    `expected` 缺失 / 空白**不算**不合法——先保留用例，评审时补
    （spec §5.3：丢掉一条可能有价值的用例代价太大）。
    """
    if not isinstance(value, list) or not value:
        return None

    steps: list[tuple[str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            return None
        action = _clean_text(row.get("action"))
        if not action:
            return None
        expected = _clean_text(row.get("expected"))
        steps.append((action[:MAX_TEXT], expected[:MAX_TEXT]))
    return steps


def _parse_case(item: Any) -> CaseDraft | None:
    """解析单条用例；不合契约返回 None（整条丢弃）。"""
    if not isinstance(item, dict):
        return None

    title = _clean_text(item.get("title"))[:MAX_TITLE]
    if not title:
        return None

    steps = _parse_steps(item.get("steps"))
    if steps is None:
        return None

    return CaseDraft(
        title=title,
        case_type=_enum(item.get("case_type"), CASE_TYPES) or DEFAULT_CASE_TYPE,
        priority=_enum(item.get("priority"), CASE_PRIORITIES) or DEFAULT_PRIORITY,
        precondition=_clean_text(item.get("precondition"))[:MAX_TEXT],
        steps=steps,
    )


def normalize_cases(payload: Any) -> CaseAnalysis:
    """校验 + 归一模型输出。

    只吃 Python 结构，测试不必造 provider——这是「丢弃 / 归一张」
    能被逐条断言的前提。
    """
    if not isinstance(payload, dict) or "cases" not in payload:
        raise TestCaseInvalid("模型输出缺少 cases 字段")
    items = payload["cases"]
    if not isinstance(items, list):
        raise TestCaseInvalid("cases 必须是数组")

    result = CaseAnalysis()
    seen: set[str] = set()
    for item in items:
        draft = _parse_case(item)
        if draft is None:
            result.discarded.append(
                {
                    "title": _clean_text(item.get("title"))[:MAX_TITLE]
                    if isinstance(item, dict)
                    else "",
                    "code": INVALID,
                }
            )
            continue

        # 同测试点内重复 title 只保留第一条：顺序由模型输出决定，确定。
        if draft.title in seen:
            result.discarded.append({"title": draft.title, "code": INVALID})
            continue
        seen.add(draft.title)
        result.cases.append(draft)
    return result


def analyze_point(provider: LLMProvider, system: str, user: str) -> CaseAnalysis:
    """调一次模型并解析：一个测试点一次调用，**不做重试、不续跑**。

    Provider 抛错原样冒泡（服务层统一记 `failed`）；
    JSON 结构坏换成 `TestCaseInvalid`，同样整次失败。
    """
    try:
        response = provider.chat(LLMRequest(system=system, user=user))
    except Exception as exc:  # Provider 抛任何异常都算调用失败
        raise LLMCallFailed(f"模型调用失败：{exc}") from exc

    try:
        payload = parse_llm_json(response.content)
    except (TypeError, ValueError, LLMOutputInvalid) as exc:
        raise TestCaseInvalid("模型返回不是合法 JSON") from exc

    return normalize_cases(payload)


__all__ = [
    "CaseAnalysis",
    "CaseDraft",
    "DEFAULT_CASE_TYPE",
    "DEFAULT_PRIORITY",
    "INVALID",
    "MAX_TEXT",
    "MAX_TITLE",
    "analyze_point",
    "normalize_cases",
]
