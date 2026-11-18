"""从文档推导基线的引擎（T89）。

**纯逻辑 + provider 注入**：不查默认配置、不建记录、不落库。
服务层负责校验、建 `baseline_derives`、把结果写进候选表。

三件事：

1. **Prompt 组装**：模板正文 + 文档信息 + 已有基线结构 + 章节正文。
   已有结构这一段不能省——不给它，模型每次把整份文档重新抽一遍，
   多次推导会产生大量重复候选。
2. **输出校验**：根结构必须是 `{"modules": [...]}`，坏 JSON 整次失败；
   单个候选名字为空 / 超长只丢弃该候选，不失败（这是"建议"不是"结论"）。
3. **跨章节合并**：同名模块 / 功能 / 功能点按名字合并，
   `source_chapter_id` 取第一次出现的章节——不合并必然撞结构表唯一索引。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.errors import LLMOutputInvalid
from app.incremental.context import BASELINE_BRIEF_MAX_RATIO
from app.llm.json_utils import parse_llm_json
from app.llm.provider import LLMProvider
from app.llm.schemas import LLMRequest
from app.models.baseline import BaselineFeaturePoint, BaselineFunction, BaselineModule
from app.models.incremental import PromptTemplate

MAX_NAME_LEN = 128
MAX_DESCRIPTION_LEN = 500
MAX_RATIONALE_LEN = 1000

EMPTY_CHAPTER_REASON = "empty_content"
NO_STRUCTURE_REASON = "no_structured_content"


@dataclass
class CandidateNode:
    """候选树节点。落库时由服务层递归展开。"""

    entity_type: str
    name: str
    description: str | None = None
    confidence: Decimal | None = None
    rationale: str | None = None
    source_chapter_id: int | None = None
    source_chapter_title: str | None = None
    children: list["CandidateNode"] = field(default_factory=list)


@dataclass
class DeriveResult:
    """一次推导的引擎产出。"""

    chapter_count: int
    processed_count: int
    skipped_chapters: list[dict]
    modules: list[CandidateNode]

    @property
    def module_count(self) -> int:
        return len(self.modules)

    @property
    def function_count(self) -> int:
        return sum(len(module.children) for module in self.modules)

    @property
    def feature_point_count(self) -> int:
        return sum(
            len(function.children)
            for module in self.modules
            for function in module.children
        )


def flatten_chapters(chapters: list[dict]) -> list[dict]:
    """把章节树按前序展开成一维列表。"""
    flat: list[dict] = []
    for chapter in chapters:
        flat.append(chapter)
        flat.extend(flatten_chapters(chapter.get("children") or []))
    return flat


def render_existing_brief(
    session: Session, *, project_id: int, max_chars: int | None = None
) -> str:
    """当前结构的名称清单，给模型「避免重复抽取」用。

    只给名称、不给 id：这份清单的用途是告诉模型"这些已经存在"，
    不是让它产出可落库的引用。排序稳定，保证同一份 Prompt 可复现。
    """
    modules = session.scalars(
        select(BaselineModule)
        .where(
            BaselineModule.project_id == project_id,
            BaselineModule.status == "active",
        )
        .order_by(BaselineModule.sort_order, BaselineModule.id)
    ).all()
    if not modules:
        return "（无）"

    module_ids = [module.id for module in modules]
    functions = session.scalars(
        select(BaselineFunction)
        .where(
            BaselineFunction.project_id == project_id,
            BaselineFunction.status == "active",
            BaselineFunction.module_id.in_(module_ids),
        )
        .order_by(BaselineFunction.id)
    ).all()
    points_by_function: dict[int, list[str]] = {}
    if functions:
        points = session.scalars(
            select(BaselineFeaturePoint)
            .where(
                BaselineFeaturePoint.project_id == project_id,
                BaselineFeaturePoint.status == "active",
                BaselineFeaturePoint.function_id.in_([f.id for f in functions]),
            )
            .order_by(BaselineFeaturePoint.id)
        ).all()
        for point in points:
            points_by_function.setdefault(point.function_id, []).append(point.name)

    functions_by_module: dict[int, list[BaselineFunction]] = {}
    for function in functions:
        functions_by_module.setdefault(function.module_id, []).append(function)

    lines: list[str] = []
    for module in modules:
        lines.append(f"- 模块：{module.name}")
        for function in functions_by_module.get(module.id, []):
            point_names = points_by_function.get(function.id, [])
            suffix = f"（功能点：{'、'.join(point_names)}）" if point_names else ""
            lines.append(f"  - 功能：{function.name}{suffix}")

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
            kept.append(f"- （其余 {omitted} 行已有结构已省略）")
        lines = kept

    return "\n".join(lines)


def build_user_prompt(
    template: PromptTemplate,
    *,
    document_name: str,
    version_no: int,
    existing_brief: str,
    chapter_title: str,
    chapter_content: str,
    max_chars: int | None = None,
) -> str:
    """组装用户提示词。超长时**只截断章节正文**，前缀保持不变。"""
    prefix = template.user_prompt.rstrip()
    prefix += (
        "\n\n## 文档信息\n"
        f"- 文档名：{document_name}\n"
        f"- 版本：v{version_no}"
        "\n\n## 已有基线结构（避免重复抽取）\n"
        f"{existing_brief}"
        f"\n\n## 章节：{chapter_title}\n"
    )
    if max_chars is None or len(prefix) + len(chapter_content) <= max_chars:
        return f"{prefix}{chapter_content}"
    remaining = max(0, max_chars - len(prefix))
    return f"{prefix}{chapter_content[:remaining]}"


def parse_modules(content: str) -> list[dict]:
    """把模型输出解析成模块列表。

    只放宽"怎么读 JSON"（复用 `parse_llm_json`），
    不放宽"根结构必须是 `{modules: [...]}`"——不是这个结构就是坏输出。
    """
    payload = parse_llm_json(content)
    if not isinstance(payload, dict):
        raise LLMOutputInvalid("模型返回不是合法的推导结果")
    modules = payload.get("modules")
    if not isinstance(modules, list):
        raise LLMOutputInvalid("模型返回缺少 modules 列表")

    normalized: list[dict] = []
    for module in modules:
        node = _normalize_node(module, "module")
        if node is None:
            continue
        node["functions"] = _normalize_children(module.get("functions"), "function")
        normalized.append(node)
    return normalized


def _normalize_children(raw: Any, child_type: str) -> list[dict]:
    if not isinstance(raw, list):
        return []
    children: list[dict] = []
    for item in raw:
        node = _normalize_node(item, child_type)
        if node is None:
            continue
        if child_type == "function":
            node["feature_points"] = _normalize_children(
                item.get("feature_points"), "feature_point"
            )
        children.append(node)
    return children


def _normalize_node(raw: Any, entity_type: str) -> dict | None:
    """校验单个候选。名字为空 / 超长 → 丢弃该候选，不失败。"""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name or len(name) > MAX_NAME_LEN:
        return None

    description = _clip(raw.get("description"), MAX_DESCRIPTION_LEN)
    rationale = _clip(raw.get("rationale"), MAX_RATIONALE_LEN)
    return {
        "entity_type": entity_type,
        "name": name,
        "description": description,
        "confidence": _to_confidence(raw.get("confidence")),
        "rationale": rationale,
    }


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


class _MergedTree:
    """跨章节合并器：同名模块 / 功能 / 功能点只留一条。"""

    def __init__(self) -> None:
        self.modules: dict[str, CandidateNode] = {}

    def add(
        self,
        modules: list[dict],
        *,
        chapter_id: int | None,
        chapter_title: str | None,
    ) -> None:
        for raw in modules:
            module = self.modules.get(raw["name"])
            if module is None:
                module = CandidateNode(
                    entity_type="module",
                    name=raw["name"],
                    description=raw["description"],
                    confidence=raw["confidence"],
                    rationale=raw["rationale"],
                    source_chapter_id=chapter_id,
                    source_chapter_title=chapter_title,
                )
                self.modules[raw["name"]] = module
            else:
                _fill_missing(module, raw)

            functions = {child.name: child for child in module.children}
            for raw_function in raw["functions"]:
                function = functions.get(raw_function["name"])
                if function is None:
                    function = CandidateNode(
                        entity_type="function",
                        name=raw_function["name"],
                        description=raw_function["description"],
                        confidence=raw_function["confidence"],
                        rationale=raw_function["rationale"],
                        source_chapter_id=chapter_id,
                        source_chapter_title=chapter_title,
                    )
                    module.children.append(function)
                    functions[function.name] = function
                else:
                    _fill_missing(function, raw_function)

                points = {child.name for child in function.children}
                for raw_point in raw_function.get("feature_points") or []:
                    if raw_point["name"] in points:
                        continue
                    function.children.append(
                        CandidateNode(
                            entity_type="feature_point",
                            name=raw_point["name"],
                            description=raw_point["description"],
                            confidence=raw_point["confidence"],
                            rationale=raw_point["rationale"],
                            source_chapter_id=chapter_id,
                            source_chapter_title=chapter_title,
                        )
                    )
                    points.add(raw_point["name"])

    def to_list(self) -> list[CandidateNode]:
        return list(self.modules.values())


def _fill_missing(node: CandidateNode, raw: dict) -> None:
    """合并时只补空缺，不改已有值——第一次出现的内容优先。"""
    if node.description is None:
        node.description = raw["description"]
    if node.confidence is None:
        node.confidence = raw["confidence"]
    if node.rationale is None:
        node.rationale = raw["rationale"]


def run_derive(
    *,
    provider: LLMProvider,
    template: PromptTemplate,
    document_name: str,
    version_no: int,
    chapters: list[dict],
    existing_brief: str,
    max_chars: int | None = None,
) -> DeriveResult:
    """逐章节调用模型并合并候选。

    - `char_count == 0` 的章节**不调模型**，记 `empty_content`；
    - 模型返回 `{"modules": []}` 不算失败，记 `no_structured_content`；
    - 坏 JSON / 根结构不对 → `LLMOutputInvalid` 向上抛，由服务层整次置 failed。
    """
    flat = flatten_chapters(chapters)
    tree = _MergedTree()
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
                    existing_brief=existing_brief,
                    chapter_title=chapter["title"],
                    chapter_content=content,
                    max_chars=max_chars,
                ),
            )
        )
        processed += 1
        modules = parse_modules(response.content)
        if not modules:
            skipped.append(
                {"chapter_id": chapter["id"], "reason": NO_STRUCTURE_REASON}
            )
            continue
        tree.add(
            modules,
            chapter_id=chapter["id"],
            chapter_title=chapter["title"],
        )

    return DeriveResult(
        chapter_count=len(flat),
        processed_count=processed,
        skipped_chapters=skipped,
        modules=tree.to_list(),
    )


__all__ = [
    "CandidateNode",
    "DeriveResult",
    "EMPTY_CHAPTER_REASON",
    "NO_STRUCTURE_REASON",
    "build_user_prompt",
    "flatten_chapters",
    "parse_modules",
    "render_existing_brief",
    "run_derive",
]
