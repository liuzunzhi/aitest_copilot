"""Prompt 分段组装（08-test-case-analysis T106 / AC-176）。

覆盖点：

- **顺序固定**：模板正文 → 测试点段 → 来源章节；
- 测试点段 5 个字段**固定出现**，缺失写「（空）」，不省略行；
- 章节为 `None` / 正文空白 → **整段不渲染**；
- 超预算只砍章节正文，前缀逐字节不变；
- `system` 原样取模板。

全程不查库：模板 / 测试点 / 章节都用轻量对象。
"""

from types import SimpleNamespace

import pytest

from app.test_cases.context import EMPTY, build_case_context


def _template() -> SimpleNamespace:
    return SimpleNamespace(
        system_prompt="[TEST_CASE_SYSTEM] 你是用例设计助手。",
        user_prompt="[TEST_CASE_USER] 请为下面的测试点设计测试用例。",
    )


def _point(**overrides) -> SimpleNamespace:
    payload = {
        "name": "扫码登录连续失败 5 次后锁定",
        "target_type": "function",
        "target_id": 10096,
        "target_name": "用户扫码登录",
        "priority": "high",
        "precondition": "账号已存在且未锁定",
        "verification": "连续输错密码 5 次，提示锁定",
        "chapter_title": "登录失败次数限制",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _chapter(title="4.2 登录失败次数限制", content="连续输错密码 5 次后锁定 30 分钟。"):
    return SimpleNamespace(title=title, content=content)


def test_ac_176_system_is_template_prompt_verbatim():
    """`system` 原样取模板，不做任何加工（AC-176 的前半）。"""
    template = _template()

    system, _ = build_case_context(template, _point(), _chapter())

    assert system == template.system_prompt


def test_ac_176_user_starts_with_template_and_keeps_section_order():
    """`user` 以模板 `user_prompt` 开头，测试点段在章节段之前。"""
    template = _template()

    _, user = build_case_context(template, _point(), _chapter())

    assert user.startswith(template.user_prompt)
    assert user.index("## 测试点") < user.index("## 来源章节")
    assert "扫码登录连续失败 5 次后锁定" in user
    assert "连续输错密码 5 次，提示锁定" in user


@pytest.mark.parametrize(
    ("target_type", "expected"),
    [
        ("function", "- 归属：功能#10096 用户扫码登录"),
        ("feature_point", "- 归属：功能点#10096 用户扫码登录"),
    ],
)
def test_ac_176_target_line_uses_business_label(target_type: str, expected: str):
    """归属行用「功能 / 功能点」而不是内部枚举值。"""
    _, user = build_case_context(_template(), _point(target_type=target_type), _chapter())

    assert expected in user


def test_ac_176_point_section_always_has_five_lines():
    """缺失字段写「（空）」：结构稳定比「少一行」重要（同输入必得同结构）。"""
    point = _point(precondition=None, verification="   ")

    _, user = build_case_context(_template(), point, None)

    lines = user.splitlines()
    point_start = lines.index("## 测试点")
    bullets = lines[point_start + 1 : point_start + 6]
    assert len(bullets) == 5
    assert bullets[0].startswith("- 名称：")
    assert bullets[1].startswith("- 归属：")
    assert bullets[2] == "- 优先级：high"
    assert bullets[3] == f"- 前置条件：{EMPTY}"
    assert bullets[4] == f"- 验证要点：{EMPTY}"


def test_ac_176_chapter_section_omitted_when_missing():
    """章节不存在 → 整段不渲染（不留空标题）。"""
    _, user = build_case_context(_template(), _point(), None)

    assert "## 来源章节" not in user


def test_ac_176_chapter_section_omitted_when_blank():
    """章节正文去空白后为空 → 同样整段不渲染。"""
    _, user = build_case_context(_template(), _point(), _chapter(content="  \n\t "))

    assert "## 来源章节" not in user


def test_ac_176_chapter_section_uses_chapter_title_and_content():
    """章节段 = `## 来源章节：{title}` + 正文。"""
    _, user = build_case_context(_template(), _point(), _chapter())

    assert "## 来源章节：4.2 登录失败次数限制" in user
    assert user.endswith("连续输错密码 5 次后锁定 30 分钟。")


def test_ac_176_truncation_only_cuts_chapter_body():
    """超预算只砍正文：前缀与章节标题逐字节保留，只截正文尾部。"""
    template = _template()
    point = _point()
    chapter = _chapter(content="正文" * 200)
    budget = 400

    _, full = build_case_context(template, point, chapter, max_chars=10_000)
    _, cut = build_case_context(template, point, chapter, max_chars=budget)

    heading = "## 来源章节：4.2 登录失败次数限制\n"
    head = full[: full.index(heading) + len(heading)]
    body = full[len(head) :]

    assert cut == head + body[: budget - len(head)]
    assert len(cut) == budget
    assert len(cut) < len(full)


def test_ac_176_point_section_is_deterministic():
    """同输入两次渲染逐字节相同——Prompt 可复现（非功能要求）。"""
    template = _template()
    point = _point()
    chapter = _chapter()

    assert build_case_context(template, point, chapter) == build_case_context(
        template, point, chapter
    )
