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


class ReviewDecision(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


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
