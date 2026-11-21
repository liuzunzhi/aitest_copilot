"""项目列表、可申请列表与项目管理（T19 / T28 / T32）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common import scoped_repo
from app.common.db import get_db
from app.common.deps import (
    SYSTEM_ADMIN,
    current_user,
    require_project_admin_or_system_admin,
    require_project_member_or_system_admin,
    require_system_admin,
)
from app.common.errors import NotProjectAdmin
from app.common.permissions import ensure_readable
from app.models.project import ProjectMember
from app.models.user import User
from app.projects import apply_service, query_service, service

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


class MemberAddRequest(BaseModel):
    """角色交给服务层校验，保证非法角色返回 400 而不是 422。"""

    user_id: int
    role: str | None = None


class MemberRoleRequest(BaseModel):
    role: str | None = None


class ProjectOverviewOut(BaseModel):
    member_count: int
    document_count: int
    baseline_count: int
    latest_execution: dict | None


class TodosOut(BaseModel):
    """工作台待办计数（AC-193）。"""

    pending_baseline_reviews: int
    pending_test_point_reviews: int
    pending_test_case_reviews: int
    total: int


class UserBriefOut(BaseModel):
    id: int
    username: str


class ApplicationOut(BaseModel):
    id: int
    applicant: UserBriefOut
    reason: str
    desired_role: str
    status: str
    created_at: datetime
    reviewer: UserBriefOut | None
    reviewed_at: datetime | None
    reject_reason: str | None
    closed_reason: str | None


class ApplicationPageOut(BaseModel):
    items: list[ApplicationOut]
    total: int
    page: int
    page_size: int


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
    "/{project_id}/overview",
    response_model=ProjectOverviewOut,
    summary="项目概览",
)
def get_overview(
    project_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_project_member_or_system_admin),
) -> ProjectOverviewOut:
    return ProjectOverviewOut(**service.get_overview(session, project_id=project_id))


@router.get(
    "/{project_id}/todos",
    response_model=TodosOut,
    summary="工作台待办计数",
)
def get_todos(
    project_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TodosOut:
    """待审核基线 / 待评审测试点 / 待评审用例的计数（AC-193）。

    成员可读——待办是团队共享的工作队列，不是管理员专属。

    用 `ensure_readable` 而不是本文件其它路由的 `require_project_member_or_system_admin`：
    后者对**不存在的项目**也返回 403（查成员表查不到就报不是成员），
    而待办接口要区分「项目不存在」(404) 与「不是成员」(403)。
    """
    ensure_readable(session, project_id=project_id, actor=user)
    return TodosOut(**service.get_todos(session, project_id=project_id))


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
    "/{project_id}/members",
    status_code=201,
    response_model=ProjectMemberOut,
    summary="添加项目成员",
)
def add_member(
    project_id: int,
    payload: MemberAddRequest,
    session: Session = Depends(get_db),
    actor: User = Depends(require_project_admin_or_system_admin),
) -> ProjectMemberOut:
    member, username = service.add_member(
        session,
        actor=actor,
        project_id=project_id,
        user_id=payload.user_id,
        role=payload.role,
    )
    return ProjectMemberOut(
        user_id=member.user_id,
        username=username,
        role=member.role,
        joined_at=member.joined_at,
    )


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMemberOut,
    summary="修改成员角色",
)
def update_member_role(
    project_id: int,
    user_id: int,
    payload: MemberRoleRequest,
    session: Session = Depends(get_db),
    actor: User = Depends(require_project_admin_or_system_admin),
) -> ProjectMemberOut:
    member, username = service.update_member_role(
        session,
        actor=actor,
        project_id=project_id,
        user_id=user_id,
        role=payload.role,
    )
    return ProjectMemberOut(
        user_id=member.user_id,
        username=username,
        role=member.role,
        joined_at=member.joined_at,
    )


@router.delete(
    "/{project_id}/members/{user_id}",
    response_model=ProjectStatusOut,
    summary="移除项目成员",
)
def remove_member(
    project_id: int,
    user_id: int,
    session: Session = Depends(get_db),
    actor: User = Depends(require_project_admin_or_system_admin),
) -> ProjectStatusOut:
    service.remove_member(
        session, actor=actor, project_id=project_id, user_id=user_id
    )
    return ProjectStatusOut(status="removed")


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


@router.get(
    "/{project_id}/applications",
    response_model=ApplicationPageOut,
    summary="本项目的申请列表",
)
def list_project_applications(
    project_id: int,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    user: User = Depends(require_project_member_or_system_admin),
) -> ApplicationPageOut:
    """项目管理员看本项目全部申请；status 缺省返回全部状态。

    非成员报 NOT_PROJECT_MEMBER、member/guest 报 NOT_PROJECT_ADMIN（AC-47）：
    「不是成员」和「是成员但角色不够」是两种不同处置，前端提示也不同。
    """
    if user.global_role != SYSTEM_ADMIN:
        member = session.get(ProjectMember, (project_id, user.id))
        if member.role != "project_admin":
            raise NotProjectAdmin("需要项目管理员权限")

    return query_service.list_project_applications(
        session,
        project_id=project_id,
        status=status,
        page=page,
        page_size=page_size,
    )


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
