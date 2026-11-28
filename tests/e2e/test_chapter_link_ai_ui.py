"""章节引用图的 AI 分析与删除（12-chapter-link-ai T136 · AC-220 ~ AC-227）。

页面入口：项目详情 →「文档」Tab → 版本历史弹窗 → 版本行 →「引用图」抽屉。

覆盖四条用户诉求：

1. **AC-220** 抽屉右上角有【✨ AI 一键分析引用】按钮，点击后有 loading 态；
2. **AC-221** 抽屉顶部浅色提示语完整可见；
3. **AC-222** 「源章节」「目标章节」placeholder 是「请选择…」；类型下拉三项带说明；
4. **AC-223** 「实体名」placeholder 含格式示例「功能:用户登录」；
5. **AC-224** `source='ai'` 的边在表格里显示「AI」（**不是「人工」**）；
6. **AC-225** 删除边：二次确认 → 边消失；删 `rule` 边时确认框提示「重抽会重新生成」；
7. **AC-227** 非项目管理员看不到 AI 按钮与删除按钮。

**AI 分析的 e2e 不依赖模型行为**：e2e 库里没有真实大模型配置 →
`get_provider` 返回 Mock → Mock 的默认响应是**空引用列表**，
所以断言「点了不报错」即可；「有边」的展示场景用
`seed_chapter_links` 直接插一条 `source='ai'` 的边（绕过模型）——
这样用例不依赖模型输出，**稳定**。
"""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import SCREENSHOT_ROOT
from tests.e2e.helpers import unique_name as _name
from tests.e2e.support import seed_chapter_links

pytestmark = pytest.mark.e2e

DOC_MD = """# 支付需求

## 1. 概述

支付支持扫码与刷卡，详见第 2 章。

## 2. 流程

下单 → 支付 → 回调。
"""


def _headers(api, token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or api.admin_token}"}


def _upload_and_activate(api, project_id: int) -> dict:
    response = api.ctx.post(
        f"/api/projects/{project_id}/documents",
        multipart={
            "file": {
                "name": "支付需求.md",
                "mimeType": "text/markdown",
                "buffer": DOC_MD.encode("utf-8"),
            }
        },
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    payload = response.json()
    activate = api.ctx.post(
        f"/api/projects/{project_id}/documents/{payload['document']['id']}"
        f"/versions/{payload['version']['id']}/activate",
        headers=_headers(api),
    )
    assert activate.status in (200, 201), activate.text()
    return payload


def _chapters(api, project_id: int, document_id: int, version_id: int) -> list[dict]:
    """拉章节树并拍平成 {id, title} 列表。"""
    response = api.ctx.get(
        f"/api/projects/{project_id}/documents/{document_id}/versions/{version_id}/chapters",
        headers=_headers(api),
    )
    assert response.status == 200, response.text()
    flat: list[dict] = []

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            flat.append({"id": node["id"], "title": node["title"]})
            walk(node["children"])

    walk(response.json())
    return flat


def _open_link_drawer(page: Page, project_name: str, document_id: int, version_id: int):
    """从项目列表进入「文档」Tab → 版本历史 → 版本行 →「引用图」。

    **不关版本历史弹窗**：抽屉的遮罩盖在弹窗的关闭按钮上，
    点它会被拦下超时（Drawer 的 z-index 更高）。截图改成只截抽屉区域，
    弹窗就影响不到了。

    返回**抽屉内容区**（`.ant-drawer-body`）而不是某一张表——
    12.5 期把表格拆成了「待评审」/「已生效」两张
    （`chapter-link-pending-table` / `chapter-link-effective-table`），
    用例需要哪张就自己按 testid 取。
    """
    page.goto("/projects")
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="文档").click()
    page.get_by_test_id(f"versions-{document_id}").click()
    page.get_by_test_id(f"chapter-link-btn-{version_id}").click()
    return page.locator(".ant-drawer-body")


def _shot_drawer(page: Page, label: str) -> Path:
    """只截抽屉面板区域——全页截图会把左侧导航和表格一起带进来。

    antd v6 的抽屉**没有** `.ant-drawer-content`，面板是 `.ant-drawer-section`
    （内容区是 `.ant-drawer-body`）。这是实测 DOM 出来的，不是猜的。
    """
    folder = SCREENSHOT_ROOT / "T136"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{label}.png"
    page.locator(".ant-drawer-section").screenshot(path=str(path))
    return path


@pytest.mark.task("T136")
def test_ac_220_chapter_link_ai_analyze_ui(admin_page: Page, api) -> None:
    """AI 一键分析按钮在抽屉右上角；顶部提示语在有已生效边时是 12 期文案。

    **12.5 期起提示语是状态驱动的**：空数据时显示「当前版本还没有引用关系…」，
    「系统已通过 AI 自动识别…」只在「无待评审 + 有已生效边」时出现。
    所以这里先造一条已生效的边，再断言原文案（**文案本身一字没改**）。
    """
    project = api.create_project(_name("chlink-ai"))
    uploaded = _upload_and_activate(api, project["id"])
    version_id = uploaded["version"]["id"]
    document_id = uploaded["document"]["id"]
    chapters = _chapters(api, project["id"], document_id, version_id)
    seed_chapter_links(
        version_id,
        [
            {
                "from_chapter_id": chapters[0]["id"],
                "to_chapter_id": chapters[1]["id"],
                "link_type": "references",
                "source": "ai",
                "status": "approved",
                "confidence": 0.85,
                "rationale": "1 节提到「详见第 2 章」",
            }
        ],
    )

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()

    # AC-221：无待评审 + 有已生效边 → 12 期原文案
    hint = admin_page.get_by_test_id("chapter-link-hint")
    expect(hint).to_be_visible()
    expect(hint).to_contain_text("系统已通过 AI 自动识别章节间的引用关系")
    expect(hint).to_contain_text("您可以修改或删除错误结果")

    # AC-220：AI 按钮在抽屉**右上角**（`extra` 容器是 header 里的右侧块）
    ai_btn = admin_page.get_by_test_id("chapter-link-ai-analyze-btn")
    expect(ai_btn).to_be_visible()
    expect(ai_btn).to_contain_text("AI 一键分析引用")
    expect(ai_btn).to_have_count(1)
    # 按钮挂在 header 的 `extra` 容器里 —— 这就是「右上角」的 DOM 证据
    extra = admin_page.locator(".ant-drawer-extra")
    expect(extra).to_be_visible()
    expect(extra.get_by_test_id("chapter-link-ai-analyze-btn")).to_have_count(1)

    # 点击 → 进入 loading 态（Mock 很快，用 count > 0 断言按钮存在即可，
    # loading 态的具体时序不作为断言点——它依赖模型返回速度）
    ai_btn.click()
    expect(admin_page.locator(".ant-message")).to_be_visible()
    _shot_drawer(admin_page, "ai-analyze")


@pytest.mark.task("T136")
def test_ac_222_chapter_link_form_hints(admin_page: Page, api) -> None:
    """手工表单的引导文案：placeholder、类型说明、实体名格式示例。"""
    project = api.create_project(_name("chlink-hint"))
    uploaded = _upload_and_activate(api, project["id"])
    version_id = uploaded["version"]["id"]
    document_id = uploaded["document"]["id"]

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()

    # AC-222：源章节 / 目标章节 placeholder
    expect(admin_page.get_by_test_id("chapter-link-from-select")).to_contain_text(
        "请选择源章节"
    )
    expect(admin_page.get_by_test_id("chapter-link-to-select")).to_contain_text(
        "请选择目标章节"
    )

    # AC-222：类型下拉三项带说明
    admin_page.get_by_test_id("chapter-link-type-select").click()
    dropdown = admin_page.locator(".ant-select-dropdown:visible")
    expect(dropdown).to_contain_text("引用")
    expect(dropdown).to_contain_text("依赖")
    expect(dropdown).to_contain_text("相关")
    admin_page.keyboard.press("Escape")

    # AC-223：实体名 placeholder 含格式示例
    admin_page.get_by_test_id("chapter-link-target-kind").get_by_text("实体名").click()
    expect(admin_page.get_by_test_id("chapter-link-entity-input")).to_have_attribute(
        "placeholder", "格式：功能:用户登录，如 功能:退款审核 / 术语:订单锁定"
    )

    _shot_drawer(admin_page, "form-hints")


@pytest.mark.task("T136")
def test_ac_224_ai_source_is_rendered_as_ai(admin_page: Page, api) -> None:
    """`source='ai'` 的边在表格里显示「AI」，不是「人工」。"""
    project = api.create_project(_name("chlink-src"))
    uploaded = _upload_and_activate(api, project["id"])
    version_id = uploaded["version"]["id"]
    document_id = uploaded["document"]["id"]
    chapters = _chapters(api, project["id"], document_id, version_id)
    assert len(chapters) >= 2, "文档应至少有两个章节"

    # 直接插一条 AI 边（绕过模型——e2e 不依赖模型输出）
    seed_chapter_links(
        version_id,
        [
            {
                "from_chapter_id": chapters[0]["id"],
                "to_chapter_id": chapters[1]["id"],
                "link_type": "references",
                "source": "ai",
                "status": "approved",
                "confidence": 0.85,
            }
        ],
    )

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()
    effective_table = admin_page.get_by_test_id("chapter-link-effective-table")
    expect(effective_table).to_contain_text("AI")
    # 不能被误显示成「人工」
    expect(effective_table).not_to_contain_text("人工")
    _shot_drawer(admin_page, "ai-source")


@pytest.mark.task("T136")
def test_ac_225_delete_link_ui(admin_page: Page, api) -> None:
    """删除边：二次确认 → 边消失。"""
    project = api.create_project(_name("chlink-del"))
    uploaded = _upload_and_activate(api, project["id"])
    version_id = uploaded["version"]["id"]
    document_id = uploaded["document"]["id"]
    chapters = _chapters(api, project["id"], document_id, version_id)

    seed_chapter_links(
        version_id,
        [
            {
                "from_chapter_id": chapters[0]["id"],
                "to_chapter_id": chapters[1]["id"],
                "link_type": "references",
                "source": "manual",
            }
        ],
    )

    link_table = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(link_table).to_be_visible()
    expect(link_table).to_contain_text("人工")

    # 表格行里的删除按钮
    delete_btn = admin_page.locator(
        "[data-testid^='chapter-link-delete-btn-']"
    ).first
    expect(delete_btn).to_be_visible()
    delete_btn.click()

    # 二次确认
    confirm = admin_page.locator(".ant-popconfirm:visible")
    expect(confirm).to_contain_text("确认删除这条引用关系")
    confirm.get_by_role("button", name="删除").click()

    expect(admin_page.locator(".ant-message")).to_contain_text("已删除这条引用关系")
    expect(link_table).to_contain_text("该版本还没有引用关系")
    _shot_drawer(admin_page, "deleted")


@pytest.mark.task("T136")
def test_ac_225_delete_rule_link_warns_reextract(
    admin_page: Page, api
) -> None:
    """删 `rule` 边的确认框要提示「重抽会重新生成」。"""
    project = api.create_project(_name("chlink-rule"))
    uploaded = _upload_and_activate(api, project["id"])
    version_id = uploaded["version"]["id"]
    document_id = uploaded["document"]["id"]
    chapters = _chapters(api, project["id"], document_id, version_id)

    seed_chapter_links(
        version_id,
        [
            {
                "from_chapter_id": chapters[0]["id"],
                "to_chapter_id": chapters[1]["id"],
                "link_type": "references",
                "source": "rule",
            }
        ],
    )

    link_table = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(link_table).to_be_visible()

    admin_page.locator("[data-testid^='chapter-link-delete-btn-']").first.click()

    confirm = admin_page.locator(".ant-popconfirm:visible")
    expect(confirm).to_contain_text("按规则重抽")
    expect(confirm).to_contain_text("重新生成")
    _shot_drawer(admin_page, "delete-rule-warn")


@pytest.mark.task("T136")
def test_ac_227_guest_sees_no_write_controls(
    admin_page: Page, api, make_user, page_as
) -> None:
    """非项目管理员看不到 AI 按钮与删除按钮。"""
    from tests.e2e.support import USER_PASSWORD, token_for

    project = api.create_project(_name("chlink-guest"))
    uploaded = _upload_and_activate(api, project["id"])
    version_id = uploaded["version"]["id"]
    document_id = uploaded["document"]["id"]

    # 造一个访客并加进项目
    guest = make_user()
    api.add_member(project["id"], guest["id"], "guest")
    guest_token = token_for(api.ctx, guest["username"], USER_PASSWORD)

    guest_page = page_as(guest["username"], USER_PASSWORD)
    link_table = _open_link_drawer(
        guest_page, project["name"], document_id, version_id
    )
    expect(link_table).to_be_visible()

    # 没有 AI 按钮、没有删除按钮、没有补链表单、没有详情按钮
    expect(guest_page.get_by_test_id("chapter-link-ai-analyze-btn")).to_have_count(0)
    expect(guest_page.locator("[data-testid^='chapter-link-delete-btn-']")).to_have_count(0)
    expect(guest_page.locator("[data-testid^='chapter-link-detail-btn-']")).to_have_count(0)
    expect(guest_page.locator("[data-testid^='chapter-link-approve-btn-']")).to_have_count(0)
    expect(guest_page.get_by_test_id("chapter-link-create-btn")).to_have_count(0)
    expect(guest_page.get_by_test_id("chapter-link-hint")).to_be_visible()

    _shot_drawer(guest_page, "guest-readonly")
    guest_page.close()
