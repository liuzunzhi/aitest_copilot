"""增量分析的请求 / 响应模型。

列表统一复用 `app.baselines.schemas.Page`，不另写一份分页信封。
`AnalysisOut` 带业务可读标识（基线版本号、文档版本号、模板名），
避免前端为了一条记录再查多个接口。
"""

from datetime import datetime

from pydantic import BaseModel

from app.baselines.schemas import Page

__all__ = [
    "AnalysisCreate",
    "AnalysisOut",
    "ChapterLinkCreate",
    "ChapterLinkOut",
    "ConclusionOut",
    "ConflictOut",
    "ConflictResolve",
    "DecisionOut",
    "Page",
]


class AnalysisCreate(BaseModel):
    """发起分析。`document_id` 由文档版本反查，不接受前端传入。"""

    template_id: int
    baseline_revision_id: int | None = None
    document_version_id: int
    split_granularity: str | None = None


class AnalysisOut(BaseModel):
    """分析记录。附带业务标识，前端不用为一条记录再查多个接口。"""

    id: int
    project_id: int
    template_id: int
    template_name: str | None = None
    template_version: int
    provider: str
    baseline_revision_id: int
    baseline_revision_version: str | None = None
    document_id: int
    document_name: str | None = None
    document_version_id: int
    document_version_no: int | None = None
    split_granularity: str
    status: str
    error_code: str | None = None
    error_message: str | None = None
    stats: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # ---- 第二遍（第二期）。NULL 表示未执行，不是失败 ----
    second_pass_template_id: int | None = None
    second_pass_status: str | None = None
    second_pass_stats: dict | None = None
    second_pass_error_code: str | None = None
    second_pass_error_message: str | None = None
    second_pass_started_at: datetime | None = None
    second_pass_finished_at: datetime | None = None
    created_by: int
    created_at: datetime


class ConclusionOut(BaseModel):
    """第一遍局部结论。`label_type` 不含 `new`。"""

    id: int
    analysis_id: int
    chapter_id: int
    chapter_title: str
    target_type: str
    target_id: int
    label_type: str
    confidence: float | None = None
    rationale: str | None = None
    created_at: datetime


class ChapterLinkCreate(BaseModel):
    """手动补链。`to_chapter_id` 与 `entity` 二选一，校验在服务层做。

    这里刻意不用 `Literal` / 自定义校验器：spec 要求非法输入返回 400
    `INVALID_CHAPTER_LINK`，而 pydantic 校验失败会变成 422。
    """

    from_chapter_id: int
    link_type: str
    to_chapter_id: int | None = None
    entity: str | None = None


class ChapterLinkOut(BaseModel):
    """章节引用图的一条边，附带两端章节标题。"""

    id: int
    version_id: int
    from_chapter_id: int
    from_chapter_title: str | None = None
    to_chapter_id: int | None = None
    to_chapter_title: str | None = None
    link_type: str
    entity: str | None = None
    confidence: float | None = None
    source: str
    created_by: int
    created_at: datetime


class DecisionOut(BaseModel):
    """第二遍无争议裁决。`decision` 不含 `new`。"""

    id: int
    analysis_id: int
    target_type: str
    target_id: int
    target_name: str
    decision: str
    confidence: float | None = None
    rationale: str | None = None
    evidence: dict | None = None
    created_at: datetime


class ConflictOut(BaseModel):
    """待人工裁决项：冲突 / 可能连带变更 / 新增。"""

    id: int
    analysis_id: int
    target_type: str
    target_id: int | None = None
    target_name: str
    conflict_type: str
    candidates: list
    status: str
    resolved_label_type: str | None = None
    resolved_by: int | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class ConflictResolve(BaseModel):
    """人工裁决入参。`decision` 只允许 confirmed / rejected，校验在服务层。

    与 `ChapterLinkCreate` 同理：非法值走 400 `INVALID_CONFLICT_RESOLUTION`，
    不用 pydantic 的枚举校验（那会变成 422）。
    """

    decision: str
    label_type: str | None = None

