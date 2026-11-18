"""Mock 供应商：可编程返回、记录收到的请求。

三个可观察点：

- `calls: list[LLMRequest]`：每次 `chat` 追加一条，用例据此断言 Prompt 来源；
- `queue: list[str]`：预设返回队列，为空时按 Prompt 类型返回默认响应；
- 默认响应分三套：第一遍（`{"conclusions": []}`）、第二遍
  （`[INCREMENTAL_2B_SYSTEM]` 前缀的 system → `decision=unchanged`）、
  文档推导（`[DERIVE_SYSTEM]` 前缀 → 一个最小三层结构）。
  这样 e2e 不预设队列也能跑通第一遍、第二遍和基线推导。
"""

import json

from app.llm.schemas import LLMRequest, LLMResponse, TokenUsage

DEFAULT_RESPONSE = '{"conclusions": []}'
SECOND_PASS_SYSTEM_PREFIX = "[INCREMENTAL_2B_SYSTEM]"
SECOND_PASS_DEFAULT_RESPONSE = (
    '{"decision": "unchanged", "confidence": 0.5, '
    '"rationale": "mock 默认结论", "new_points": []}'
)
DERIVE_SYSTEM_PREFIX = "[DERIVE_SYSTEM]"
DERIVE_DEFAULT_RESPONSE = json.dumps(
    {
        "modules": [
            {
                "name": "示例模块",
                "description": "mock 推导出的示例模块",
                "functions": [
                    {
                        "name": "示例功能",
                        "description": "mock 推导出的示例功能",
                        "feature_points": [
                            {
                                "name": "示例功能点",
                                "description": "mock 推导出的示例功能点",
                            }
                        ],
                    }
                ],
            }
        ]
    },
    ensure_ascii=False,
)


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

        if self.queue:
            content = self.queue.pop(0)
        elif req.system.startswith(SECOND_PASS_SYSTEM_PREFIX):
            content = SECOND_PASS_DEFAULT_RESPONSE
        elif req.system.startswith(DERIVE_SYSTEM_PREFIX):
            content = DERIVE_DEFAULT_RESPONSE
        else:
            content = self.default_response
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


__all__ = [
    "DEFAULT_RESPONSE",
    "DERIVE_DEFAULT_RESPONSE",
    "DERIVE_SYSTEM_PREFIX",
    "MockProvider",
    "SECOND_PASS_DEFAULT_RESPONSE",
    "SECOND_PASS_SYSTEM_PREFIX",
]
