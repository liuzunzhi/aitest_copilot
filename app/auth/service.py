"""认证业务逻辑：注册、登录、登出、密码重置。

`router` 只做参数校验与权限声明，这里不接触 `Request`；
事务边界在 service 内部，一次调用一个完整业务单元。
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.captcha import verify_captcha
from app.common.errors import (
    CaptchaInvalid,
    CaptchaRequired,
    ContactTaken,
    UsernameTaken,
    WeakPassword,
)
from app.common.security import hash_password
from app.models.user import User

MIN_PASSWORD_LENGTH = 8

MYSQL_DUPLICATE_ENTRY = 1062


def register(
    session: Session,
    *,
    username: str,
    password: str,
    email: str | None,
    phone: str | None,
    captcha_id: str | None,
    captcha: str | None,
) -> User:
    """注册即激活（AC-08）。

    顺序：密码强度 → 验证码 → 落库。
    强度先查，避免用户改完密码还得重新拿验证码。
    """
    _ensure_password_strength(password)
    _ensure_captcha(captcha_id, captcha)

    user = User(
        username=username,
        password_hash=hash_password(password),
        email=email or None,
        phone=phone or None,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise _duplicate_error(exc) from exc

    write_audit(
        session,
        "register.submit",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
    )
    session.commit()
    return user


def _ensure_password_strength(password: str) -> None:
    """AC-10：≥ 8 位，且同时包含字母与数字。"""
    has_letter = any(char.isascii() and char.isalpha() for char in password)
    has_digit = any(char.isascii() and char.isdigit() for char in password)
    if len(password) < MIN_PASSWORD_LENGTH or not has_letter or not has_digit:
        raise WeakPassword("密码至少 8 位，且需同时包含字母和数字")


def _ensure_captcha(captcha_id: str | None, captcha: str | None) -> None:
    """AC-11：缺失与错误分开报，便于前端区分刷新还是提示。"""
    if not captcha_id or not captcha:
        raise CaptchaRequired("图形验证码必填")
    if not verify_captcha(captcha_id, captcha):
        raise CaptchaInvalid("图形验证码错误或已过期")


def _duplicate_error(exc: IntegrityError) -> Exception:
    """AC-09：把 1062 按唯一索引名映射成业务错误。

    判断依据是索引名而不是字段名——错误信息里只有索引名是稳定的。
    """
    args = exc.orig.args if exc.orig is not None else ()
    code = args[0] if args else None
    message = str(args[1]) if len(args) > 1 else ""

    if code == MYSQL_DUPLICATE_ENTRY:
        if "uk_users_username" in message:
            return UsernameTaken("用户名已被占用")
        if "uk_users_email" in message or "uk_users_phone" in message:
            return ContactTaken("邮箱或手机号已被占用")

    return exc


__all__ = ["register"]
