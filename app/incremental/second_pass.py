"""第二遍引擎：2b-1 索引 + 2b-2 按点分治（T73）。

与一期 `engine.py` 同构：只算不写库，返回待落库的裁决 / 冲突，
由 `service.run_second_pass`（T75）负责事务与落库。

2b-2 的核心是「小输入」与「先判证据一致性」：

- 每个目标单独组装 Prompt，只带该目标及其所辖功能的局部结论；
- 作用域内标签不一致 → 不调模型，直接产出 `conflict` 候选；
- 一致 → 调 Mock，以模型 `decision` 为准产出 `decisions`；
- `new_points` 只产出 `new` 冲突（没有基线 id），同名去重、理由合并。

2b-3 图传播（`propagate_impacts`）：

- 只沿 `references` / `depends_on` 边走一跳，源章节有 `changed` / `affected` 结论才触发；
- 传播结果一律产 `possible_impact` 冲突，不改写 `decisions`；
- 命中已被 2b-2 裁决的目标 → 删除该 `decisions`，原标签并入候选，
  保证同一目标只出现在 `decisions` / `conflicts` 之一；
- 同目标既有 `conflict` 又有 `possible_impact` → 合并为一条 `conflict`。
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.errors import LLMCallFailed, LLMOutputInvalid
from app.incremental.context import baseline_index
from app.incremental.context2b import TARGET_LABELS, build_system_prompt, build_user_prompt
from app.llm.json_utils import parse_llm_json
from app.llm.provider import LLMProvider
from app.llm.schemas import LLMRequest
from app.models.baseline import BaselineFeaturePoint, BaselineFunction, BaselineModule
from app.models.chapter_link import DocumentChapterLink
from app.models.document import DocumentChapter
from app.models.incremental import (
    DECISION_TYPES,
    IncrementalAnalysis,
    IncrementalConclusion,
    PromptTemplate,
)

POINT_PASS_SOURCE = "point_pass"
_PROPAGATION_LINK_TYPES = ("references", "depends_on")
_STRONG_LABELS = ("changed", "affected")


@dataclass(frozen=True)
class LocalConclusion:
    """2b-1 索引里的一条局部结论。"""

    id: int
    chapter_id: int
    chapter_title: str
    target_type: str
    target_id: int
    label_type: str
    confidence: Decimal | None = None
    rationale: str | None = None


@dataclass
class PointIndex:
    """2b-1 的输出：结论、功能→功能点、章节引用图、名称。"""

    conclusions: dict[tuple[str, int], list[LocalConclusion]]
    function_points: dict[int, list[int]]
    chapter_links: dict[int, list[int]]
    names: dict[tuple[str, int], str]
    chapters: dict[int, DocumentChapter]


@dataclass
class PendingDecision:
    """待落库的无争议裁决。"""

    target_type: str
    target_id: int
    target_name: str
    decision: str
    confidence: Decimal | None = None
    rationale: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingConflict:
    """待落库的冲突 / 可能连带 / 新增。"""

    target_type: str
    target_id: int | None
    target_name: str
    conflict_type: str
    candidates: list[dict[str, Any]]


@dataclass
class SecondPassResult:
    """2b-2 的汇总结果。`prompted_count` 等于实际调用模型的次数（AC-89）。"""

    point_count: int
    prompted_count: int
    decisions: list[PendingDecision] = field(default_factory=list)
    conflicts: list[PendingConflict] = field(default_factory=list)
    propagated_count: int = 0


# ------------------------------------------------------------ 2b-1 索引


def build_point_index(session: Session, analysis: IncrementalAnalysis) -> PointIndex:
    """按本分析的第一遍结论建索引；只收当前结构里仍有效的目标。"""
    names = baseline_index(session, project_id=analysis.project_id)

    chapters = {
        chapter.id: chapter
        for chapter in session.scalars(
            select(DocumentChapter).where(
                DocumentChapter.version_id == analysis.document_version_id
            )
        ).all()
    }

    rows = session.scalars(
        select(IncrementalConclusion)
        .where(IncrementalConclusion.analysis_id == analysis.id)
        .order_by(IncrementalConclusion.id)
    ).all()
    conclusions: dict[tuple[str, int], list[LocalConclusion]] = {}
    for row in rows:
        if (row.target_type, row.target_id) not in names:
            # 第一遍落库后目标被归档：按口径直接忽略
            continue
        chapter = chapters.get(row.chapter_id)
        item = LocalConclusion(
            id=row.id,
            chapter_id=row.chapter_id,
            chapter_title=chapter.title if chapter is not None else "",
            target_type=row.target_type,
            target_id=row.target_id,
            label_type=row.label_type,
            confidence=row.confidence,
            rationale=row.rationale,
        )
        conclusions.setdefault((row.target_type, row.target_id), []).append(item)

    link_rows = session.execute(
        select(DocumentChapterLink.from_chapter_id, DocumentChapterLink.to_chapter_id)
        .where(
            DocumentChapterLink.version_id == analysis.document_version_id,
            DocumentChapterLink.link_type.in_(_PROPAGATION_LINK_TYPES),
            DocumentChapterLink.to_chapter_id.is_not(None),
        )
        .order_by(DocumentChapterLink.from_chapter_id, DocumentChapterLink.to_chapter_id)
    ).all()
    chapter_links: dict[int, list[int]] = {}
    for from_chapter_id, to_chapter_id in link_rows:
        bucket = chapter_links.setdefault(from_chapter_id, [])
        if to_chapter_id not in bucket:
            bucket.append(to_chapter_id)

    return PointIndex(
        conclusions=conclusions,
        function_points=_active_function_points(session, analysis.project_id),
        chapter_links=chapter_links,
        names=names,
        chapters=chapters,
    )


def _active_function_points(session: Session, project_id: int) -> dict[int, list[int]]:
    """功能 id → 功能点 id 列表（只算有效模块与有效功能）。"""
    rows = session.execute(
        select(BaselineFeaturePoint.id, BaselineFeaturePoint.function_id)
        .join(BaselineFunction, BaselineFunction.id == BaselineFeaturePoint.function_id)
        .join(BaselineModule, BaselineModule.id == BaselineFunction.module_id)
        .where(
            BaselineFeaturePoint.project_id == project_id,
            BaselineFeaturePoint.status == "active",
            BaselineFunction.status == "active",
            BaselineModule.status == "active",
            BaselineModule.project_id == project_id,
        )
        .order_by(BaselineFeaturePoint.id)
    ).all()
    mapping: dict[int, list[int]] = {}
    for point_id, function_id in rows:
        mapping.setdefault(function_id, []).append(point_id)
    return mapping


def participating_targets(index: PointIndex) -> list[tuple[str, int]]:
    """参与 2b-2 的目标：有结论的功能点 + 有结论且没有功能点的功能。"""
    targets: list[tuple[str, int]] = []
    for target_type, target_id in index.conclusions:
        if target_type == "feature_point":
            targets.append((target_type, target_id))
        elif target_id not in index.function_points:
            targets.append((target_type, target_id))
    return sorted(targets, key=lambda item: (item[0] == "feature_point", item[1]))


def scoped_conclusions(
    index: PointIndex, target_type: str, target_id: int
) -> list[LocalConclusion]:
    """目标的证据作用域：功能点连其所辖功能的结论一起带，反之只有自己。"""
    items = list(index.conclusions.get((target_type, target_id), []))
    if target_type != "feature_point":
        return items
    for function_id, point_ids in index.function_points.items():
        if target_id in point_ids:
            items.extend(index.conclusions.get(("function", function_id), []))
    return items


def target_name(index: PointIndex, target_type: str, target_id: int) -> str:
    return index.names.get((target_type, target_id)) or f"{target_type}#{target_id}"


# ------------------------------------------------------------ 2b-2 按点分治


def _parse_confidence(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence 必须是数字")
    return Decimal(str(value))


def _invalid(target_type: str, target_id: int, name: str, detail: str) -> LLMOutputInvalid:
    return LLMOutputInvalid(
        f"目标「{name}」第二遍返回不合法：{detail}",
        target_type=target_type,
        target_id=target_id,
    )


def _parse_payload(
    content: str, *, target_type: str, target_id: int, name: str
) -> tuple[str, Decimal | None, str | None, list[dict[str, Any]]]:
    """解析第二遍模型输出。`decision` 非法或非 JSON 直接抛错。"""
    try:
        payload = parse_llm_json(content)
    except (TypeError, ValueError, LLMOutputInvalid) as exc:
        # LLMOutputInvalid 是 AppError 子类，不是 ValueError，要显式接住
        # 才能换成带目标上下文的错误（与改造前行为一致）。
        raise _invalid(target_type, target_id, name, "返回不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise _invalid(target_type, target_id, name, "返回不是 JSON 对象")

    decision = payload.get("decision")
    if decision not in DECISION_TYPES:
        raise _invalid(target_type, target_id, name, "decision 不在 changed/affected/unchanged 内")
    try:
        confidence = _parse_confidence(payload.get("confidence"))
    except ValueError as exc:
        raise _invalid(target_type, target_id, name, "confidence 不是数字") from exc

    rationale = payload.get("rationale")
    if rationale is not None:
        rationale = rationale if isinstance(rationale, str) else str(rationale)
        rationale = rationale[:1000]

    new_points: list[dict[str, Any]] = []
    raw_points = payload.get("new_points")
    if isinstance(raw_points, list):
        for item in raw_points:
            if not isinstance(item, dict):
                continue
            point_name = item.get("name")
            if not isinstance(point_name, str) or not point_name.strip():
                continue
            point_rationale = item.get("rationale")
            new_points.append(
                {
                    "name": point_name.strip()[:255],
                    "rationale": (
                        (point_rationale if isinstance(point_rationale, str) else None)
                        or None
                    ),
                }
            )
    return decision, confidence, rationale, new_points


def _conflict_candidates(items: list[LocalConclusion]) -> list[dict[str, Any]]:
    """按 label 聚合去重：每个标签一条候选，置信度取最大。"""
    grouped: dict[str, list[LocalConclusion]] = {}
    for item in items:
        grouped.setdefault(item.label_type, []).append(item)

    candidates: list[dict[str, Any]] = []
    for label_type in sorted(grouped):
        bucket = grouped[label_type]
        confidences = [item.confidence for item in bucket if item.confidence is not None]
        rationale = next((item.rationale for item in bucket if item.rationale), None)
        candidates.append(
            {
                "label_type": label_type,
                "confidence": float(max(confidences)) if confidences else None,
                "rationale": rationale,
                "source": POINT_PASS_SOURCE,
            }
        )
    return candidates


def _chapter_pairs(
    index: PointIndex, items: list[LocalConclusion]
) -> list[tuple[str, str]]:
    """作用域章节 + 一跳关联章节，按章节 id 去重。"""
    ids: list[int] = []
    for item in items:
        if item.chapter_id not in ids:
            ids.append(item.chapter_id)
        for linked in index.chapter_links.get(item.chapter_id, []):
            if linked not in ids:
                ids.append(linked)
    pairs: list[tuple[str, str]] = []
    for chapter_id in ids:
        chapter = index.chapters.get(chapter_id)
        if chapter is not None:
            pairs.append((chapter.title, chapter.content))
    return pairs


def _merge_new_point(
    conflicts: dict[str, PendingConflict], name: str, rationale: str | None
) -> None:
    """同名新增只留一条，理由拼接去重。"""
    existing = conflicts.get(name)
    candidate = {
        "label_type": "new",
        "confidence": None,
        "rationale": rationale,
        "source": POINT_PASS_SOURCE,
    }
    if existing is None:
        conflicts[name] = PendingConflict(
            target_type="feature_point",
            target_id=None,
            target_name=name,
            conflict_type="new",
            candidates=[candidate],
        )
        return
    rationales = [item["rationale"] for item in existing.candidates]
    if rationale and rationale not in rationales:
        existing.candidates.append(candidate)


def run_point_pass(
    session: Session,
    *,
    analysis: IncrementalAnalysis,
    provider: LLMProvider,
    template: PromptTemplate,
    index: PointIndex | None = None,
    max_chars: int | None = None,
) -> SecondPassResult:
    """逐目标跑 2b-2。证据矛盾的目标不调模型（AC-89 / AC-91）。"""
    index = index or build_point_index(session, analysis)
    limit = max_chars if max_chars is not None else get_settings().incremental_max_input_chars
    system = build_system_prompt(template)

    targets = participating_targets(index)
    result = SecondPassResult(point_count=len(targets), prompted_count=0)
    new_points: dict[str, PendingConflict] = {}

    for target_type, target_id in targets:
        items = scoped_conclusions(index, target_type, target_id)
        name = target_name(index, target_type, target_id)
        labels = {item.label_type for item in items}

        if len(labels) > 1:
            result.conflicts.append(
                PendingConflict(
                    target_type=target_type,
                    target_id=target_id,
                    target_name=name,
                    conflict_type="conflict",
                    candidates=_conflict_candidates(items),
                )
            )
            continue

        user = build_user_prompt(
            template,
            target_label=TARGET_LABELS[target_type],
            name=name,
            scope=[(item.label_type, item.chapter_title, item.rationale) for item in items],
            chapters=_chapter_pairs(index, items),
            max_chars=limit,
        )
        try:
            response = provider.chat(LLMRequest(system=system, user=user))
        except Exception as exc:  # Provider 抛任何异常都算调用失败
            raise LLMCallFailed(
                f"目标「{name}」第二遍模型调用失败：{exc}",
                target_type=target_type,
                target_id=target_id,
            ) from exc
        result.prompted_count += 1

        decision, confidence, rationale, points = _parse_payload(
            response.content, target_type=target_type, target_id=target_id, name=name
        )
        result.decisions.append(
            PendingDecision(
                target_type=target_type,
                target_id=target_id,
                target_name=name,
                decision=decision,
                confidence=confidence,
                rationale=rationale,
                evidence={
                    "chapter_ids": sorted({item.chapter_id for item in items}),
                    "conclusion_ids": sorted({item.id for item in items}),
                    "propagated_from": [],
                },
            )
        )
        for point in points:
            _merge_new_point(new_points, point["name"], point["rationale"])

    result.conflicts.extend(new_points.values())
    return result


# ------------------------------------------------------------ 2b-3 图传播


def _targets_of_chapter(
    index: PointIndex, chapter_id: int
) -> list[tuple[str, int]]:
    """某章节直接命中的基线目标（结论所在章节 == 该章节）。"""
    return [
        key
        for key, items in index.conclusions.items()
        if any(item.chapter_id == chapter_id for item in items)
    ]


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(candidate.get("label_type")),
        str(candidate.get("source")),
        str(candidate.get("rationale")),
    )


def _merge_candidates(
    existing: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """按 `(label_type, source, rationale)` 去重合并候选。"""
    seen = {_candidate_key(item) for item in existing}
    merged = list(existing)
    for candidate in extra:
        key = _candidate_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        merged.append(candidate)
    return merged


def propagate_impacts(
    index: PointIndex, result: SecondPassResult
) -> SecondPassResult:
    """沿章节引用图传播「可能连带变更」，就地改写 `result`。

    - 一跳：只沿 `references` / `depends_on` 走一层；
    - 源章节有 `changed` / `affected` 结论才触发；
    - 传播结果一律进冲突队列（`possible_impact`），不直接改写标签；
    - 命中已有 `decisions` 的目标 → 删除该裁决，原标签并入候选；
    - 同目标既有 `conflict` 又有 `possible_impact` → 合并为 `conflict`。
    """
    strong_targets: dict[int, set[tuple[str, int]]] = {}
    for chapter_id in index.chapter_links:
        for key in _targets_of_chapter(index, chapter_id):
            labels = {
                item.label_type
                for item in index.conclusions[key]
                if item.chapter_id == chapter_id and item.label_type in _STRONG_LABELS
            }
            if labels:
                strong_targets.setdefault(chapter_id, set()).add(key)

    decisions_by_target = {
        (item.target_type, item.target_id): item for item in result.decisions
    }
    conflicts_by_target: dict[tuple[str, int], PendingConflict] = {
        (item.target_type, item.target_id): item
        for item in result.conflicts
        if item.target_id is not None
    }

    propagated: list[tuple[str, int]] = []
    for from_chapter_id, to_chapter_ids in index.chapter_links.items():
        sources = strong_targets.get(from_chapter_id)
        if not sources:
            continue
        for to_chapter_id in to_chapter_ids:
            for key in _targets_of_chapter(index, to_chapter_id):
                if key in sources:
                    # 源章节自己就是这个目标，不算连带
                    continue
                if key not in propagated:
                    propagated.append(key)

                candidates: list[dict[str, Any]] = [
                    {
                        "label_type": "affected",
                        "confidence": None,
                        "rationale": f"章节 {from_chapter_id} 变更可能连带影响",
                        "source": f"chapter:{from_chapter_id}",
                    }
                ]

                decision = decisions_by_target.get(key)
                if decision is not None:
                    # 同一目标只出现在一张表：删除裁决，原标签并入候选
                    result.decisions.remove(decision)
                    decisions_by_target.pop(key, None)
                    candidates.append(
                        {
                            "label_type": decision.decision,
                            "confidence": (
                                float(decision.confidence)
                                if decision.confidence is not None
                                else None
                            ),
                            "rationale": decision.rationale,
                            "source": POINT_PASS_SOURCE,
                        }
                    )

                conflict = conflicts_by_target.get(key)
                if conflict is None:
                    conflict = PendingConflict(
                        target_type=key[0],
                        target_id=key[1],
                        target_name=target_name(index, key[0], key[1]),
                        conflict_type="possible_impact",
                        candidates=candidates,
                    )
                    conflicts_by_target[key] = conflict
                    result.conflicts.append(conflict)
                else:
                    conflict.candidates = _merge_candidates(conflict.candidates, candidates)
                    # 类型保持：2b-2 产的 conflict 仍是 conflict（人工裁决优先级更高），
                    # 两次传播命中仍是 possible_impact

    result.propagated_count = len(propagated)
    return result


__all__ = [
    "LocalConclusion",
    "POINT_PASS_SOURCE",
    "PendingConflict",
    "PendingDecision",
    "PointIndex",
    "SecondPassResult",
    "build_point_index",
    "participating_targets",
    "propagate_impacts",
    "run_point_pass",
    "scoped_conclusions",
    "target_name",
]
