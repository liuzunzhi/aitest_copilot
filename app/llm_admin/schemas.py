"""06 期（T85）的请求 / 响应模型。

两条贯穿全包的规矩：

1. **响应里没有 `api_key`，也没有 `api_key_ciphertext`**——
   只有 `api_key_masked`（形如 `sk-****1234`）；
2. **校验在服务层做**，不用 pydantic 的枚举 / 长度校验。
   pydantic 校验失败会变成 422，而 spec 要求非法输入返回 400
   `LLM_PROVIDER_INVALID` / `PROMPT_TEMPLATE_INVALID`（与 01–05 的
   既有口径一致）。所以这里只声明字段类型，长度与取值范围在服务层校。
"""

from datetime import datetime

from pydantic import BaseModel

from app.baselines.schemas import Page

__all__ = [
    "Page",
    "ProviderCreate",
    "ProviderOut",
    "ProviderTestOut",
    "ProviderUpdate",
    "TemplateBriefOut",
    "TemplateDetailOut",
    "TemplateUpdate",
    "TemplateListOut",
    "ReadonlyTemplateOut",
    "ReadonlyTemplateListOut",
]


# ------------------------------------------------------------ 大模型配置


class ProviderCreate(BaseModel):
    """新建配置。`api_key` 是明文，只在请求里出现，落库前就加密。"""

    name: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60
    is_default: bool = False


class ProviderUpdate(BaseModel):
    """更新配置。字段全可选，只传要改的。

    `api_key` 为 `None` 或不传 → **保持原密文与 `last4` 不变**。
    """

    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_seconds: int | None = None
    status: str | None = None
    is_default: bool | None = None


class ProviderOut(BaseModel):
    """配置响应。**只有掩码，没有密文也没有明文。**"""

    id: int
    name: str
    provider_type: str
    base_url: str
    model: str
    api_key_masked: str
    timeout_seconds: int
    status: str
    is_default: bool
    last_test_status: str | None = None
    last_test_at: datetime | None = None
    last_test_error: str | None = None
    created_at: datetime
    updated_at: datetime


class ProviderTestOut(BaseModel):
    """连通性测试结果。

    **失败也返回 200**，`ok=false` + 可读 `message`——
    前端要在表单里内联展示错误，不该拿到异常。
    """

    ok: bool
    latency_ms: int
    model: str | None = None
    message: str


# ------------------------------------------------------------ 提示词模板


class TemplateBriefOut(BaseModel):
    """模板列表项。**不含 Prompt 正文。**"""

    id: int
    name: str
    task_type: str
    description: str | None = None
    version_no: int
    status: str
    updated_at: datetime


class TemplateDetailOut(TemplateBriefOut):
    """模板详情。含完整 System / User Prompt。"""

    system_prompt: str
    user_prompt: str
    created_at: datetime


class TemplateUpdate(BaseModel):
    """编辑模板。

    `task_type` **不在入参里**——改了等于换了个模板的身份，
    历史分析对不上（spec §7.2 第 6 条）。
    """

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    user_prompt: str | None = None
    status: str | None = None


class TemplateListOut(Page[TemplateBriefOut]):
    """模板分页列表。"""


class ReadonlyTemplateOut(BaseModel):
    """只读模板项。只给元信息——普通成员没有管理权限。"""

    id: int
    name: str
    task_type: str
    version_no: int
    description: str | None = None


class ReadonlyTemplateListOut(BaseModel):
    """只读模板列表。"""

    items: list[ReadonlyTemplateOut]
