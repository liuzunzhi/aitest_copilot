"""管理员用户管理（T25，AC-03）。

禁用不吊销令牌：`current_user` 每次请求都校验 `status=active`，
失效来源保持单一——状态一改，已签发 token 立刻得到 403 ACCOUNT_DISABLED；
重新启用后旧 token 也随状态恢复，不会出现「禁用时没吊销、启用后不知能否用」的歧义。
"""

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.tokens import revoke_all
from app.common.audit import write_audit
from app.common.clock import utcnow_naive
from app.common.db import get_db
from app.common.deps import require_system_admin
from app.common.errors import InvalidStatus, UserNotFound
from app.common.security import hash_password
from app.models.user import User

router = APIRouter(prefix="/api/admin/users", tags=["admin"])

ALLOWED_STATUSES = ("active", "disabled")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    phone: str | None
    status: str
    global_role: str
    created_at: datetime


class StatusRequest(BaseModel):
    status: str | None = None


class StatusOut(BaseModel):
    status: str


class PasswordResetOut(BaseModel):
    status: str
    temporary_password: str
    must_change_password: bool


def _generate_temporary_password() -> str:
    """随机临时密码，直接满足 AC-10（长度、字母、数字）。

    追加 `aA1` 是为了不依赖 token_urlsafe 恰好抽到数字/大小写。
    """
    return secrets.token_urlsafe(9) + "aA1"


@router.get("", response_model=list[UserOut], summary="用户列表")
def list_users(
    session: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
) -> list[User]:
    return list(session.execute(select(User).order_by(User.id)).scalars())


@router.patch("/{uid}/status", response_model=StatusOut, summary="启用 / 禁用账号")
def update_status(
    uid: int,
    payload: StatusRequest,
    session: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> StatusOut:
    if payload.status not in ALLOWED_STATUSES:
        raise InvalidStatus("状态仅支持 active / disabled")

    user = session.get(User, uid)
    if user is None:
        raise UserNotFound("用户不存在")

    if user.status == payload.status:
        return StatusOut(status=user.status)

    previous = user.status
    user.status = payload.status

    write_audit(
        session,
        "user.disable" if payload.status == "disabled" else "user.enable",
        actor_id=admin.id,
        actor_role=admin.global_role,
        target_type="user",
        target_id=uid,
        before_data={"status": previous},
        after_data={"status": payload.status},
    )
    session.commit()
    return StatusOut(status=user.status)


@router.patch("/{uid}/password", response_model=PasswordResetOut, summary="管理员重置密码")
def reset_password(
    uid: int,
    session: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> PasswordResetOut:
    """随机强密码 + 强制首登修改（spec 待确认 4 的落地）。

    临时密码只在本次响应里出现一次，库里只有 bcrypt 哈希。
    """
    user = session.get(User, uid)
    if user is None:
        raise UserNotFound("用户不存在")

    temporary_password = _generate_temporary_password()
    user.password_hash = hash_password(temporary_password)
    user.password_changed_at = utcnow_naive()
    user.must_change_password = True
    revoke_all(session, user.id)

    write_audit(
        session,
        "user.password.reset",
        actor_id=admin.id,
        actor_role=admin.global_role,
        target_type="user",
        target_id=uid,
    )
    session.commit()
    return PasswordResetOut(
        status="ok",
        temporary_password=temporary_password,
        must_change_password=True,
    )
