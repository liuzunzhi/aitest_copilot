"""AC-121 · 第一遍 Prompt 里的基线目标清单。

**为什么必须有**：真实模型不会像 Mock 那样凭空知道 `target_id`。
第一遍模板文案本身就写着「并与比对基准基线中的功能 / 功能点对照」，
但基线清单从来没给过——于是模型只能瞎猜 id，猜出来的**全部被 AC-79
当越界丢弃**，整次分析跑完一条结论都没有。

Mock 时代这个洞一直隐形：测试用例直接硬编码了正确的 `target_id`。
这是「Mock 通过 ≠ 真实模型能跑」的典型例子（L2 真实联调踩出来的）。

**判定逻辑未变**：字段校验、标签分类、丢弃规则、错误码全部原样。
这里只断言「喂给模型什么」。
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.incremental.context import (
    BASELINE_BRIEF_MAX_RATIO,
    build_user_prompt,
    render_baseline_brief,
)
from tests.incremental import helpers as H


def _index() -> dict[tuple[str, int], str]:
    return {
        ("function", 10096): "用户扫码登录",
        ("function", 10097): "账号密码登录",
        ("feature_point", 5630): "扫码入口",
    }


def test_ac_121_brief_lists_all_targets():
    """清单列出全部可用目标，标注类型与 id。"""
    brief = render_baseline_brief(_index())

    assert "功能#10096 用户扫码登录" in brief
    assert "功能#10097 账号密码登录" in brief
    assert "功能点#5630 扫码入口" in brief


def test_ac_121_brief_is_stable_order():
    """渲染顺序稳定——否则 Prompt 不可复现，问题无法复现。"""
    first = render_baseline_brief(_index())
    second = render_baseline_brief(dict(reversed(list(_index().items()))))

    assert first == second


def test_ac_121_brief_empty_index():
    """索引为空 → 清单为空（不产出「## 可对照的基线目标」空段）。"""
    assert render_baseline_brief({}) == ""


def test_ac_121_brief_truncates_and_notes_omitted():
    """清单过长时截断，并注明省略了多少条。"""
    index = {("function", 1000 + i): f"功能{i}" for i in range(200)}

    brief = render_baseline_brief(index, max_chars=500)

    assert "已省略" in brief
    # 省略数要对得上
    omitted_line = [line for line in brief.splitlines() if "已省略" in line][0]
    assert "其余" in omitted_line


def test_ac_121_brief_ratio_leaves_room_for_body():
    """清单最多占输入预算的一部分，剩下的留给章节正文。"""
    index = {("function", 1000 + i): f"功能{i}" for i in range(200)}

    brief = render_baseline_brief(index, max_chars=1000)

    assert len(brief) <= int(1000 * BASELINE_BRIEF_MAX_RATIO) + 40


def test_ac_121_prompt_contains_brief_and_keeps_prefix(client: TestClient, db: Session, provider):
    """Prompt 里既有基线清单，又仍以模板 user_prompt 开头（AC-78 不破）。"""
    chain = H.build_chain(db, chapters=[("登录", "账号密码登录")])
    headers = H.login(client, chain["admin"])
    provider.queue = [json.dumps({"conclusions": []})]

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )
    assert response.status_code == 201, response.text

    request = provider.calls[0]
    function_id = chain["structure"]["function"].id
    assert request.user.startswith(chain["template"].user_prompt)
    assert "## 可对照的基线目标" in request.user
    assert f"功能#{function_id} 下单" in request.user
    # 章节标题与正文仍在
    assert "## 章节：登录" in request.user
    assert "账号密码登录" in request.user


def test_ac_121_build_user_prompt_without_brief_unchanged():
    """不传清单时组装结果与原来完全一致（向后兼容）。"""
    template = type("T", (), {"user_prompt": "[U] 模板"})()
    chapter = type("C", (), {"title": "登录", "content": "正文"})()

    result = build_user_prompt(template, chapter)

    assert result == "[U] 模板\n\n## 章节：登录\n正文"
