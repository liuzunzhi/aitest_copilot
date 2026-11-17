"""LLM 调用的数据契约（05-incremental）。

本期只定义协议与数据结构，不绑定任何模型供应商。
"""

from pydantic import BaseModel, Field


class LLMRequest(BaseModel):
    """一次对话请求：系统提示词 + 用户提示词。"""

    system: str
    user: str
    temperature: float = 0.0
    max_tokens: int | None = None


class TokenUsage(BaseModel):
    """用量统计。Mock 用字符数估算，真实 provider 按供应商返回值填充。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """一次对话响应。

    `raw` 原样回带本次请求，用例据此断言「Prompt 确实从数据库模板来」，
    不依赖日志、不靠打补丁。
    """

    content: str
    usage: TokenUsage
    model: str
    raw: dict = Field(default_factory=dict)


__all__ = ["LLMRequest", "LLMResponse", "TokenUsage"]
