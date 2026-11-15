"""统一错误响应。

业务错误用 `AppError` 子类表达「HTTP 状态 + 稳定 code」，响应体固定
`{"code": ..., "message": ...}`，前端只按 `code` 分支。
FastAPI 默认的 `HTTPException` 会包成 `{"detail": ...}`，与 spec 的
`{"code": "USERNAME_TAKEN"}` 不一致，所以统一在这里转换。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务错误基类：子类只需声明 status_code 与 code。"""

    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str | None = None, **extra: object) -> None:
        self.message = message or self.code
        self.extra = extra
        super().__init__(self.message)


class CaptchaRequired(AppError):
    status_code = 400
    code = "CAPTCHA_REQUIRED"


class CaptchaInvalid(AppError):
    status_code = 400
    code = "CAPTCHA_INVALID"


class WeakPassword(AppError):
    status_code = 400
    code = "WEAK_PASSWORD"


class UsernameTaken(AppError):
    status_code = 409
    code = "USERNAME_TAKEN"


class ContactTaken(AppError):
    status_code = 409
    code = "CONTACT_TAKEN"


class InvalidCredentials(AppError):
    """AC-02：用户名不存在、密码错误、账号已删除共用这一个响应。"""

    status_code = 401
    code = "INVALID_CREDENTIALS"


class AccountDisabled(AppError):
    status_code = 403
    code = "ACCOUNT_DISABLED"


class AccountLocked(AppError):
    """AC-04：423 并带 unlock_at，前端据此显示剩余时间。"""

    status_code = 423
    code = "ACCOUNT_LOCKED"


class Unauthenticated(AppError):
    """AC-06：不带令牌或令牌无法识别。"""

    status_code = 401
    code = "UNAUTHENTICATED"


class TokenExpired(AppError):
    status_code = 401
    code = "TOKEN_EXPIRED"


class TokenRevoked(AppError):
    status_code = 401
    code = "TOKEN_REVOKED"


class InvalidResetCode(AppError):
    """联系人不存在、验证码错误或已过期，统一一个响应，不泄露账号是否存在。"""

    status_code = 400
    code = "INVALID_RESET_CODE"


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class Forbidden(AppError):
    """AC-27 / AC-23：已登录但没有该资源或该操作的权限。"""

    status_code = 403
    code = "FORBIDDEN"


class NotProjectMember(AppError):
    """AC-27：非项目成员访问项目内资源。"""

    status_code = 403
    code = "NOT_PROJECT_MEMBER"


class ProjectNotFound(AppError):
    """项目不存在或已归档——归档项目不再接受申请。"""

    status_code = 404
    code = "PROJECT_NOT_FOUND"


class ProjectNameRequired(AppError):
    """AC-31：项目名称必填。"""

    status_code = 400
    code = "PROJECT_NAME_REQUIRED"


class InvalidProjectName(AppError):
    """AC-31：项目名称超出 128 字符。"""

    status_code = 400
    code = "INVALID_PROJECT_NAME"


class InvalidProjectDescription(AppError):
    """AC-31：项目简介超出 500 字符。"""

    status_code = 400
    code = "INVALID_PROJECT_DESCRIPTION"


class ProjectArchived(AppError):
    """AC-32 / AC-34：归档项目只读，不允许再编辑或维护成员。"""

    status_code = 409
    code = "PROJECT_ARCHIVED"


class ReasonRequired(AppError):
    status_code = 400
    code = "REASON_REQUIRED"


class InvalidDesiredRole(AppError):
    status_code = 400
    code = "INVALID_DESIRED_ROLE"


class AlreadyProjectMember(AppError):
    status_code = 409
    code = "ALREADY_PROJECT_MEMBER"


class DuplicateApplication(AppError):
    status_code = 409
    code = "DUPLICATE_APPLICATION"


class ApplyDisabled(AppError):
    status_code = 403
    code = "APPLY_DISABLED"


class ApplicationNotFound(AppError):
    status_code = 404
    code = "APPLICATION_NOT_FOUND"


class NotApplicationOwner(AppError):
    status_code = 403
    code = "NOT_APPLICATION_OWNER"


class ApplicationNotPending(AppError):
    status_code = 409
    code = "APPLICATION_NOT_PENDING"


class InvalidRoleAssignment(AppError):
    """AC-21：审批通过时授予的角色只允许 project_admin / member / guest。"""

    status_code = 400
    code = "INVALID_ROLE_ASSIGNMENT"


class ApplyCooldown(AppError):
    """AC-22：驳回后的冷却期内再次申请，extra 带 next_available_at。"""

    status_code = 429
    code = "APPLY_COOLDOWN"


class UserNotFound(AppError):
    status_code = 404
    code = "USER_NOT_FOUND"


class InvalidStatus(AppError):
    status_code = 400
    code = "INVALID_STATUS"


class PasswordChangeRequired(AppError):
    """管理员重置密码后，改密前除改密接口外一律拒绝。"""

    status_code = 403
    code = "PASSWORD_CHANGE_REQUIRED"


class NotProjectAdmin(AppError):
    """AC-23：不是该项目管理员（系统管理员除外）。"""

    status_code = 403
    code = "NOT_PROJECT_ADMIN"


class MemberNotFound(AppError):
    """AC-37 / AC-38：目标用户不是该项目成员。"""

    status_code = 404
    code = "MEMBER_NOT_FOUND"


class LastProjectAdmin(AppError):
    """AC-37 / AC-38：项目至少保留一名项目管理员。"""

    status_code = 409
    code = "LAST_PROJECT_ADMIN"


class CannotRemoveSelf(AppError):
    """AC-38：成员不能通过成员管理移除自己。"""

    status_code = 400
    code = "CANNOT_REMOVE_SELF"


def install_error_handlers(app: FastAPI) -> None:
    """把 AppError 统一渲染成 {"code","message",**extra}。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, **exc.extra},
        )


__all__ = [
    "AccountDisabled",
    "AccountLocked",
    "AlreadyProjectMember",
    "AppError",
    "ApplicationNotFound",
    "ApplicationNotPending",
    "ApplyCooldown",
    "ApplyDisabled",
    "CaptchaInvalid",
    "CaptchaRequired",
    "CannotRemoveSelf",
    "ContactTaken",
    "DuplicateApplication",
    "Forbidden",
    "InvalidCredentials",
    "InvalidDesiredRole",
    "InvalidProjectDescription",
    "InvalidProjectName",
    "InvalidResetCode",
    "InvalidRoleAssignment",
    "InvalidStatus",
    "LastProjectAdmin",
    "MemberNotFound",
    "NotApplicationOwner",
    "NotProjectAdmin",
    "NotProjectMember",
    "PasswordChangeRequired",
    "ProjectArchived",
    "ProjectNameRequired",
    "ProjectNotFound",
    "RateLimited",
    "ReasonRequired",
    "TokenExpired",
    "TokenRevoked",
    "Unauthenticated",
    "UserNotFound",
    "UsernameTaken",
    "WeakPassword",
    "install_error_handlers",
]
