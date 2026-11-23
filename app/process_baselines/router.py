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
- `POST   /reviews/submit`      提交审核（**提交即冻结** `draft_snapshot`）
- `POST   /reviews/{id}/approve` 审核通过（`structure_json` 原样转正 + 版本号）
- `POST   /reviews/{id}/reject` 审核驳回（意见必填，不占版本号）
- `GET    /revisions`           快照列表（状态筛选 + 分页）
- `GET    /revisions/{id}`      快照详情（`draft_snapshot` / `structure_json` 原文）

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
    ReviewDecision,
    ReviewSubmit,
    RevisionDetail,
    RevisionOut,
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


# ---------------------------------------------------------------- 审核与快照


@router.get("/revisions", response_model=Page[RevisionOut])
def list_revisions(
    project_id: int,
    status: str = Query(default="approved", pattern="^(approved|submitted|rejected|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[RevisionOut]:
    """快照列表。默认只列审核通过的；`status=submitted` 看待审核的。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_revisions(
        session, project_id, status=status, page=page, page_size=page_size
    )
    return Page[RevisionOut](
        items=[RevisionOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/revisions/{revision_id}", response_model=RevisionDetail)
def get_revision(
    project_id: int,
    revision_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RevisionDetail:
    """快照详情，含 `draft_snapshot` 与 `structure_json` 两份原文。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return RevisionDetail(
        **service.get_revision(session, project_id=project_id, revision_id=revision_id)
    )


@router.post("/reviews/submit", response_model=RevisionOut, status_code=201)
def submit_review(
    project_id: int,
    payload: ReviewSubmit,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RevisionOut:
    """提交审核（项目管理员）。**提交即冻结**——`draft_snapshot` 在此刻定稿。

    **同步接口**：前端要长超时（与 04 推导的同步执行同一策略）。
    """
    revision = service.submit_review(
        session,
        project_id=project_id,
        actor=user,
        comment=payload.comment,
        payload=payload,
    )
    return RevisionOut(
        id=revision.id,
        project_id=revision.project_id,
        version_no=revision.version_no,
        status=revision.status,
        scenario_count=revision.scenario_count,
        step_count=revision.step_count,
        link_count=revision.link_count,
        submitted_by=revision.submitted_by,
        submitted_at=revision.submitted_at,
        reviewed_by=revision.reviewed_by,
        reviewed_at=revision.reviewed_at,
        review_comment=revision.review_comment,
        created_at=revision.created_at,
    )


@router.post("/reviews/{revision_id}/approve", response_model=RevisionOut)
def approve_review(
    project_id: int,
    revision_id: int,
    payload: ReviewDecision,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RevisionOut:
    """审核通过：`structure_json` **原样转正** + 分配版本号（v1.0、v1.1…）。"""
    revision = service.approve_review(
        session,
        project_id=project_id,
        revision_id=revision_id,
        actor=user,
        comment=payload.comment,
        payload=payload,
    )
    return RevisionOut(
        id=revision.id,
        project_id=revision.project_id,
        version_no=revision.version_no,
        status=revision.status,
        scenario_count=revision.scenario_count,
        step_count=revision.step_count,
        link_count=revision.link_count,
        submitted_by=revision.submitted_by,
        submitted_at=revision.submitted_at,
        reviewed_by=revision.reviewed_by,
        reviewed_at=revision.reviewed_at,
        review_comment=revision.review_comment,
        created_at=revision.created_at,
    )


@router.post("/reviews/{revision_id}/reject", response_model=RevisionOut)
def reject_review(
    project_id: int,
    revision_id: int,
    payload: ReviewDecision,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RevisionOut:
    """驳回。意见必填；**不占版本号、不写 `structure_json`**，`draft_snapshot` 保留。"""
    revision = service.reject_review(
        session,
        project_id=project_id,
        revision_id=revision_id,
        actor=user,
        comment=payload.comment,
        payload=payload,
    )
    return RevisionOut(
        id=revision.id,
        project_id=revision.project_id,
        version_no=revision.version_no,
        status=revision.status,
        scenario_count=revision.scenario_count,
        step_count=revision.step_count,
        link_count=revision.link_count,
        submitted_by=revision.submitted_by,
        submitted_at=revision.submitted_at,
        reviewed_by=revision.reviewed_by,
        reviewed_at=revision.reviewed_at,
        review_comment=revision.review_comment,
        created_at=revision.created_at,
    )
