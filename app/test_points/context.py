"""测试点生成的 Prompt 组装与输入上下文取数（07-test-points T100）。

组装规则（spec §5.1）——**严格分段，顺序固定**：

    user = f"{template.user_prompt}
             \n\n## 可对照的基线目标\n{清单}
             \n\n## 标签依据\n{标签明细}
             \n\n## 增量结论\n{结论明细}
             \n\n## 章节：{title}\n{content}"

为什么必须分段且顺序固定：

1. **真实模型需要清单**——不给 `target_id` 清单，模型只能瞎猜，
   猜出来的 id 全部被当越界丢弃。06 期 L2 实测：模型明说「baseline unavailable」。
2. **Prompt 必须可复现**——同样的输入必须渲染出**逐字节相同**的 Prompt，
   否则问题无法复现、排查无从下手。所以所有清单都按确定键排序，
   **绝不使用数据库的默认返回顺序**（那条顺序没有保证）。
3. **截断只砍章节正文**——前缀（模板正文 + 清单 + 依据 + 结论）保持不变，
   这样「user 以模板 user_prompt 开头」在超长场景下依然成立。

**取数口径**：

- 标签一律 `baseline_labels.status='active'`——已清除的标签连同它的目标
  **完全不进 Prompt**（spec AC-142，服务端强制过滤，不依赖前端）。
- 增量结论只取 `label_type IN ('changed','affected')`——`unchanged` 没有测试价值。
- 结构实体用 04 的 `approved_entities()` 过滤被驳回的节点（与 05 同口径）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.baselines.approval import approved_entities
from app.models.baseline import BaselineFeaturePoint, BaselineFunction, BaselineLabel
from app.models.incremental import IncrementalConclusion, PromptTemplate

# 基线清单最多占输入预算的比例。剩下的留给章节正文——
# 清单太长会把正文挤没，模型拿不到内容就无从判断。
# 与 05 的 `BASELINE_BRIEF_MAX_RATIO` 同值：两个模块各调各的会漂移。
BRIEF_MAX_RATIO = 0.4

# 标签类型 → 展示文案
LABEL_TYPE_LABELS = {
    "new": "新增",
    "changed": "变更",
    "affected": "受影响",
    "unchanged": "无变化",
}

# 结论判定 → 展示文案
CONCLUSION_LABELS = {
    "changed": "变更",
    "affected": "受影响",
}

# 只取这两类结论进 Prompt：`unchanged` 的结论没有测试价值。
CONCLUSION_TYPES = ("changed", "affected")


@dataclass
class LabelContext:
    """生效标签上下文。

    - `index`：`(target_type, target_id) → 目标名称`，就是喂给模型的清单；
    - `labels`：标签明细（供 Prompt 渲染「标签依据」段）；
    - `label_ids`：`(target_type, target_id) → label_id`，
      落库时记来源标签用。
    """

    index: dict[tuple[str, int], str] = field(default_factory=dict)
    labels: list[dict[str, Any]] = field(default_factory=list)
    label_ids: dict[tuple[str, int], int] = field(default_factory=dict)


@dataclass
class ConclusionContext:
    """增量结论上下文。"""

    items: list[dict[str, Any]] = field(default_factory=list)
    by_target: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    conclusion_ids: dict[tuple[str, int], int] = field(default_factory=dict)


def build_system_prompt(template: PromptTemplate) -> str:
    """系统提示词原样取自数据库模板，不做任何加工。"""
    return template.system_prompt


def render_target_brief(
    index: dict[tuple[str, int], str], *, max_chars: int | None = None
) -> str:
    """把目标清单渲染成给模型看的文本。

    每行一条：`功能#10096 用户扫码登录` / `功能点#5630 提交订单`。

    **排序按 `(target_type, target_id)`**——同一次生成里渲染结果必须稳定，
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
        budget = max(0, int(max_chars * BRIEF_MAX_RATIO))
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


def render_label_brief(labels: list[dict[str, Any]]) -> str:
    """渲染「标签依据」段。

    每行一条：`[变更] 用户扫码登录（功能#10096），确认人 admin，确认于 2026-11-18 10:00:00`。

    **排序按 `(target_type, target_id, label_type)`**——确定性渲染。
    """
    if not labels:
        return ""
    lines = []
    for item in sorted(
        labels,
        key=lambda row: (
            row["target_type"],
            row["target_id"],
            row["label_type"],
        ),
    ):
        type_label = LABEL_TYPE_LABELS.get(item["label_type"], item["label_type"])
        target_name = item.get("target_name") or "已删除的对象"
        confirmed_at = item.get("confirmed_at")
        when = _format_time(confirmed_at)
        lines.append(
            f"- [{type_label}] {target_name}（{item['target_type']}#{item['target_id']}）"
            f"，确认人 {item.get('confirmed_by_name') or '未知'}，确认于 {when}"
        )
    return "\n".join(lines)


def render_conclusion_brief(items: list[dict[str, Any]]) -> str:
    """渲染「增量结论」段。

    每行一条：`4.2 登录失败次数限制 → 用户扫码登录：受影响（0.76）锁定期内扫码登录也会受阻`。

    **排序按 `(chapter_id, target_type, target_id)`**——确定性渲染。
    """
    if not items:
        return ""
    lines = []
    for item in sorted(
        items,
        key=lambda row: (
            row.get("chapter_id") or 0,
            row["target_type"],
            row["target_id"],
        ),
    ):
        decision = CONCLUSION_LABELS.get(item["label_type"], item["label_type"])
        target_name = item.get("target_name") or "已删除的对象"
        chapter_title = item.get("chapter_title") or "未知章节"
        confidence = item.get("confidence")
        score = f"（{confidence}）" if confidence is not None else ""
        rationale = item.get("rationale") or ""
        lines.append(
            f"- {chapter_title} → {target_name}：{decision}{score} {rationale}".rstrip()
        )
    return "\n".join(lines)


def _format_time(value: datetime | None) -> str:
    if value is None:
        return "未知时间"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def build_user_prompt(
    template: PromptTemplate,
    chapter: Any,
    *,
    max_chars: int | None = None,
    target_brief: str = "",
    label_brief: str = "",
    conclusion_brief: str = "",
) -> str:
    """组装用户提示词；超长时只截断章节正文。

    **分段固定**：模板正文 → 基线目标清单 → 标签依据 → 增量结论 → 章节正文。
    空段落**整段省略**（不留空标题），但段落之间的相对顺序永不改变。

    前缀（模板正文 + 清单 + 依据 + 结论 + 章节标题）保持不变，
    这样 AC-156 的「user 以模板 user_prompt 开头」在截断场景下依然成立。
    """
    prefix = template.user_prompt
    if target_brief:
        prefix += f"\n\n## 可对照的基线目标\n{target_brief}"
    if label_brief:
        prefix += f"\n\n## 标签依据\n{label_brief}"
    if conclusion_brief:
        prefix += f"\n\n## 增量结论\n{conclusion_brief}"
    prefix += f"\n\n## 章节：{chapter.title}\n"

    content = chapter.content or ""
    if max_chars is None or len(prefix) + len(content) <= max_chars:
        return f"{prefix}{content}"
    remaining = max(0, max_chars - len(prefix))
    return f"{prefix}{content[:remaining]}"


# --------------------------------------------------------------------- 取数


def _target_names(
    session: Session, rows: list[tuple[str, int]]
) -> dict[tuple[str, int], str]:
    """功能与功能点的 id → 业务名称。

    用户认对象靠名称，不靠内部 id；名称查不到时统一显示「已删除的对象」。
    """
    function_ids = [target_id for target_type, target_id in rows if target_type == "function"]
    point_ids = [
        target_id for target_type, target_id in rows if target_type == "feature_point"
    ]

    names: dict[tuple[str, int], str] = {}
    if function_ids:
        for function_id, function_name in session.execute(
            select(BaselineFunction.id, BaselineFunction.name).where(
                BaselineFunction.id.in_(function_ids)
            )
        ).all():
            names[("function", function_id)] = function_name
    if point_ids:
        for point_id, point_name in session.execute(
            select(BaselineFeaturePoint.id, BaselineFeaturePoint.name).where(
                BaselineFeaturePoint.id.in_(point_ids)
            )
        ).all():
            names[("feature_point", point_id)] = point_name
    return names


def active_label_context(
    session: Session,
    *,
    project_id: int,
    revision_id: int | None = None,
) -> LabelContext:
    """取项目里**生效中**的标签，作为生成测试点的依据。

    `status='active'` 是硬口径（与 04 的 `_label_type_map` 一致）：
    已清除的标签连同它的目标**完全不出现**在 Prompt 里。

    目标名查不到（目标已删）的标签**跳过**——不把悬空目标喂给模型。

    `revision_id` 给了就只取该快照上的标签。
    """
    query = select(
        BaselineLabel.id,
        BaselineLabel.target_type,
        BaselineLabel.target_id,
        BaselineLabel.label_type,
        BaselineLabel.source_analysis_id,
        BaselineLabel.confirmed_by,
        BaselineLabel.confirmed_at,
    ).where(
        BaselineLabel.project_id == project_id,
        BaselineLabel.status == "active",
    )
    if revision_id is not None:
        query = query.where(BaselineLabel.revision_id == revision_id)

    rows = session.execute(query).all()
    if not rows:
        return LabelContext()

    names = _target_names(
        session, [(row[1], row[2]) for row in rows]
    )

    # 被分点审核驳回的节点不进清单（与 05 的 baseline_index 同口径）。
    approved = approved_entities(session, project_id)

    context = LabelContext()
    for (
        label_id,
        target_type,
        target_id,
        label_type,
        source_analysis_id,
        confirmed_by,
        confirmed_at,
    ) in rows:
        key = (target_type, target_id)
        if key not in names:
            # 目标已被删除：跳过，不把悬空 id 喂给模型。
            continue
        if approved is not None and key not in approved:
            continue
        context.index[key] = names[key]
        context.label_ids[key] = label_id
        context.labels.append(
            {
                "id": label_id,
                "target_type": target_type,
                "target_id": target_id,
                "target_name": names[key],
                "label_type": label_type,
                "source_analysis_id": source_analysis_id,
                "confirmed_by": confirmed_by,
                "confirmed_at": confirmed_at,
            }
        )
    return context


def conclusion_context(
    session: Session, *, analysis_id: int) -> ConclusionContext:
    """取一次增量分析的结论，作为生成测试点的依据。

    **只取 `label_type IN ('changed','affected')`**——`unchanged` 的结论
    没有测试价值（功能没变，没什么可测的新东西）。

    同一目标有多条结论时，**取第一条**（按 `id` 升序）——
    结果确定，不随数据库返回顺序漂移。
    """
    rows = session.execute(
        select(
            IncrementalConclusion.id,
            IncrementalConclusion.chapter_id,
            IncrementalConclusion.chapter_title,
            IncrementalConclusion.target_type,
            IncrementalConclusion.target_id,
            IncrementalConclusion.label_type,
            IncrementalConclusion.confidence,
            IncrementalConclusion.rationale,
        )
        .where(
            IncrementalConclusion.analysis_id == analysis_id,
            IncrementalConclusion.label_type.in_(CONCLUSION_TYPES),
        )
        .order_by(IncrementalConclusion.id)
    ).all()
    if not rows:
        return ConclusionContext()

    names = _target_names(session, [(row[3], row[4]) for row in rows])

    context = ConclusionContext()
    for (
        conclusion_id,
        chapter_id,
        chapter_title,
        target_type,
        target_id,
        label_type,
        confidence,
        rationale,
    ) in rows:
        key = (target_type, target_id)
        if key in context.by_target:
            continue
        context.by_target[key] = {
            "id": conclusion_id,
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "target_type": target_type,
            "target_id": target_id,
            "target_name": names.get(key),
            "label_type": label_type,
            "confidence": str(confidence) if confidence is not None else None,
            "rationale": rationale,
        }
        context.conclusion_ids[key] = conclusion_id
        context.items.append(context.by_target[key])
    return context


def analysis_fully_revoked(session: Session, *, analysis_id: int) -> bool:
    """该次增量分析产出的标签是否**全部**被清除。

    PRD 2.4.4：「分析结论已全部撤销的增量记录默认不可选」。

    连接点是 `baseline_labels.source_analysis_id`——标签挂在**快照**上，
    而分析记录是另一次比对，二者只有这一个字段对得上（04 预留，05 写入）。

    **没有标签 ≠ 全部撤销**：一条标签都没有说明这次分析没产出可打标的东西，
    不该按「已撤销」处理。
    """
    total = session.scalar(
        select(func.count())
        .select_from(BaselineLabel)
        .where(BaselineLabel.source_analysis_id == analysis_id)
    )
    if not total:
        return False
    active = session.scalar(
        select(func.count())
        .select_from(BaselineLabel)
        .where(
            BaselineLabel.source_analysis_id == analysis_id,
            BaselineLabel.status == "active",
        )
    )
    return (active or 0) == 0


__all__ = [
    "BRIEF_MAX_RATIO",
    "CONCLUSION_LABELS",
    "CONCLUSION_TYPES",
    "ConclusionContext",
    "LABEL_TYPE_LABELS",
    "LabelContext",
    "active_label_context",
    "analysis_fully_revoked",
    "build_system_prompt",
    "build_user_prompt",
    "conclusion_context",
    "render_conclusion_brief",
    "render_label_brief",
    "render_target_brief",
]
