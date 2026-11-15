"""应用入口。"""

from fastapi import FastAPI

from app import __version__

app = FastAPI(title="AI 辅助测试平台", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    """健康检查。返回固定结构，供部署探针与本地验证使用。"""
    return {"status": "ok"}
