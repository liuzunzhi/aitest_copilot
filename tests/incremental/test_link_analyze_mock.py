"""AI 分析引擎与模型交互的端到端（12-chapter-link-ai T131）。

用可编程的假供应商验证：

- 小文档走整篇路径（1 次调用）；
- 大文档走两阶段（块数 + 1 次调用）；
- 阶段一某块失败 → 只跳过该块，不整次失败；
- 全部块失败 → 抛 `LLMCallFailed`；
- Mock 的默认响应（空引用列表）能被引擎正常读回。

**为什么不用 `MockProvider(queue=[...])`**：阶段一是**并发**的，
队列的消费顺序不确定 → 断言「哪块拿到哪个响应」会随机挂。
这里用**按 Prompt 内容分派**的假供应商（`_PhaseProvider`）：
阶段一的 user prompt 含「## 本批章节」，阶段二含「## 全局章节目录」——
按内容分派是确定的，与并发无关。
"""

import json

import pytest

from app.common.errors import LLMCallFailed, LLMOutputInvalid
from app.incremental.link_analyze import MODE_CHUNKED, MODE_FULL, analyze
from app.llm.mock import MockProvider
from app.llm.schemas import LLMRequest, LLMResponse, TokenUsage
from app.models.incremental import PromptTemplate


class _PhaseProvider:
    """按 user prompt 的阶段特征分派响应的假供应商。

    `brief_response` 给阶段一，`compare_response` 给阶段二。
    `fail_brief_ids` 里的章节 id 所在的块**必定**返回坏输出
    （用来测「某块失败只跳过该块」）——按 Prompt 里的章节编号判定，
    与并发完成顺序无关。
    """

    name = "phase"

    def __init__(
        self,
        *,
        brief_response: str,
        compare_response: str,
        fail_brief_ids: set[int] | None = None,
    ) -> None:
        self.brief_response = brief_response
        self.compare_response = compare_response
        self.fail_brief_ids = fail_brief_ids or set()
        self.calls: list[LLMRequest] = []

    def chat(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        if "## 全局章节目录" in req.user:
            content = self.compare_response
        elif self.fail_brief_ids & _prompt_chapter_ids(req.user):
            content = "坏 JSON"
        else:
            content = self.brief_response
        return LLMResponse(
            content=content,
            usage=TokenUsage(),
            model=self.name,
            raw={"index": len(self.calls)},
        )


def _prompt_chapter_ids(user_prompt: str) -> set[int]:
    """从 Prompt 里抠出「章节#N」的编号集合。"""
    import re

    return {int(item) for item in re.findall(r"章节#(\d+)", user_prompt)}


def _template() -> PromptTemplate:
    return PromptTemplate(
        name="临时",
        task_type="chapter_link_analyze",
        system_prompt="[CHAPTER_LINK_ANALYZE_SYSTEM] 测试",
        user_prompt="[CHAPTER_LINK_ANALYZE_USER] 测试",
        version_no=1,
        status="active",
    )


def _chapters(count: int, *, content_len: int = 100) -> list[dict]:
    return [
        {"id": i, "title": f"章{i}", "content": "正" * content_len, "children": []}
        for i in range(1, count + 1)
    ]


def _ref(from_id: int, to_id: int) -> dict:
    return {
        "from_chapter_id": from_id,
        "to_chapter_id": to_id,
        "link_type": "references",
        "confidence": 0.9,
        "rationale": "提到",
    }


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


# ------------------------------------------------------------ 整篇路径


def test_mock_default_response_is_accepted():
    """Mock 默认响应能被引擎读回——不抛异常。"""
    provider = MockProvider()

    result = analyze(
        provider=provider,
        template=_template(),
        document_name="需求",
        version_no=1,
        chapters=_chapters(2),
    )

    assert result.mode == MODE_FULL
    assert result.references == []
    assert result.analyzed_count == 0
    assert result.discarded_count == 0


def test_full_path_calls_model_once():
    """整篇路径只调 1 次模型。"""
    provider = MockProvider()

    analyze(
        provider=provider,
        template=_template(),
        document_name="需求",
        version_no=1,
        chapters=_chapters(3),
    )

    assert len(provider.calls) == 1


def test_full_path_parses_references():
    """整篇路径能读出模型给的引用边。"""
    provider = MockProvider(queue=[_json({"references": [_ref(1, 2), _ref(2, 3)]})])

    result = analyze(
        provider=provider,
        template=_template(),
        document_name="需求",
        version_no=1,
        chapters=_chapters(3),
    )

    assert result.analyzed_count == 2
    assert result.references[0]["from_chapter_id"] == 1
    assert result.references[1]["to_chapter_id"] == 3


def test_out_of_scope_reference_is_discarded_not_stored():
    """越界 id 被丢弃并计入 `discarded_count`。"""
    provider = MockProvider(
        queue=[_json({"references": [_ref(1, 2), _ref(1, 99999)]})]
    )

    result = analyze(
        provider=provider,
        template=_template(),
        document_name="需求",
        version_no=1,
        chapters=_chapters(2),
    )

    assert result.analyzed_count == 1
    assert result.discarded_count == 1


# ------------------------------------------------------------ 两阶段路径


def test_chunked_path_calls_model_per_block_plus_one():
    """两阶段路径：块数次 + 阶段二 1 次。"""
    provider = _PhaseProvider(
        brief_response=_json({"chapters": [{"chapter_id": 1, "title": "章1"}]}),
        compare_response=_json({"references": [_ref(1, 3)]}),
    )

    result = analyze(
        provider=provider,
        template=_template(),
        document_name="需求",
        version_no=1,
        chapters=_chapters(3, content_len=1000),
        full_doc_threshold=100,
        chunk_size=2,
    )

    assert result.mode == MODE_CHUNKED
    # 3 章 / 每块 2 章 = 2 块 + 阶段二 1 次 = 3 次
    assert len(provider.calls) == 3
    assert result.analyzed_count == 1
    assert len(result.briefs) == 2


def test_stage_one_block_failure_skips_only_that_block():
    """阶段一某块失败 → 只跳过该块，其余块照常出摘要。"""
    provider = _PhaseProvider(
        brief_response=_json({"chapters": [{"chapter_id": 3, "title": "章3"}]}),
        compare_response=_json({"references": [_ref(3, 1)]}),
        # 第 1 章所在的那块失败（第 2 块含第 3 章，正常）
        fail_brief_ids={1},
    )

    result = analyze(
        provider=provider,
        template=_template(),
        document_name="需求",
        version_no=1,
        chapters=_chapters(3, content_len=1000),
        full_doc_threshold=100,
        chunk_size=2,
    )

    assert result.mode == MODE_CHUNKED
    assert len(result.skipped_blocks) == 1
    assert result.skipped_blocks[0]["reason"] == "block_failed"
    # 第 2 块的摘要仍然进了全局目录
    assert [brief.chapter_id for brief in result.briefs] == [3]
    assert result.analyzed_count == 1


def test_all_blocks_failing_raises_llm_call_failed():
    """全部块都失败 → 抛 `LLMCallFailed`（整次失败，不产出空结果）。"""
    provider = _PhaseProvider(
        brief_response="",
        compare_response="",
        fail_brief_ids={1, 2, 3},
    )

    with pytest.raises(LLMCallFailed):
        analyze(
            provider=provider,
            template=_template(),
            document_name="需求",
            version_no=1,
            chapters=_chapters(3, content_len=1000),
            full_doc_threshold=100,
            chunk_size=2,
        )


def test_stage_two_bad_output_raises():
    """阶段二返回坏 JSON → 抛 `LLMOutputInvalid`。"""
    provider = _PhaseProvider(
        brief_response=_json({"chapters": [{"chapter_id": 1}]}),
        compare_response="阶段二返回了非 JSON",
    )

    with pytest.raises(LLMOutputInvalid):
        analyze(
            provider=provider,
            template=_template(),
            document_name="需求",
            version_no=1,
            chapters=_chapters(3, content_len=1000),
            full_doc_threshold=100,
            chunk_size=2,
        )


def test_chunked_path_uses_mock_default_response():
    """Mock 默认响应同时满足两阶段的根结构（`chapters` + `references`）。"""
    provider = MockProvider()

    result = analyze(
        provider=provider,
        template=_template(),
        document_name="需求",
        version_no=1,
        chapters=_chapters(3, content_len=1000),
        full_doc_threshold=100,
        chunk_size=2,
    )

    assert result.mode == MODE_CHUNKED
    assert result.analyzed_count == 0
    assert result.skipped_blocks == []
