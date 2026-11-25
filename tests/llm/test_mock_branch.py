"""AC-228 · Mock 的前缀分支分流（12-chapter-link-ai T130）。

Mock 按 `req.system.startswith(PREFIX)` 分派返回。12 期新增了
`[CHAPTER_LINK_ANALYZE_SYSTEM]` 分支（引用图 AI 分析），
**既有六个分支的行为必须一个字节不变**——这是 06 / 07 / 08 / 10 期
每次加分支都要守的红线（见 `app/llm/mock.py` 的 docstring）。

同时断言新分支的默认响应是**空引用列表**——Mock 不知道真实章节 id，
编一个出来必然越界被丢弃。
"""

import json

from app.llm.mock import (
    CHAPTER_LINK_DEFAULT_RESPONSE,
    CHAPTER_LINK_SYSTEM_PREFIX,
    DERIVE_DEFAULT_RESPONSE,
    DERIVE_SYSTEM_PREFIX,
    MockProvider,
    PROCESS_BASELINE_DEFAULT_RESPONSE,
    PROCESS_BASELINE_SYSTEM_PREFIX,
    SECOND_PASS_DEFAULT_RESPONSE,
    SECOND_PASS_SYSTEM_PREFIX,
    TEST_CASE_DEFAULT_RESPONSE,
    TEST_CASE_SYSTEM_PREFIX,
    TEST_POINT_DEFAULT_RESPONSE,
    TEST_POINT_SYSTEM_PREFIX,
)
from app.llm.schemas import LLMRequest

# 既有六个分支的 system 前缀与其默认响应（逐字节固定）
LEGACY_BRANCHES = [
    (SECOND_PASS_SYSTEM_PREFIX, SECOND_PASS_DEFAULT_RESPONSE),
    (DERIVE_SYSTEM_PREFIX, DERIVE_DEFAULT_RESPONSE),
    (TEST_POINT_SYSTEM_PREFIX, TEST_POINT_DEFAULT_RESPONSE),
    (TEST_CASE_SYSTEM_PREFIX, TEST_CASE_DEFAULT_RESPONSE),
    (PROCESS_BASELINE_SYSTEM_PREFIX, PROCESS_BASELINE_DEFAULT_RESPONSE),
]


def _chat(system: str) -> str:
    """用 Mock 调一次，返回响应正文。"""
    return MockProvider().chat(LLMRequest(system=system, user="u")).content


def test_ac_228_chapter_link_branch_returns_empty_references():
    """新前缀命中引用图分支，默认返回空引用列表。"""
    content = _chat(f"{CHAPTER_LINK_SYSTEM_PREFIX} 你是章节引用关系分析助手。")

    assert json.loads(content) == {"references": []}


def test_ac_228_chapter_link_default_response_is_json():
    """默认响应是**合法 JSON**，且根结构是 `{"references": [...]}`。

    根结构错一个字母，服务端的根结构校验就会失败——
    Mock 存在的意义就是让 e2e 不依赖真实模型也能跑通。
    """
    payload = json.loads(CHAPTER_LINK_DEFAULT_RESPONSE)

    assert set(payload) == {"references"}
    assert payload["references"] == []


def test_ac_228_legacy_branches_unchanged():
    """既有五个分支的默认响应逐字节不变（12 期只新增分支，不改旧的）。"""
    for prefix, expected in LEGACY_BRANCHES:
        assert _chat(f"{prefix} 任意内容") == expected


def test_ac_228_chapter_link_branch_does_not_shadow_others():
    """新分支不影响其他前缀的命中（分流是 startswith，不是包含）。

    `provider.calls` 记的是**请求**（`LLMRequest`），响应正文要从
    `chat()` 的返回值拿。
    """
    provider = MockProvider()

    link_response = provider.chat(
        LLMRequest(system=CHAPTER_LINK_SYSTEM_PREFIX, user="u")
    )
    baseline_response = provider.chat(
        LLMRequest(system=PROCESS_BASELINE_SYSTEM_PREFIX, user="u")
    )

    assert json.loads(link_response.content) == {"references": []}
    assert json.loads(baseline_response.content) == json.loads(
        PROCESS_BASELINE_DEFAULT_RESPONSE
    )
    # 两次调用都记下来了（`calls` 记请求，不是响应）
    assert len(provider.calls) == 2
