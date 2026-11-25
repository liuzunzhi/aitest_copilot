"""AI 分析的 Prompt 组装（12-chapter-link-ai T131）。

三条约定：

1. **同一份输入两次渲染逐字节相同**——Prompt 必须可复现，
   否则问题不可复现、排查无从下手；
2. **超长时只截断章节正文**，前缀（模板 + 文档信息 + 章节清单）保持不变；
3. **章节清单必须带 id**——不给清单模型就会自己编 id
   （06 期 L2 联调翻车的根因）。
"""

from app.incremental.link_analyze import (
    ChapterBrief,
    build_brief_prompt,
    build_compare_prompt,
    build_full_prompt,
)
from app.models.incremental import PromptTemplate

CHAPTERS = [
    {"id": 1, "title": "1 概述", "content": "总体说明。", "children": []},
    {"id": 2, "title": "2 登录", "content": "账号密码登录。", "children": []},
]


def _template() -> PromptTemplate:
    return PromptTemplate(
        name="临时",
        task_type="chapter_link_analyze",
        system_prompt="[CHAPTER_LINK_ANALYZE_SYSTEM] 测试",
        user_prompt="[CHAPTER_LINK_ANALYZE_USER] 请分析章节引用关系。",
        version_no=1,
        status="active",
    )


def test_full_prompt_is_reproducible():
    """同一份输入两次渲染逐字节相同。"""
    template = _template()

    first = build_full_prompt(
        template, document_name="需求", version_no=1, chapters=CHAPTERS
    )
    second = build_full_prompt(
        template, document_name="需求", version_no=1, chapters=CHAPTERS
    )

    assert first == second


def test_full_prompt_contains_chapter_ids():
    """章节清单带 id，且明确告诉模型 id 从哪来。"""
    prompt = build_full_prompt(
        _template(), document_name="需求", version_no=1, chapters=CHAPTERS
    )

    assert "章节#1 1 概述" in prompt
    assert "章节#2 2 登录" in prompt
    assert "from_chapter_id / to_chapter_id 取自这里" in prompt


def test_full_prompt_carries_document_info():
    """文档信息段带文档名与版本号。"""
    prompt = build_full_prompt(
        _template(), document_name="Matrix系统说明书", version_no=3, chapters=CHAPTERS
    )

    assert "## 文档信息" in prompt
    assert "Matrix系统说明书" in prompt
    assert "v3" in prompt


def test_full_prompt_contains_chapter_bodies():
    """章节正文进 Prompt（模型要读正文才能判断引用）。"""
    prompt = build_full_prompt(
        _template(), document_name="需求", version_no=1, chapters=CHAPTERS
    )

    assert "总体说明。" in prompt
    assert "账号密码登录。" in prompt


def test_full_prompt_truncates_body_only():
    """超长时只截断正文，前缀（模板 + 文档信息 + 章节清单）不变。"""
    template = _template()
    chapters = [{"id": 1, "title": "一", "content": "正" * 5000}]

    full = build_full_prompt(
        template, document_name="需求", version_no=1, chapters=chapters
    )
    truncated = build_full_prompt(
        template, document_name="需求", version_no=1, chapters=chapters, max_chars=500
    )

    # 前缀完整保留
    assert truncated.startswith(full[: full.index("## 章节正文")])
    # 正文被砍短
    assert len(truncated) < len(full)
    assert len(truncated) <= 500


def test_brief_prompt_asks_for_this_block_only():
    """阶段一提示词只含本批章节。"""
    prompt = build_brief_prompt(
        _template(),
        document_name="需求",
        version_no=1,
        block=[CHAPTERS[0]],
    )

    assert "章节#1 1 概述" in prompt
    assert "章节#2 2 登录" not in prompt
    assert "总体说明。" in prompt


def test_brief_prompt_is_reproducible():
    """阶段一 Prompt 也必须可复现。"""
    template = _template()

    first = build_brief_prompt(
        template, document_name="需求", version_no=1, block=CHAPTERS
    )
    second = build_brief_prompt(
        template, document_name="需求", version_no=1, block=CHAPTERS
    )

    assert first == second


def test_compare_prompt_contains_global_directory():
    """阶段二提示词含全局目录（id + 标题 + 摘要 + 实体）。"""
    briefs = [
        ChapterBrief(
            chapter_id=1,
            title="1 概述",
            summary="总体说明",
            entities=["用户登录"],
        ),
        ChapterBrief(chapter_id=2, title="2 登录", summary="账号密码登录"),
    ]

    prompt = build_compare_prompt(
        _template(), document_name="需求", version_no=1, briefs=briefs
    )

    assert "## 全局章节目录（from_chapter_id / to_chapter_id 取自这里）" in prompt
    assert "章节#1 1 概述" in prompt
    assert "章节#2 2 登录" in prompt
    assert "摘要：总体说明" in prompt
    assert "实体：用户登录" in prompt


def test_compare_prompt_has_no_raw_body():
    """阶段二只给目录清单，**不给正文**（正文已在阶段一压成摘要）。"""
    briefs = [ChapterBrief(chapter_id=1, title="1 概述", summary="总体说明")]

    prompt = build_compare_prompt(
        _template(), document_name="需求", version_no=1, briefs=briefs
    )

    assert "总体说明" in prompt
    assert "## 章节正文" not in prompt


def test_compare_prompt_is_reproducible():
    """阶段二 Prompt 也必须可复现。"""
    template = _template()
    briefs = [ChapterBrief(chapter_id=1, title="一", summary="摘要")]

    first = build_compare_prompt(
        template, document_name="需求", version_no=1, briefs=briefs
    )
    second = build_compare_prompt(
        template, document_name="需求", version_no=1, briefs=briefs
    )

    assert first == second
