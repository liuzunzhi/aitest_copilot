"""应用入口。"""

from fastapi import FastAPI

from app import __version__
from app.admin.applications_router import router as admin_applications_router
from app.applications.router import router as applications_router
from app.auth.router import router as auth_router
from app.baselines.router import router as baselines_router
from app.common.errors import install_error_handlers
from app.documents.router import router as documents_router
from app.incremental.links_router import router as incremental_links_router
from app.incremental.router import router as incremental_router
from app.llm_admin.router import admin_router as llm_admin_router
from app.llm_admin.router import templates_router as prompt_templates_router
from app.projects.router import router as projects_router
from app.users.router import router as users_router

app = FastAPI(title="AI 辅助测试平台", version=__version__)

install_error_handlers(app)
app.include_router(admin_applications_router)
app.include_router(applications_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(documents_router)
app.include_router(users_router)
app.include_router(baselines_router)
app.include_router(incremental_router)
app.include_router(incremental_links_router)
app.include_router(llm_admin_router)
app.include_router(prompt_templates_router)


@app.get("/health")
def health() -> dict[str, str]:
    """健康检查。返回固定结构，供部署探针与本地验证使用。"""
    return {"status": "ok"}
