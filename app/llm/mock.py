"""Mock 供应商：可编程返回、记录收到的请求。

两个可观察点：

- `calls: list[LLMRequest]`：每次 `chat` 追加一条，用例据此断言 Prompt 来源；
- `queue: list[str]`：预设返回队列，为空时返回 `default_response`。

默认返回 `{"conclusions": []}`，保证「不预设也能跑通」。
"""

from app.llm.schemas import LLMRequest, LLMResponse, TokenUsage

DEFAULT_RESPONSE = '{"conclusions": []}'


class MockProvider:
    """确定性的本地供应商，零网络请求。"""

    name = "mock"

    def __init__(
        self,
        *,
        default_response: str = DEFAULT_RESPONSE,
        queue: list[str] | None = None,
    ) -> None:
        self.calls: list[LLMRequest] = []
        self.default_response = default_response
        self.queue: list[str] = list(queue or [])

    def chat(self, req: LLMRequest) -> LLMResponse:
        index = len(self.calls)
        self.calls.append(req)

        content = self.queue.pop(0) if self.queue else self.default_response
        prompt_tokens = len(req.system) + len(req.user)
        completion_tokens = len(content)
        return LLMResponse(
            content=content,
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            model=self.name,
            raw={"request": req.model_dump(), "index": index},
        )


__all__ = ["DEFAULT_RESPONSE", "MockProvider"]
