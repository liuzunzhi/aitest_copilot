"""从文档反推流程基线场景的引擎（10-process-baseline T119）。

**纯函数 + provider 注入**：不查默认配置、不建记录、不落库。
服务层负责校验、取章节、组清单，把结果交给用户勾选后走 `POST /scenarios` 采纳。

**签名里没有 `session`**——「反推只出草案不写表」从「靠自觉」变成
「结构上做不到」（spec §5.4）。

与 04 的 `app/baselines/derive.py` 同构，但有四点差异（plan §4.1）：

1. **输出根结构**是 `{"scenarios": [...]}`——**平铺列表**，不是三级树
   （流程基线是场景列表，没有层级）。
2. **「已有清单」段给两样东西**：已有流程基线场景名清单（防重复抽取）
   与可关联的功能基线清单（**带 id**）。第二份**不能省**——06 期 L2 联调
   翻车就是因为没给清单，模型自己编 `target_id=1`。
3. **合并策略**：同名场景按名字合并，**步骤保留首次出现**（不追加）——
   步骤是有序列表，追加会重复。
4. **落库方式**：引擎只出候选，响应直接返回；用户勾选后走 `POST /scenarios`
   批量采纳（**不造候选表**）。

长度上限是**引擎口径**（比库更严）：场景名 128 / 描述 500 / 前置条件 1000 /
理由 1000 / `action` 与 `expected` 各 1000。
注意 `service.py` 里另有一套 `MAX_NAME_LEN=255`（DB 列宽）——**不要互相 import**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.common.errors import LLMOutputInvalid
from app.incremental.context import BASELINE_BRIEF_MAX_RATIO
from app.llm.json_utils import parse_llm_json
from app.llm.provider import LLMProvider
from app.llm.schemas import LLMRequest
from app.models.incremental import PromptTemplate
from app.models.process_baseline import TARGET_TYPES

# 引擎侧的长度上限（比 DB 列宽更严，采纳时不会超列宽）
MAX_NAME_LEN = 128
MAX_DESCRIPTION_LEN = 500
MAX_PRECONDITION_LEN = 1000
MAX_RATIONALE_LEN = 1000
MAX_TEXT_LEN = 1000

EMPTY_CHAPTER_REASON = "empty_content"
NO_STRUCTURE_REASON = "no_structured_content"

# 两份清单里「已有场景清单」占清单预算的比例，剩下的留给「可关联目标清单」——
# 后者是模型产出关联的依据，砍光了模型只能瞎猜 id。
EXISTING_SCENARIO_RATIO = 0.4


@dataclass
class CandidateScenario:
    """候选场景（尚未落库）。

    `steps` 是 `(action, expected)` 的有序列表；`links` 是关联建议
    （`target_type` / `target_id` / `target_name`）。
    """

    name: str
    description: str | None = None
    precondition: str | None = None
    confidence: Decimal | None = None
    rationale: str | None = None
    source_chapter_id: int | None = None
    source_chapter_title: str | None = None
    steps: list[tuple[str, str]] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)


@dataclass
class DeriveResult:
    """一次推导的引擎产出。"""

    chapter_count: int
    processed_count: int
    skipped_chapters: list[dict]
    scenarios: list[CandidateScenario]

    @property
    def candidate_count(self) -> int:
        return len(self.scenarios)


def flatten_chapters(chapters: list[dict]) -> list[dict]:
    """把章节树按前序展开成一维列表。"""
    flat: list[dict] = []
    for chapter in chapters:
        flat.append(chapter)
        flat.extend(flatten_chapters(chapter.get("children") or []))
    return flat


# ---------------------------------------------------------------- 清单渲染


def _render_existing_scenarios(existing_scenarios: list[str]) -> list[str]:
    """已有流程基线场景的**名称**清单（防重复抽取）。

    只给名称、不给 id：这份清单的用途是告诉模型「这些已经存在」。
    """
    return [f"- 场景：{name}" for name in existing_scenarios]


def _render_linkable_targets(linkable_targets: list[dict]) -> list[str]:
    """可关联的功能基线目标清单（**带 id**）。

    形如：

    ```
    - 模块：登录模块
      - 功能#12 用户扫码登录
        - 功能点#13 展示扫码二维码
    ```

    **id 必须出现**：模型要产出关联就得知道有哪些目标可选、id 是多少。
    不给清单它就会自己编 `target_id=1`（06 期的教训）。

    按模块**分组**渲染（模块头只出现一次）——功能 id 是全局自增的，
    同一模块的功能不一定连号，不分组会出现重复的模块头。
    """
    groups: dict[str, list[dict]] = {}
    for row in linkable_targets:
        module_name = (row.get("module_name") or "").strip()
        groups.setdefault(module_name, []).append(row)

    lines: list[str] = []
    for module_name, rows in groups.items():
        if module_name:
            lines.append(f"- 模块：{module_name}")
        for row in rows:
            label = "功能" if row.get("target_type") == "function" else "功能点"
            lines.append(
                f"  - {label}#{row.get('target_id')} {row.get('target_name') or ''}".rstrip()
            )
    return lines


def _take_lines(lines: list[str], budget: int | None) -> tuple[list[str], int]:
    """按预算取清单的前若干行，返回 `(保留行, 实际用掉的字符数)`。

    截断**只砍清单段的尾部**——模板正文与章节正文不动（spec §3.10）。
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


def build_user_prompt(
    template: PromptTemplate,
    *,
    document_name: str,
    version_no: int,
    existing_scenarios: list[str],
    linkable_targets: list[dict],
    chapter_title: str,
    chapter_content: str,
    max_chars: int | None = None,
) -> str:
    """组装用户提示词。

    **四段固定顺序**（模板正文之外的四段）：

    1. `## 文档信息`
    2. `## 已有流程基线场景（避免重复抽取）`
    3. `## 可关联的功能基线目标（target_id 取自这里）`
    4. `## 章节：{title}`

    顺序固定、清单排序稳定 → 同一份文档渲染出**逐字节相同**的 Prompt。
    超长时**只截断章节正文**，前缀保持不变。
    """
    prefix = template.user_prompt.rstrip()
    prefix += (
        "\n\n## 文档信息\n"
        f"- 文档名：{document_name}\n"
        f"- 版本：v{version_no}"
    )

    brief_budget = (
        None if max_chars is None else int(max_chars * BASELINE_BRIEF_MAX_RATIO)
    )
    existing_budget = (
        None
        if brief_budget is None
        else int(brief_budget * EXISTING_SCENARIO_RATIO)
    )
    existing_lines, existing_used = _take_lines(
        _render_existing_scenarios(existing_scenarios), existing_budget
    )
    target_budget = (
        None if brief_budget is None else max(0, brief_budget - existing_used)
    )
    target_lines, _ = _take_lines(
        _render_linkable_targets(linkable_targets), target_budget
    )

    existing_text = "\n".join(existing_lines) if existing_lines else "（无）"
    target_text = "\n".join(target_lines) if target_lines else "（无）"
    prefix += (
        "\n\n## 已有流程基线场景（避免重复抽取）\n"
        f"{existing_text}"
        "\n\n## 可关联的功能基线目标（target_id 取自这里）\n"
        f"{target_text}"
        f"\n\n## 章节：{chapter_title}\n"
    )
    if max_chars is None or len(prefix) + len(chapter_content) <= max_chars:
        return f"{prefix}{chapter_content}"
    remaining = max(0, max_chars - len(prefix))
    return f"{prefix}{chapter_content[:remaining]}"


# ---------------------------------------------------------------- 输出解析


def parse_scenarios(
    content: str, *, linkable_targets: list[dict] | None = None
) -> list[dict]:
    """把模型输出解析成场景列表。

    只放宽「怎么读 JSON」（复用 `parse_llm_json`），
    不放宽「根结构必须是 `{"scenarios": [...]}`」——不是这个结构就是坏输出，
    整次失败（`LLMOutputInvalid`）。

    给了 `linkable_targets` 时：**越界的 `target_id` 只丢该条关联**，
    候选与其步骤照常返回（本期新增，04 没有关联概念）。
    """
    payload = parse_llm_json(content)
    if not isinstance(payload, dict):
        raise LLMOutputInvalid("模型返回不是合法的推导结果")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list):
        raise LLMOutputInvalid("模型返回缺少 scenarios 列表")

    index = None if linkable_targets is None else _linkable_index(linkable_targets)

    normalized: list[dict] = []
    for raw in scenarios:
        item = _normalize_scenario(raw)
        if item is None:
            continue
        if index is not None:
            item["links"] = [
                link
                for link in item["links"]
                if (link["target_type"], link["target_id"]) in index
            ]
            for link in item["links"]:
                link["target_name"] = index[(link["target_type"], link["target_id"])]
        normalized.append(item)
    return normalized


def _linkable_index(linkable_targets: list[dict]) -> dict[tuple[str, int], str]:
    """可关联目标索引：`(target_type, target_id)` → 真实名称。"""
    index: dict[tuple[str, int], str] = {}
    for row in linkable_targets:
        target_type = row.get("target_type")
        target_id = row.get("target_id")
        if target_type not in TARGET_TYPES:
            continue
        if not isinstance(target_id, int) or isinstance(target_id, bool):
            continue
        index[(target_type, target_id)] = row.get("target_name") or ""
    return index


def _normalize_scenario(raw: Any) -> dict | None:
    """校验单个候选。名字为空 / 超长 → 丢弃该候选，不失败。

    「建议」不是「结论」——丢掉一个坏候选比整次失败有用。
    """
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name or len(name) > MAX_NAME_LEN:
        return None

    return {
        "name": name,
        "description": _clip(raw.get("description"), MAX_DESCRIPTION_LEN),
        "precondition": _clip(raw.get("precondition"), MAX_PRECONDITION_LEN),
        "confidence": _to_confidence(raw.get("confidence")),
        "rationale": _clip(raw.get("rationale"), MAX_RATIONALE_LEN),
        "steps": _normalize_steps(raw.get("steps")),
        "links": _normalize_links(raw.get("links")),
    }


def _normalize_steps(raw: Any) -> list[tuple[str, str]]:
    """步骤列表。`action` 为空的步骤**只丢该步骤**——候选与其余步骤保留。"""
    if not isinstance(raw, list):
        return []
    steps: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        action = _clip(item.get("action"), MAX_TEXT_LEN)
        if not action:
            continue
        expected = _clip(item.get("expected"), MAX_TEXT_LEN) or ""
        steps.append((action, expected))
    return steps


def _normalize_links(raw: Any) -> list[dict]:
    """关联建议。结构不对的条目**只丢该条关联**。"""
    if not isinstance(raw, list):
        return []
    links: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        target_type = item.get("target_type")
        if target_type not in TARGET_TYPES:
            continue
        target_id = item.get("target_id")
        if not isinstance(target_id, int) or isinstance(target_id, bool):
            continue
        if target_id <= 0:
            continue
        links.append(
            {
                "target_type": target_type,
                "target_id": target_id,
                "target_name": (item.get("target_name") or "").strip(),
            }
        )
    return links


def _clip(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def _to_confidence(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    number = min(1.0, max(0.0, number))
    return Decimal(f"{number:.2f}")


# ---------------------------------------------------------------- 合并


class _MergedScenarioMerger:
    """跨章节合并器：同名场景只留一条。

    - **步骤保留首次出现**（不追加）——步骤是有序列表，追加会重复；
    - **关联取并集**（按 `(target_type, target_id)` 去重）——关联是「这个场景
      覆盖了哪些目标」的集合，不是有序列表，跨章节的关联不该互相覆盖掉；
    - `source_chapter_id` / `source_chapter_title` 取**第一次出现**；
    - 其余字段只补空缺（与 04 的 `_fill_missing` 同一思路）。
    """

    def __init__(self) -> None:
        self.scenarios: dict[str, CandidateScenario] = {}

    def add(
        self,
        scenarios: list[dict],
        *,
        chapter_id: int | None,
        chapter_title: str | None,
    ) -> None:
        for raw in scenarios:
            scenario = self.scenarios.get(raw["name"])
            if scenario is None:
                self.scenarios[raw["name"]] = CandidateScenario(
                    name=raw["name"],
                    description=raw["description"],
                    precondition=raw["precondition"],
                    confidence=raw["confidence"],
                    rationale=raw["rationale"],
                    source_chapter_id=chapter_id,
                    source_chapter_title=chapter_title,
                    steps=list(raw["steps"]),
                    links=list(raw["links"]),
                )
                continue
            _fill_missing(scenario, raw)
            if not scenario.steps and raw["steps"]:
                scenario.steps = list(raw["steps"])
            known = {
                (link["target_type"], link["target_id"]) for link in scenario.links
            }
            for link in raw["links"]:
                key = (link["target_type"], link["target_id"])
                if key in known:
                    continue
                known.add(key)
                scenario.links.append(link)

    def to_list(self) -> list[CandidateScenario]:
        return list(self.scenarios.values())


def _fill_missing(scenario: CandidateScenario, raw: dict) -> None:
    """合并时只补空缺，不改已有值——第一次出现的内容优先。"""
    if scenario.description is None:
        scenario.description = raw["description"]
    if scenario.precondition is None:
        scenario.precondition = raw["precondition"]
    if scenario.confidence is None:
        scenario.confidence = raw["confidence"]
    if scenario.rationale is None:
        scenario.rationale = raw["rationale"]


# ---------------------------------------------------------------- 主流程


def run_derive(
    *,
    provider: LLMProvider,
    template: PromptTemplate,
    document_name: str,
    version_no: int,
    chapters: list[dict],
    existing_scenarios: list[str],
    linkable_targets: list[dict],
    max_chars: int | None = None,
) -> DeriveResult:
    """逐章节调用模型并合并候选。

    - `char_count == 0` 的章节**不调模型**，记 `empty_content`；
    - 模型返回 `{"scenarios": []}` 不算失败，记 `no_structured_content`；
    - 坏 JSON / 根结构不对 → `LLMOutputInvalid` 向上抛，整次失败。

    **签名里没有 `session`**——「反推只出草案不写表」结构上做不到。
    """
    flat = flatten_chapters(chapters)
    merger = _MergedScenarioMerger()
    skipped: list[dict] = []
    processed = 0

    for chapter in flat:
        content = chapter.get("content") or ""
        if not chapter.get("char_count") or not content.strip():
            skipped.append(
                {"chapter_id": chapter["id"], "reason": EMPTY_CHAPTER_REASON}
            )
            continue

        response = provider.chat(
            LLMRequest(
                system=template.system_prompt,
                user=build_user_prompt(
                    template,
                    document_name=document_name,
                    version_no=version_no,
                    existing_scenarios=existing_scenarios,
                    linkable_targets=linkable_targets,
                    chapter_title=chapter["title"],
                    chapter_content=content,
                    max_chars=max_chars,
                ),
            )
        )
        processed += 1
        scenarios = parse_scenarios(
            response.content, linkable_targets=linkable_targets
        )
        if not scenarios:
            skipped.append(
                {"chapter_id": chapter["id"], "reason": NO_STRUCTURE_REASON}
            )
            continue
        merger.add(
            scenarios,
            chapter_id=chapter["id"],
            chapter_title=chapter["title"],
        )

    return DeriveResult(
        chapter_count=len(flat),
        processed_count=processed,
        skipped_chapters=skipped,
        scenarios=merger.to_list(),
    )


__all__ = [
    "EMPTY_CHAPTER_REASON",
    "NO_STRUCTURE_REASON",
    "CandidateScenario",
    "DeriveResult",
    "build_user_prompt",
    "flatten_chapters",
    "parse_scenarios",
    "run_derive",
]
