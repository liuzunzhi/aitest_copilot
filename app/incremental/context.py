"""Prompt 组装与基线索引。

组装规则（AC-78）：

    system = template.system_prompt
    user   = f"{template.user_prompt}\n\n## 章节：{chapter.title}\n{chapter.content}"

06 期（T87 真实联调）起，`user` 还会带上**基线清单**：

    user   = f"{template.user_prompt}\n\n## 可对照的基线目标\n{清单}\n\n## 章节：{title}\n{content}"

为什么必须给清单：真实模型不会像 Mock 那样凭空知道 `target_id`。
第一遍模板文案本身就写着「并与比对基准基线中的功能 / 功能点对照」——
基线不给，模型只能瞎猜 id，猜出来的**全部被 AC-79 当越界丢弃**，
整次分析跑完一条结论都没有。

> Mock 时代这个洞一直隐形：测试用例直接硬编码了正确的 `target_id`。
> 这是「Mock 通过 ≠ 真实模型能跑」的典型例子。

**判定逻辑未变**：字段校验、标签分类、丢弃规则、错误码全部原样。
这里只改「喂给模型什么」，不改「怎么判定模型说得对不对」。

基线索引：从比对基准快照对应的**当前**结构表取功能 / 功能点 id → name，
排除归档模块及其下属。目标不在索引里即越界（AC-79）。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.baseline import BaselineFeaturePoint, BaselineFunction, BaselineModule
from app.models.document import DocumentChapter
from app.models.incremental import PromptTemplate

# 基线清单最多占输入预算的比例。剩下的留给章节正文——
# 清单太长会把正文挤没，模型拿不到内容就无从判断。
BASELINE_BRIEF_MAX_RATIO = 0.4


def build_system_prompt(template: PromptTemplate) -> str:
    """系统提示词原样取自数据库模板，不做任何加工。"""
    return template.system_prompt


def render_baseline_brief(
    index: dict[tuple[str, int], str], *, max_chars: int | None = None
) -> str:
    """把基线索引渲染成给模型看的清单。

    每行一条：`功能#10094 用户扫码登录` / `功能点#5630 提交订单`。

    排序按 `(target_type, target_id)`——同一次分析里渲染结果必须稳定，
    否则 Prompt 不可复现，问题无法复现。

    清单过长时截断，并注明省略了多少条：让模型知道「还有没列出来的」，
    比让它以为「基线就这么多」诚实。
    """
    if not index:
        return ""

    lines = [
        f"- {'功能' if target_type == 'function' else '功能点'}#{target_id} {name}"
        for (target_type, target_id), name in sorted(index.items())
    ]

    if max_chars is not None:
        budget = max(0, int(max_chars * BASELINE_BRIEF_MAX_RATIO))
        kept: list[str] = []
        used = 0
        for line in lines:
            cost = len(line) + 1
            if used + cost > budget:
                break
            kept.append(line)
            used += cost
        omitted = len(lines) - len(kept)
        if omitted:
            kept.append(f"- （其余 {omitted} 项基线目标已省略）")
        lines = kept

    return "\n".join(lines)


def build_user_prompt(
    template: PromptTemplate,
    chapter: DocumentChapter,
    *,
    max_chars: int | None = None,
    baseline_brief: str = "",
) -> str:
    """组装用户提示词；超长时只截断正文。

    前缀（模板正文 + 基线清单 + 章节标题）保持不变，这样 AC-78 的
    「user 以模板 user_prompt 开头」在截断场景下依然成立。
    """
    prefix = template.user_prompt
    if baseline_brief:
        prefix += f"\n\n## 可对照的基线目标\n{baseline_brief}"
    prefix += f"\n\n## 章节：{chapter.title}\n"
    if max_chars is None or len(prefix) + len(chapter.content) <= max_chars:
        return f"{prefix}{chapter.content}"
    remaining = max(0, max_chars - len(prefix))
    return f"{prefix}{chapter.content[:remaining]}"


def baseline_index(session: Session, *, project_id: int) -> dict[tuple[str, int], str]:
    """当前结构的 `(target_type, target_id) → name` 索引。

    与快照冻结口径一致：归档模块及其下功能、功能点都不参与。
    这份索引就是 AC-79 的判定依据——目标不在索引里即越界。
    """
    module_ids = list(
        session.scalars(
            select(BaselineModule.id).where(
                BaselineModule.project_id == project_id,
                BaselineModule.status == "active",
            )
        )
    )
    if not module_ids:
        return {}

    functions = session.execute(
        select(BaselineFunction.id, BaselineFunction.name).where(
            BaselineFunction.project_id == project_id,
            BaselineFunction.status == "active",
            BaselineFunction.module_id.in_(module_ids),
        )
    ).all()
    index: dict[tuple[str, int], str] = {
        ("function", function_id): name for function_id, name in functions
    }

    function_ids = [function_id for function_id, _ in functions]
    if function_ids:
        points = session.execute(
            select(BaselineFeaturePoint.id, BaselineFeaturePoint.name).where(
                BaselineFeaturePoint.project_id == project_id,
                BaselineFeaturePoint.status == "active",
                BaselineFeaturePoint.function_id.in_(function_ids),
            )
        ).all()
        index.update({("feature_point", point_id): name for point_id, name in points})
    return index


__all__ = [
    "BASELINE_BRIEF_MAX_RATIO",
    "baseline_index",
    "build_system_prompt",
    "build_user_prompt",
    "render_baseline_brief",
]
