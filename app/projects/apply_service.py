"""项目申请：提交（T20，AC-13 ~ 19）。

并发去重交给数据库唯一索引：两个请求同时通过「无 pending」检查时，
后插入的那条会撞 `uk_app_pending`，映射成 409 而不是 500。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.clock import utcnow_naive
from app.common.errors import (
    AlreadyProjectMember,
    ApplicationNotFound,
    ApplicationNotPending,
    ApplyCooldown,
    ApplyDisabled,
    DuplicateApplication,
    InvalidDesiredRole,
    InvalidRoleAssignment,
    NotApplicationOwner,
    ProjectNotFound,
    ReasonRequired,
)
from app.common.settings import get_setting
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.user import User

DESIRED_ROLES = ("member", "guest")
GRANTABLE_ROLES = ("project_admin", "member", "guest")


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

    next_available = _cooldown_until(session, project_id, user.id)
    if next_available is not None:
        raise ApplyCooldown(
            "申请被驳回后的冷却期内不可再次申请",
            next_available_at=_iso_utc(next_available),
        )

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


def approve(
    session: Session,
    *,
    reviewer: User,
    project_id: int,
    application_id: int,
    role: str | None,
) -> None:
    """审批通过（AC-21）：状态流转 + 写成员 + 同事务审计。"""
    if role not in GRANTABLE_ROLES:
        raise InvalidRoleAssignment(
            "审批授予的角色仅支持 project_admin / member / guest"
        )

    application = _pending_application(session, project_id, application_id)
    now = utcnow_naive()
    _transition(
        session,
        application_id,
        "approved",
        reviewer_id=reviewer.id,
        reviewed_at=now,
    )

    # 成员写入用 ON DUPLICATE KEY UPDATE：并发双批时不会撞主键，
    # 授予的角色以本次审批为准。
    stmt = mysql_insert(ProjectMember).values(
        project_id=project_id,
        user_id=application.applicant_id,
        role=role,
    )
    session.execute(stmt.on_duplicate_key_update(role=stmt.inserted.role))

    write_audit(
        session,
        "project.apply.approve",
        actor_id=reviewer.id,
        actor_role=reviewer.global_role,
        project_id=project_id,
        target_type="project_application",
        target_id=application_id,
        before_data={"status": "pending"},
        after_data={"status": "approved", "role": role},
    )
    session.commit()


def reject(
    session: Session,
    *,
    reviewer: User,
    project_id: int,
    application_id: int,
    reason: str | None,
) -> None:
    """驳回（AC-22）：理由必填，记录 rejected_at 供下次申请判冷却。"""
    reason = (reason or "").strip()
    if not reason:
        raise ReasonRequired("驳回理由必填")

    _pending_application(session, project_id, application_id)
    now = utcnow_naive()
    _transition(
        session,
        application_id,
        "rejected",
        reviewer_id=reviewer.id,
        reviewed_at=now,
        reject_reason=reason,
        rejected_at=now,
    )

    write_audit(
        session,
        "project.apply.reject",
        actor_id=reviewer.id,
        actor_role=reviewer.global_role,
        project_id=project_id,
        target_type="project_application",
        target_id=application_id,
        before_data={"status": "pending"},
        after_data={"status": "rejected"},
        reason=reason,
    )
    session.commit()


def _pending_application(
    session: Session, project_id: int, application_id: int
) -> ProjectApplication:
    application = session.get(ProjectApplication, application_id)
    if application is None or application.project_id != project_id:
        raise ApplicationNotFound("申请不存在")
    if application.status != "pending":
        raise ApplicationNotPending("该申请已被处理")
    return application


def _transition(session: Session, application_id: int, status: str, **values: object) -> None:
    """条件更新：只有仍为 pending 才能流转。

    两个人同时点「通过」时，后到的那条 `rowcount == 0`，得到 409 而不是覆盖结果。
    """
    updated = session.execute(
        update(ProjectApplication)
        .where(
            ProjectApplication.id == application_id,
            ProjectApplication.status == "pending",
        )
        .values(status=status, **values)
    )
    if updated.rowcount == 0:
        raise ApplicationNotPending("该申请已被处理")


def _cooldown_until(session: Session, project_id: int, user_id: int) -> datetime | None:
    """驳回冷却结束时间；未在冷却期返回 None（AC-22）。"""
    rejected_at = session.execute(
        select(func.max(ProjectApplication.rejected_at)).where(
            ProjectApplication.project_id == project_id,
            ProjectApplication.applicant_id == user_id,
        )
    ).scalar_one()
    if rejected_at is None:
        return None

    cooldown_hours = get_setting("apply_cooldown_hours", session)
    next_available = rejected_at + timedelta(hours=cooldown_hours)
    return next_available if utcnow_naive() < next_available else None


def _iso_utc(value: datetime) -> str:
    """库里存的是 UTC naive，输出补上时区标记，前端才能正确换算。"""
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["DESIRED_ROLES", "GRANTABLE_ROLES", "approve", "reject", "submit", "withdraw"]
