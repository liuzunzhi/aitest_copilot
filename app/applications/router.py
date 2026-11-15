"""我的项目申请（T38，AC-42）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import current_user
from app.models.user import User
from app.projects import query_service

router = APIRouter(prefix="/api/applications", tags=["applications"])


class ProjectBriefOut(BaseModel):
    id: int
    name: str


class MyApplicationOut(BaseModel):
    id: int
    project: ProjectBriefOut
    reason: str
    desired_role: str
    status: str
    created_at: datetime
    reviewed_at: datetime | None
    reject_reason: str | None
    closed_reason: str | None


class MyApplicationPageOut(BaseModel):
    items: list[MyApplicationOut]
    total: int
    page: int
    page_size: int


@router.get("/mine", response_model=MyApplicationPageOut, summary="我的项目申请")
def list_my_applications(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MyApplicationPageOut:
    return query_service.list_my_applications(
        session,
        applicant_id=user.id,
        status=status,
        page=page,
        page_size=page_size,
    )
