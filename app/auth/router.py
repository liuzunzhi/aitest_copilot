"""认证接口：/api/auth/*。

只做参数校验与响应组装，业务错误以 AppError 抛出，由统一处理器渲染。
"""

from datetime import timezone

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import service
from app.common.db import get_db

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
