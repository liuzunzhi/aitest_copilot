"""测试点分析的请求 / 响应模型。

列表统一复用 `app.baselines.schemas.Page`，不另写一份分页信封。

**枚举字段一律用 `str` 不用 `Literal`**（与 `app/incremental/schemas.py` 同款）：
非法值走服务层 400（`TEST_POINT_INVALID` / `TEST_POINT_TEMPLATE_INVALID`），
而不是 pydantic 的 422——spec 要求的是稳定错误码，不是 pydantic 的默认行为。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.baselines.schemas import Page

__all__ = [
    "AnalysisCreate",
    "AnalysisDetailOut",
    "AnalysisOut",
    "Page",
    "PointCreate",
    "PointOut",
    "PointUpdate",
    "ReviewRequest",
]


class AnalysisCreate(BaseModel):
    """发起生成。

    `analysis_id` 与 `baseline_revision_id` **至少给一个**——
    两个都给则取交集。`chapter_ids` 为空表示全文档。
    """

    template_id: int
    analysis_id: int | None = None
    baseline_revision_id: int | None = None
    document_id: int | None = None
    document_version_id: int | None = None
    chapter_ids: list[int] | None = None


class AnalysisOut(BaseModel):
    """生成记录。附带业务标识，前端不用为一条记录再查多个接口。"""

    id: int
    project_id: int
    template_id: int
    template_name: str | None = None
    template_version: int
    provider: str
    analysis_id: int | None = None
    baseline_revision_id: int | None = None
    document_id: int | None = None
    document_name: str | None = None
    document_version_id: int | None = None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    stats: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int
    created_at: datetime


class AnalysisDetailOut(AnalysisOut):
    """生成记录详情：带上这次产出的测试点。

    响应直接带候选列表——前端不用再发一次 GET。
    """

    points: list["PointOut"] = Field(default_factory=list)


class PointOut(BaseModel):
    """一条测试点。

    `target_name` / `chapter_title` 是落库快照——目标或章节后来改名、
    被删，历史测试点仍然对得上原文。
    `needs_review` 标「依赖的标签已被清除，请复核」。
    """

    id: int
    project_id: int
    analysis_id: int | None = None
    name: str
    target_type: str
    target_id: int
    target_name: str
    priority: str
    precondition: str | None = None
    verification: str | None = None
    chapter_id: int | None = None
    chapter_title: str | None = None
    source_label_id: int | None = None
    source_conclusion_id: int | None = None
    status: str
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    needs_review: bool = False
    needs_review_reason: str | None = None
    needs_review_at: datetime | None = None
    source_type: str
    created_by: int
    created_at: datetime
    updated_at: datetime


class PointCreate(BaseModel):
    """手工新增测试点。

    `target_type` / `target_id` 必填——测试点必须挂到某个功能或功能点上，
    否则既不可追溯，也无法参与 08 期的用例生成。
    """

    name: str
    target_type: str
    target_id: int
    priority: str = "medium"
    precondition: str | None = None
    verification: str | None = None
    chapter_id: int | None = None


class PointUpdate(BaseModel):
    """手工改测试点。

    **只接受这 4 个字段**——目标 / 状态 / 来源都不该手工改。
    传了别的字段 → 400 `TEST_POINT_INVALID`（校验在服务层）。

    `extra="allow"`：**多余字段要活到服务层**才能被判 400。
    pydantic 默认的 `ignore` 会在校验阶段就把它们**悄悄丢掉**，
    接口会返回 200 —— 用户以为改了，其实什么都没改。
    （`forbid` 更糟：会变成 422，而 spec 要求的是 400。）
    """

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    priority: str | None = None
    precondition: str | None = None
    verification: str | None = None


class ReviewRequest(BaseModel):
    """评审入参。`action` 只允许 approve / reject，校验在服务层。"""

    action: str
    comment: str | None = None


AnalysisDetailOut.model_rebuild()
