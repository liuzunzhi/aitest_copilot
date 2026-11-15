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

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.code
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


def install_error_handlers(app: FastAPI) -> None:
    """把 AppError 统一渲染成 {"code","message"}。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )


__all__ = [
    "AppError",
    "CaptchaInvalid",
    "CaptchaRequired",
    "ContactTaken",
    "UsernameTaken",
    "WeakPassword",
    "install_error_handlers",
]
