"""测试用例生成的 Prompt 组装（08-test-case-analysis T106）。

**严格分段，顺序固定**：

    user = f"{template.user_prompt}

             ## 测试点
             - 名称：...
             - 归属：功能#10096 用户扫码登录
             - 优先级：...
             - 前置条件：...
             - 验证要点：...

             ## 来源章节：{title}
             {content}"

为什么这样排：

1. **测试点是唯一输入**——用例必须能追溯到具体的测试点，
   所以「测试点」段必出，且字段一个不省（缺失写「（空）」），
   保证不同测试点渲染出的结构完全一致。
2. **章节段可整段省略**——章节被删、正文为空时不给模型空洞的标题，
   只让它看测试点本身（spec §5.2）。
3. **截断只砍章节正文**——前缀（模板正文 + 测试点段 + 章节标题）保持不变，
   这样「user 以模板 user_prompt 开头」在超长场景下依然成立（AC-176）。

**不在这里查库**：章节由服务层用 `session.get(DocumentChapter, point.chapter_id)` 取，
模板来自 `prompt_templates`；本函数只吃三个对象，纯函数、可逐字节断言。
"""

from typing import Any

from app.common.config import get_settings

# 字段缺失时的占位符：不省略整行，保证结构稳定（spec §5.2）。
EMPTY = "（空）"

# 目标类型 → 展示文案。与 07 的「功能 / 功能点」口径一致。
TARGET_LABELS = {
    "function": "功能",
    "feature_point": "功能点",
}


def _text(value: Any) -> str:
    """取展示文本；`None` / 空白一律写「（空）」。"""
    if value is None:
        return EMPTY
    text = str(value).strip()
    return text or EMPTY


def build_case_context(
    template: Any,
    point: Any,
    chapter: Any = None,
    *,
    max_chars: int | None = None,
) -> tuple[str, str]:
    """返回 `(system, user)`；`user` 已按固定顺序拼好并在超预算时截断章节正文。

    - `system` = 模板 `system_prompt`，原样，不加工；
    - `user` 前缀 = 模板 `user_prompt` + 测试点段（5 个字段固定出现）；
    - 章节段：`chapter is None` 或正文去空白后为空 → **整段不渲染**；
    - 超预算只切章节正文尾部；前缀本身超预算时不再二次截断
      （与 07 同策略：交给 provider 报错，而不是悄悄砍掉输入）。
    """
    target_label = TARGET_LABELS.get(point.target_type, point.target_type)
    bullets = [
        f"- 名称：{_text(point.name)}",
        f"- 归属：{target_label}#{point.target_id} {_text(point.target_name)}",
        f"- 优先级：{_text(point.priority)}",
        f"- 前置条件：{_text(point.precondition)}",
        f"- 验证要点：{_text(point.verification)}",
    ]
    prefix = f"{template.user_prompt}\n\n## 测试点\n" + "\n".join(bullets)

    if chapter is None:
        return template.system_prompt, prefix

    content = chapter.content or ""
    if not content.strip():
        return template.system_prompt, prefix

    title = chapter.title or point.chapter_title or EMPTY
    prefix += f"\n\n## 来源章节：{title}\n"

    budget = max_chars
    if budget is None:
        budget = get_settings().incremental_max_input_chars
    if len(prefix) + len(content) > budget:
        content = content[: max(0, budget - len(prefix))]

    return template.system_prompt, f"{prefix}{content}"


__all__ = [
    "EMPTY",
    "TARGET_LABELS",
    "build_case_context",
]
