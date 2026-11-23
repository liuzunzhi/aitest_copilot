"""流程基线的请求 / 响应模型（10-process-baseline T118）。

分页信封复用 `app.baselines.schemas.Page`（与 04 / 08 同一形态）。

**枚举字段一律用 `str`**——非法值走服务层 400
（`PROCESS_BASELINE_INVALID` / `PROCESS_BASELINE_STEP_INVALID` /
`PROCESS_BASELINE_LINK_INVALID`），而不是 pydantic 的 422：
422 的报错信息指不到「场景状态只能是什么」这件事上。

**入参模型一律 `extra="allow"`**（与 08 的写模型同口径）：多余字段要活到
服务层才能被判 400（pydantic 默认的 `ignore` 会把它们悄悄丢掉，
接口返回 200，用户以为改了，其实什么都没改）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.baselines.schemas import Page

__all__ = [
    "LinkInput",
    "LinksReplace",
    "LinkOut",
    "Page",
    "ScenarioBatchCreate",
    "ScenarioCreate",
    "ScenarioCreatedItem",
    "ScenarioCreatedOut",
    "ScenarioOut",
    "ScenarioUpdate",
    "StepInput",
    "StepOut",
    "StepsReplace",
]


class StepInput(BaseModel):
    """一步操作。

    `step_no` **不接受入参**——序号由服务端按数组顺序重排为 1..n，
    不信客户端给的序号（spec §5.2）。
    """

    model_config = ConfigDict(extra="allow")

    action: str
    expected: str | None = None


class LinkInput(BaseModel):
    """一条关联（场景 ↔ 功能 / 功能点）。

    `target_name` 可以传（前端回显用），但**服务端会重查覆盖**——
    名称快照必须来自库里的真名，不能采信客户端传值（spec §5.3）。
    """

    model_config = ConfigDict(extra="allow")

    target_type: str
    target_id: int
    target_name: str | None = None


class ScenarioCreate(BaseModel):
    """批量新建里的一个场景。

    **来源追溯 6 列**：`source_type='manual'` 时服务端**强制置 NULL**
    （PRD：手工添加不做追溯要求）；`source_type='document_derived'` 时
    三元组（文档 / 版本 / 章节）**必填且自洽**，否则整批拒（spec §5.1）。
    """

    model_config = ConfigDict(extra="allow")

    name: str
    description: str | None = None
    precondition: str | None = None
    source_type: str = "manual"
    status: str | None = None
    source_document_id: int | None = None
    source_version_id: int | None = None
    source_chapter_id: int | None = None
    source_chapter_title: str | None = None
    source_method: str | None = None
    source_analysis_id: int | None = None
    steps: list[StepInput] = Field(default_factory=list)
    links: list[LinkInput] = Field(default_factory=list)


class ScenarioBatchCreate(BaseModel):
    """批量新建场景的请求体。`scenarios` 为空 → 400。"""

    model_config = ConfigDict(extra="allow")

    scenarios: list[ScenarioCreate] = Field(default_factory=list)


class ScenarioUpdate(BaseModel):
    """改场景元数据。

    **只接受名称 / 描述 / 前置条件 / 状态**：
    - 来源追溯 6 列**只读**——`PATCH` 传了也不写（AC-201）；
    - 步骤与关联走各自的整体覆盖接口（`PUT .../steps` / `PUT .../links`）。

    `extra="allow"`：多余字段要活到服务层才能被判 400。
    """

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    description: str | None = None
    precondition: str | None = None
    status: str | None = None


class StepsReplace(BaseModel):
    """整体覆盖步骤：传完整的新步骤数组。"""

    model_config = ConfigDict(extra="allow")

    steps: list[StepInput] = Field(default_factory=list)


class LinksReplace(BaseModel):
    """整体覆盖关联：传完整的新关联数组（**空数组合法** = 清空关联）。"""

    model_config = ConfigDict(extra="allow")

    links: list[LinkInput] = Field(default_factory=list)


class StepOut(BaseModel):
    """一步。`step_no` 由服务端按数组顺序重排。"""

    step_no: int
    action: str
    expected: str


class LinkOut(BaseModel):
    """一条关联。

    `target_name` 是**落库快照**——目标被 04 物理删除后仍返回原名；
    `target_deleted=true` 表示目标已被删除（spec §5.6）。
    """

    target_type: str
    target_id: int
    target_name: str
    target_deleted: bool = False


class ScenarioOut(BaseModel):
    """一个场景。

    `source_chapter_title` 是**快照列**——章节改名不影响场景上的标题。
    `links[].target_deleted` 是**读时派生**的（一次 `IN` 批量查目标，不做 N+1）。

    `step_count` / `link_count` 是**计数**：列表页只给计数（省掉按场景数
    放大的查询次数），详情页同时给全量 `steps` / `links`。
    """

    id: int
    project_id: int
    name: str
    description: str | None = None
    precondition: str | None = None
    source_type: str
    status: str
    version_no: int
    source_document_id: int | None = None
    source_version_id: int | None = None
    source_chapter_id: int | None = None
    source_chapter_title: str | None = None
    source_method: str | None = None
    source_analysis_id: int | None = None
    created_by: int
    created_at: datetime
    updated_at: datetime
    step_count: int = 0
    link_count: int = 0
    steps: list[StepOut] = Field(default_factory=list)
    links: list[LinkOut] = Field(default_factory=list)


class ScenarioCreatedItem(BaseModel):
    """批量新建结果里的一项。"""

    index: int
    id: int
    name: str
    source_type: str
    version_no: int
    step_count: int
    link_count: int


class ScenarioCreatedOut(BaseModel):
    """批量新建的响应。`created` = 成功落库的场景数。"""

    created: int
    items: list[ScenarioCreatedItem] = Field(default_factory=list)
