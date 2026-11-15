"""e2e 数据准备。

前台用例必须与开发库隔离：e2e 后端连 `<开发库>_e2e`（见 `specs/验证约定.md`），
否则会往开发库里塞项目、申请与审计记录，把后端全量 pytest 的全局断言打红。

用户没有开放注册接口（验证码在 Redis 里），所以用户直接写库；
项目、成员、申请一律走真实 API。UI 只用来验证被检查的那一步。
"""

import os
import uuid
from pathlib import Path

from playwright.sync_api import APIRequestContext
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.user import User

BACKEND_URL = os.getenv("E2E_BACKEND_URL", "http://127.0.0.1:8001")
ADMIN_USERNAME = os.getenv("E2E_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "Admin12345")
USER_PASSWORD = "E2ePassw0rd1"

_engine: Engine | None = None


def _e2e_dsn() -> str:
    """优先用 E2E_DB_DSN；否则读 .env 的开发 DSN，把库名换成 `_e2e`。

    只在本模块内部用，不改 os.environ：全量 pytest 会一并 import 本模块，
    改全局 DB_DSN 会让后端用例读到 e2e 库。
    """
    explicit = os.getenv("E2E_DB_DSN")
    if explicit:
        return explicit
    env_file = Path(__file__).resolve().parents[2] / '.env'
    for line in env_file.read_text(encoding='utf-8').splitlines():
        if line.startswith('DB_DSN='):
            parts = line.split('=', 1)[1].split('/')
            parts[-1] = 'aitest_copilot_e2e?charset=utf8mb4'
            return '/'.join(parts)
    raise RuntimeError('.env 里没有 DB_DSN，无法定位 e2e 库')


def _session() -> Session:
    global _engine
    if _engine is None:
        _engine = create_engine(_e2e_dsn(), pool_pre_ping=True, future=True)
    return Session(_engine, expire_on_commit=False)


def create_user(global_role: str = "user") -> dict:
    """直接在 e2e 库里造一个可登录用户（用户名带 uuid，不撞已有数据）。"""
    payload = {
        "username": f"e2e-{uuid.uuid4().hex[:10]}",
        "password": USER_PASSWORD,
    }
    session = _session()
    try:
        user = User(
            username=payload["username"],
            password_hash=hash_password(USER_PASSWORD),
            global_role=global_role,
        )
        session.add(user)
        session.commit()
        payload["id"] = user.id
    finally:
        session.close()
    return payload


def token_for(ctx: APIRequestContext, username: str, password: str) -> str:
    response = ctx.post(
        "/api/auth/login", data={"username": username, "password": password}
    )
    assert response.ok, response.text()
    return response.json()["access_token"]


def storage_state(base_url: str, token: str) -> dict:
    """把令牌塞进 localStorage，省掉每个用例都走一遍登录表单。"""
    return {
        "cookies": [],
        "origins": [
            {
                "origin": base_url.rstrip("/"),
                "localStorage": [{"name": "aitest.token", "value": token}],
            }
        ],
    }


class Api:
    """以系统管理员身份造数；需要别的身份时用 `token_for` 换令牌。"""

    def __init__(self, ctx: APIRequestContext):
        self.ctx = ctx
        self.admin_token = token_for(ctx, ADMIN_USERNAME, ADMIN_PASSWORD)

    def _headers(self, token: str | None = None) -> dict:
        return {"Authorization": f"Bearer {token or self.admin_token}"}

    def create_project(self, name: str, description: str | None = None, token: str | None = None) -> dict:
        response = self.ctx.post(
            "/api/projects",
            data={"name": name, "description": description},
            headers=self._headers(token),
        )
        assert response.status in (200, 201), response.text()
        return response.json()

    def archive_project(self, project_id: int) -> None:
        response = self.ctx.post(
            f"/api/projects/{project_id}/archive", headers=self._headers()
        )
        assert response.ok, response.text()

    def add_member(self, project_id: int, user_id: int, role: str) -> None:
        response = self.ctx.post(
            f"/api/projects/{project_id}/members",
            data={"user_id": user_id, "role": role},
            headers=self._headers(),
        )
        assert response.status in (200, 201), response.text()

    def submit_application(
        self, project_id: int, token: str, reason: str = "e2e 前台核对"
    ) -> None:
        response = self.ctx.post(
            f"/api/projects/{project_id}/applications",
            data={"reason": reason, "desired_role": "member"},
            headers=self._headers(token),
        )
        assert response.status in (200, 201), response.text()

    def set_role(self, user_id: int, global_role: str) -> None:
        """改全局角色，用管理员令牌（AC-45 的后台动作，前台只负责展示结果）。"""
        response = self.ctx.patch(
            f"/api/admin/users/{user_id}/role",
            data={"global_role": global_role},
            headers=self._headers(),
        )
        assert response.ok, response.text()
