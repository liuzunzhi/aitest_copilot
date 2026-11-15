"""项目列表、可申请列表与项目管理（T19 / T28 / T32）。"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common import scoped_repo
from app.common.db import get_db
from app.common.deps import (
    current_user,
    require_project_admin_or_system_admin,
    require_project_member_or_system_admin,
    require_system_admin,
)
from app.models.user import User
from app.projects import apply_service, service

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None
    status: str


class MyProjectOut(ProjectOut):
    role: str


class ProjectCreateRequest(BaseModel):
    """名称与简介交给服务层校验，保证空名称返回 400 而不是 422。"""

    name: str | None = None
    description: str | None = None


class ProjectUpdateRequest(BaseModel):
    """同样交给服务层校验；用 `model_fields_set` 区分「未传」与「显式 null」。"""

    name: str | None = None
    description: str | None = None


class ProjectStatusOut(BaseModel):
    status: str


class ProjectMemberOut(BaseModel):
    user_id: int
    username: str
    role: str
    joined_at: datetime


class SubmitApplicationRequest(BaseModel):
    """字段都允许缺省，由服务层给「理由必填 / 角色白名单」的稳定错误码。

    交给 Pydantic 校验会得到 422，而 AC-14 / AC-15 要求的是 400。
    """

    reason: str | None = None
    desired_role: str | None = None


class ApplicationStatusOut(BaseModel):
    status: str


class ApproveRequest(BaseModel):
    role: str | None = None


class RejectRequest(BaseModel):
    reason: str | None = None


@router.get("", response_model=list[MyProjectOut], summary="我参与的项目")
def list_projects(
    session: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[MyProjectOut]:
    return [
        MyProjectOut(
            id=project.id,
            name=project.name,
            description=project.description,
            status=project.status,
            role=role,
        )
        for project, role in scoped_repo.list_member_projects(session, user.id)
    ]


@router.get("/available", response_model=list[ProjectOut], summary="可申请的项目")
def list_available_projects(
    session: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[ProjectOut]:
    return [
        ProjectOut(
            id=project.id,
            name=project.name,
            description=project.description,
            status=project.status,
        )
        for project in scoped_repo.list_available_projects(session, user.id)
    ]


@router.post("", status_code=201, response_model=ProjectOut, summary="创建项目")
def create_project(
    payload: ProjectCreateRequest,
    session: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> ProjectOut:
    project = service.create_project(
        session, actor=admin, name=payload.name, description=payload.description
    )
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
    )


@router.patch("/{project_id}", response_model=ProjectOut, summary="编辑项目")
def update_project(
    project_id: int,
    payload: ProjectUpdateRequest,
    session: Session = Depends(get_db),
    actor: User = Depends(require_project_admin_or_system_admin),
) -> ProjectOut:
    project = service.update_project(
        session,
        actor=actor,
        project_id=project_id,
        changes=payload.model_dump(exclude_unset=True),
    )
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
    )


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberOut],
    summary="项目成员列表",
)
def list_members(
    project_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_project_member_or_system_admin),
) -> list[ProjectMemberOut]:
    """成员与系统管理员可读，只暴露用户名，不带邮箱手机号。"""
    return [
        ProjectMemberOut(
            user_id=member.user_id,
            username=username,
            role=member.role,
            joined_at=member.joined_at,
        )
        for member, username in service.list_members(session, project_id=project_id)
    ]


@router.post(
    "/{project_id}/archive", response_model=ProjectStatusOut, summary="归档项目"
)
def archive_project(
    project_id: int,
    session: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> ProjectStatusOut:
    """平台不提供物理删除，归档即删除入口；重复归档保持幂等。"""
    service.archive_project(session, project_id=project_id, actor=admin)
    return ProjectStatusOut(status="archived")


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


@router.post(
    "/{project_id}/applications/{application_id}/approve",
    response_model=ApplicationStatusOut,
    summary="审批通过",
)
def approve_application(
    project_id: int,
    application_id: int,
    payload: ApproveRequest,
    session: Session = Depends(get_db),
    reviewer: User = Depends(require_project_admin_or_system_admin),
) -> ApplicationStatusOut:
    apply_service.approve(
        session,
        reviewer=reviewer,
        project_id=project_id,
        application_id=application_id,
        role=payload.role,
    )
    return ApplicationStatusOut(status="approved")


@router.post(
    "/{project_id}/applications/{application_id}/reject",
    response_model=ApplicationStatusOut,
    summary="驳回申请",
)
def reject_application(
    project_id: int,
    application_id: int,
    payload: RejectRequest,
    session: Session = Depends(get_db),
    reviewer: User = Depends(require_project_admin_or_system_admin),
) -> ApplicationStatusOut:
    apply_service.reject(
        session,
        reviewer=reviewer,
        project_id=project_id,
        application_id=application_id,
        reason=payload.reason,
    )
    return ApplicationStatusOut(status="rejected")
