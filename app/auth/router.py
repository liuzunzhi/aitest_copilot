"""认证接口：/api/auth/*。

只做参数校验与响应组装，业务错误以 AppError 抛出，由统一处理器渲染。
"""

from datetime import timezone

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import service
from app.common.db import get_db
from app.common.deps import auth_context, authenticated_user, bearer_token
from app.models.token import AccessToken
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    captcha: str | None = None
    captcha_id: str | None = None


class RegisterResponse(BaseModel):
    status: str
    user_id: int


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False


class LoginResponse(BaseModel):
    access_token: str
    expires_at: str
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class MeResponse(BaseModel):
    id: int
    username: str
    global_role: str
    must_change_password: bool


@router.get("/me", response_model=MeResponse, summary="当前登录用户")
def me(user: User = Depends(authenticated_user)) -> MeResponse:
    """前端靠它拿到用户名与全局角色，决定是否展示管理入口。

    故意不用 `current_user`：待改密用户也要能读到 `must_change_password`，
    否则前端无法把他引到改密页。
    """
    return MeResponse(
        id=user.id,
        username=user.username,
        global_role=user.global_role,
        must_change_password=user.must_change_password,
    )


class SendResetCodeRequest(BaseModel):
    contact: str = Field(min_length=1, max_length=255)


class ResetPasswordRequest(BaseModel):
    contact: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1)
    new_password: str


@router.post("/password/send-code", summary="发送密码重置验证码")
def send_reset_code(
    payload: SendResetCodeRequest, session: Session = Depends(get_db)
) -> dict[str, str]:
    service.send_reset_code(session, contact=payload.contact)
    return {"status": "ok"}


@router.post("/password/reset", summary="重置密码")
def reset_password(
    payload: ResetPasswordRequest, session: Session = Depends(get_db)
) -> dict[str, str]:
    service.reset_password(
        session,
        contact=payload.contact,
        code=payload.code,
        new_password=payload.new_password,
    )
    return {"status": "ok"}


@router.post("/password/change", summary="修改密码（含管理员重置后的首次改密）")
def change_password(
    payload: ChangePasswordRequest,
    session: Session = Depends(get_db),
    context: tuple[User, AccessToken] = Depends(auth_context),
) -> dict[str, str]:
    user, access_token = context
    service.change_password(
        session,
        user=user,
        old_password=payload.old_password,
        new_password=payload.new_password,
        keep_token_id=access_token.id,
    )
    return {"status": "ok"}


@router.post("/logout", summary="登出")
def logout(
    session: Session = Depends(get_db), token: str = Depends(bearer_token)
) -> dict[str, str]:
    service.logout(session, token)
    return {"status": "ok"}


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="登录",
)
def login(
    payload: LoginRequest, session: Session = Depends(get_db)
) -> LoginResponse:
    result = service.login(
        session,
        username=payload.username,
        password=payload.password,
        remember=payload.remember,
    )
    return LoginResponse(
        access_token=result.access_token,
        expires_at=result.expires_at.replace(tzinfo=timezone.utc).isoformat(),
        must_change_password=result.must_change_password,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterResponse,
    summary="注册（注册即激活）",
)
def register(
    payload: RegisterRequest, session: Session = Depends(get_db)
) -> RegisterResponse:
    user = service.register(
        session,
        username=payload.username,
        password=payload.password,
        email=payload.email,
        phone=payload.phone,
        captcha_id=payload.captcha_id,
        captcha=payload.captcha,
    )
    return RegisterResponse(status=user.status, user_id=user.id)
