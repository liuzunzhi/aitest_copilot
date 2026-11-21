"""测试用例分析的请求 / 响应模型（08-test-case-analysis T107）。

列表统一复用 `app.baselines.schemas.Page`，不另写分页信封。
枚举字段一律用 `str`——非法值走服务层 400（`TEST_CASE_INVALID` /
`TEST_CASE_STEP_INVALID`），而不是 pydantic 的 422。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.baselines.schemas import Page

__all__ = [
    "AnalysisCreate",
    "AnalysisDetailOut",
    "AnalysisOut",
    "CaseCreate",
    "CaseOut",
    "CaseUpdate",
    "Page",
    "ReviewRequest",
    "StepOut",
    "StepsReplace",
]


class AnalysisCreate(BaseModel):
    """发起生成。

    - `test_point_ids` 给了 → **严格只用这些**（必须全部存在、属于本项目、已评审通过）；
    - 不给 → 按 `chapter_ids` / `target_type+target_id` / `test_point_analysis_id` 筛；
      都不给 = 全项目 approved。
    """

    template_id: int
    test_point_ids: list[int] | None = None
    chapter_ids: list[int] | None = None
    target_type: str | None = None
    target_id: int | None = None
    test_point_analysis_id: int | None = None


class AnalysisOut(BaseModel):
    """生成记录。附带模板名，前端不用为一行记录再查一次。"""

    id: int
    project_id: int
    template_id: int
    template_name: str | None = None
    template_version: int
    provider: str
    test_point_analysis_id: int | None = None
    chapter_ids: list[int] | None = None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    stats: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int
    created_at: datetime


class StepOut(BaseModel):
    """一步。`step_no` 由服务端按数组顺序重排，模型给的序号一律不用。"""

    step_no: int
    action: str
    expected: str


class CaseOut(BaseModel):
    """一条用例。

    `test_point_name` / `target_name` / `chapter_title` 是**落库快照**——
    测试点或章节后来改名、被删，历史用例仍然对得上原文。
    `needs_review` 是**响应字段**：读时按内容指纹派生，不落库（T108 接线）。
    """

    id: int
    project_id: int
    analysis_id: int | None = None
    test_point_id: int
    test_point_name: str
    title: str
    case_type: str
    priority: str
    precondition: str | None = None
    target_type: str
    target_id: int
    target_name: str
    chapter_id: int | None = None
    chapter_title: str | None = None
    status: str
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    source_type: str
    needs_review: bool = False
    needs_review_reason: str | None = None
    needs_review_ack_at: datetime | None = None
    created_by: int
    created_at: datetime
    updated_at: datetime
    steps: list[StepOut] = Field(default_factory=list)


class AnalysisDetailOut(AnalysisOut):
    """生成记录详情：带上这次产出的用例（含步骤）。"""

    cases: list[CaseOut] = Field(default_factory=list)


class CaseCreate(BaseModel):
    """手工新增用例。

    `test_point_id` 必填——用例必须挂到某个测试点上，否则既不可追溯，
    也无法参与「源变更 → 待复核」的派生。

    `test_point_id` **不要求 approved**：手工补录是人工判断，
    不该被评审状态卡死（spec §6.1 的说明）。
    """

    test_point_id: int
    title: str
    case_type: str = "functional"
    priority: str = "medium"
    precondition: str | None = None
    steps: list["StepInput"] = Field(default_factory=list)


class CaseUpdate(BaseModel):
    """手工改用例元数据。

    **只接受这 4 个字段**：用例名称 / 用例类型 / 优先级 / 前置条件。
    状态（要评审）、来源测试点（要重新追溯）、步骤（走 `PUT /steps`）
    都不该在这里改——那会破坏追溯链或评审生命周期。

    `extra="allow"`：多余字段要活到服务层才能被判 400
    （pydantic 默认的 `ignore` 会把它们悄悄丢掉，接口返回 200，
    用户以为改了，其实什么都没改）。
    """

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    case_type: str | None = None
    priority: str | None = None
    precondition: str | None = None


class StepInput(BaseModel):
    """一步。`step_no` 不接受入参——序号由服务端按数组顺序重排。"""

    action: str
    expected: str | None = None


class StepsReplace(BaseModel):
    """整体覆盖步骤：传完整的新步骤数组。"""

    steps: list[StepInput] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    """评审入参。`action` 只允许 approve / reject，校验在服务层。"""

    action: str
    comment: str | None = None


CaseCreate.model_rebuild()
