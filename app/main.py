"""应用入口。"""

from fastapi import FastAPI

from app import __version__
from app.auth.router import router as auth_router
from app.common.errors import install_error_handlers
from app.projects.router import router as projects_router
from app.users.router import router as users_router

app = FastAPI(title="AI 辅助测试平台", version=__version__)

install_error_handlers(app)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(users_router)


@app.get("/health")
def health() -> dict[str, str]:
    """健康检查。返回固定结构，供部署探针与本地验证使用。"""
    return {"status": "ok"}
