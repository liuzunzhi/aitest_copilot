"""功能基线的请求 / 响应模型（T56–T63）。

列表统一返回 `{items, total, page, page_size}`；写接口只接受
「业务字段」，来源追溯字段不出现在任何入参里（AC-63）。
"""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# 标签类型：新增 / 变更 / 受影响 / 无变化
LABEL_TYPES = ("new", "changed", "affected", "unchanged")

# 来源追溯字段：只读，不允许从任何写接口写入（AC-63）
TRACE_FIELDS = (
    "source_document_id",
    "source_version_id",
    "source_chapter_id",
    "source_chapter_title",
    "source_method",
    "source_analysis_id",
)

T = TypeVar("T")

# 清除原因 6 类（PRD 2.4.2「人工清除」）
CLEAR_REASONS = (
    "requirement_done",
    "requirement_cancelled",
    "misjudged",
    "priority_changed",
    "duplicate_label",
    "other",
)


class Page(BaseModel, Generic[T]):
    """列表统一分页信封。"""

    items: list[T]
    total: int
    page: int
    page_size: int


def trace_fields_in(payload: BaseModel) -> list[str]:
    """入参里出现的来源追溯字段名（AC-63）。

    写模型用 `extra="allow"`，多余字段会落在 `model_extra` 里——
    这里把它们挑出来，由服务层抛 400 `TRACE_FIELDS_READONLY`，
    而不是让 FastAPI 的默认 422 抢占语义。
    """
    extra = getattr(payload, "model_extra", None) or {}
    return [field for field in TRACE_FIELDS if field in extra]


class ModuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int = 0


class ModuleUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class ModuleOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    sort_order: int
    source_type: str
    status: str
    function_count: int = 0
    created_at: datetime


class FunctionCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    module_id: int
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)


class FunctionUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class MigrateRequest(BaseModel):
    target_module_id: int
    function_ids: list[int] = Field(min_length=1)


class FeaturePointCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)


class FeaturePointUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class LabelOut(BaseModel):
    id: int
    revision_id: int
    target_type: str
    target_id: int
    label_type: str
    status: str
    confirmed_by: int
    confirmed_at: datetime
    cleared_by: int | None = None
    cleared_at: datetime | None = None
    clear_reason: str | None = None
    clear_note: str | None = None


class LabelCreate(BaseModel):
    revision_id: int | None = None
    target_type: str = Field(pattern="^(function|feature_point)$")
    target_id: int
    label_type: str


class LabelClear(BaseModel):
    clear_reason: str | None = None
    clear_note: str | None = Field(default=None, max_length=500)


class FeaturePointOut(BaseModel):
    id: int
    function_id: int
    name: str
    description: str | None = None
    source_type: str
    status: str
    label_types: list[str] = Field(default_factory=list)
    created_at: datetime


class FunctionOut(BaseModel):
    id: int
    module_id: int
    module_name: str
    name: str
    description: str | None = None
    version_no: int
    source_type: str
    status: str
    moved_from_module_id: int | None = None
    source_document_id: int | None = None
    source_version_id: int | None = None
    source_chapter_id: int | None = None
    source_chapter_title: str | None = None
    source_method: str | None = None
    source_analysis_id: int | None = None
    label_types: list[str] = Field(default_factory=list)
    feature_point_count: int = 0
    feature_point_label_count: int = 0
    created_at: datetime


class ReviewSubmit(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


class ReviewItemDecision(BaseModel):
    """一条逐项决策。`rejected` 必须带 comment。

    枚举值故意用 `str` 而不是 `Literal`：非法值要返回 400
    `INVALID_REVIEW_ITEM` / `INVALID_REVIEW_DECISION`（AC-132 的固定校验顺序），
    用 `Literal` 会先被 Pydantic 拦成 422。
    """

    entity_type: str = Field(max_length=16)
    entity_id: int
    decision: str = Field(max_length=16)
    comment: str | None = Field(default=None, max_length=500)


class ReviewDecision(BaseModel):
    comment: str | None = Field(default=None, max_length=500)
    # 不传 items = 旧行为「全部通过」；传了 items 才按逐项决策冻结。
    items: list[ReviewItemDecision] | None = None


class ReviewDecideRequest(BaseModel):
    items: list[ReviewItemDecision] = Field(min_length=1)


class ReviewItemOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    entity_name: str
    decision: str
    comment: str | None = None
    decided_by: int | None = None
    decided_at: datetime | None = None


class ReviewStats(BaseModel):
    total: int = 0
    approved: int = 0
    rejected: int = 0
    pending: int = 0


class ReviewItemsOut(BaseModel):
    revision_id: int
    round_id: int
    round_no: int
    status: str
    items: list[ReviewItemOut] = Field(default_factory=list)
    stats: ReviewStats


class ReviewTreeNode(BaseModel):
    entity_type: str
    entity_id: int
    name: str
    description: str | None = None
    source_type: str | None = None
    version_no: int | None = None
    decision: str = "pending"
    comment: str | None = None
    children: list["ReviewTreeNode"] = Field(default_factory=list)


ReviewTreeNode.model_rebuild()


class ReviewTreeOut(BaseModel):
    revision_id: int
    round_id: int
    round_no: int
    status: str
    tree: list[ReviewTreeNode] = Field(default_factory=list)
    stats: ReviewStats


class ReviewDecideOut(BaseModel):
    updated: int
    stats: ReviewStats


class RevisionOut(BaseModel):
    id: int
    version_no: int | None = None
    status: str
    module_count: int
    function_count: int
    feature_point_count: int
    label_count: int
    submitted_by: int | None = None
    submitted_at: datetime | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    created_at: datetime


class RevisionDetail(RevisionOut):
    # 冻结的结构树：模块 → 功能 → 功能点
    structure: list[dict] | None = None


class RetentionUpdate(BaseModel):
    max_count: int | None = Field(default=None, ge=0)


class RetentionOut(BaseModel):
    max_count: int | None = None
    enabled: bool = False
    snapshot_count: int = 0
    keep_count: int | None = None
    candidates: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DeleteResponse(BaseModel):
    deleted: bool = True
    warning: str | None = None
    cleared_label_count: int = 0


# ------------------------------------------------- 从文档推导基线（T90）


class DeriveRunRequest(BaseModel):
    document_id: int
    document_version_id: int
    template_id: int


class DeriveStats(BaseModel):
    chapter_count: int = 0
    processed_count: int = 0
    candidate_count: int = 0
    module_count: int = 0
    function_count: int = 0
    feature_point_count: int = 0
    skipped_chapters: list[dict] = Field(default_factory=list)


class DeriveOut(BaseModel):
    id: int
    provider: str
    status: str
    document_id: int
    document_version_id: int
    template_id: int
    stats: DeriveStats | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class DeriveCandidateOut(BaseModel):
    id: int
    parent_id: int | None = None
    entity_type: str
    name: str
    description: str | None = None
    source_chapter_title: str | None = None
    confidence: float | None = None
    rationale: str | None = None
    status: str
    # 空子列表不返回（spec §5.2：前端渲染更简单）
    children: list["DeriveCandidateOut"] | None = None


DeriveCandidateOut.model_rebuild()


class DeriveDetailOut(DeriveOut):
    document_name: str | None = None
    candidates: list[DeriveCandidateOut] = Field(default_factory=list)


class AdoptItem(BaseModel):
    candidate_id: int
    action: str = Field(pattern="^(reuse|create|skip)$")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    existing_entity_id: int | None = None


class AdoptRequest(BaseModel):
    candidates: list[AdoptItem] = Field(min_length=1)


class AdoptCounts(BaseModel):
    modules: int = 0
    functions: int = 0
    feature_points: int = 0


class AdoptItemResult(BaseModel):
    candidate_id: int
    entity_type: str
    entity_id: int | None = None
    name: str
    action: str


class AdoptOut(BaseModel):
    derive_id: int
    adopted_count: int
    created: AdoptCounts
    reused: AdoptCounts
    skipped: AdoptCounts
    items: list[AdoptItemResult] = Field(default_factory=list)
