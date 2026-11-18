"""AC-111 · OpenAI 兼容请求形状；AC-110 · 超时与异常统一收敛。

**断网红线**：本文件的所有 HTTP 行为都用 `httpx.MockTransport`，
不产生任何真实 socket。

AC-111 断言请求长什么样（URL / Header / Body / 解析），
AC-110 断言六类失败全部收敛成 `LLMCallFailed`，且**消息里绝不带 API Key**。
"""

import json

import httpx
import pytest

from app.common.errors import LLMCallFailed
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.schemas import LLMRequest

API_KEY = "sk-supersecret-1234"
BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"


def _provider(handler, **kwargs) -> OpenAICompatProvider:
    """造一个注入 MockTransport 的 Provider（**不产生真实 socket**）。"""
    return OpenAICompatProvider(
        base_url=kwargs.pop("base_url", BASE_URL),
        api_key=kwargs.pop("api_key", API_KEY),
        model=kwargs.pop("model", MODEL),
        timeout_seconds=kwargs.pop("timeout_seconds", 60),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _ok(content: str = '{"conclusions": []}'):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 22,
                    "total_tokens": 33,
                },
            },
        )

    return handler


# ------------------------------------------------------------ AC-111


def test_ac_111_url_is_exact():
    """URL 恰为 `{base_url}/chat/completions`。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _provider(handler).chat(LLMRequest(system="s", user="u"))

    assert seen["url"] == f"{BASE_URL}/chat/completions"


def test_ac_111_trailing_slash_is_stripped():
    """base_url 末尾的 `/` 不产生双斜杠。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _provider(handler, base_url="https://api.deepseek.com/v1/").chat(
        LLMRequest(system="s", user="u")
    )

    assert seen["url"] == f"{BASE_URL}/chat/completions"
    assert "//chat" not in seen["url"].replace("https://", "")


def test_ac_111_authorization_header_is_exact():
    """Header `Authorization` 恰为 `Bearer <api_key>`。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _provider(handler).chat(LLMRequest(system="s", user="u"))

    assert seen["auth"] == f"Bearer {API_KEY}"


def test_ac_111_content_type_header():
    """Content-Type 是 application/json。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ct"] = request.headers.get("Content-Type")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _provider(handler).chat(LLMRequest(system="s", user="u"))

    assert seen["ct"] == "application/json"


def test_ac_111_body_shape():
    """Body 含 model 与恰好两条 messages（system 在前、user 在后）。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _provider(handler).chat(LLMRequest(system="系统提示词", user="用户提示词"))

    body = seen["body"]
    assert body["model"] == MODEL
    assert body["messages"] == [
        {"role": "system", "content": "系统提示词"},
        {"role": "user", "content": "用户提示词"},
    ]


def test_ac_111_body_has_no_temperature_or_max_tokens():
    """本期不传 temperature / max_tokens——不同供应商默认值差异大。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _provider(handler).chat(LLMRequest(system="s", user="u"))

    assert "temperature" not in seen["body"]
    assert "max_tokens" not in seen["body"]


def test_ac_111_content_is_passed_through_verbatim():
    """`choices[0].message.content` 原样作为 `LLMResponse.content`。"""
    raw = '```json\n{"conclusions": [{"target_id": 1}]}\n```'

    response = _provider(_ok(raw)).chat(LLMRequest(system="s", user="u"))

    assert response.content == raw


def test_ac_111_usage_is_passthrough():
    """usage 透传（不落库、不计费）。"""
    response = _provider(_ok()).chat(LLMRequest(system="s", user="u"))

    assert response.usage.prompt_tokens == 11
    assert response.usage.completion_tokens == 22
    assert response.usage.total_tokens == 33


def test_ac_111_usage_missing_is_zero():
    """供应商没返回 usage → 留 0，不报错。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    response = _provider(handler).chat(LLMRequest(system="s", user="u"))

    assert response.usage.total_tokens == 0


def test_ac_111_raw_carries_request():
    """`raw` 回带请求——05 的「Prompt 确实从库里来」断言在真 Provider 下同样成立。"""
    provider = _provider(_ok())

    response = provider.chat(LLMRequest(system="系统提示词", user="用户提示词"))

    assert response.raw["request"]["system"] == "系统提示词"
    assert response.raw["request"]["user"] == "用户提示词"
    assert response.raw["index"] == 0


def test_ac_111_calls_are_counted():
    """调用次数可数——运行留痕靠它算 call_count。"""
    provider = _provider(_ok())

    provider.chat(LLMRequest(system="s", user="u1"))
    provider.chat(LLMRequest(system="s", user="u2"))

    assert len(provider.calls) == 2
    assert [call.user for call in provider.calls] == ["u1", "u2"]


# ------------------------------------------------------------ AC-110


def test_ac_110_timeout_converges():
    """超时 → LLMCallFailed，消息含「超时」。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timeout", request=request)

    with pytest.raises(LLMCallFailed) as exc:
        _provider(handler, timeout_seconds=7).chat(LLMRequest(system="s", user="u"))

    assert "超时" in str(exc.value)
    assert "7" in str(exc.value)


def test_ac_110_connect_error_converges():
    """连接失败 → LLMCallFailed，消息可读。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(LLMCallFailed) as exc:
        _provider(handler).chat(LLMRequest(system="s", user="u"))

    assert "无法连接" in str(exc.value)


def test_ac_110_http_error_converges():
    """其他 HTTPError → LLMCallFailed，消息含异常类型名。"""

    def handler(request: httpx.Request) -> httpx.Response:
        # RequestError 是 HTTPError 的子类，且能带 request（HTTPError 基类不能）
        raise httpx.RequestError("boom", request=request)

    with pytest.raises(LLMCallFailed) as exc:
        _provider(handler).chat(LLMRequest(system="s", user="u"))

    assert "RequestError" in str(exc.value)


@pytest.mark.parametrize("status", [401, 403])
def test_ac_110_auth_failure_converges(status):
    """401 / 403 → LLMCallFailed，消息含「鉴权失败」。"""
    with pytest.raises(LLMCallFailed) as exc:
        _provider(lambda r: httpx.Response(status)).chat(
            LLMRequest(system="s", user="u")
        )

    assert "鉴权失败" in str(exc.value)
    assert str(status) in str(exc.value)


def test_ac_110_server_error_converges():
    """500 → LLMCallFailed，消息含状态码。"""
    with pytest.raises(LLMCallFailed) as exc:
        _provider(lambda r: httpx.Response(500)).chat(LLMRequest(system="s", user="u"))

    assert "500" in str(exc.value)


def test_ac_110_invalid_structure_converges():
    """响应缺 choices → LLMCallFailed，消息含「结构不合法」。"""
    with pytest.raises(LLMCallFailed) as exc:
        _provider(lambda r: httpx.Response(200, json={"foo": "bar"})).chat(
            LLMRequest(system="s", user="u")
        )

    assert "结构不合法" in str(exc.value)


def test_ac_110_content_not_string_converges():
    """content 不是字符串 → LLMCallFailed。"""
    payload = {"choices": [{"message": {"content": {"nested": 1}}}]}

    with pytest.raises(LLMCallFailed) as exc:
        _provider(lambda r: httpx.Response(200, json=payload)).chat(
            LLMRequest(system="s", user="u")
        )

    assert "结构不合法" in str(exc.value)


def test_ac_110_non_json_body_converges():
    """响应体不是 JSON → LLMCallFailed。"""
    with pytest.raises(LLMCallFailed) as exc:
        _provider(lambda r: httpx.Response(200, text="not json")).chat(
            LLMRequest(system="s", user="u")
        )

    assert "结构不合法" in str(exc.value)


@pytest.mark.parametrize(
    "handler_factory",
    [
        lambda: (lambda r: httpx.Response(401)),
        lambda: (lambda r: httpx.Response(500)),
        lambda: (lambda r: httpx.Response(200, json={"no": "choices"})),
        lambda: (lambda r: httpx.Response(200, text="not json")),
    ],
)
def test_ac_110_failure_message_never_leaks_api_key(handler_factory):
    """**任何一种失败，异常消息里都不出现 API Key。**"""
    with pytest.raises(LLMCallFailed) as exc:
        _provider(handler_factory()).chat(LLMRequest(system="s", user="u"))

    assert API_KEY not in str(exc.value)


def test_ac_110_timeout_message_never_leaks_api_key():
    """超时路径同样不带 Key。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(LLMCallFailed) as exc:
        _provider(handler).chat(LLMRequest(system="s", user="u"))

    assert API_KEY not in str(exc.value)


def test_ac_110_error_code_is_llm_call_failed():
    """错误码统一是 LLM_CALL_FAILED（502）。"""
    with pytest.raises(LLMCallFailed) as exc:
        _provider(lambda r: httpx.Response(500)).chat(LLMRequest(system="s", user="u"))

    assert exc.value.code == "LLM_CALL_FAILED"
    assert exc.value.status_code == 502
