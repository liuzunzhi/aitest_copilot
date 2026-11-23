"""流程基线的路由（10-process-baseline T118 / T119）。

前缀 `/api/projects/{project_id}/process-baselines`：

- `GET    /scenarios`           场景列表（keyword / source_type / status 筛选，分页）
- `POST   /scenarios`           **批量**新建场景（手工添加 / 反推候选采纳）
- `GET    /scenarios/{id}`      场景详情（步骤 + 关联 + 目标存活标记）
- `PATCH  /scenarios/{id}`      改元数据（名称 / 描述 / 前置条件 / 状态）
- `DELETE /scenarios/{id}`      删场景（物理删除，级联步骤与关联）
- `PUT    /scenarios/{id}/steps` **整体覆盖**步骤
- `PUT    /scenarios/{id}/links` **整体覆盖**关联
- `POST   /derive`              文档反推（**不写表**，返回候选 + 统计）

**权限在服务层判定**（与 04 / 05 / 07 / 08 一致）：
「归档先判、角色后判」的顺序只有一个出处——`app/common/permissions.py`。
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import current_user
from app.llm.provider import LLMProvider, get_provider
from app.models.user import User

from app.process_baselines import service
from app.process_baselines.schemas import (
    DeriveRequest,
    DeriveResponse,
    LinksReplace,
    Page,
    ScenarioBatchCreate,
    ScenarioCreatedOut,
    ScenarioOut,
    ScenarioUpdate,
    StepsReplace,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/process-baselines", tags=["process-baselines"]
)


@router.get("/scenarios", response_model=Page[ScenarioOut])
def list_scenarios(
    project_id: int,
    keyword: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    status: str = Query(default="active", pattern="^(active|archived|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[ScenarioOut]:
    """场景列表。默认只列在用场景；`status=archived` 看归档的，`status=all` 全看。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_scenarios(
        session,
        project_id,
        keyword=keyword,
        source_type=source_type,
        status=status,
        page=page,
        page_size=page_size,
    )
    return Page[ScenarioOut](
        items=[ScenarioOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/scenarios", response_model=ScenarioCreatedOut, status_code=201)
def create_scenarios(
    project_id: int,
    payload: ScenarioBatchCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ScenarioCreatedOut:
    """**批量**新建场景（项目管理员）。任一条校验失败 → 整批拒，不半批。"""
    return ScenarioCreatedOut(
        **service.create_scenarios(
            session, project_id=project_id, actor=user, payload=payload
        )
    )


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
def get_scenario(
    project_id: int,
    scenario_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ScenarioOut:
    """场景详情（含步骤与关联；目标被删时标 `target_deleted`）。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return ScenarioOut(
        **service.get_scenario(
            session, project_id=project_id, scenario_id=scenario_id
        )
    )


@router.patch("/scenarios/{scenario_id}", response_model=ScenarioOut)
def update_scenario(
    project_id: int,
    scenario_id: int,
    payload: ScenarioUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ScenarioOut:
    """改场景元数据（项目管理员）。来源追溯字段只读——传了也不写。"""
    return ScenarioOut(
        **service.update_scenario(
            session,
            project_id=project_id,
            scenario_id=scenario_id,
            actor=user,
            payload=payload,
        )
    )


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(
    project_id: int,
    scenario_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """删场景（项目管理员）。步骤与关联由数据库级联删除。"""
    service.delete_scenario(
        session, project_id=project_id, scenario_id=scenario_id, actor=user
    )
    return Response(status_code=204)


@router.put("/scenarios/{scenario_id}/steps", response_model=ScenarioOut)
def replace_steps(
    project_id: int,
    scenario_id: int,
    payload: StepsReplace,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ScenarioOut:
    """整体覆盖步骤（项目管理员）。`step_no` 由服务端按数组顺序重排。"""
    return ScenarioOut(
        **service.replace_steps(
            session,
            project_id=project_id,
            scenario_id=scenario_id,
            actor=user,
            payload=payload,
        )
    )


@router.put("/scenarios/{scenario_id}/links", response_model=ScenarioOut)
def replace_links(
    project_id: int,
    scenario_id: int,
    payload: LinksReplace,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ScenarioOut:
    """整体覆盖关联（项目管理员）。`target_name` 由服务端重查写入。"""
    return ScenarioOut(
        **service.replace_links(
            session,
            project_id=project_id,
            scenario_id=scenario_id,
            actor=user,
            payload=payload,
        )
    )


@router.post("/derive", response_model=DeriveResponse)
def run_derive(
    project_id: int,
    payload: DeriveRequest,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
    provider: LLMProvider = Depends(get_provider),
) -> DeriveResponse:
    """文档反推（项目管理员）。**同步**执行，响应直接带候选与统计。

    **不写表**：三张业务表行数不变——候选只是临时草稿，
    用户勾选后走 `POST /scenarios` 批量采纳。
    """
    return DeriveResponse(
        **service.run_derive(
            session,
            project_id=project_id,
            actor=user,
            document_id=payload.document_id,
            document_version_id=payload.document_version_id,
            template_id=payload.template_id,
            provider=provider,
            payload=payload,
        )
    )
