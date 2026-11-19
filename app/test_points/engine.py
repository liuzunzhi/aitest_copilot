"""测试点生成引擎（07-test-points T100）。

**纯函数**：只负责产出待落库的测试点，不写库——丢弃判定因此可以
纯函数级测试，不必起 HTTP、不必起数据库。写库在 `service.py`，
通过 `on_chapter` 回调逐章落库。

执行策略（与 05 第一遍同构）：

- 逐章节调用 `LLMProvider.chat`，章节按 `seq` 升序、跳过 `char_count == 0`；
- **单章失败即整体失败**：Provider 抛错或返回非 JSON 时立即中止循环，
  抛 `LLMCallFailed` / `TestPointInvalid`，不续跑后续章节、不静默吞异常。
- 逐条校验（spec §5.3）：
  - `name` 缺失 / 空 → **整条丢弃**（`TEST_POINT_INVALID`）；
  - `target_type` 不在枚举 → **整条丢弃**（`TEST_POINT_INVALID`）；
  - `target_id` 不在本次输入清单 → **整条丢弃**（`TEST_POINT_TARGET_OUT_OF_BASELINE`）；
  - `priority` 不在枚举 → **归一到 `medium`**（不丢）；
  - `precondition` / `verification` 缺失 → **存空串**（不丢）。

**为什么 `target_id` 越界要丢**：真实模型会照抄模板示例里的 id
（06 期 L2 实测——模板写死 `"target_id": 1`，模型就抄 1，
真实的 10096 / 10097 全被丢弃）。不丢 = 把脏数据写进库，
后面没人知道它挂在哪个功能上。

**为什么 `priority` 不合法不丢**：优先级是展示属性，
丢掉整条测试点（可能包含有价值的验证要点）代价太大，归一即可。
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.errors import LLMCallFailed, LLMOutputInvalid, TestPointInvalid
from app.llm.json_utils import parse_llm_json
from app.llm.provider import LLMProvider
from app.llm.schemas import LLMRequest
from app.models.document import DocumentChapter
from app.models.incremental import PromptTemplate
from app.models.test_point import POINT_PRIORITIES, POINT_TARGET_TYPES
from app.test_points.context import (
    ConclusionContext,
    LabelContext,
    build_system_prompt,
    build_user_prompt,
    render_conclusion_brief,
    render_label_brief,
    render_target_brief,
)

logger = logging.getLogger(__name__)

# 丢弃码。写进 `stats.discarded`，不是 HTTP 错误。
INVALID = "TEST_POINT_INVALID"
OUT_OF_BASELINE = "TEST_POINT_TARGET_OUT_OF_BASELINE"

DEFAULT_PRIORITY = "medium"


@dataclass
class PendingPoint:
    """待落库的测试点（尚未绑定 analysis_id）。"""

    name: str
    target_type: str
    target_id: int
    target_name: str
    priority: str = DEFAULT_PRIORITY
    precondition: str = ""
    verification: str = ""
    chapter_id: int | None = None
    chapter_title: str | None = None
    source_label_id: int | None = None
    source_conclusion_id: int | None = None


@dataclass
class ChapterResult:
    """单个章节的处理结果。"""

    chapter: DocumentChapter
    points: list[PendingPoint] = field(default_factory=list)
    discarded: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GenerateResult:
    """一次生成的汇总结果。`chapter_count` 含被跳过的空章节。"""

    chapter_count: int
    chapters: list[DocumentChapter]
    points: list[PendingPoint]
    discarded: list[dict[str, Any]]
    skipped_empty: int = 0


def load_chapters(session: Session, version_id: int) -> list[DocumentChapter]:
    """生效版本的章节，按 `seq` 升序。"""
    return list(
        session.scalars(
            select(DocumentChapter)
            .where(DocumentChapter.version_id == version_id)
            .order_by(DocumentChapter.seq)
        ).all()
    )


def _invalid(chapter: DocumentChapter, detail: str, *, chapter_count: int):
    return TestPointInvalid(
        f"章节「{chapter.title}」模型返回不合法：{detail}",
        chapter_id=chapter.id,
        chapter_title=chapter.title,
        chapter_count=chapter_count,
    )


def _parse_target_id(value: Any) -> int | None:
    """解析 `target_id`。模型可能给字符串数字——**归一**而不是丢弃。

    真实模型经常把 id 写成 `"10096"`（带引号）。这是格式噪声，
    还原成整数就是原文——与「补引号」那种猜测性修复不同，
    这里只是把同一个数字换种写法。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _clean_text(value: Any) -> str:
    """取文本字段；缺失或类型不对都退化成空串（**不丢整条测试点**）。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip()


def _parse_point(item: Any) -> tuple[str, str, int, str, str, str] | None:
    """解析单条测试点。

    返回 `(name, target_type, target_id, priority, precondition, verification)`；
    字段不合契约返回 None，由调用方**整条丢弃**。
    """
    if not isinstance(item, dict):
        return None

    name = _clean_text(item.get("name"))
    if not name:
        return None

    target_type = item.get("target_type")
    if target_type not in POINT_TARGET_TYPES:
        return None

    target_id = _parse_target_id(item.get("target_id"))
    if target_id is None:
        return None

    priority = item.get("priority")
    if priority not in POINT_PRIORITIES:
        # 归一到 medium 而不是丢弃：优先级是展示属性，
        # 丢掉整条测试点代价太大。
        priority = DEFAULT_PRIORITY

    precondition = _clean_text(item.get("precondition"))
    verification = _clean_text(item.get("verification"))
    return name, target_type, target_id, priority, precondition, verification


def _process_chapter(
    *,
    chapter: DocumentChapter,
    template: PromptTemplate,
    provider: LLMProvider,
    labels: LabelContext,
    conclusions: ConclusionContext,
    target_brief: str,
    label_brief: str,
    conclusion_brief: str,
    chapter_count: int,
    max_chars: int,
) -> ChapterResult:
    """单章节：调模型 → 解析 → 校验。任何不合法立即抛错，不续跑。"""
    system = build_system_prompt(template)
    user = build_user_prompt(
        template,
        chapter,
        max_chars=max_chars,
        target_brief=target_brief,
        label_brief=label_brief,
        conclusion_brief=conclusion_brief,
    )
    if len(user) > max_chars:
        logger.warning(
            "章节 %s「%s」Prompt 超过 %s 字符，已截断正文",
            chapter.id,
            chapter.title,
            max_chars,
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
        # 要显式接住才能换成带章节上下文的错误。
        raise _invalid(chapter, "返回不是合法 JSON", chapter_count=chapter_count) from exc

    if not isinstance(payload, dict) or "test_points" not in payload:
        raise _invalid(chapter, "缺少 test_points 字段", chapter_count=chapter_count)
    items = payload["test_points"]
    if not isinstance(items, list):
        raise _invalid(chapter, "test_points 必须是数组", chapter_count=chapter_count)

    result = ChapterResult(chapter=chapter)
    seen: set[tuple[str, int]] = set()
    for item in items:
        parsed = _parse_point(item)
        if parsed is None:
            result.discarded.append(
                {
                    "chapter_id": chapter.id,
                    "chapter_title": chapter.title,
                    "name": _clean_text(item.get("name"))
                    if isinstance(item, dict)
                    else "",
                    "code": INVALID,
                }
            )
            continue

        name, target_type, target_id, priority, precondition, verification = parsed
        key = (target_type, target_id)
        # 模型重复输出同一目标时只留第一条
        if key in seen:
            continue
        seen.add(key)

        if key not in labels.index:
            # 越界：模型猜的 id 不在本次输入清单里 → 丢弃，不落库。
            result.discarded.append(
                {
                    "chapter_id": chapter.id,
                    "chapter_title": chapter.title,
                    "name": name,
                    "target_type": target_type,
                    "target_id": target_id,
                    "code": OUT_OF_BASELINE,
                }
            )
            continue

        result.points.append(
            PendingPoint(
                name=name,
                target_type=target_type,
                target_id=target_id,
                target_name=labels.index[key],
                priority=priority,
                precondition=precondition,
                verification=verification,
                chapter_id=chapter.id,
                chapter_title=chapter.title,
                source_label_id=labels.label_ids.get(key),
                source_conclusion_id=conclusions.conclusion_ids.get(key),
            )
        )
    return result


def run_generate(
    session: Session,
    *,
    provider: LLMProvider,
    template: PromptTemplate,
    chapters: list[DocumentChapter],
    labels: LabelContext,
    conclusions: ConclusionContext | None = None,
    on_chapter: Callable[[ChapterResult], None] | None = None,
) -> GenerateResult:
    """遍历章节生成测试点。

    `on_chapter` 在每章成功后调用一次，服务层用它逐章落库；
    任何一章失败都会立刻抛错，后面章节不再执行。
    """
    conclusions = conclusions or ConclusionContext()
    max_chars = get_settings().incremental_max_input_chars

    # 清单 / 依据 / 结论：整次生成共用一份，渲染一次即可。
    # **确定性排序**在 render_* 里做——同样的输入永远渲染出同样的文本。
    target_brief = render_target_brief(labels.index, max_chars=max_chars)
    label_brief = render_label_brief(labels.labels)
    conclusion_brief = render_conclusion_brief(conclusions.items)

    points: list[PendingPoint] = []
    discarded: list[dict[str, Any]] = []
    processed: list[DocumentChapter] = []
    skipped_empty = 0
    chapter_count = len(chapters)

    for chapter in chapters:
        if chapter.char_count == 0:
            skipped_empty += 1
            continue
        result = _process_chapter(
            chapter=chapter,
            template=template,
            provider=provider,
            labels=labels,
            conclusions=conclusions,
            target_brief=target_brief,
            label_brief=label_brief,
            conclusion_brief=conclusion_brief,
            chapter_count=chapter_count,
            max_chars=max_chars,
        )
        points.extend(result.points)
        discarded.extend(result.discarded)
        processed.append(chapter)
        if on_chapter is not None:
            on_chapter(result)

    return GenerateResult(
        chapter_count=chapter_count,
        chapters=processed,
        points=points,
        discarded=discarded,
        skipped_empty=skipped_empty,
    )


__all__ = [
    "ChapterResult",
    "DEFAULT_PRIORITY",
    "GenerateResult",
    "INVALID",
    "OUT_OF_BASELINE",
    "PendingPoint",
    "load_chapters",
    "run_generate",
]
