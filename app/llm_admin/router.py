"""06 期（T85）的三个路由。

- `/api/admin/llm-providers`：大模型配置管理（`require_system_admin`）
- `/api/admin/prompt-templates`：提示词模板管理（`require_system_admin`）
- `/api/prompt-templates`：只读模板列表（登录即可）

**响应里绝不出现 API Key 的密文或明文**——只有 `api_key_masked`。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import current_user, require_system_admin
from app.llm_admin import provider_service, template_service
from app.llm_admin.schemas import (
    ProviderCreate,
    ProviderOut,
    ProviderTestOut,
    ProviderUpdate,
    ReadonlyTemplateListOut,
    TemplateDetailOut,
    TemplateListOut,
    TemplateUpdate,
)
from app.models.user import User

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
templates_router = APIRouter(prefix="/api/prompt-templates", tags=["prompt-templates"])


def provider_transport() -> Any:
    """连通性测试用的 HTTP transport。生产环境是 `None`（真实网络）。

    测试通过 `dependency_overrides[provider_transport]` 注入
    `httpx.MockTransport`，**零真实 socket**。
    """
    return None


# ------------------------------------------------------------ 大模型配置


@admin_router.get(
    "/llm-providers",
    response_model=list[ProviderOut],
    summary="大模型配置列表",
)
def list_llm_providers(
    session: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
) -> list[ProviderOut]:
    return [
        ProviderOut(**provider_service.to_out(row))
        for row in provider_service.list_providers(session)
    ]


@admin_router.post(
    "/llm-providers",
    response_model=ProviderOut,
    status_code=201,
    summary="新建大模型配置",
)
def create_llm_provider(
    payload: ProviderCreate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_system_admin),
) -> ProviderOut:
    row = provider_service.create_provider(
        session,
        actor=actor,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        timeout_seconds=payload.timeout_seconds,
        is_default=payload.is_default,
    )
    return ProviderOut(**provider_service.to_out(row))


@admin_router.put(
    "/llm-providers/{provider_id}",
    response_model=ProviderOut,
    summary="更新大模型配置",
)
def update_llm_provider(
    provider_id: int,
    payload: ProviderUpdate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_system_admin),
) -> ProviderOut:
    row = provider_service.update_provider(
        session,
        actor=actor,
        provider_id=provider_id,
        payload=payload.model_dump(exclude_unset=True),
    )
    return ProviderOut(**provider_service.to_out(row))


@admin_router.post(
    "/llm-providers/{provider_id}/test",
    response_model=ProviderTestOut,
    summary="连通性测试（失败也返回 200）",
)
def test_llm_provider(
    provider_id: int,
    session: Session = Depends(get_db),
    actor: User = Depends(require_system_admin),
    transport: Any = Depends(provider_transport),
) -> ProviderTestOut:
    """连通性测试。

    **失败也返回 200** + `ok=false`——它不是业务异常，
    是「这个配置连不通」的正常反馈，前端要在表单里内联展示。
    """
    result = provider_service.test_provider(
        session, actor=actor, provider_id=provider_id, transport=transport
    )
    return ProviderTestOut(**result)


# ------------------------------------------------------------ 提示词模板（管理）


@admin_router.get(
    "/prompt-templates",
    response_model=TemplateListOut,
    summary="提示词模板列表（不含正文）",
)
def list_prompt_templates(
    task_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
) -> TemplateListOut:
    return TemplateListOut(
        **template_service.list_templates(
            session,
            task_type=task_type,
            status=status,
            page=page,
            page_size=page_size,
        )
    )


@admin_router.get(
    "/prompt-templates/{template_id}",
    response_model=TemplateDetailOut,
    summary="提示词模板详情（含正文）",
)
def get_prompt_template(
    template_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
) -> TemplateDetailOut:
    row = template_service.get_template(session, template_id)
    return TemplateDetailOut(**template_service.to_detail(row))


@admin_router.put(
    "/prompt-templates/{template_id}",
    response_model=TemplateDetailOut,
    summary="编辑提示词模板",
)
def update_prompt_template(
    template_id: int,
    payload: TemplateUpdate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_system_admin),
) -> TemplateDetailOut:
    row = template_service.update_template(
        session,
        actor=actor,
        template_id=template_id,
        payload=payload.model_dump(exclude_unset=True),
    )
    return TemplateDetailOut(**template_service.to_detail(row))


# ------------------------------------------------------------ 提示词模板（只读）


@templates_router.get(
    "",
    response_model=ReadonlyTemplateListOut,
    summary="可用提示词模板列表（登录即可，不含正文）",
)
def list_readonly_templates(
    task_type: str | None = Query(default=None),
    session: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> ReadonlyTemplateListOut:
    """只返回 `status='active'` 的模板元信息。

    普通成员没有管理权限，**不该看到 Prompt 正文**。
    """
    return ReadonlyTemplateListOut(
        items=template_service.readonly_templates(session, task_type=task_type)
    )
