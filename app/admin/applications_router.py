"""系统管理员全局申请记录（T39，AC-43）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import require_system_admin
from app.models.user import User
from app.projects import query_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ProjectBriefOut(BaseModel):
    id: int
    name: str


class UserBriefOut(BaseModel):
    id: int
    username: str


class AdminApplicationOut(BaseModel):
    id: int
    project: ProjectBriefOut
    applicant: UserBriefOut
    reason: str
    desired_role: str
    status: str
    created_at: datetime
    reviewer: UserBriefOut | None
    reviewed_at: datetime | None
    reject_reason: str | None
    closed_reason: str | None


class AdminApplicationPageOut(BaseModel):
    items: list[AdminApplicationOut]
    total: int
    page: int
    page_size: int


@router.get(
    "/applications",
    response_model=AdminApplicationPageOut,
    summary="全局申请记录",
)
def list_all_applications(
    project_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    applicant_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
) -> AdminApplicationPageOut:
    return query_service.list_all_applications(
        session,
        project_id=project_id,
        status=status,
        applicant_id=applicant_id,
        page=page,
        page_size=page_size,
    )
