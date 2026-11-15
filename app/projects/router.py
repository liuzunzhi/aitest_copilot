"""项目列表与可申请列表（T19，AC-26 / 28 / 29 / 30）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common import scoped_repo
from app.common.db import get_db
from app.common.deps import current_user
from app.models.user import User
from app.projects import apply_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectOut(BaseModel):
    id: int
    name: str
    status: str


class MyProjectOut(ProjectOut):
    role: str


class SubmitApplicationRequest(BaseModel):
    """字段都允许缺省，由服务层给「理由必填 / 角色白名单」的稳定错误码。

    交给 Pydantic 校验会得到 422，而 AC-14 / AC-15 要求的是 400。
    """

    reason: str | None = None
    desired_role: str | None = None


class ApplicationStatusOut(BaseModel):
    status: str


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


@router.post(
    "/{project_id}/applications",
    status_code=201,
    response_model=ApplicationStatusOut,
    summary="提交项目申请",
)
def submit_application(
    project_id: int,
    payload: SubmitApplicationRequest,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ApplicationStatusOut:
    application = apply_service.submit(
        session,
        user=user,
        project_id=project_id,
        reason=payload.reason,
        desired_role=payload.desired_role,
    )
    return ApplicationStatusOut(status=application.status)


@router.post(
    "/{project_id}/applications/{application_id}/withdraw",
    response_model=ApplicationStatusOut,
    summary="撤回项目申请",
)
def withdraw_application(
    project_id: int,
    application_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ApplicationStatusOut:
    apply_service.withdraw(
        session, user=user, project_id=project_id, application_id=application_id
    )
    return ApplicationStatusOut(status="withdrawn")
