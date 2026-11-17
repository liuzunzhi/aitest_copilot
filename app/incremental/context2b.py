"""第二遍 Prompt 组装（2b-2 按点分治）。

固定形状（spec-phase2 §6.2 / AC-89）：

    user = f"{template.user_prompt}\n\n## 功能点：{name}\n## 局部结论\n{scoped}\n## 关联章节\n{chapters}"

- 目标标签只会是「功能点」或「功能」，第一行是稳定锚点；
- `scoped` 只含该目标及其所辖功能的局部结论，不带其他功能点 id，也不带全量基线；
- `chapters` 只带标题与正文摘要（截断），不带全文。
"""

from collections.abc import Iterable

from app.models.incremental import PromptTemplate

TARGET_LABELS = {"feature_point": "功能点", "function": "功能"}

SUMMARY_CHARS = 60


def build_system_prompt(template: PromptTemplate) -> str:
    """系统提示词原样取自数据库模板，不做任何加工。"""
    return template.system_prompt


def _scope_line(label_type: str, chapter_title: str, rationale: str | None) -> str:
    return f"- [{label_type}] {chapter_title}：{rationale or '无'}"


def _chapter_line(title: str, content: str) -> str:
    compact = " ".join((content or "").split())
    if len(compact) > SUMMARY_CHARS:
        compact = f"{compact[:SUMMARY_CHARS]}…"
    return f"- {title}：{compact or '（空）'}"


def build_user_prompt(
    template: PromptTemplate,
    *,
    target_label: str,
    name: str,
    scope: Iterable[tuple[str, str, str | None]],
    chapters: Iterable[tuple[str, str]],
    max_chars: int | None = None,
) -> str:
    """组装单个目标的第二遍用户提示词。

    `scope` 每项是 `(label_type, chapter_title, rationale)`；
    `chapters` 每项是 `(title, content)`，正文在这里截成摘要。
    """
    scope_text = "\n".join(_scope_line(*item) for item in scope) or "- 无"
    chapter_text = "\n".join(_chapter_line(*item) for item in chapters) or "- 无"
    prefix = f"{template.user_prompt}\n\n## {target_label}：{name}\n## 局部结论\n{scope_text}\n## 关联章节\n"
    body = chapter_text
    if max_chars is None or len(prefix) + len(body) <= max_chars:
        return f"{prefix}{body}"
    # 超长只截尾部摘要，锚点与局部结论保持不变
    remaining = max(0, max_chars - len(prefix))
    return f"{prefix}{body[:remaining]}"


__all__ = [
    "SUMMARY_CHARS",
    "TARGET_LABELS",
    "build_system_prompt",
    "build_user_prompt",
]
