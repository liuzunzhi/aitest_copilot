"""项目申请的分页查询（T37 / T38 / T39）。

三个列表接口共用同一分页形状 `{items,total,page,page_size}`，
排序一律 `created_at DESC, id DESC`——只按时间排序时同毫秒记录顺序不稳定，
翻页会出现重复或漏项。
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.common.errors import InvalidApplicationStatus
from app.models.application import ProjectApplication
from app.models.project import Project
from app.models.user import User

APPLICATION_STATUSES = ("pending", "approved", "rejected", "withdrawn", "closed")


def _validate_status(status: str | None) -> None:
    if status is not None and status not in APPLICATION_STATUSES:
        raise InvalidApplicationStatus("申请状态不合法")


def _total(session: Session, stmt: Any) -> int:
    return session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()


def _page(session: Session, stmt: Any, *, page: int, page_size: int) -> dict[str, Any]:
    total = _total(session, stmt)
    rows = session.execute(
        stmt.limit(page_size).offset((page - 1) * page_size)
    ).all()
    return {"total": total, "page": page, "page_size": page_size, "rows": rows}


def _user_brief(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "username": user.username}


def list_project_applications(
    session: Session,
    *,
    project_id: int,
    status: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """本项目申请列表（AC-41）。"""
    _validate_status(status)

    Applicant = aliased(User)
    Reviewer = aliased(User)
    stmt = (
        select(ProjectApplication, Applicant, Reviewer)
        .join(Applicant, Applicant.id == ProjectApplication.applicant_id)
        .outerjoin(Reviewer, Reviewer.id == ProjectApplication.reviewer_id)
        .where(ProjectApplication.project_id == project_id)
        .order_by(ProjectApplication.created_at.desc(), ProjectApplication.id.desc())
    )
    if status is not None:
        stmt = stmt.where(ProjectApplication.status == status)

    result = _page(session, stmt, page=page, page_size=page_size)
    result["items"] = [
        {
            "id": application.id,
            "applicant": _user_brief(applicant),
            "reason": application.reason,
            "desired_role": application.desired_role,
            "status": application.status,
            "created_at": application.created_at,
            "reviewer": _user_brief(reviewer),
            "reviewed_at": application.reviewed_at,
            "reject_reason": application.reject_reason,
            "closed_reason": application.closed_reason,
        }
        for application, applicant, reviewer in result.pop("rows")
    ]
    return result


def list_my_applications(
    session: Session,
    *,
    applicant_id: int,
    status: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """我的申请（AC-42）：只返回本人记录，带项目名称。"""
    _validate_status(status)

    stmt = (
        select(ProjectApplication, Project)
        .join(Project, Project.id == ProjectApplication.project_id)
        .where(ProjectApplication.applicant_id == applicant_id)
        .order_by(ProjectApplication.created_at.desc(), ProjectApplication.id.desc())
    )
    if status is not None:
        stmt = stmt.where(ProjectApplication.status == status)

    result = _page(session, stmt, page=page, page_size=page_size)
    result["items"] = [
        {
            "id": application.id,
            "project": {"id": project.id, "name": project.name},
            "reason": application.reason,
            "desired_role": application.desired_role,
            "status": application.status,
            "created_at": application.created_at,
            "reviewed_at": application.reviewed_at,
            "reject_reason": application.reject_reason,
            "closed_reason": application.closed_reason,
        }
        for application, project in result.pop("rows")
    ]
    return result


def list_all_applications(
    session: Session,
    *,
    project_id: int | None,
    status: str | None,
    applicant_id: int | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """系统管理员全局申请记录（AC-43）：三个筛选条件可任意组合。"""
    _validate_status(status)

    Applicant = aliased(User)
    Reviewer = aliased(User)
    stmt = (
        select(ProjectApplication, Project, Applicant, Reviewer)
        .join(Project, Project.id == ProjectApplication.project_id)
        .join(Applicant, Applicant.id == ProjectApplication.applicant_id)
        .outerjoin(Reviewer, Reviewer.id == ProjectApplication.reviewer_id)
        .order_by(ProjectApplication.created_at.desc(), ProjectApplication.id.desc())
    )
    if project_id is not None:
        stmt = stmt.where(ProjectApplication.project_id == project_id)
    if status is not None:
        stmt = stmt.where(ProjectApplication.status == status)
    if applicant_id is not None:
        stmt = stmt.where(ProjectApplication.applicant_id == applicant_id)

    result = _page(session, stmt, page=page, page_size=page_size)
    result["items"] = [
        {
            "id": application.id,
            "project": {"id": project.id, "name": project.name},
            "applicant": _user_brief(applicant),
            "reason": application.reason,
            "desired_role": application.desired_role,
            "status": application.status,
            "created_at": application.created_at,
            "reviewer": _user_brief(reviewer),
            "reviewed_at": application.reviewed_at,
            "reject_reason": application.reject_reason,
            "closed_reason": application.closed_reason,
        }
        for application, project, applicant, reviewer in result.pop("rows")
    ]
    return result


__all__ = [
    "APPLICATION_STATUSES",
    "list_all_applications",
    "list_my_applications",
    "list_project_applications",
]
