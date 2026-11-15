"""项目生命周期（T24，AC-24）。"""

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.common.errors import ProjectNotFound
from app.models.application import ProjectApplication
from app.models.project import Project

CLOSED_REASON_ARCHIVED = "project_archived"


def archive_project(session: Session, *, project_id: int) -> None:
    """归档项目，并在同一事务里关闭所有待审批申请（AC-24）。

    pending 申请直接进终态 `closed` 而不是 `rejected`：
    它没有被任何人审批过，也不应触发驳回冷却。
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFound("项目不存在")

    project.status = "archived"
    session.execute(
        update(ProjectApplication)
        .where(
            ProjectApplication.project_id == project_id,
            ProjectApplication.status == "pending",
        )
        .values(status="closed", closed_reason=CLOSED_REASON_ARCHIVED)
    )
    session.commit()


__all__ = ["CLOSED_REASON_ARCHIVED", "archive_project"]
