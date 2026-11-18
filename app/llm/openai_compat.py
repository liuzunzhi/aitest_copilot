"""OpenAI 兼容的真实大模型供应商。

端点 `POST {base_url}/chat/completions`，兼容 DeepSeek、通义千问等
一切 OpenAI 兼容服务。

设计取舍：

- **用 `httpx` 而不是 `openai` SDK**：SDK 自带重试、代理、异步体系，
  我们只要「一次 POST + 一次 JSON 解析」，SDK 太重；
- **超时必填**：`httpx.Timeout(connect=5.0, read=timeout_seconds, ...)`，
  绝不允许出现无超时的网络调用；
- **不传 `temperature` / `max_tokens`**：不同供应商的默认值差异大，
  传固定值反而制造行为不一致；
- **每次 `chat` 新建 Client**：本期调用量小，不做连接池复用，
  避免长连接泄漏与跨线程问题；
- **异常统一收敛到 `LLMCallFailed`**：超时、连接失败、401、500、
  响应结构不对——对前端都是同一件事：「模型调不动」。
  消息给可读原因，但**永远不带 API Key**。

`transport` 参数让测试能注入 `httpx.MockTransport`，**不产生真实 socket**。
"""

from __future__ import annotations

import httpx

from app.common.errors import LLMCallFailed
from app.llm.schemas import LLMRequest, LLMResponse, TokenUsage


class OpenAICompatProvider:
    """OpenAI 兼容供应商。"""

    name = "openai_compat"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        # 与 MockProvider 同契约：调用次数可数，便于写运行留痕
        self.calls: list[LLMRequest] = []

    @classmethod
    def from_config(
        cls,
        config,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        """从 `LLMProviderConfig` 行构造。

        `api_key` 必须是**解密后**的明文——配置行里只有密文
        （`api_key_ciphertext`），解密由调用方（工厂）负责，
        解密失败在那里抛 `LLMConfigInvalid`。
        """
        return cls(
            base_url=config.base_url,
            api_key=api_key,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            transport=transport,
        )

    def chat(self, req: LLMRequest) -> LLMResponse:
        """发一次请求并解析响应。"""
        self.calls.append(req)
        index = len(self.calls) - 1

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(
            connect=5.0,
            read=self.timeout_seconds,
            write=self.timeout_seconds,
            pool=5.0,
        )

        try:
            with httpx.Client(timeout=timeout, transport=self._transport) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMCallFailed(
                f"调用大模型超时（超过 {self.timeout_seconds} 秒）"
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMCallFailed(
                "无法连接大模型服务，请检查 Base URL 与网络"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMCallFailed(
                f"调用大模型失败：{type(exc).__name__}"
            ) from exc

        if response.status_code in (401, 403):
            raise LLMCallFailed(
                f"大模型鉴权失败（HTTP {response.status_code}），请检查 API Key"
            )
        if response.status_code >= 400:
            raise LLMCallFailed(f"大模型返回 HTTP {response.status_code}")

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMCallFailed("大模型返回结构不合法") from exc

        content = self._extract_content(data)
        return LLMResponse(
            content=content,
            usage=self._extract_usage(data),
            model=self.model,
            raw={"request": req.model_dump(), "index": index},
        )

    def _extract_content(self, data) -> str:
        """取 `choices[0].message.content`。结构不符抛 `LLMCallFailed`。"""
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMCallFailed("大模型返回结构不合法") from exc
        if not isinstance(content, str):
            raise LLMCallFailed("大模型返回结构不合法")
        return content

    def _extract_usage(self, data) -> TokenUsage:
        """透传 `usage`，但**不落库、不计费**。没有就留 0。"""
        raw = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            return TokenUsage()
        return TokenUsage(
            prompt_tokens=int(raw.get("prompt_tokens") or 0),
            completion_tokens=int(raw.get("completion_tokens") or 0),
            total_tokens=int(raw.get("total_tokens") or 0),
        )


__all__ = ["OpenAICompatProvider"]
