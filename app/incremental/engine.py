"""第一遍引擎。

只负责产出结论，不写库——丢弃判定因此可以纯函数级测试，不必起 HTTP。
写库在 `service.py`，通过 `on_chapter` 回调逐章落库，保证单章失败时
此前章节的结论已经进入事务、不会被一起丢掉。

执行策略（本期同步）：

- 逐章节调用 `LLMProvider.chat`，章节按 `seq` 升序、跳过 `char_count == 0`；
- **单章失败即整体失败**：Provider 抛错或返回非 JSON 时立即中止循环，
  抛出对应业务错误（`LLM_CALL_FAILED` / `LLM_OUTPUT_INVALID`），
  不继续跑后续章节、不静默吞掉异常。同步请求下这是唯一能让前端
  立刻拿到 `failed` 而不干等的做法；第二期接真实模型、引入后台队列后
  再改成异步重试。
- 单条结论分类：越界 → `INCREMENTAL_TARGET_OUT_OF_BASELINE`；
  `label_type='new'` → `INCREMENTAL_LABEL_NEW_DROPPED`；其余待落库。
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.errors import LLMCallFailed, LLMOutputInvalid
from app.incremental.context import (
    baseline_index,
    build_system_prompt,
    build_user_prompt,
    render_baseline_brief,
)
from app.llm.json_utils import parse_llm_json
from app.llm.provider import LLMProvider
from app.llm.schemas import LLMRequest
from app.models.document import DocumentChapter
from app.models.incremental import (
    CONCLUSION_LABEL_TYPES,
    TARGET_TYPES,
    IncrementalAnalysis,
    PromptTemplate,
)

logger = logging.getLogger(__name__)

OUT_OF_BASELINE = "INCREMENTAL_TARGET_OUT_OF_BASELINE"
NEW_DROPPED = "INCREMENTAL_LABEL_NEW_DROPPED"

# 模型可能返回 new（第二遍才允许），这里先放行解析，再统一丢弃
_ALLOWED_LABELS = ("new", *CONCLUSION_LABEL_TYPES)


@dataclass
class PendingConclusion:
    """待落库的局部结论（尚未绑定 analysis_id）。"""

    chapter_id: int
    chapter_title: str
    target_type: str
    target_id: int
    label_type: str
    confidence: Decimal | None = None
    rationale: str | None = None


@dataclass
class ChapterResult:
    """单个章节的处理结果。"""

    chapter: DocumentChapter
    conclusions: list[PendingConclusion] = field(default_factory=list)
    discarded: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PassResult:
    """一次第一遍的汇总结果。`chapter_count` 含被跳过的空章节。"""

    chapter_count: int
    chapters: list[DocumentChapter]
    conclusions: list[PendingConclusion]
    discarded: list[dict[str, Any]]


def load_chapters(session: Session, version_id: int) -> list[DocumentChapter]:
    """生效版本的章节，按 `seq` 升序。"""
    return list(
        session.scalars(
            select(DocumentChapter)
            .where(DocumentChapter.version_id == version_id)
            .order_by(DocumentChapter.seq)
        ).all()
    )


def _invalid(
    chapter: DocumentChapter, detail: str, *, chapter_count: int
) -> LLMOutputInvalid:
    return LLMOutputInvalid(
        f"章节「{chapter.title}」模型返回不合法：{detail}",
        chapter_id=chapter.id,
        chapter_title=chapter.title,
        chapter_count=chapter_count,
    )


def _parse_confidence(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence 必须是数字")
    return Decimal(str(value))


def _parse_conclusion(
    item: Any,
) -> tuple[str, int, str, Decimal | None, str | None] | None:
    """解析单条结论；字段不合契约返回 None 由调用方抛业务错误。"""
    if not isinstance(item, dict):
        return None

    target_type = item.get("target_type")
    target_id = item.get("target_id")
    label_type = item.get("label_type")
    if target_type not in TARGET_TYPES:
        return None
    if isinstance(target_id, bool) or not isinstance(target_id, int):
        return None
    if label_type not in _ALLOWED_LABELS:
        return None

    try:
        confidence = _parse_confidence(item.get("confidence"))
    except ValueError:
        return None

    rationale = item.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        rationale = str(rationale)
    if rationale is not None:
        rationale = rationale[:1000]
    return target_type, target_id, label_type, confidence, rationale


def _process_chapter(
    *,
    chapter: DocumentChapter,
    template: PromptTemplate,
    provider: LLMProvider,
    index: dict[tuple[str, int], str],
    chapter_count: int,
    max_chars: int,
    baseline_brief: str = "",
) -> ChapterResult:
    """单章节：调模型 → 解析 → 分类。任何不合法立即抛错，不续跑。"""
    system = build_system_prompt(template)
    prefix_len = (
        len(template.user_prompt)
        + len(baseline_brief)
        + len(chapter.title)
        + len("\n\n## 章节：\n")
    )
    if prefix_len + len(chapter.content) > max_chars:
        logger.warning(
            "章节 %s「%s」Prompt 超过 %s 字符，已截断正文",
            chapter.id,
            chapter.title,
            max_chars,
        )
    user = build_user_prompt(
        template,
        chapter,
        max_chars=max_chars,
        baseline_brief=baseline_brief,
    )

    try:
        response = provider.chat(LLMRequest(system=system, user=user))
    except Exception as exc:  # Provider 抛任何异常都算调用失败
        raise LLMCallFailed(
            f"章节「{chapter.title}」模型调用失败：{exc}",
            chapter_id=chapter.id,
            chapter_title=chapter.title,
            chapter_count=chapter_count,
        ) from exc

    try:
        payload = parse_llm_json(response.content)
    except (TypeError, ValueError, LLMOutputInvalid) as exc:
        # LLMOutputInvalid 是 AppError 子类，不是 ValueError，
        # 要显式接住才能换成带章节上下文的错误（与改造前行为一致）。
        raise _invalid(chapter, "返回不是合法 JSON", chapter_count=chapter_count) from exc

    if not isinstance(payload, dict) or "conclusions" not in payload:
        raise _invalid(chapter, "缺少 conclusions 字段", chapter_count=chapter_count)
    items = payload["conclusions"]
    if not isinstance(items, list):
        raise _invalid(chapter, "conclusions 必须是数组", chapter_count=chapter_count)

    result = ChapterResult(chapter=chapter)
    seen: set[tuple[str, int]] = set()
    for item in items:
        parsed = _parse_conclusion(item)
        if parsed is None:
            raise _invalid(chapter, "结论字段不完整或取值非法", chapter_count=chapter_count)

        target_type, target_id, label_type, confidence, rationale = parsed
        key = (target_type, target_id)
        # 模型重复输出同一目标时只留第一条，避免撞结论唯一键
        if key in seen:
            continue
        seen.add(key)

        if key not in index:
            result.discarded.append(
                {
                    "chapter_id": chapter.id,
                    "chapter_title": chapter.title,
                    "target_type": target_type,
                    "target_id": target_id,
                    "label_type": label_type,
                    "code": OUT_OF_BASELINE,
                }
            )
            continue
        if label_type == "new":
            result.discarded.append(
                {
                    "chapter_id": chapter.id,
                    "chapter_title": chapter.title,
                    "target_type": target_type,
                    "target_id": target_id,
                    "label_type": label_type,
                    "code": NEW_DROPPED,
                }
            )
            continue

        result.conclusions.append(
            PendingConclusion(
                chapter_id=chapter.id,
                chapter_title=chapter.title,
                target_type=target_type,
                target_id=target_id,
                label_type=label_type,
                confidence=confidence,
                rationale=rationale,
            )
        )
    return result


def run_first_pass(
    session: Session,
    *,
    analysis: IncrementalAnalysis,
    provider: LLMProvider,
    template: PromptTemplate,
    on_chapter: Callable[[ChapterResult], None] | None = None,
) -> PassResult:
    """遍历章节跑第一遍。

    `on_chapter` 在每章成功后调用一次，服务层用它逐章落库；
    任何一章失败都会立刻抛错，后面章节不再执行。
    """
    chapters = load_chapters(session, analysis.document_version_id)
    chapter_count = len(chapters)
    index = baseline_index(session, project_id=analysis.project_id)
    max_chars = get_settings().incremental_max_input_chars
    # 基线清单：真实模型必须看到可用目标才能给出合法的 target_id。
    # 整次分析共用一份，渲染一次即可。
    baseline_brief = render_baseline_brief(index, max_chars=max_chars)

    conclusions: list[PendingConclusion] = []
    discarded: list[dict[str, Any]] = []
    processed: list[DocumentChapter] = []

    for chapter in chapters:
        if chapter.char_count == 0:
            continue
        result = _process_chapter(
            chapter=chapter,
            template=template,
            provider=provider,
            index=index,
            chapter_count=chapter_count,
            max_chars=max_chars,
            baseline_brief=baseline_brief,
        )
        conclusions.extend(result.conclusions)
        discarded.extend(result.discarded)
        processed.append(chapter)
        if on_chapter is not None:
            on_chapter(result)

    return PassResult(
        chapter_count=chapter_count,
        chapters=processed,
        conclusions=conclusions,
        discarded=discarded,
    )


__all__ = [
    "ChapterResult",
    "NEW_DROPPED",
    "OUT_OF_BASELINE",
    "PassResult",
    "PendingConclusion",
    "load_chapters",
    "run_first_pass",
]
