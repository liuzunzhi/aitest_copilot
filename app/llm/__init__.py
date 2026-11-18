"""LLM 抽象层（05-incremental / 06-real-llm）。

对外暴露：数据结构、供应商协议、工厂函数，以及 06 期新增的
真实供应商与加密 / 容错解析工具。
"""

from app.llm.crypto import decrypt, encrypt, mask
from app.llm.json_utils import parse_llm_json
from app.llm.mock import MockProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.provider import LLMProvider, get_provider
from app.llm.schemas import LLMRequest, LLMResponse, TokenUsage

__all__ = [
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "MockProvider",
    "OpenAICompatProvider",
    "TokenUsage",
    "decrypt",
    "encrypt",
    "get_provider",
    "mask",
    "parse_llm_json",
]
