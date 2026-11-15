"""项目生命周期（T24 归档；T28 创建；T29 编辑；T31 归档只读）。"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.errors import (
    InvalidProjectDescription,
    InvalidProjectName,
    ProjectArchived,
    ProjectNameRequired,
    ProjectNotFound,
)
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.user import User

CLOSED_REASON_ARCHIVED = "project_archived"
NAME_MAX_LENGTH = 128
DESCRIPTION_MAX_LENGTH = 500


def _locked_active_project(session: Session, project_id: int) -> Project:
    """锁住项目行并确认可写（AC-34）。

    所有项目内写操作都从这里进入：行锁同时承担两件事——
    归档判定不被并发绕过，以及成员角色变更串行化（T34 / T35）。
    读接口不走这里，归档后仍可查看历史。
    """
    project = session.execute(
        select(Project).where(Project.id == project_id).with_for_update()
    ).scalar_one_or_none()
    if project is None:
        raise ProjectNotFound("项目不存在")
    if project.status != "active":
        raise ProjectArchived("项目已归档，不可编辑")
    return project


def create_project(
    session: Session, *, actor: User, name: str | None, description: str | None
) -> Project:
    """创建项目，并把创建人写成项目管理员（AC-31）。

    创建与成员写入必须同一事务：否则会出现「项目建好了但没人能审批」的孤儿项目。
    名称与简介在服务层校验，保证空名称返回 400 而不是 Pydantic 的 422。
    """
    name = (name or "").strip()
    if not name:
        raise ProjectNameRequired("项目名称必填")
    if len(name) > NAME_MAX_LENGTH:
        raise InvalidProjectName(f"项目名称不能超过 {NAME_MAX_LENGTH} 个字符")

    description = (description or "").strip() or None
    if description is not None and len(description) > DESCRIPTION_MAX_LENGTH:
        raise InvalidProjectDescription(
            f"项目简介不能超过 {DESCRIPTION_MAX_LENGTH} 个字符"
        )

    project = Project(name=name, description=description)
    session.add(project)
    session.flush()

    session.add(
        ProjectMember(project_id=project.id, user_id=actor.id, role="project_admin")
    )

    write_audit(
        session,
        "project.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project.id,
        target_type="project",
        target_id=project.id,
        after_data={"name": name, "description": description, "status": "active"},
    )
    session.commit()
    return project


def update_project(
    session: Session,
    *,
    actor: User,
    project_id: int,
    changes: dict[str, object],
) -> Project:
    """局部更新项目（AC-32）。

    只处理请求里显式出现的字段：未传保持不变，显式传 null 清空简介。
    归档项目只读，编辑一律 409。
    """
    project = _locked_active_project(session, project_id)

    before = {"name": project.name, "description": project.description}

    if "name" in changes:
        name = str(changes["name"] or "").strip()
        if not name:
            raise ProjectNameRequired("项目名称必填")
        if len(name) > NAME_MAX_LENGTH:
            raise InvalidProjectName(f"项目名称不能超过 {NAME_MAX_LENGTH} 个字符")
        project.name = name

    if "description" in changes:
        description = str(changes["description"] or "").strip() or None
        if description is not None and len(description) > DESCRIPTION_MAX_LENGTH:
            raise InvalidProjectDescription(
                f"项目简介不能超过 {DESCRIPTION_MAX_LENGTH} 个字符"
            )
        project.description = description

    after = {"name": project.name, "description": project.description}
    if before != after:
        write_audit(
            session,
            "project.update",
            actor_id=actor.id,
            actor_role=actor.global_role,
            project_id=project_id,
            target_type="project",
            target_id=project_id,
            before_data=before,
            after_data=after,
        )
        session.commit()

    return project


def archive_project(
    session: Session, *, project_id: int, actor: User | None = None
) -> None:
    """归档项目，并在同一事务里关闭所有待审批申请（AC-24 / AC-33）。

    pending 申请直接进终态 `closed` 而不是 `rejected`：
    它没有被任何人审批过，也不应触发驳回冷却。

    已归档时直接返回，不重复写 `project.archive`（AC-33 幂等）。
    关闭是按申请逐条记审计（AC-25 要按 applicant_id 检索）；
    `actor` 为空表示系统触发（例如定时归档）。
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFound("项目不存在")
    if project.status == "archived":
        return

    pending = session.execute(
        select(ProjectApplication.id, ProjectApplication.applicant_id).where(
            ProjectApplication.project_id == project_id,
            ProjectApplication.status == "pending",
        )
    ).all()

    project.status = "archived"
    write_audit(
        session,
        "project.archive",
        actor_id=None if actor is None else actor.id,
        actor_role=None if actor is None else actor.global_role,
        project_id=project_id,
        target_type="project",
        target_id=project_id,
        before_data={"status": "active"},
        after_data={"status": "archived"},
    )
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


__all__ = [
    "CLOSED_REASON_ARCHIVED",
    "archive_project",
    "create_project",
    "update_project",
]
