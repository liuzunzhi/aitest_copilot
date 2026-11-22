"""自动化执行的请求 / 响应模型（09-automation T112 / T114）。

列表复用 `app.baselines.schemas.Page`，与 04 / 07 / 08 同一形态。

**入参一律 `extra="forbid"`**（与 08 的写模型相反）：自动化这层的入参
字段少且语义明确，多传一个字段大概率是前端拼错了名字——直接 422 报错，
比默默丢掉更安全。业务枚举值（框架 / 状态）仍走服务层 400。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.baselines.schemas import Page

__all__ = [
    "AssetOut",
    "AssetPatch",
    "AssetCreateItem",
    "AssetsCreate",
    "AssetsCreateOut",
    "Page",
    "RunCreate",
    "RunItemOut",
    "RunOut",
    "RunReportOut",
    "ScanRequest",
    "ScanOut",
    "ScannedAssetOut",
    "TraceabilityOut",
]


class ScanRequest(BaseModel):
    """扫描请求。

    `directory` 是**相对 `AUTOMATION_ROOT` 的相对路径**。
    空串 = 扫整个 root（但仍受 2000 文件上限保护）。
    """

    model_config = ConfigDict(extra="forbid")

    directory: str = ""


class ScannedAssetOut(BaseModel):
    """扫描清单里的一项。

    `status` 取值：`new`（未入库） / `existing`（已入库，
    `existing_asset_id` 给出既有 id）。
    """

    file_path: str
    name: str
    framework: str
    parse_confidence: float
    detected_cases: int
    status: str
    existing_asset_id: int | None = None
    low_confidence: bool = False


class ScanOut(BaseModel):
    """扫描响应。

    `root` 是**相对展示名**（如 `var/automation`）——
    **绝不返回绝对路径**，绝对路径会泄露服务器目录结构。
    """

    root: str
    directory: str
    scanned_files: int
    matched: int
    skipped: int
    assets: list[ScannedAssetOut] = Field(default_factory=list)


class AssetCreateItem(BaseModel):
    """入库请求里的一项。

    `parse_confidence` / `detected_cases` **不采信**——
    服务端入库时会重新扫描该文件重算（spec §7.2）。
    这里仍然接收它们，是为了让前端能把「前端看到的值」与
    「服务端重算的值」做对照展示。
    """

    model_config = ConfigDict(extra="forbid")

    file_path: str
    name: str | None = None
    framework: str
    parse_confidence: float | None = None
    detected_cases: int | None = None
    skip: bool = False


class AssetsCreate(BaseModel):
    """人工确认后批量入库。"""

    model_config = ConfigDict(extra="forbid")

    assets: list[AssetCreateItem] = Field(default_factory=list)


class AssetCreatedItem(BaseModel):
    """入库结果里的一项。"""

    file_path: str
    asset_id: int | None = None
    skipped: bool = False
    reason: str | None = None


class AssetsCreateOut(BaseModel):
    """入库响应。`skipped` = 因同路径已存在而跳过的数量。"""

    created: int
    skipped: int
    items: list[AssetCreatedItem] = Field(default_factory=list)


class AssetOut(BaseModel):
    """一个资产。

    `linked_case_title` 是关联用例的**当前名称**（读时联查一次），
    `linked_case_deleted` 表示关联的用例已被 08 物理删除。
    """

    id: int
    project_id: int
    name: str
    file_path: str
    framework: str
    source: str
    parse_confidence: float | None = None
    detected_cases: int
    linked_case_id: int | None = None
    linked_case_title: str | None = None
    linked_case_deleted: bool = False
    status: str
    created_by: int
    created_at: datetime


class AssetPatch(BaseModel):
    """改资产（项目管理员）。

    只接受三件事：改关联用例（`linked_case_id`，null = 解绑）、
    归档 / 恢复（`status`）、刷新识别到的用例数（`detected_cases`）。

    `extra="allow"`：多余字段要活到服务层才能被判 400
    （pydantic 默认的 `ignore` 会把它们悄悄丢掉，接口返回 200，
    用户以为改了，其实什么都没改）。
    """

    model_config = ConfigDict(extra="allow")

    linked_case_id: int | None = None
    status: str | None = None
    detected_cases: int | None = None


# --------------------------------------------------------------- 执行（T114）


class RunCreate(BaseModel):
    """触发执行。

    `asset_ids` 为空 → 服务层 400 `AUTOMATION_RUN_INPUT_EMPTY`。
    **必填且不给默认值**——pydantic 的 `Field(...)` 让缺字段直接 422，
    不给「忘了传就当空数组」的机会（空数组同样是 400，错误码更明确）。
    """

    model_config = ConfigDict(extra="forbid")

    asset_ids: list[int] = Field(...)


class TraceabilityOut(BaseModel):
    """一条明细的追溯链。

    字段全部来自 08 已落库的用例快照（`test_point_name` / `target_name` /
    `chapter_title`）——**读快照，不联表**，也不受上游删除影响。

    `source_case_deleted` = 关联的用例已被 08 物理删除 →
    此时 `case_title` 仍显示**执行时**的快照值。
    """

    linked_case_id: int | None = None
    case_title: str | None = None
    test_point_name: str | None = None
    target_name: str | None = None
    chapter_title: str | None = None
    source_case_deleted: bool = False


class RunItemOut(BaseModel):
    """一条执行明细（粒度是**资产**，不是 pytest 的测试函数）。"""

    asset_id: int
    file_path: str | None = None
    framework: str | None = None
    result: str
    duration_ms: int | None = None
    error: str | None = None
    traceability: TraceabilityOut


class RunOut(BaseModel):
    """一次执行记录。

    `status` 表达「系统是否正常完成执行」：
    `succeeded` = pytest 进程正常跑完（**哪怕退出码是 1**——
    那只是「有测试失败」，是业务结果，不是系统错误）；
    `failed` = 跑不起来（超时 / 启动失败），此时 `error` 非空。
    """

    id: int
    project_id: int
    framework: str
    status: str
    exit_code: int | None = None
    stats: dict | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int
    created_at: datetime
    items: list[RunItemOut] = Field(default_factory=list)


class RunReportOut(RunOut):
    """单次报告：比列表多一份 `log`（执行输出）。"""

    log: str | None = None
    duration_ms: int | None = None
