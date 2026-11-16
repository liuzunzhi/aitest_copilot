"""项目生命周期（T24 归档；T28 创建；T29 编辑；T31 归档只读）。"""

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.errors import (
    AlreadyProjectMember,
    CannotRemoveSelf,
    Forbidden,
    InvalidProjectDescription,
    InvalidProjectName,
    InvalidRoleAssignment,
    LastProjectAdmin,
    MemberNotFound,
    ProjectArchived,
    ProjectNameRequired,
    ProjectNotFound,
    UserNotFound,
)
from app.models.application import ProjectApplication
from app.models.document import BaselineSnapshot, Document
from app.models.project import Project, ProjectMember
from app.models.user import User

CLOSED_REASON_ARCHIVED = "project_archived"
NAME_MAX_LENGTH = 128
DESCRIPTION_MAX_LENGTH = 500
MEMBER_ROLES = ("project_admin", "member", "guest")


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


def list_members(
    session: Session, *, project_id: int
) -> list[tuple[ProjectMember, str]]:
    """成员列表（AC-35）。

    归档项目仍可查看历史，所以不经过 `_locked_active_project`。
    一次 join 取用户名避免逐行查询；`user_id` 兜底保证同一时刻加入时顺序稳定。
    """
    return list(
        session.execute(
            select(ProjectMember, User.username)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.joined_at, ProjectMember.user_id)
        ).all()
    )


def add_member(
    session: Session,
    *,
    actor: User,
    project_id: int,
    user_id: int,
    role: str | None,
) -> tuple[ProjectMember, str]:
    """添加项目成员（AC-36）。

    重复添加不先查后插：`project_members` 是复合主键，
    并发两个请求都通过预检查时，后插入的撞 1062，映射成 409。
    """
    _locked_active_project(session, project_id)

    if role not in MEMBER_ROLES:
        raise InvalidRoleAssignment("角色仅支持 project_admin / member / guest")

    user = session.get(User, user_id)
    if user is None:
        raise UserNotFound("用户不存在")

    member = ProjectMember(project_id=project_id, user_id=user_id, role=role)
    session.add(member)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if "PRIMARY" in str(exc.orig) or exc.orig.args[0] == 1062:
            raise AlreadyProjectMember("该用户已是项目成员") from exc
        raise

    write_audit(
        session,
        "project.member.add",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="project_member",
        target_id=user_id,
        after_data={"role": role},
    )
    session.commit()
    return member, user.username


def update_member_role(
    session: Session,
    *,
    actor: User,
    project_id: int,
    user_id: int,
    role: str | None,
) -> tuple[ProjectMember, str]:
    """修改成员角色（AC-37）。

    「最后一名 project_admin」是跨行约束，先锁项目行再计数，
    否则两人同时降级仅剩的两位管理员会双双通过，项目失去管理员。
    """
    _locked_active_project(session, project_id)

    if role not in MEMBER_ROLES:
        raise InvalidRoleAssignment("角色仅支持 project_admin / member / guest")

    row = session.execute(
        select(ProjectMember, User.username)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).first()
    if row is None:
        raise MemberNotFound("该用户不是项目成员")
    member, username = row

    if member.role == "project_admin" and role != "project_admin":
        # 必须用锁定读取：普通 SELECT 在 REPEATABLE READ 下读的是事务开始时的快照，
        # 并发降级时另一名管理员已提交的变更看不到，两人会同时通过。
        roles = session.execute(
            select(ProjectMember.role)
            .where(ProjectMember.project_id == project_id)
            .with_for_update()
        ).scalars()
        if sum(1 for value in roles if value == "project_admin") == 1:
            raise LastProjectAdmin("项目至少保留一名项目管理员")

    before = {"role": member.role}
    member.role = role
    write_audit(
        session,
        "project.member.role",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="project_member",
        target_id=user_id,
        before_data=before,
        after_data={"role": role},
    )
    session.commit()
    return member, username


def remove_member(
    session: Session, *, actor: User, project_id: int, user_id: int
) -> None:
    """移除项目成员（AC-38）。

    移除自己走 400、最后一名项目管理员走 409；项目管理员不能移除系统管理员。
    成员记录删除后，目标用户下一次项目内请求的成员校验立即失败，不需要重新登录。
    """
    _locked_active_project(session, project_id)

    row = session.execute(
        select(ProjectMember, User.global_role)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).first()
    if row is None:
        raise MemberNotFound("该用户不是项目成员")
    member, target_global_role = row

    if user_id == actor.id:
        raise CannotRemoveSelf("不能移除自己")
    if actor.global_role != "system_admin" and target_global_role == "system_admin":
        raise Forbidden("项目管理员不能移除系统管理员")

    if member.role == "project_admin":
        roles = session.execute(
            select(ProjectMember.role)
            .where(ProjectMember.project_id == project_id)
            .with_for_update()
        ).scalars()
        if sum(1 for value in roles if value == "project_admin") == 1:
            raise LastProjectAdmin("项目至少保留一名项目管理员")

    before = {"role": member.role}
    session.delete(member)
    write_audit(
        session,
        "project.member.remove",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="project_member",
        target_id=user_id,
        before_data=before,
    )
    session.commit()


def get_overview(session: Session, *, project_id: int) -> dict[str, object]:
    """项目概览（AC-40）。

    文档与基线已是真实计数；执行模块尚未上线，`latest_execution` 仍返回 None。
    读接口不受归档影响。
    """
    member_count = session.execute(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.project_id == project_id)
    ).scalar_one()
    document_count = session.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.project_id == project_id)
    ).scalar_one()
    baseline_count = session.execute(
        select(func.count())
        .select_from(BaselineSnapshot)
        .where(BaselineSnapshot.project_id == project_id)
    ).scalar_one()
    return {
        "member_count": member_count,
        "document_count": document_count,
        "baseline_count": baseline_count,
        "latest_execution": None,
    }


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
    "MEMBER_ROLES",
    "add_member",
    "archive_project",
    "create_project",
    "get_overview",
    "list_members",
    "remove_member",
    "update_member_role",
    "update_project",
]
