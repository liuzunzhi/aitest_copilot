"""章节引用图的 AI 分析引擎（12-chapter-link-ai T131）。

**纯函数 + provider 注入**：不查默认配置、不建记录、不落库。
服务层负责校验、取章节、落库。引擎只负责「给模型什么」与「怎么读回模型说的」。

**签名里没有 `session`**——「引擎不碰数据库」从「靠自觉」变成
「结构上做不到」（与 10 期的 `app/process_baselines/derive.py` 同构）。

## 两条路径（用户拍板的口径）

```
总正文字符数 = sum(len(chapter.content))
├── ≤ full_doc_threshold (30000)  → 【整篇一次调用】
│     一次 LLM 调用，Prompt = 模板 + 章节清单 + 全文
└── > 30000                        → 【两阶段分析】
      阶段一（并发）：按每 chunk_size(20) 章一块切分
                     → ThreadPoolExecutor 并发调模型
                     → 每块产出 [{chapter_id, title, summary, entities[]}]
      阶段二（全局比对）：Prompt = 模板 + 全局章节目录清单
                        （每章一行：id + 标题 + 摘要 + 实体）
                     → 一次 LLM 调用，产出引用边
```

**为什么要有分块**：整篇拼一个 Prompt 必然 token 溢出或让模型产生幻觉
（几百章的大文档）。但**逐章调用**又会让模型看不到全局结构，
跨章引用（「本节依赖第 3 章的需求说明」）几乎必然漏掉。
分块映射法两头都占：阶段一压上下文，阶段二拿全局目录做比对。

## 三条硬规矩

1. **必须给带 id 的章节清单**：真实模型不会凭空知道 `chapter_id`。
   不给清单它就会自己编（06 期 L2 联调翻车的根因）。
2. **越界即丢**：模型返回的 id 不在清单里 → **丢弃该条**，
   不静默写脏数据（与 05 的越界丢弃同一口径）。
3. **坏条目只丢该条，不整次失败**：引用关系是「建议」，
   丢掉一条比整次分析失败有用。

## AI 分析只产出「章节 → 章节」边

不产出 `entity` 边——实体名没有 id 可校验，越界无法判定。
实体边仍由人工补链负责。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.common.errors import LLMCallFailed, LLMOutputInvalid
from app.llm.json_utils import parse_llm_json
from app.llm.provider import LLMProvider
from app.llm.schemas import LLMRequest
from app.models.chapter_link import CHAPTER_LINK_TYPES
from app.models.incremental import PromptTemplate

# 引擎侧的长度上限（比 DB 列宽更严，落库时不会超列宽）
MAX_RATIONALE_LEN = 500
MAX_SUMMARY_LEN = 500
MAX_ENTITIES_PER_CHAPTER = 10
MAX_ENTITY_LEN = 64

# 全篇一次调用的字符阈值。超过则走两阶段。
FULL_DOC_THRESHOLD = 30000
# 两阶段：每块多少章
CHUNK_SIZE = 20
# 两阶段：阶段一的并发度
MAX_WORKERS = 4

# 模式标识（回传给前端，让用户知道走的哪条路）
MODE_FULL = "full"
MODE_CHUNKED = "chunked"

# 阶段一失败时的跳过原因
SKIP_BLOCK_FAILED = "block_failed"


@dataclass
class ChapterBrief:
    """一个章节的摘要卡片（阶段一的产物，阶段二的清单素材）。"""

    chapter_id: int
    title: str
    summary: str = ""
    entities: list[str] = field(default_factory=list)


@dataclass
class AnalyzeResult:
    """一次分析的引擎产出。"""

    mode: str
    chapter_count: int
    references: list[dict] = field(default_factory=list)
    discarded_count: int = 0
    briefs: list[ChapterBrief] = field(default_factory=list)
    skipped_blocks: list[dict] = field(default_factory=list)

    @property
    def analyzed_count(self) -> int:
        return len(self.references)


# ---------------------------------------------------------------- 章节处理


def flatten_chapters(chapters: list[dict]) -> list[dict]:
    """把章节树按前序展开成一维列表。"""
    flat: list[dict] = []
    for chapter in chapters:
        flat.append(chapter)
        flat.extend(flatten_chapters(chapter.get("children") or []))
    return flat


def total_content_chars(chapters: list[dict]) -> int:
    """全篇正文字符数（决定走整篇还是两阶段）。"""
    return sum(len(chapter.get("content") or "") for chapter in chapters)


def chunk_chapters(chapters: list[dict], size: int) -> list[list[dict]]:
    """按固定块数切分章节（保持前序，块内顺序不变）。"""
    if size <= 0:
        raise ValueError("chunk size 必须为正")
    return [
        chapters[start : start + size]
        for start in range(0, len(chapters), size)
    ]


# ---------------------------------------------------------------- 清单渲染


def render_chapter_briefs(briefs: list[ChapterBrief]) -> list[str]:
    """全局章节目录清单（带 id，防模型编 id）。

    形如：

    ```
    - 章节#12 2.1 登录流程
      摘要：账号密码登录后跳转首页
      实体：用户登录、登录失败
    ```
    """
    lines: list[str] = []
    for brief in briefs:
        lines.append(f"- 章节#{brief.chapter_id} {brief.title}")
        if brief.summary:
            lines.append(f"  摘要：{brief.summary}")
        if brief.entities:
            lines.append(f"  实体：{'、'.join(brief.entities)}")
    return lines


def render_chapter_list(chapters: list[dict]) -> list[str]:
    """章节清单（整篇路径用）——每章一行，带 id。"""
    return [
        f"- 章节#{chapter['id']} {chapter.get('title') or ''}".rstrip()
        for chapter in chapters
    ]


def _take_lines(lines: list[str], budget: int | None) -> tuple[list[str], int]:
    """按预算取清单的前若干行，返回 `(保留行, 实际用掉的字符数)`。

    截断**只砍清单段的尾部**——模板正文与章节正文不动。
    砍掉多少要**告诉模型**（追加一行省略说明），否则它会以为「清单就这么多」。
    """
    if budget is None:
        return list(lines), sum(len(line) + 1 for line in lines)
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
        kept.append(f"- （其余 {omitted} 行已省略）")
        used += len(kept[-1]) + 1
    return kept, used


# ---------------------------------------------------------------- Prompt


def build_full_prompt(
    template: PromptTemplate,
    *,
    document_name: str,
    version_no: int,
    chapters: list[dict],
    max_chars: int | None = None,
) -> str:
    """整篇路径的用户提示词。

    **四段固定顺序**（模板正文之外的三段）：

    1. `## 文档信息`
    2. `## 章节清单（from_chapter_id / to_chapter_id 取自这里）`
    3. `## 章节正文`

    顺序固定、清单排序稳定 → 同一份文档渲染出**逐字节相同**的 Prompt。
    超长时**只截断章节正文**，前缀保持不变。
    """
    prefix = template.user_prompt.rstrip()
    prefix += (
        "\n\n## 文档信息\n"
        f"- 文档名：{document_name}\n"
        f"- 版本：v{version_no}"
    )

    list_lines, _ = _take_lines(
        render_chapter_list(chapters),
        None if max_chars is None else int(max_chars * 0.2),
    )
    prefix += (
        "\n\n## 章节清单（from_chapter_id / to_chapter_id 取自这里）\n"
        + ("\n".join(list_lines) if list_lines else "（无）")
        + "\n\n## 章节正文\n"
    )

    body = "".join(
        f"### {chapter.get('title') or ''}（章节#{chapter['id']}）\n"
        f"{chapter.get('content') or ''}\n\n"
        for chapter in chapters
    )
    if max_chars is None or len(prefix) + len(body) <= max_chars:
        return f"{prefix}{body}"
    remaining = max(0, max_chars - len(prefix))
    return f"{prefix}{body[:remaining]}"


def build_brief_prompt(
    template: PromptTemplate,
    *,
    document_name: str,
    version_no: int,
    block: list[dict],
    max_chars: int | None = None,
) -> str:
    """阶段一（分块摘要）的用户提示词。

    问模型要的是**这一块里每章的摘要与实体**，不是引用关系——
    引用关系要等阶段二拿全局目录来判断（单块看不到全局）。
    """
    prefix = template.user_prompt.rstrip()
    prefix += (
        "\n\n## 文档信息\n"
        f"- 文档名：{document_name}\n"
        f"- 版本：v{version_no}"
        + "\n\n## 本批章节（章节编号取自这里）\n"
        + "\n".join(render_chapter_list(block))
        + "\n\n## 本批章节正文\n"
    )

    body = "".join(
        f"### {chapter.get('title') or ''}（章节#{chapter['id']}）\n"
        f"{chapter.get('content') or ''}\n\n"
        for chapter in block
    )
    if max_chars is None or len(prefix) + len(body) <= max_chars:
        return f"{prefix}{body}"
    remaining = max(0, max_chars - len(prefix))
    return f"{prefix}{body[:remaining]}"


def build_compare_prompt(
    template: PromptTemplate,
    *,
    document_name: str,
    version_no: int,
    briefs: list[ChapterBrief],
    max_chars: int | None = None,
) -> str:
    """阶段二（全局比对）的用户提示词。

    **只有全局目录清单**（每章一行：id + 标题 + 摘要 + 实体），
    没有正文——正文已在阶段一压缩成摘要了。这一步算的是
    「哪个章节引用了哪个章节」，靠的是摘要里的语义线索。
    """
    prefix = template.user_prompt.rstrip()
    prefix += (
        "\n\n## 文档信息\n"
        f"- 文档名：{document_name}\n"
        f"- 版本：v{version_no}"
        + "\n\n## 全局章节目录（from_chapter_id / to_chapter_id 取自这里）\n"
    )

    list_lines, _ = _take_lines(
        render_chapter_briefs(briefs),
        None if max_chars is None else int(max_chars * 0.6),
    )
    prefix += "\n".join(list_lines) if list_lines else "（无）"

    return f"{prefix}\n\n请基于上面的全局章节目录，判断章节之间的引用与依赖关系。"


# ---------------------------------------------------------------- 输出解析


def parse_references(
    content: str, *, chapter_ids: set[int]
) -> tuple[list[dict], int]:
    """把模型输出解析成引用边列表。

    返回 `(保留的边, 丢弃的条数)`。

    只放宽「怎么读 JSON」（复用 `parse_llm_json`），
    不放宽「根结构必须是 `{"references": [...]}`」——不是这个结构就是坏输出，
    整次失败（`LLMOutputInvalid`）。

    **逐条校验**（坏条目只丢该条，不整次失败）：

    - `from_chapter_id` / `to_chapter_id` 不在 `chapter_ids` 内 → 丢弃
      （模型编 id 的防线）；
    - `from == to`（自引用）→ 丢弃；
    - `link_type` 不在枚举内 → 丢弃；
    - `confidence` 收敛到 `[0, 1]`，转 `Decimal("0.00")`（DECIMAL(3,2) 口径）；
    - `rationale` 截断 500。
    """
    payload = parse_llm_json(content)
    if not isinstance(payload, dict):
        raise LLMOutputInvalid("模型返回不是合法的引用关系列表")
    raw_references = payload.get("references")
    if not isinstance(raw_references, list):
        raise LLMOutputInvalid("模型返回缺少 references 列表")

    references: list[dict] = []
    discarded = 0
    seen: set[tuple[int, str, int]] = set()
    for raw in raw_references:
        item = _normalize_reference(raw, chapter_ids=chapter_ids)
        if item is None:
            discarded += 1
            continue
        key = (item["from_chapter_id"], item["link_type"], item["to_chapter_id"])
        if key in seen:
            discarded += 1
            continue
        seen.add(key)
        references.append(item)
    return references, discarded


def _normalize_reference(raw: Any, *, chapter_ids: set[int]) -> dict | None:
    """校验单条引用边。结构不对的**只丢该条**。"""
    if not isinstance(raw, dict):
        return None

    from_id = _to_int(raw.get("from_chapter_id"))
    to_id = _to_int(raw.get("to_chapter_id"))
    if from_id is None or to_id is None:
        return None
    # 越界即丢：模型编的 id 一律不要
    if from_id not in chapter_ids or to_id not in chapter_ids:
        return None
    # 自引用丢弃
    if from_id == to_id:
        return None

    link_type = raw.get("link_type")
    if link_type not in CHAPTER_LINK_TYPES:
        return None

    return {
        "from_chapter_id": from_id,
        "to_chapter_id": to_id,
        "link_type": link_type,
        "confidence": _to_confidence(raw.get("confidence")),
        "rationale": _clip(raw.get("rationale"), MAX_RATIONALE_LEN),
    }


def parse_briefs(content: str) -> list[ChapterBrief]:
    """把阶段一的输出解析成章节摘要卡片。

    根结构是 `{"chapters": [{"chapter_id":1,"title":"...","summary":"...","entities":[...]}]}`。
    **结构不对的条目只丢该条**——阶段一丢一块不该让整次分析失败。
    """
    payload = parse_llm_json(content)
    if not isinstance(payload, dict):
        raise LLMOutputInvalid("模型返回不是合法的章节摘要列表")
    raw_chapters = payload.get("chapters")
    if not isinstance(raw_chapters, list):
        raise LLMOutputInvalid("模型返回缺少 chapters 列表")

    briefs: list[ChapterBrief] = []
    for raw in raw_chapters:
        if not isinstance(raw, dict):
            continue
        chapter_id = _to_int(raw.get("chapter_id"))
        if chapter_id is None:
            continue
        briefs.append(
            ChapterBrief(
                chapter_id=chapter_id,
                title=_clip(raw.get("title"), MAX_SUMMARY_LEN) or "",
                summary=_clip(raw.get("summary"), MAX_SUMMARY_LEN) or "",
                entities=_normalize_entities(raw.get("entities")),
            )
        )
    return briefs


def _normalize_entities(raw: Any) -> list[str]:
    """实体名列表。结构不对 → 空列表（不丢整条摘要）。"""
    if not isinstance(raw, list):
        return []
    entities: list[str] = []
    for item in raw:
        text = _clip(item, MAX_ENTITY_LEN)
        if not text:
            continue
        if text not in entities:
            entities.append(text)
        if len(entities) >= MAX_ENTITIES_PER_CHAPTER:
            break
    return entities


def _clip(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def _to_int(value: Any) -> int | None:
    """整数解析。`bool` 不是整数（`True` 不该被当成 1）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _to_confidence(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    number = min(1.0, max(0.0, number))
    return Decimal(f"{number:.2f}")


# ---------------------------------------------------------------- 阶段一


def _summarize_block(
    provider: LLMProvider,
    template: PromptTemplate,
    *,
    document_name: str,
    version_no: int,
    block: list[dict],
    max_chars: int | None,
) -> list[ChapterBrief]:
    """对一个块调模型拿摘要卡片。

    **失败即抛**：由调用方决定是跳过这块还是整次失败。
    """
    response = provider.chat(
        LLMRequest(
            system=template.system_prompt,
            user=build_brief_prompt(
                template,
                document_name=document_name,
                version_no=version_no,
                block=block,
                max_chars=max_chars,
            ),
        )
    )
    return parse_briefs(response.content)


def _run_stage_one(
    provider: LLMProvider,
    template: PromptTemplate,
    *,
    document_name: str,
    version_no: int,
    blocks: list[list[dict]],
    max_chars: int | None,
    max_workers: int,
) -> tuple[list[ChapterBrief], list[dict]]:
    """阶段一：并发分块摘要。

    **某块失败只跳过该块**，不整次失败（尽力而为，与 10 期
    「空章节跳过」同一哲学）。全部块都失败 → 抛 `LLMCallFailed`。

    **关于并发下的 `provider.calls`**：Mock 与真实 Provider 的 `calls`
    都是列表 append，多线程下 append 受 GIL 保护，**安全**。
    Mock 里的 `index = len(self.calls)` 存在竞态，但那只影响
    `raw["index"]` 的取值——测试断言 `calls` 的**数量与内容**，
    不断言 `index`，所以不受影响。
    """
    briefs: list[ChapterBrief] = []
    skipped: list[dict] = []
    failed_count = 0

    def _work(item: tuple[int, list[dict]]) -> tuple[int, list[ChapterBrief] | None]:
        index, block = item
        try:
            return index, _summarize_block(
                provider,
                template,
                document_name=document_name,
                version_no=version_no,
                block=block,
                max_chars=max_chars,
            )
        except LLMCallFailed:
            return index, None
        except LLMOutputInvalid:
            return index, None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(_work, list(enumerate(blocks))))

    # 按块序还原（并发完成顺序不固定，但清单顺序必须稳定 → Prompt 可复现）
    for index, block_briefs in sorted(results, key=lambda item: item[0]):
        if block_briefs is None:
            failed_count += 1
            skipped.append({"block_index": index, "reason": SKIP_BLOCK_FAILED})
            continue
        briefs.extend(block_briefs)

    if blocks and failed_count == len(blocks):
        raise LLMCallFailed("AI 分析引用关系失败：所有分块摘要都调不动模型")

    return briefs, skipped


# ---------------------------------------------------------------- 主流程


def analyze(
    *,
    provider: LLMProvider,
    template: PromptTemplate,
    document_name: str,
    version_no: int,
    chapters: list[dict],
    max_chars: int | None = None,
    full_doc_threshold: int = FULL_DOC_THRESHOLD,
    chunk_size: int = CHUNK_SIZE,
    max_workers: int = MAX_WORKERS,
) -> AnalyzeResult:
    """分析章节间的引用关系。

    - **整篇**（总正文字符数 ≤ `full_doc_threshold`）：一次调用；
    - **两阶段**（超过阈值）：并发分块摘要 → 全局目录比对。

    **签名里没有 `session`**——「引擎不碰数据库」结构上做不到。
    """
    flat = flatten_chapters(chapters)
    chapter_ids = {chapter["id"] for chapter in flat}

    if total_content_chars(flat) <= full_doc_threshold:
        response = provider.chat(
            LLMRequest(
                system=template.system_prompt,
                user=build_full_prompt(
                    template,
                    document_name=document_name,
                    version_no=version_no,
                    chapters=flat,
                    max_chars=max_chars,
                ),
            )
        )
        references, discarded = parse_references(
            response.content, chapter_ids=chapter_ids
        )
        return AnalyzeResult(
            mode=MODE_FULL,
            chapter_count=len(flat),
            references=references,
            discarded_count=discarded,
        )

    blocks = chunk_chapters(flat, chunk_size)
    briefs, skipped = _run_stage_one(
        provider,
        template,
        document_name=document_name,
        version_no=version_no,
        blocks=blocks,
        max_chars=max_chars,
        max_workers=max_workers,
    )

    response = provider.chat(
        LLMRequest(
            system=template.system_prompt,
            user=build_compare_prompt(
                template,
                document_name=document_name,
                version_no=version_no,
                briefs=briefs,
                max_chars=max_chars,
            ),
        )
    )
    references, discarded = parse_references(
        response.content, chapter_ids=chapter_ids
    )
    return AnalyzeResult(
        mode=MODE_CHUNKED,
        chapter_count=len(flat),
        references=references,
        discarded_count=discarded,
        briefs=briefs,
        skipped_blocks=skipped,
    )


__all__ = [
    "CHUNK_SIZE",
    "FULL_DOC_THRESHOLD",
    "MAX_WORKERS",
    "MODE_CHUNKED",
    "MODE_FULL",
    "SKIP_BLOCK_FAILED",
    "AnalyzeResult",
    "ChapterBrief",
    "analyze",
    "build_brief_prompt",
    "build_compare_prompt",
    "build_full_prompt",
    "chunk_chapters",
    "flatten_chapters",
    "parse_briefs",
    "parse_references",
    "render_chapter_briefs",
    "render_chapter_list",
    "total_content_chars",
]
