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
    "AppError",
    "CaptchaInvalid",
    "CaptchaRequired",
    "ContactTaken",
    "Forbidden",
    "InvalidCredentials",
    "InvalidResetCode",
    "RateLimited",
    "TokenExpired",
    "TokenRevoked",
    "Unauthenticated",
    "UsernameTaken",
    "WeakPassword",
    "install_error_handlers",
]
