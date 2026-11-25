"""AI 分析引擎的纯函数（12-chapter-link-ai T131）。

覆盖输出解析的三条硬规矩：① 越界 id 丢弃；② 自引用丢弃；
③ 非法 link_type 丢弃。坏条目**只丢该条**，不整次失败。
"""

import json
from decimal import Decimal

import pytest

from app.common.errors import LLMOutputInvalid
from app.incremental.link_analyze import (
    ChapterBrief,
    analyze,
    chunk_chapters,
    flatten_chapters,
    parse_briefs,
    parse_references,
    render_chapter_briefs,
    render_chapter_list,
    total_content_chars,
)
from app.llm.mock import MockProvider
from app.llm.schemas import LLMRequest

CHAPTER_IDS = {1, 2, 3}


def _resp(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _ref(from_id: int, to_id: int, **overrides) -> dict:
    item = {
        "from_chapter_id": from_id,
        "to_chapter_id": to_id,
        "link_type": "references",
        "confidence": 0.85,
        "rationale": "提到见另一章",
    }
    item.update(overrides)
    return item


# ------------------------------------------------------------ 越界即丢


def test_out_of_scope_id_is_dropped():
    """模型编造的 id 越界 → 丢弃该条，不落脏数据。"""
    content = _resp(
        {
            "references": [
                _ref(1, 2),
                _ref(1, 99999),  # to 越界
                _ref(88888, 2),  # from 越界
            ]
        }
    )

    references, discarded = parse_references(content, chapter_ids=CHAPTER_IDS)

    assert len(references) == 1
    assert references[0]["from_chapter_id"] == 1
    assert references[0]["to_chapter_id"] == 2
    assert discarded == 2


def test_self_reference_is_dropped():
    """自引用 → 丢弃。"""
    content = _resp({"references": [_ref(2, 2), _ref(1, 3)]})

    references, discarded = parse_references(content, chapter_ids=CHAPTER_IDS)

    assert len(references) == 1
    assert references[0]["from_chapter_id"] == 1
    assert discarded == 1


def test_invalid_link_type_is_dropped():
    """非法 link_type → 丢弃该条。"""
    content = _resp(
        {"references": [_ref(1, 2, link_type="unknown"), _ref(2, 3)]}
    )

    references, discarded = parse_references(content, chapter_ids=CHAPTER_IDS)

    assert len(references) == 1
    assert references[0]["link_type"] == "references"
    assert discarded == 1


def test_duplicated_reference_is_dropped():
    """同源同类型同目标重复 → 只留一条（对齐 `uk_chlinks_to_chapter` 唯一键）。"""
    content = _resp({"references": [_ref(1, 2), _ref(1, 2)]})

    references, discarded = parse_references(content, chapter_ids=CHAPTER_IDS)

    assert len(references) == 1
    assert discarded == 1


def test_same_pair_different_type_kept():
    """同源同目标但 link_type 不同 → 两条都留（唯一键含 link_type）。"""
    content = _resp(
        {"references": [_ref(1, 2), _ref(1, 2, link_type="depends_on")]}
    )

    references, discarded = parse_references(content, chapter_ids=CHAPTER_IDS)

    assert len(references) == 2
    assert discarded == 0


def test_confidence_is_clamped_to_decimal():
    """置信度收敛到 [0,1] 并转成两位小数（DECIMAL(3,2) 口径）。"""
    content = _resp(
        {
            "references": [
                _ref(1, 2, confidence=1.7),
                _ref(2, 3, confidence=-0.5),
            ]
        }
    )

    references, _ = parse_references(content, chapter_ids=CHAPTER_IDS)

    assert references[0]["confidence"] == Decimal("1.00")
    assert references[1]["confidence"] == Decimal("0.00")


def test_rationale_is_clipped():
    """理由截断到 500 字（DB 列宽口径）。"""
    content = _resp({"references": [_ref(1, 2, rationale="理" * 900)]})

    references, _ = parse_references(content, chapter_ids=CHAPTER_IDS)

    assert len(references[0]["rationale"]) == 500


def test_bool_is_not_treated_as_int():
    """`True` 不该被当成章节 id 1（Python 的 bool 是 int 子类）。"""
    content = _resp({"references": [_ref(1, 2, from_chapter_id=True)]})

    references, discarded = parse_references(content, chapter_ids=CHAPTER_IDS)

    assert references == []
    assert discarded == 1


def test_bad_root_structure_raises():
    """根结构不是 `{"references": [...]}` → 整次失败（`LLMOutputInvalid`）。"""
    with pytest.raises(LLMOutputInvalid):
        parse_references(_resp({"conclusions": []}), chapter_ids=CHAPTER_IDS)


def test_missing_references_key_raises():
    """缺 `references` 键 → 整次失败。"""
    with pytest.raises(LLMOutputInvalid):
        parse_references(_resp({"other": 1}), chapter_ids=CHAPTER_IDS)


def test_empty_references_is_not_failure():
    """`{"references": []}` → 不算失败（模型没找到引用是正常结果）。"""
    references, discarded = parse_references(_resp({"references": []}), chapter_ids=CHAPTER_IDS)

    assert references == []
    assert discarded == 0


# ------------------------------------------------------------ 阶段一解析


def test_parse_briefs_normalizes_entities():
    """阶段一输出解析成摘要卡片，实体去重且限长。"""
    content = _resp(
        {
            "chapters": [
                {
                    "chapter_id": 1,
                    "title": "登录",
                    "summary": "账号密码登录",
                    "entities": ["用户登录", "用户登录", "  ", "登录失败"],
                }
            ]
        }
    )

    briefs = parse_briefs(content)

    assert len(briefs) == 1
    assert briefs[0].chapter_id == 1
    assert briefs[0].summary == "账号密码登录"
    assert briefs[0].entities == ["用户登录", "登录失败"]


def test_parse_briefs_drops_bad_entries_only():
    """阶段一某条结构不对 → 只丢该条。"""
    content = _resp(
        {
            "chapters": [
                {"chapter_id": 1, "title": "A"},
                {"title": "没有 id"},
                {"chapter_id": 2, "title": "B"},
            ]
        }
    )

    briefs = parse_briefs(content)

    assert [brief.chapter_id for brief in briefs] == [1, 2]


def test_parse_briefs_bad_root_raises():
    """阶段一根结构不对 → 抛 `LLMOutputInvalid`。"""
    with pytest.raises(LLMOutputInvalid):
        parse_briefs(_resp({"references": []}))


# ------------------------------------------------------------ 章节工具


def test_flatten_chapters_is_preorder():
    """章节树按前序展开。"""
    tree = [
        {
            "id": 1,
            "title": "一",
            "content": "a",
            "children": [{"id": 2, "title": "1.1", "content": "b", "children": []}],
        },
        {"id": 3, "title": "二", "content": "c", "children": []},
    ]

    flat = flatten_chapters(tree)

    assert [item["id"] for item in flat] == [1, 2, 3]


def test_total_content_chars():
    """全篇正文字符数 = 各章正文长度之和。"""
    chapters = [{"id": 1, "content": "abc"}, {"id": 2, "content": "de"}]

    assert total_content_chars(chapters) == 5


def test_chunk_chapters_keeps_order():
    """按块数切分，块内与块间顺序都不变。"""
    chapters = [{"id": i} for i in range(1, 6)]

    blocks = chunk_chapters(chapters, 2)

    assert [len(block) for block in blocks] == [2, 2, 1]
    assert [item["id"] for block in blocks for item in block] == [1, 2, 3, 4, 5]


def test_chunk_chapters_rejects_non_positive_size():
    """块大小必须为正。"""
    with pytest.raises(ValueError):
        chunk_chapters([{"id": 1}], 0)


# ------------------------------------------------------------ 清单渲染


def test_render_chapter_list_carries_ids():
    """章节清单必须带 id（防模型编 id 的第一道防线）。"""
    lines = render_chapter_list([{"id": 12, "title": "2.1 登录流程"}])

    assert lines == ["- 章节#12 2.1 登录流程"]


def test_render_chapter_briefs_includes_summary_and_entities():
    """全局目录清单含摘要与实体。"""
    lines = render_chapter_briefs(
        [ChapterBrief(chapter_id=1, title="登录", summary="账号密码登录", entities=["用户登录"])]
    )

    assert lines[0] == "- 章节#1 登录"
    assert "摘要：账号密码登录" in lines[1]
    assert "实体：用户登录" in lines[2]


# ------------------------------------------------------------ 阈值分流


def test_small_document_uses_full_path():
    """小文档 → 整篇一次调用（只调 1 次模型）。"""
    provider = MockProvider()
    template = _template()

    result = analyze(
        provider=provider,
        template=template,
        document_name="需求",
        version_no=1,
        chapters=[{"id": 1, "title": "一", "content": "短正文"}],
    )

    assert result.mode == "full"
    assert len(provider.calls) == 1


def test_large_document_uses_chunked_path():
    """大文档 → 两阶段（块数 + 1 次调用）。"""
    provider = MockProvider()
    template = _template()

    chapters = [
        {"id": i, "title": f"章{i}", "content": "正" * 1000}
        for i in range(1, 6)
    ]
    result = analyze(
        provider=provider,
        template=template,
        document_name="需求",
        version_no=1,
        chapters=chapters,
        full_doc_threshold=100,
        chunk_size=2,
    )

    assert result.mode == "chunked"
    # 5 章 / 每块 2 章 = 3 块 + 阶段二 1 次 = 4 次调用
    assert len(provider.calls) == 4

def _template():
    """一个最小的模板对象（只需要两个 prompt 字段）。"""
    from app.models.incremental import PromptTemplate

    return PromptTemplate(
        name="临时",
        task_type="chapter_link_analyze",
        system_prompt="[CHAPTER_LINK_ANALYZE_SYSTEM] 测试",
        user_prompt="[CHAPTER_LINK_ANALYZE_USER] 测试",
        version_no=1,
        status="active",
    )
