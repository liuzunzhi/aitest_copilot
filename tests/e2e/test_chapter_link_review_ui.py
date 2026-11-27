"""章节引用图的人工评审闭环（12.5 期 T143 · AC-233 ~ AC-237）。

页面入口与 12 期一致：项目详情 →「文档」Tab → 版本历史弹窗 → 版本行 →「引用图」抽屉。

覆盖：

- **AC-233** 顶部提示语**按数据状态切换**（空 / 有待评审 / 只有已生效）；
- **AC-234** AI 分析进行中**锁住抽屉**（删除 / 补链 / 下拉全部禁用）；
- **AC-235** 前端**没有**「按规则重抽」入口；
- **AC-236** 表单三个字段都有引导文案，类型下拉是两行式；
- **AC-237** 「详情」弹窗展示 rationale 与置信度。

**不依赖模型**：需要「有待评审的边」就直接
`seed_chapter_links(..., source="ai", status="pending")`；
需要「已生效」就 `status="approved"`。
"""

import re
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
    """进「文档」Tab → 版本历史 → 版本行「引用图」，返回抽屉内容区。

    与 12 期的同一入口；**不关版本历史弹窗**（抽屉遮罩盖住它的关闭按钮），
    截图只截 `.ant-drawer-section`。
    """
    page.goto("/projects")
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="文档").click()
    page.get_by_test_id(f"versions-{document_id}").click()
    page.get_by_test_id(f"chapter-link-btn-{version_id}").click()
    return page.locator(".ant-drawer-body")


def _shot(page: Page, label: str) -> Path:
    """只截抽屉面板（antd v6 没有 `.ant-drawer-content`，面板是 `.ant-drawer-section`）。"""
    folder = SCREENSHOT_ROOT / "T143"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{label}.png"
    page.locator(".ant-drawer-section").screenshot(path=str(path))
    return path


def _project_with_version(api, prefix: str) -> tuple[dict, int, int, list[dict]]:
    project = api.create_project(_name(prefix))
    uploaded = _upload_and_activate(api, project["id"])
    version_id = uploaded["version"]["id"]
    document_id = uploaded["document"]["id"]
    chapters = _chapters(api, project["id"], document_id, version_id)
    assert len(chapters) >= 2, "文档应至少有两个章节"
    return project, document_id, version_id, chapters


# ------------------------------------------------------------ AC-233 提示语三态


@pytest.mark.task("T143")
def test_ac_233_hint_empty_state(admin_page: Page, api) -> None:
    """一条边都没有 → 提示引导去点 AI 分析（而不是 12 期的静态文案）。"""
    project, document_id, version_id, _ = _project_with_version(api, "chlink-h0")

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()

    hint = admin_page.get_by_test_id("chapter-link-hint")
    expect(hint).to_be_visible()
    expect(hint).to_contain_text("还没有引用关系")
    expect(hint).to_contain_text("AI 一键分析引用")
    # 12 期的静态文案**不该**在空数据下出现
    expect(hint).not_to_contain_text("系统已通过 AI 自动识别")
    _shot(admin_page, "ac233-hint-empty")


@pytest.mark.task("T143")
def test_ac_233_hint_pending_state(admin_page: Page, api) -> None:
    """有待评审的边 → 提示「待确认后生效」，并说明不影响传播计算。"""
    project, document_id, version_id, chapters = _project_with_version(api, "chlink-h1")
    seed_chapter_links(
        version_id,
        [
            {
                "from_chapter_id": chapters[0]["id"],
                "to_chapter_id": chapters[1]["id"],
                "link_type": "references",
                "source": "ai",
                "status": "pending",
                "confidence": 0.85,
                "rationale": "1 节提到「详见第 2 章」",
            }
        ],
    )

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()

    hint = admin_page.get_by_test_id("chapter-link-hint")
    expect(hint).to_contain_text("待你确认后生效")
    expect(hint).to_contain_text("1 条")
    expect(hint).to_contain_text("传播计算")
    # 待评审区出现、已生效区为空
    expect(admin_page.get_by_test_id("chapter-link-pending-table")).to_be_visible()
    _shot(admin_page, "ac233-hint-pending")


@pytest.mark.task("T143")
def test_ac_233_hint_effective_state(admin_page: Page, api) -> None:
    """只有已生效边 → 12 期原文案（**一字不改**，只是变成条件显示）。"""
    project, document_id, version_id, chapters = _project_with_version(api, "chlink-h2")
    seed_chapter_links(
        version_id,
        [
            {
                "from_chapter_id": chapters[0]["id"],
                "to_chapter_id": chapters[1]["id"],
                "link_type": "references",
                "source": "ai",
                "status": "approved",
                "confidence": 0.9,
            }
        ],
    )

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()

    hint = admin_page.get_by_test_id("chapter-link-hint")
    expect(hint).to_contain_text("系统已通过 AI 自动识别章节间的引用关系")
    expect(hint).to_contain_text("您可以修改或删除错误结果")
    expect(admin_page.get_by_test_id("chapter-link-effective-table")).to_be_visible()
    _shot(admin_page, "ac233-hint-effective")


# ------------------------------------------------------------ AC-234 分析期间锁抽屉


@pytest.mark.task("T143")
def test_ac_234_analyzing_locks_drawer(admin_page: Page, api) -> None:
    """AI 分析进行中：删除 / 补链 / 下拉全部禁用，AI 按钮自己保持 loading。

    **把 `/links/analyze` 挂起**（route handler 不处理请求）来稳定拿到 analyzing 态——
    Mock 分析几毫秒就返回，直接点根本抓不到中间态。
    """
    project, document_id, version_id, chapters = _project_with_version(api, "chlink-lock")
    seed_chapter_links(
        version_id,
        [
            {
                "from_chapter_id": chapters[0]["id"],
                "to_chapter_id": chapters[1]["id"],
                "link_type": "references",
                "source": "manual",
                "status": "approved",
            }
        ],
    )

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()

    # 挂起分析请求：handler 立即返回、不 continue，请求保持 pending
    admin_page.route("**/links/analyze", lambda route: None)
    ai_btn = admin_page.get_by_test_id("chapter-link-ai-analyze-btn")
    ai_btn.click()

    # 分析中提示
    expect(admin_page.get_by_test_id("chapter-link-analyzing-tip")).to_be_visible()
    # AI 按钮自己进入 loading（它在 ConfigProvider 外，**不能被禁用**）
    expect(ai_btn).to_have_class(re.compile("ant-btn-loading"))
    # 补链按钮显式禁用（双保险）
    expect(admin_page.get_by_test_id("chapter-link-create-btn")).to_be_disabled()
    # 表格里的删除按钮被 ConfigProvider 禁用
    expect(
        admin_page.locator("[data-testid^='chapter-link-delete-btn-']").first
    ).to_be_disabled()
    # 源章节下拉被禁用
    expect(admin_page.get_by_test_id("chapter-link-from-select")).to_have_class(
        re.compile("ant-select-disabled")
    )
    _shot(admin_page, "ac234-analyzing-locked")

    # 收尾：解除挂起（pending 请求会被 abort，前端走 catch，不影响已完成的断言）
    admin_page.unroute("**/links/analyze")


# ------------------------------------------------------------ AC-235 无重抽入口


@pytest.mark.task("T143")
def test_ac_235_no_reextract_entry(admin_page: Page, api) -> None:
    """抽屉里**没有**「按规则重抽」按钮（后端接口仍在，只是入口删了）。"""
    project, document_id, version_id, _ = _project_with_version(api, "chlink-norule")

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()

    expect(admin_page.get_by_test_id("chapter-link-extract-btn")).to_have_count(0)
    expect(drawer_body.get_by_text("按规则重抽")).to_have_count(0)
    _shot(admin_page, "ac235-no-reextract")


# ------------------------------------------------------------ AC-236 表单引导


@pytest.mark.task("T143")
def test_ac_236_form_guidance(admin_page: Page, api) -> None:
    """源章节 / 类型 / 目标章节三个字段都有引导文案；类型下拉两行式。"""
    project, document_id, version_id, _ = _project_with_version(api, "chlink-form")

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()

    # 三个字段的 extra 说明
    expect(drawer_body).to_contain_text("从这里出发的章节")
    expect(drawer_body).to_contain_text("被引用的章节")
    expect(drawer_body).to_contain_text("引用 —— A 提到")

    # 类型下拉：两行式（名称 + 说明）
    admin_page.get_by_test_id("chapter-link-type-select").click()
    dropdown = admin_page.locator(".ant-select-dropdown:visible")
    expect(dropdown).to_contain_text("引用")
    expect(dropdown).to_contain_text("A 章节提到「见 B 章节」")
    expect(dropdown).to_contain_text("依赖")
    expect(dropdown).to_contain_text("A 章节的实现依赖 B 章节")
    admin_page.keyboard.press("Escape")
    _shot(admin_page, "ac236-form-guidance")


# ------------------------------------------------------------ AC-237 详情弹窗


@pytest.mark.task("T143")
def test_ac_237_detail_modal_shows_rationale(admin_page: Page, api) -> None:
    """点「详情」→ 弹窗展示模型给的分析理由与置信度。"""
    project, document_id, version_id, chapters = _project_with_version(api, "chlink-detail")
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
                "rationale": "1 节正文里写了「详见第 2 章」，因此判定为引用",
            }
        ],
    )

    drawer_body = _open_link_drawer(
        admin_page, project["name"], document_id, version_id
    )
    expect(drawer_body).to_be_visible()

    admin_page.locator("[data-testid^='chapter-link-detail-btn-']").first.click()

    modal = admin_page.get_by_test_id("chapter-link-detail-modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("1 节正文里写了「详见第 2 章」")
    expect(modal).to_contain_text("0.85")
    expect(modal).to_contain_text("已生效")
    expect(modal).to_contain_text("AI")
    _shot(admin_page, "ac237-detail-modal")
