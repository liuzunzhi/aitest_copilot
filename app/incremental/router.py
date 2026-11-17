"""增量分析路由。

前缀 `/api/projects/{project_id}/incremental`：

- `GET  /analyses`                         记录列表（分页，可按 status 筛选）
- `POST /analyses`                         发起分析（项目管理员）
- `GET  /analyses/{analysis_id}`           详情（含 stats 与丢弃明细）
- `GET  /analyses/{analysis_id}/conclusions` 局部结论列表（分页）
- `POST /analyses/{analysis_id}/second-pass` 触发第二遍（项目管理员）
- `GET  /analyses/{analysis_id}/decisions` 第二遍裁决列表（分页）
- `GET  /analyses/{analysis_id}/conflicts` 第二遍待人工裁决队列（分页）
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import current_user
from app.incremental import service
from app.incremental.schemas import (
    AnalysisCreate,
    AnalysisOut,
    ConclusionOut,
    ConflictOut,
    DecisionOut,
    Page,
)
from app.llm.provider import get_provider
from app.models.user import User

router = APIRouter(prefix="/api/projects/{project_id}/incremental", tags=["incremental"])


@router.get("/analyses", response_model=Page[AnalysisOut])
def list_analyses(
    project_id: int,
    status: str | None = Query(
        default=None, pattern="^(pending|running|succeeded|failed)$"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[AnalysisOut]:
    """分析记录列表，新记录在前。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_analyses(
        session, project_id, status=status, page=page, page_size=page_size
    )
    return Page[AnalysisOut](
        items=[AnalysisOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/analyses", response_model=AnalysisOut, status_code=201)
def create_analysis(
    project_id: int,
    payload: AnalysisCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
    provider=Depends(get_provider),
) -> AnalysisOut:
    """发起分析。同步跑完第一遍后返回，单章失败即整体 failed。"""
    analysis = service.create_analysis(
        session,
        project_id=project_id,
        actor=user,
        payload=payload,
        provider=provider,
    )
    return AnalysisOut(
        **service.get_analysis(
            session, project_id=project_id, analysis_id=analysis.id
        )
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
def get_analysis(
    project_id: int,
    analysis_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AnalysisOut:
    """分析详情，含 `stats` 与丢弃明细。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return AnalysisOut(
        **service.get_analysis(
            session, project_id=project_id, analysis_id=analysis_id
        )
    )


@router.get(
    "/analyses/{analysis_id}/conclusions", response_model=Page[ConclusionOut]
)
def list_conclusions(
    project_id: int,
    analysis_id: int,
    chapter_id: int | None = Query(default=None),
    target_type: str | None = Query(
        default=None, pattern="^(function|feature_point)$"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[ConclusionOut]:
    """第一遍局部结论列表，支持章节 / 目标类型筛选。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_conclusions(
        session,
        project_id=project_id,
        analysis_id=analysis_id,
        chapter_id=chapter_id,
        target_type=target_type,
        page=page,
        page_size=page_size,
    )
    return Page[ConclusionOut](
        items=[ConclusionOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/analyses/{analysis_id}/second-pass", response_model=AnalysisOut)
def run_second_pass(
    project_id: int,
    analysis_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
    provider=Depends(get_provider),
) -> AnalysisOut:
    """触发第二遍。同步跑完返回，失败时第二遍状态为 failed。"""
    analysis = service.run_second_pass(
        session,
        project_id=project_id,
        analysis_id=analysis_id,
        actor=user,
        provider=provider,
    )
    return AnalysisOut(
        **service.get_analysis(
            session, project_id=project_id, analysis_id=analysis.id
        )
    )


@router.get("/analyses/{analysis_id}/decisions", response_model=Page[DecisionOut])
def list_decisions(
    project_id: int,
    analysis_id: int,
    target_type: str | None = Query(
        default=None, pattern="^(function|feature_point)$"
    ),
    decision: str | None = Query(
        default=None, pattern="^(changed|affected|unchanged)$"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[DecisionOut]:
    """第二遍无争议裁决列表。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_decisions(
        session,
        project_id=project_id,
        analysis_id=analysis_id,
        target_type=target_type,
        decision=decision,
        page=page,
        page_size=page_size,
    )
    return Page[DecisionOut](
        items=[DecisionOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/analyses/{analysis_id}/conflicts", response_model=Page[ConflictOut])
def list_conflicts(
    project_id: int,
    analysis_id: int,
    status: str | None = Query(
        default=None, pattern="^(pending|confirmed|rejected)$"
    ),
    conflict_type: str | None = Query(
        default=None, pattern="^(conflict|possible_impact|new)$"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[ConflictOut]:
    """第二遍待人工裁决队列。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_conflicts(
        session,
        project_id=project_id,
        analysis_id=analysis_id,
        status=status,
        conflict_type=conflict_type,
        page=page,
        page_size=page_size,
    )
    return Page[ConflictOut](
        items=[ConflictOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


__all__ = ["router"]