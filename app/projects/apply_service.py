"""项目申请：提交（T20，AC-13 ~ 19）。

并发去重交给数据库唯一索引：两个请求同时通过「无 pending」检查时，
后插入的那条会撞 `uk_app_pending`，映射成 409 而不是 500。
"""

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.errors import (
    AlreadyProjectMember,
    ApplicationNotFound,
    ApplicationNotPending,
    ApplyDisabled,
    DuplicateApplication,
    InvalidDesiredRole,
    NotApplicationOwner,
    ProjectNotFound,
    ReasonRequired,
)
from app.common.settings import get_setting
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.user import User

DESIRED_ROLES = ("member", "guest")


def submit(
    session: Session,
    *,
    user: User,
    project_id: int,
    reason: str | None,
    desired_role: str | None,
) -> ProjectApplication:
    """提交项目申请（AC-13）。"""
    reason = (reason or "").strip()
    if not reason:
        raise ReasonRequired("申请理由必填")

    if desired_role not in DESIRED_ROLES:
        raise InvalidDesiredRole("期望角色仅支持 member / guest")

    project = session.get(Project, project_id)
    if project is None or project.status != "active":
        raise ProjectNotFound("项目不存在或已归档")

    if not get_setting("enable_project_apply", session):
        raise ApplyDisabled("当前平台未开放自助申请，请联系系统管理员分配项目")

    if session.get(ProjectMember, (project_id, user.id)) is not None:
        raise AlreadyProjectMember("你已是该项目成员")

    application = ProjectApplication(
        project_id=project_id,
        applicant_id=user.id,
        reason=reason,
        desired_role=desired_role,
    )
    session.add(application)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if "uk_app_pending" in str(exc.orig):
            raise DuplicateApplication("已有待审批的申请，请等待审批结果") from exc
        raise

    write_audit(
        session,
        "project.apply.submit",
        actor_id=user.id,
        actor_role=user.global_role,
        project_id=project_id,
        target_type="project_application",
        target_id=application.id,
        after_data={"status": application.status},
    )
    session.commit()
    return application


def withdraw(
    session: Session, *, user: User, project_id: int, application_id: int
) -> None:
    """撤回自己的待审批申请（AC-20）。

    先判归属再判状态：别人的申请无论什么状态都只回 403，
    不通过「状态不对」泄露该申请是否存在。
    """
    application = session.get(ProjectApplication, application_id)
    if application is None or application.project_id != project_id:
        raise ApplicationNotFound("申请不存在")

    if application.applicant_id != user.id:
        raise NotApplicationOwner("只能撤回自己的申请")

    updated = session.execute(
        update(ProjectApplication)
        .where(
            ProjectApplication.id == application_id,
            ProjectApplication.status == "pending",
        )
        .values(status="withdrawn")
    )
    if updated.rowcount == 0:
        raise ApplicationNotPending("只能撤回待审批的申请")

    write_audit(
        session,
        "project.apply.withdraw",
        actor_id=user.id,
        actor_role=user.global_role,
        project_id=project_id,
        target_type="project_application",
        target_id=application_id,
        before_data={"status": "pending"},
        after_data={"status": "withdrawn"},
    )
    session.commit()


__all__ = ["DESIRED_ROLES", "submit", "withdraw"]
