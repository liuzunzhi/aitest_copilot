"""测试点分析路由。

前缀 `/api/projects/{project_id}/test-points`：

- `GET    /analyses`                          生成记录列表（分页）
- `POST   /analyses`                          发起生成（项目管理员，同步执行）
- `GET    /analyses/{analysis_id}`            详情（含产出的测试点）
- `GET    /analyses/{analysis_id}/points`     该次生成的测试点
- `DELETE /analyses/{analysis_id}`            删除生成记录（项目管理员）
- `GET    /points`                            测试点列表（分页 + 筛选）
- `GET    /points/{point_id}`                 测试点详情
- `PATCH  /points/{point_id}`                 手工改（项目管理员）
- `DELETE /points/{point_id}`                 删测试点（项目管理员）
- `POST   /points/{point_id}/review`          评审：通过 / 驳回（项目管理员）

**权限在服务层判定**（与 04 / 05 一致）：
「归档先判、角色后判」的顺序只有一个出处——`app/common/permissions.py`。
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import current_user
from app.llm.provider import get_provider
from app.models.user import User

from app.test_points import service
from app.test_points.schemas import (
    AnalysisCreate,
    AnalysisDetailOut,
    AnalysisOut,
    Page,
    PointCreate,
    PointOut,
    PointUpdate,
    ReviewRequest,
)

router = APIRouter(prefix="/api/projects/{project_id}/test-points", tags=["test-points"])


@router.get("/analyses", response_model=Page[AnalysisOut])
def list_analyses(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[AnalysisOut]:
    """生成记录列表，新记录在前。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_analyses(
        session, project_id=project_id, page=page, page_size=page_size
    )
    return Page[AnalysisOut](
        items=[AnalysisOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/analyses", response_model=AnalysisDetailOut, status_code=201)
def create_analysis(
    project_id: int,
    payload: AnalysisCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
    provider=Depends(get_provider),
) -> AnalysisDetailOut:
    """发起生成。同步跑完后返回，响应直接带上产出的测试点。"""
    analysis = service.create_analysis(
        session,
        project_id=project_id,
        actor=user,
        payload=payload,
        provider=provider,
    )
    return AnalysisDetailOut(
        **service.get_analysis(
            session, project_id=project_id, analysis_id=analysis.id
        )
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetailOut)
def get_analysis(
    project_id: int,
    analysis_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AnalysisDetailOut:
    """生成详情，含 `stats`、丢弃明细与产出的测试点。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return AnalysisDetailOut(
        **service.get_analysis(
            session, project_id=project_id, analysis_id=analysis_id
        )
    )


@router.get("/analyses/{analysis_id}/points", response_model=list[PointOut])
def list_analysis_points(
    project_id: int,
    analysis_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[PointOut]:
    """某次生成产出的测试点。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return [
        PointOut(**item)
        for item in service.list_analysis_points(
            session, project_id=project_id, analysis_id=analysis_id
        )
    ]


@router.delete("/analyses/{analysis_id}", status_code=204)
def delete_analysis(
    project_id: int,
    analysis_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """删除生成记录，连带删除它产出的测试点（项目管理员）。

    已有评审通过的测试点 → 409，不允许连带删除。
    """
    service.delete_analysis(
        session, project_id=project_id, analysis_id=analysis_id, actor=user
    )
    return Response(status_code=204)


@router.get("/points", response_model=Page[PointOut])
def list_points(
    project_id: int,
    status: str | None = Query(
        default=None, pattern="^(pending|approved|rejected)$"
    ),
    target_type: str | None = Query(
        default=None, pattern="^(function|feature_point)$"
    ),
    target_id: int | None = Query(default=None),
    analysis_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[PointOut]:
    """测试点列表，新记录在前。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_points(
        session,
        project_id=project_id,
        status=status,
        target_type=target_type,
        target_id=target_id,
        analysis_id=analysis_id,
        page=page,
        page_size=page_size,
    )
    return Page[PointOut](
        items=[PointOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/points", response_model=PointOut, status_code=201)
def create_manual_point(
    project_id: int,
    payload: PointCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PointOut:
    """手工新增一条测试点（项目管理员）。"""
    return PointOut(
        **service.create_manual_point(
            session, project_id=project_id, actor=user, payload=payload
        )
    )


@router.get("/points/{point_id}", response_model=PointOut)
def get_point(
    project_id: int,
    point_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PointOut:
    """测试点详情。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return PointOut(**service.get_point(session, project_id=project_id, point_id=point_id))


@router.patch("/points/{point_id}", response_model=PointOut)
def update_point(
    project_id: int,
    point_id: int,
    payload: PointUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PointOut:
    """手工改测试点（项目管理员）。只接受名称 / 优先级 / 前置条件 / 验证要点。"""
    return PointOut(
        **service.update_point(
            session,
            project_id=project_id,
            point_id=point_id,
            actor=user,
            payload=payload,
        )
    )


@router.delete("/points/{point_id}", status_code=204)
def delete_point(
    project_id: int,
    point_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """删测试点（项目管理员）。"""
    service.delete_point(
        session, project_id=project_id, point_id=point_id, actor=user
    )
    return Response(status_code=204)


@router.post("/points/{point_id}/review", response_model=PointOut)
def review_point(
    project_id: int,
    point_id: int,
    payload: ReviewRequest,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PointOut:
    """评审测试点：通过 / 驳回（项目管理员）。"""
    return PointOut(
        **service.review_point(
            session,
            project_id=project_id,
            point_id=point_id,
            actor=user,
            action=payload.action,
            comment=payload.comment,
        )
    )
