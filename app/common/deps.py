"""鉴权与权限依赖。

`current_user` 是认证的唯一入口：命中令牌 → 未吊销 → 未过期 → 用户 active。
前三条在 `tokens.authenticate` 里，这里补第四条。
"""

from collections.abc import Callable

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.auth import tokens
from app.common.db import get_db
from app.common.errors import (
    AccountDisabled,
    Forbidden,
    NotProjectAdmin,
    PasswordChangeRequired,
    Unauthenticated,
)
from app.models.token import AccessToken
from app.models.project import ProjectMember
from app.models.user import User

SYSTEM_ADMIN = "system_admin"
PROJECT_ADMIN = "project_admin"


def bearer_token(authorization: str | None = Header(default=None)) -> str:
    """解析 `Authorization: Bearer <token>`。

    缺失、方案不对、令牌为空都按未登录处理（AC-06）。
    """
    if not authorization:
        raise Unauthenticated("未登录")

    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        raise Unauthenticated("未登录")

    return credentials.strip()


def auth_context(
    session: Session = Depends(get_db),
    token: str = Depends(bearer_token),
) -> tuple[User, AccessToken]:
    """解析令牌，返回 (用户, 令牌行)。

    不检查是否待改密——改密接口需要它，否则待改密用户永远出不来。
    """
    user, access_token = tokens.authenticate(session, token)
    if user.status != "active":
        raise AccountDisabled("账号已被禁用")
    return user, access_token


def authenticated_user(
    context: tuple[User, AccessToken] = Depends(auth_context),
) -> User:
    return context[0]


def current_user(user: User = Depends(authenticated_user)) -> User:
    """四重校验（AC-06）+ 待改密拦截。

    禁用账号返回 403 而不是 401：账号本身有效，禁用是可解释的状态，
    前端据此提示「账号已被禁用」而不是跳登录页。
    """
    if user.must_change_password:
        raise PasswordChangeRequired("请先修改初始密码")
    return user


def require_system_admin(user: User = Depends(current_user)) -> User:
    """系统管理员兜底权限（AC-23）。"""
    if user.global_role != SYSTEM_ADMIN:
        raise Forbidden("需要系统管理员权限")
    return user


def require_project_admin_or_system_admin(
    project_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> User:
    """AC-23：项目管理员只能审本项目，系统管理员兜底。

    非本项目管理员与不是成员统一返回 NOT_PROJECT_ADMIN——
    区分「项目存在但你无权」与「项目不存在」会泄露项目是否存在。
    """
    if user.global_role == SYSTEM_ADMIN:
        return user

    member = session.get(ProjectMember, (project_id, user.id))
    if member is None or member.role != PROJECT_ADMIN:
        raise NotProjectAdmin("需要项目管理员权限")
    return user


def require_project_role(*roles: str) -> Callable[..., ProjectMember]:
    """生成「必须是该项目指定角色」的依赖。

    用法：`member = Depends(require_project_role("project_admin"))`。
    路径参数名固定为 `project_id`，与接口路径保持一致。
    非成员与角色不符都是 403，不区分——否则等于告诉对方「这个项目存在」。
    """

    def dependency(
        project_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> ProjectMember:
        member = session.get(ProjectMember, (project_id, user.id))
        if member is None or member.role not in roles:
            raise Forbidden("无权访问该项目")
        return member

    return dependency


__all__ = [
    "PROJECT_ADMIN",
    "SYSTEM_ADMIN",
    "auth_context",
    "authenticated_user",
    "bearer_token",
    "current_user",
    "require_project_admin_or_system_admin",
    "require_project_role",
    "require_system_admin",
]
