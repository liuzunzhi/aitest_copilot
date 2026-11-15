"""鉴权依赖：从请求中提取令牌。

`current_user` 与角色依赖在 T18 补充，这里先提供登出所需的令牌提取。
"""

from fastapi import Header

from app.common.errors import Unauthenticated


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


__all__ = ["bearer_token"]
