"""测试用例输出校验与归一（08-test-case-analysis T106）。

覆盖点（AC-164 / AC-165 / AC-166）：

- 坏 JSON / `cases` 不是数组 → **整次失败**（`TestCaseInvalid`）；
- 带 Markdown 围栏的 JSON → 照常解析（证明走 `parse_llm_json`）；
- 缺 `title` / `steps` 为空 / `action` 为空 → **整条丢弃**并记 `TEST_CASE_INVALID`；
- `case_type` / `priority` 非法 → **归一**；`expected` 缺失 → 存空串；
- 同测试点内重复 `title` → 只保留第一条；
- 超长文本按列宽截断（不因超长丢弃整条）。
"""

import json

import pytest

from app.common.errors import LLMCallFailed, TestCaseInvalid
from app.llm.mock import TEST_CASE_SYSTEM_PREFIX, MockProvider
from app.test_cases.engine import (
    INVALID,
    MAX_TEXT,
    MAX_TITLE,
    analyze_point,
    normalize_cases,
)


def _step(action: str = "输入正确用户名与错误密码", expected: str = "提示用户名或密码错误"):
    return {"action": action, "expected": expected}


def _case(title: str = "连续输错密码 5 次后账号锁定", **overrides) -> dict:
    payload = {
        "title": title,
        "case_type": "functional",
        "priority": "high",
        "precondition": "账号已存在、未锁定",
        "steps": [_step(), _step("连续重复 4 次", "每次提示用户名或密码错误")],
    }
    payload.update(overrides)
    return payload


def _payload(*cases) -> dict:
    return {"cases": list(cases)}


# --------------------------------------------------------------- 正常路径


def test_ac_164_normalize_keeps_valid_case_and_steps():
    """合法用例原样归一：字段与步骤顺序都保留。"""
    result = normalize_cases(_payload(_case()))

    assert result.discarded == []
    assert len(result.cases) == 1
    draft = result.cases[0]
    assert draft.title == "连续输错密码 5 次后账号锁定"
    assert draft.case_type == "functional"
    assert draft.priority == "high"
    assert draft.precondition == "账号已存在、未锁定"
    assert draft.steps == [
        ("输入正确用户名与错误密码", "提示用户名或密码错误"),
        ("连续重复 4 次", "每次提示用户名或密码错误"),
    ]


def test_ac_164_illegal_enums_are_normalized_not_dropped():
    """`case_type='perf'` / `priority='urgent'` → functional / medium，不丢。"""
    result = normalize_cases(_payload(_case(case_type="perf", priority="urgent")))

    assert result.discarded == []
    assert result.cases[0].case_type == "functional"
    assert result.cases[0].priority == "medium"


def test_ac_164_missing_expected_becomes_empty_string():
    """`steps[].expected` 缺失 → 存空串（先保留，评审时补）。"""
    case = _case(steps=[{"action": "提交表单"}])

    result = normalize_cases(_payload(case))

    assert result.cases[0].steps == [("提交表单", "")]


def test_ac_164_missing_precondition_becomes_empty_string():
    """`precondition` 缺失 → 空串。"""
    case = _case()
    case.pop("precondition")

    result = normalize_cases(_payload(case))

    assert result.cases[0].precondition == ""


def test_ac_164_long_texts_are_truncated_not_dropped():
    """超长 title / action 按列宽截断，整条用例保留。"""
    case = _case(title="长" * 400, steps=[_step(action="操" * 2000, expected="预" * 2000)])

    result = normalize_cases(_payload(case))

    assert result.discarded == []
    draft = result.cases[0]
    assert len(draft.title) == MAX_TITLE
    assert len(draft.steps[0][0]) == MAX_TEXT
    assert len(draft.steps[0][1]) == MAX_TEXT


# --------------------------------------------------------------- 整条丢弃


@pytest.mark.parametrize(
    "case",
    [
        {"title": "", "steps": [_step()]},
        {"title": "   ", "steps": [_step()]},
        {"steps": [_step()]},
        {"title": "没有步骤"},
        {"title": "空步骤", "steps": []},
        {"title": "步骤不是数组", "steps": "输入密码"},
        {"title": "步骤项不是对象", "steps": ["输入密码"]},
        {"title": "action 为空", "steps": [{"action": "  ", "expected": "x"}]},
        {"title": "action 缺失", "steps": [{"expected": "x"}]},
    ],
)
def test_ac_164_invalid_case_is_discarded_with_reason(case: dict):
    """结构不合法 → 整条丢弃并记 `TEST_CASE_INVALID`，不中断其它条目。"""
    result = normalize_cases(_payload(case, _case("保留这条")))

    assert [draft.title for draft in result.cases] == ["保留这条"]
    assert len(result.discarded) == 1
    assert result.discarded[0]["code"] == INVALID


def test_ac_164_duplicate_title_keeps_first():
    """同测试点内重复 title 只保留第一条（顺序确定）。"""
    result = normalize_cases(
        _payload(
            _case("重复标题", priority="high"),
            _case("重复标题", priority="low"),
        )
    )

    assert len(result.cases) == 1
    assert result.cases[0].priority == "high"
    assert result.discarded == [{"title": "重复标题", "code": INVALID}]


# --------------------------------------------------------------- 整次失败


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"cases": "不是数组"},
        {"cases": None},
        {"items": []},
        [],
    ],
)
def test_ac_165_structural_payload_fails_whole_run(payload):
    """`cases` 缺失 / 不是数组 → 整次失败，不返回任何用例。"""
    with pytest.raises(TestCaseInvalid):
        normalize_cases(payload)


def test_ac_165_bad_json_fails_whole_run():
    """非 JSON → `TestCaseInvalid`（不是逐条丢弃）。"""
    provider = MockProvider(queue=["这不是 JSON"])

    with pytest.raises(TestCaseInvalid):
        analyze_point(
            provider,
            system=f"{TEST_CASE_SYSTEM_PREFIX} x",
            user="u",
        )


def test_ac_166_fenced_json_is_parsed():
    """Markdown 围栏里的 JSON 照常解析（复用 06 的 `parse_llm_json`）。"""
    fenced = "```json\n" + json.dumps(_payload(_case()), ensure_ascii=False) + "\n```"
    provider = MockProvider(queue=[fenced])

    result = analyze_point(
        provider,
        system=f"{TEST_CASE_SYSTEM_PREFIX} x",
        user="u",
    )

    assert len(result.cases) == 1
    assert result.cases[0].title == "连续输错密码 5 次后账号锁定"


def test_ac_166_analyze_point_calls_model_once():
    """一个测试点**只调一次**模型：不重试、不续跑（同步逐点执行的硬约束）。"""
    provider = MockProvider(queue=[json.dumps(_payload(_case()), ensure_ascii=False)])

    analyze_point(provider, system="[TEST_CASE_SYSTEM] x", user="u")

    assert len(provider.calls) == 1
    assert provider.calls[0].system.startswith("[TEST_CASE_SYSTEM]")


def test_ac_165_provider_error_becomes_llm_call_failed():
    """Provider 抛错 → `LLMCallFailed`（与 05 / 07 同一口径，服务层记 failed）。"""

    class _Broken:
        name = "broken"

        def chat(self, req):  # noqa: ANN001
            raise RuntimeError("connection reset")

    with pytest.raises(LLMCallFailed):
        analyze_point(_Broken(), system="s", user="u")
