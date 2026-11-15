"""认证业务逻辑：注册、登录、登出、密码重置。

`router` 只做参数校验与权限声明，这里不接触 `Request`；
事务边界在 service 内部，一次调用一个完整业务单元。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.tokens import authenticate, issue, revoke, revoke_all
from app.common.audit import write_audit
from app.common.captcha import (
    RateLimited as CaptchaRateLimited,
    send_reset_code as issue_reset_code,
    verify_captcha,
    verify_reset_code,
)
from app.common.clock import utcnow_naive
from app.common.errors import (
    AccountDisabled,
    AccountLocked,
    CaptchaInvalid,
    CaptchaRequired,
    ContactTaken,
    InvalidCredentials,
    InvalidResetCode,
    RateLimited,
    UsernameTaken,
    WeakPassword,
)
from app.common.security import DUMMY_HASH, hash_password, verify_password
from app.common.settings import get_setting
from app.models.user import User

MIN_PASSWORD_LENGTH = 8

MYSQL_DUPLICATE_ENTRY = 1062


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    expires_at: datetime  # naive UTC，响应时补时区


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


def login(
    session: Session,
    *,
    username: str,
    password: str,
    remember: bool = False,
) -> LoginResult:
    """登录（AC-01 ~ 05）。

    顺序刻意安排为「查用户 → 查锁定 → 验密码 → 查禁用」：
    锁定先于验密码，锁定期内正确密码也返回 423；
    禁用放在验密码之后，错误密码对禁用账号仍只报 401，不泄露状态。
    """
    ttl_key = "remember_ttl_seconds" if remember else "token_ttl_seconds"
    ttl_seconds = int(get_setting(ttl_key, session))
    max_failures = int(get_setting("max_login_failures", session))
    lock_minutes = int(get_setting("lock_duration_minutes", session))

    # 用列查询而不是 ORM 实体：同一会话里 ORM 实体可能是旧值，
    # 并发/连续失败的计数必须读数据库真实值。
    row = session.execute(
        select(
            User.id,
            User.password_hash,
            User.status,
            User.locked_until,
        ).where(User.username == username)
    ).one_or_none()

    if row is None:
        # 空跑 bcrypt，让「用户不存在」与「密码错误」耗时一致（AC-02）。
        verify_password(password, DUMMY_HASH)
        raise InvalidCredentials("用户名或密码错误")

    if row.locked_until is not None and row.locked_until > utcnow_naive():
        raise AccountLocked(
            "账号已锁定",
            unlock_at=row.locked_until.replace(tzinfo=timezone.utc).isoformat(),
        )

    if not verify_password(password, row.password_hash):
        locked_until = _bump_failed_login(
            session, row.id, max_failures=max_failures, lock_minutes=lock_minutes
        )
        if locked_until is not None:
            write_audit(
                session,
                "login.locked",
                actor_id=row.id,
                target_type="user",
                target_id=row.id,
            )
        session.commit()
        raise InvalidCredentials("用户名或密码错误")

    if row.status != "active":
        write_audit(
            session,
            "login.blocked.disabled",
            actor_id=row.id,
            target_type="user",
            target_id=row.id,
        )
        session.commit()
        raise AccountDisabled("账号已被禁用")

    was_locked = row.locked_until is not None
    session.execute(
        update(User)
        .where(User.id == row.id)
        .values(failed_login_count=0, locked_until=None)
    )
    if was_locked:
        write_audit(
            session,
            "login.unlocked",
            actor_id=row.id,
            target_type="user",
            target_id=row.id,
        )

    token = issue(session, row.id, ttl_seconds)
    expires_at = utcnow_naive() + timedelta(seconds=ttl_seconds)
    write_audit(
        session,
        "login.success",
        actor_id=row.id,
        target_type="user",
        target_id=row.id,
    )
    session.commit()
    return LoginResult(access_token=token, expires_at=expires_at)


def logout(session: Session, token: str) -> None:
    """登出（AC-07）：吊销当前令牌并写审计。

    先 `resolve` 再 `revoke`：既拿到 actor 写审计，也保证已吊销/过期
    的令牌不会被当成一次成功登出。幂等性由再次调用时 `TOKEN_REVOKED` 体现。
    """
    user, _ = authenticate(session, token)
    revoke(session, token)
    write_audit(
        session,
        "logout",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
    )
    session.commit()


def send_reset_code(session: Session, *, contact: str) -> None:
    """发送密码重置验证码（AC-12）。

    联系人是否存在都返回同样的结果，且都占用 60s 限流键——
    否则「存在返回 429、不存在返回 200」就成了账号枚举通道。

    一期没有邮件/短信通道，验证码只写 Redis，由前端联调时读取。
    """
    user = _find_by_contact(session, contact)
    try:
        code = issue_reset_code(contact)
    except CaptchaRateLimited as exc:
        raise RateLimited("验证码发送过于频繁，请稍后再试") from exc

    if user is not None:
        _deliver_reset_code(user, code)


def reset_password(
    session: Session, *, contact: str, code: str, new_password: str
) -> User:
    """校验验证码并重置密码（AC-12）。

    强度先查，避免验证码被一次弱密码提交白白消耗；
    成功后吊销该用户全部令牌。
    """
    _ensure_password_strength(new_password)

    user = _find_by_contact(session, contact)
    if user is None or not verify_reset_code(contact, code):
        raise InvalidResetCode("验证码无效或已过期")

    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow_naive()
    revoke_all(session, user.id)
    write_audit(
        session,
        "password.reset",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
    )
    session.commit()
    return user


def _find_by_contact(session: Session, contact: str) -> User | None:
    """按邮箱或手机号找人。排序规则大小写不敏感，邮箱匹配天然忽略大小写。"""
    return session.execute(
        select(User).where(or_(User.email == contact, User.phone == contact))
    ).scalars().first()


def _deliver_reset_code(user: User, code: str) -> None:
    """发送通道占位：一期只写 Redis，接入邮件/短信后在这里发送。

    刻意不写日志，验证码落在日志里等于泄露。
    """
    del user, code


def _bump_failed_login(
    session: Session, user_id: int, *, max_failures: int, lock_minutes: int
) -> datetime | None:
    """失败计数 +1，达到阈值时写锁定时间（AC-04）。

    单条原子 UPDATE：并发失败由行锁串行化，不会丢计数；
    MySQL 没有 RETURNING，所以同事务再 SELECT 一次读回自己写的值。
    时间在 Python 侧算好再绑定，不在 SQL 里写 INTERVAL。

    注意 SET 子句的顺序：MySQL 从左到右求值，`locked_until` 必须写在
    自增之前。否则 CASE 读到的是已经 +1 的计数，会提前一次触发锁定
    （4 次失败就锁 5 次阈值的账号）。
    """
    new_unlock_at = utcnow_naive() + timedelta(minutes=lock_minutes)
    session.execute(
        text(
            """
            UPDATE users
            SET locked_until = CASE
                    WHEN failed_login_count + 1 >= :max_failures THEN :new_unlock_at
                    ELSE locked_until
                END,
                failed_login_count = failed_login_count + 1,
                updated_at = CURRENT_TIMESTAMP(3)
            WHERE id = :uid
            """
        ),
        {
            "max_failures": max_failures,
            "new_unlock_at": new_unlock_at,
            "uid": user_id,
        },
    )
    return session.execute(
        text("SELECT locked_until FROM users WHERE id = :uid"), {"uid": user_id}
    ).scalar_one()


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


__all__ = [
    "LoginResult",
    "login",
    "logout",
    "register",
    "reset_password",
    "send_reset_code",
]
