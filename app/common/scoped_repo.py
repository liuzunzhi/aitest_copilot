"""项目数据访问层：成员过滤与数据隔离都在这里。

AC-26 要求「按成员过滤」在数据访问层统一生效，而不是各接口自己判断；
AC-27 要求非成员访问项目内资源一律 403。
"""

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.common.errors import NotProjectMember
from app.models.project import Project, ProjectMember


def list_member_projects(session: Session, user_id: int) -> list[tuple[Project, str]]:
    """用户已加入的项目及自己在项目内的角色（AC-26）。"""
    return session.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
        .order_by(Project.id)
    ).all()


def list_available_projects(session: Session, user_id: int) -> list[Project]:
    """全部尚未加入的项目（AC-29）。

    只排除已归档项目：归档后无法再加入，列出来只会让人点进死路。
    刻意不看 `enable_project_apply`——开关只拦提交（AC-18），不改变列表。
    """
    joined = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
    return list(
        session.execute(
            select(Project)
            .where(Project.status == "active", Project.id.not_in(joined))
            .order_by(Project.id)
        ).scalars()
    )


class ProjectScopedRepo:
    """项目内表（documents / applications / ...）的唯一访问入口。

    子类声明 `model`，其必须带 `project_id` 列；构造即校验成员身份，
    之后每条查询都被强制加上 `project_id` 条件。
    """

    model: Any

    def __init__(self, session: Session, project_id: int, user_id: int) -> None:
        self.session = session
        self.project_id = project_id
        self.user_id = user_id
        if session.get(ProjectMember, (project_id, user_id)) is None:
            raise NotProjectMember("不是该项目成员")

    def scoped(self, stmt: Select) -> Any:
        """执行带项目隔离条件的查询。"""
        return self.session.execute(
            stmt.where(self.model.project_id == self.project_id)
        )


__all__ = ["ProjectScopedRepo", "list_available_projects", "list_member_projects"]
