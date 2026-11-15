"""项目生命周期（T24，AC-24；T26 补 close 审计）。"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.errors import ProjectNotFound
from app.models.application import ProjectApplication
from app.models.project import Project
from app.models.user import User

CLOSED_REASON_ARCHIVED = "project_archived"


def archive_project(
    session: Session, *, project_id: int, actor: User | None = None
) -> None:
    """归档项目，并在同一事务里关闭所有待审批申请（AC-24）。

    pending 申请直接进终态 `closed` 而不是 `rejected`：
    它没有被任何人审批过，也不应触发驳回冷却。

    关闭是按申请逐条记审计（AC-25 要按 applicant_id 检索）；
    `actor` 为空表示系统触发（例如定时归档）。
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFound("项目不存在")

    pending = session.execute(
        select(ProjectApplication.id, ProjectApplication.applicant_id).where(
            ProjectApplication.project_id == project_id,
            ProjectApplication.status == "pending",
        )
    ).all()

    project.status = "archived"
    session.execute(
        update(ProjectApplication)
        .where(
            ProjectApplication.project_id == project_id,
            ProjectApplication.status == "pending",
        )
        .values(status="closed", closed_reason=CLOSED_REASON_ARCHIVED)
    )

    for application_id, applicant_id in pending:
        write_audit(
            session,
            "project.apply.close",
            actor_id=None if actor is None else actor.id,
            actor_role=None if actor is None else actor.global_role,
            applicant_id=applicant_id,
            project_id=project_id,
            target_type="project_application",
            target_id=application_id,
            before_data={"status": "pending"},
            after_data={"status": "closed"},
            reason=CLOSED_REASON_ARCHIVED,
        )
    session.commit()


__all__ = ["CLOSED_REASON_ARCHIVED", "archive_project"]
