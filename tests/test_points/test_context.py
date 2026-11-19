"""Prompt 组装与输入上下文取数（07-test-points T100）。

覆盖点：

- **严格分段**：模板正文 → 基线目标清单 → 标签依据 → 增量结论 → 章节正文；
- **确定性排序**：清单按 `(target_type, target_id)` 排，同输入必得同输出；
- **截断只砍章节正文**：前缀保持不变；
- **只吃生效标签**：已清除的标签连同其目标**完全不进 Prompt**；
- 「增量结论已全部撤销」的判定。
"""

import pytest
from sqlalchemy.orm import Session

from app.models.document import DocumentChapter
from app.test_points.context import (
    active_label_context,
    analysis_fully_revoked,
    build_system_prompt,
    build_user_prompt,
    conclusion_context,
    render_conclusion_brief,
    render_label_brief,
    render_target_brief,
)
from tests.test_points.helpers import (
    build_chain,
    make_analysis,
    make_conclusion,
    make_label,
)


def _chapter(title: str = "登录", content: str = "账号密码登录") -> DocumentChapter:
    """引擎级用例不需要真章节——用同构的轻量对象即可。"""
    return DocumentChapter(
        version_id=1, parent_id=None, seq=1, level=1, title=title, content=content
    )


# --------------------------------------------------------------- 清单渲染


def test_ac_142_target_brief_is_sorted_deterministically():
    """清单按 `(target_type, target_id)` 排序——同输入必得同输出。

    **Prompt 漂移的防线**：排序键固定，不依赖数据库的默认返回顺序。
    排序键是**元组**，`"feature_point" < "function"`（字典序），
    所以功能点排在功能前面——与 05 的 `render_baseline_brief` 完全一致。
    """
    index = {
        ("feature_point", 5630): "提交订单",
        ("function", 10097): "账号密码登录",
        ("function", 10096): "用户扫码登录",
    }

    brief = render_target_brief(index)

    assert brief.splitlines() == [
        "- 功能点#5630 提交订单",
        "- 功能#10096 用户扫码登录",
        "- 功能#10097 账号密码登录",
    ]
    # 再渲染一次必须逐字节相同
    assert render_target_brief(index) == brief


def test_ac_142_target_brief_is_empty_when_no_target():
    """清单为空 → 空字符串（不渲染空标题段）。"""
    assert render_target_brief({}) == ""


def test_ac_142_target_brief_truncates_and_notes_omission():
    """清单超预算 → 截断并注明省略了多少条。

    让模型知道「还有没列出来的」，比让它以为「基线就这么多」诚实。
    """
    index = {("function", 10000 + i): f"功能{i}" for i in range(50)}

    brief = render_target_brief(index, max_chars=200)

    assert "已省略" in brief
    assert brief.splitlines()[-1].startswith("- （其余")
    assert len(brief) <= 200 + len("- （其余 49 项基线目标已省略）")


# --------------------------------------------------------------- 分段组装


def test_ac_156_prompt_segments_are_strictly_ordered():
    """Prompt 严格分段，顺序固定：模板 → 清单 → 依据 → 结论 → 章节。"""
    template = _template()

    user = build_user_prompt(
        template,
        _chapter(),
        target_brief="- 功能#10096 用户扫码登录",
        label_brief="- [变更] 用户扫码登录（function#10096）",
        conclusion_brief="- 登录 → 用户扫码登录：变更（0.8）",
    )

    assert user.startswith(template.user_prompt)
    segments = [
        "## 可对照的基线目标",
        "## 标签依据",
        "## 增量结论",
        "## 章节：登录",
    ]
    positions = [user.index(seg) for seg in segments]
    assert positions == sorted(positions), f"段落顺序不对：{positions}"
    assert user.endswith("账号密码登录")


def test_ac_156_empty_segments_are_omitted_entirely():
    """空段落整段省略，不留空标题。"""
    template = _template()

    user = build_user_prompt(template, _chapter(), target_brief="- 功能#1 x")

    assert "## 标签依据" not in user
    assert "## 增量结论" not in user
    assert "## 可对照的基线目标" in user


def test_ac_156_system_prompt_comes_from_database():
    """system 原样取自模板，不做任何加工。"""
    template = _template()
    assert build_system_prompt(template) == template.system_prompt


def test_ac_156_truncation_only_cuts_chapter_content():
    """超长时只截章节正文，前缀保持不变。"""
    template = _template()
    chapter = _chapter(content="很长" * 5000)

    user = build_user_prompt(
        template,
        chapter,
        max_chars=300,
        target_brief="- 功能#10096 用户扫码登录",
    )

    assert user.startswith(template.user_prompt)
    assert "## 可对照的基线目标" in user
    assert "## 章节：登录" in user
    assert len(user) <= 300 + len("很长")


# --------------------------------------------------------------- 标签取数


def test_ac_142_only_active_labels_reach_prompt(db: Session):
    """**只吃生效标签**：已清除的标签连同其目标完全不进 Prompt。"""
    chain = build_chain(db)
    function = chain["structure"]["function"]

    active = make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
        status="active",
    )
    cleared = make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=999999,
        label_type="changed",
        status="cleared",
    )

    context = active_label_context(db, project_id=chain["project"].id)

    assert ("function", function.id) in context.index
    assert ("function", 999999) not in context.index
    assert [row["id"] for row in context.labels] == [active.id]
    assert cleared.id not in context.label_ids.values()


def test_ac_142_label_brief_is_sorted_deterministically(db: Session):
    """标签依据段按 `(target_type, target_id, label_type)` 排序。"""
    chain = build_chain(db)
    function = chain["structure"]["function"]

    make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
    )

    context = active_label_context(db, project_id=chain["project"].id)
    brief = render_label_brief(context.labels)

    assert brief.startswith("- [变更]")
    assert f"function#{function.id}" in brief
    # 再渲染一次必须逐字节相同
    assert render_label_brief(context.labels) == brief


def test_ac_142_deleted_target_label_is_skipped(db: Session):
    """目标已删的标签**跳过**——不把悬空 id 喂给模型。"""
    chain = build_chain(db)
    make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=888888,
        label_type="changed",
    )

    context = active_label_context(db, project_id=chain["project"].id)

    assert context.index == {}
    assert context.labels == []


# --------------------------------------------------------------- 结论取数


def test_ac_143_conclusion_context_only_takes_changed_and_affected(db: Session):
    """只取 `changed` / `affected` 的结论——`unchanged` 没有测试价值。"""
    chain = build_chain(db)
    function = chain["structure"]["function"]
    analysis = make_analysis(db, chain)

    make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="function",
        target_id=function.id,
        label_type="changed",
    )
    make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="function",
        target_id=function.id + 1,
        label_type="unchanged",
    )

    context = conclusion_context(db, analysis_id=analysis.id)

    assert len(context.items) == 1
    assert context.items[0]["label_type"] == "changed"
    assert context.items[0]["target_name"] == function.name


def test_ac_143_conclusion_brief_is_sorted_deterministically(db: Session):
    """结论段按 `(chapter_id, target_type, target_id)` 排序。"""
    chain = build_chain(db)
    function = chain["structure"]["function"]
    analysis = make_analysis(db, chain)

    make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="function",
        target_id=function.id,
        label_type="changed",
    )

    context = conclusion_context(db, analysis_id=analysis.id)
    brief = render_conclusion_brief(context.items)

    assert "用户扫码登录" in brief
    assert render_conclusion_brief(context.items) == brief


# --------------------------------------------------------------- 全部撤销


def test_ac_143_fully_revoked_analysis(db: Session):
    """增量结论产出的标签**全部**被清除 → 视为「已全部撤销」。"""
    chain = build_chain(db)
    function = chain["structure"]["function"]
    analysis = make_analysis(db, chain)

    make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
        status="cleared",
        source_analysis_id=analysis.id,
    )

    assert analysis_fully_revoked(db, analysis_id=analysis.id) is True


def test_ac_143_partially_revoked_analysis(db: Session):
    """还有一条生效标签 → 不算全部撤销。"""
    chain = build_chain(db)
    function = chain["structure"]["function"]
    analysis = make_analysis(db, chain)

    make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
        status="cleared",
        source_analysis_id=analysis.id,
    )
    make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id + 1,
        label_type="affected",
        status="active",
        source_analysis_id=analysis.id,
    )

    assert analysis_fully_revoked(db, analysis_id=analysis.id) is False


def test_ac_143_analysis_without_labels_is_not_revoked(db: Session):
    """**没有标签 ≠ 全部撤销**：一条标签都没有说明没产出可打标的东西。"""
    chain = build_chain(db)
    analysis = make_analysis(db, chain)

    assert analysis_fully_revoked(db, analysis_id=analysis.id) is False


def _template():
    """借用 05 的模板做 Prompt 组装用例（只关心分段与截断，不关心模板内容）。"""
    from app.models.incremental import PromptTemplate

    return PromptTemplate(
        id=1,
        name="测试点生成·基于标签与增量结论",
        task_type="test_point",
        system_prompt="[TEST_POINT_SYSTEM] 你是测试设计助手。",
        user_prompt="[TEST_POINT_USER] 请基于下面的依据设计测试点。",
        version_no=1,
        status="active",
    )
