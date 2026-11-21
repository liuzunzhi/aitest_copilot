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

    # 大模型配置的主密钥（06 期）。用于加密 llm_providers.api_key_ciphertext，
    # 必填——与 db_dsn 同一口径，不允许带空密钥启动。
    # 由 sha256 派生出 Fernet 密钥，所以任意长度的字符串都能用。
    llm_secret_key: str = Field(
        ...,
        min_length=1,
        description="大模型 API Key 的加密主密钥",
    )

    # 自动化资产的根目录（09 期）。扫描目录必须落在它之内——
    # 服务端用 Path.resolve() 校验，越界直接拒绝（防目录穿越 / 任意文件读取）。
    # 相对项目根或绝对路径都可以；库里只存相对该目录的相对路径。
    automation_root: str = Field(default="var/automation", min_length=1)

    # 单次自动化执行的超时秒数（09 期）。超时后进程被 kill，
    # 防止一次同步请求把后端永久挂起。
    automation_exec_timeout_seconds: int = Field(default=300, gt=0, le=3600)


@lru_cache
def get_settings() -> Settings:
    """获取配置单例。测试中可通过 `get_settings.cache_clear()` 重置。"""
    return Settings()
