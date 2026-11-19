"""项目级权限判定（07-test-points T101 引入）。

**为什么搬到这里**：04 的 `app/baselines/service.py` 与 05 的
`app/incremental/service.py` 各写了一份几乎一样的权限判定，
07 要用同样的「归档先判、角色后判」顺序——
再抄第三份，三份判定逻辑必然漂移。

**固定顺序**（spec §3）：项目 404 → 归档 409 → 角色 403。
「先判归档再判角色」是 04 的 `app/baselines/router.py` docstring
明写的约定：顺序只有一个出处，不能每个模块各写一遍。

**搬迁不改行为**：函数体从 05 的 `service.py` 原样搬过来，
只有一处变化——错误消息里的动作名由调用方传入（`action` 参数），
这样 05 传 `"发起增量分析"`、04 传 `"修改功能基线"`，
各自的文案与搬迁前**逐字节一致**。
"""

from sqlalchemy.orm import Session

from app.common.deps import SYSTEM_ADMIN
from app.common.errors import (
    NotProjectAdmin,
    NotProjectMember,
    ProjectArchived,
    ProjectNotFound,
)
from app.models.project import Project, ProjectMember

__all__ = [
    "ensure_admin",
    "ensure_member",
    "ensure_project",
    "ensure_readable",
    "ensure_writable_project",
]


def ensure_project(session: Session, project_id: int) -> Project:
    """项目存在性。"""
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFound("项目不存在")
    return project


def ensure_writable_project(
    session: Session, project_id: int, *, action: str = "操作"
) -> Project:
    """写接口的项目校验：不存在 404，已归档 409。

    顺序与 03 一致：先判归档再判角色，避免用权限错误掩盖归档状态。
    """
    project = ensure_project(session, project_id)
    if project.status != "active":
        raise ProjectArchived(f"项目已归档，不可{action}")
    return project


def ensure_admin(
    session: Session, *, project_id: int, actor, action: str = "操作"
) -> None:
    """写操作限项目管理员；系统管理员兜底。

    非成员与角色不符统一 `NOT_PROJECT_ADMIN`——区分会泄露项目是否存在。
    """
    if actor.global_role == SYSTEM_ADMIN:
        return
    member = session.get(ProjectMember, (project_id, actor.id))
    if member is None or member.role != "project_admin":
        raise NotProjectAdmin(f"只有项目管理员可以{action}")


def ensure_member(session: Session, *, project_id: int, actor) -> None:
    """读接口：成员（含访客）可读；非成员 `NOT_PROJECT_MEMBER`。"""
    if actor.global_role == SYSTEM_ADMIN:
        return
    if session.get(ProjectMember, (project_id, actor.id)) is None:
        raise NotProjectMember("不是该项目成员")


def ensure_readable(session: Session, *, project_id: int, actor) -> None:
    """读接口的权限入口（路由调用）。"""
    ensure_project(session, project_id)
    ensure_member(session, project_id=project_id, actor=actor)
