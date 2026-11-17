"""应用配置。

所有运行时配置从环境变量或项目根目录的 `.env` 读取。
必填项缺失时构造即失败，不允许带着空配置启动。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行时配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 数据库连接串，必填
    db_dsn: str = Field(..., min_length=1, description="MySQL DSN")

    # Redis 连接串
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", min_length=1)

    # bcrypt 计算成本，4 ~ 16
    bcrypt_cost: int = Field(default=12, ge=4, le=16)

    # 文档原文存放目录（相对项目根或绝对路径），库里只存相对该目录的路径
    upload_dir: str = Field(default="var/uploads", min_length=1)

    # 单个上传文件上限，默认 10MB
    doc_max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    # 增量分析单章节 Prompt 的字符上限，超出截断正文并记 WARN
    incremental_max_input_chars: int = Field(default=8000, gt=0)


@lru_cache
def get_settings() -> Settings:
    """获取配置单例。测试中可通过 `get_settings.cache_clear()` 重置。"""
    return Settings()
