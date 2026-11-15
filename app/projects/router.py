"""项目列表与可申请列表（T19，AC-26 / 28 / 29 / 30）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common import scoped_repo
from app.common.db import get_db
from app.common.deps import current_user
from app.models.user import User

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectOut(BaseModel):
    id: int
    name: str
    status: str


class MyProjectOut(ProjectOut):
    role: str


@router.get("", response_model=list[MyProjectOut], summary="我参与的项目")
def list_projects(
    session: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[MyProjectOut]:
    return [
        MyProjectOut(id=project.id, name=project.name, status=project.status, role=role)
        for project, role in scoped_repo.list_member_projects(session, user.id)
    ]


@router.get("/available", response_model=list[ProjectOut], summary="可申请的项目")
def list_available_projects(
    session: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[ProjectOut]:
    return [
        ProjectOut(id=project.id, name=project.name, status=project.status)
        for project in scoped_repo.list_available_projects(session, user.id)
    ]
