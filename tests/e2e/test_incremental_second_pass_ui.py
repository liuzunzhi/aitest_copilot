"""增量分析第二期前台核对（T77）。

页面入口：项目详情 →「增量分析」Tab → 详情抽屉 →「第二遍（全局裁决）」区块；
文档 Tab → 版本行 →「引用图」。

覆盖：管理员触发第二遍 → 裁决与冲突可见 → 确认一条冲突 → 状态更新；
访客只读（无触发 / 裁决入口）；引用图列表可见、管理员可补链。

Mock 第二遍默认返回 `unchanged`，能跑出裁决；冲突与新增由
`support.seed_second_pass_rows` 按真实表结构补写后再核对展示，
裁决动作仍走真实 `resolve` 接口。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import pick_select_option as _pick
from tests.e2e.helpers import unique_name as _name
from tests.e2e.support import seed_chapter_links, seed_second_pass_rows

pytestmark = pytest.mark.e2e

DOC_MD = """# 支付需求

## 1. 概述

支付支持扫码与刷卡，详见第 2 章。

## 2. 流程

下单 → 支付 → 回调。
"""


def _headers(api, token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or api.admin_token}"}


def _create_module(api, project_id: int, name: str) -> dict:
    response = api.ctx.post(
        f"/api/projects/{project_id}/baselines/modules",
        data={"name": name},
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    return response.json()


def _create_function(api, project_id: int, module_id: int, name: str) -> dict:
    response = api.ctx.post(
        f"/api/projects/{project_id}/baselines/functions",
        data={"module_id": module_id, "name": name},
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    return response.json()


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


def _approve_snapshot(api, project_id: int, make_user) -> dict:
    from tests.e2e.support import USER_PASSWORD, token_for

    reviewer = make_user()
    api.add_member(project_id, reviewer["id"], "project_admin")
    reviewer_token = token_for(api.ctx, reviewer["username"], USER_PASSWORD)

    submit = api.ctx.post(
        f"/api/projects/{project_id}/baselines/reviews/submit",
        data={"comment": "e2e 第二遍造快照"},
        headers=_headers(api),
    )
    assert submit.status in (200, 201), submit.text()
    pending = api.ctx.get(
        f"/api/projects/{project_id}/baselines/revisions?status=submitted",
        headers=_headers(api),
    ).json()["items"]
    assert pending, "应有一条审核中的快照"

    approve = api.ctx.post(
        f"/api/projects/{project_id}/baselines/reviews/{pending[0]['id']}/approve",
        data={"comment": "e2e 通过"},
        headers=_headers(api, reviewer_token),
    )
    assert approve.status == 200, approve.text()
    return approve.json()


def _latest_analysis(api, project_id: int) -> dict:
    response = api.ctx.get(
        f"/api/projects/{project_id}/incremental/analyses", headers=_headers(api)
    )
    assert response.status == 200, response.text()
    items = response.json()["items"]
    assert items, "分析记录应已落库"
    return items[0]


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


def _open_incremental(page: Page, project_name: str) -> None:
    """从项目列表进入项目的「增量分析」Tab。

    每次都先回到 `/projects`：详情页是 SPA 路由，`reload()` 不会退回列表，
    而列表页才有「详情」按钮可点。
    """
    page.goto("/projects")
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="增量分析").click()
    expect(page.get_by_test_id("incremental-analysis-table")).to_be_visible()


def _open_detail(page: Page, analysis_id: int) -> None:
    page.get_by_test_id(f"incremental-detail-btn-{analysis_id}").click()
    expect(page.get_by_test_id("incremental-conclusion-table")).to_be_visible()


@pytest.mark.task("T77")
def test_ac_89_93_second_pass_and_resolve_ui(admin_page: Page, api, make_user, shot) -> None:
    """触发第二遍 → 裁决 / 冲突可见 → 确认一条冲突 → 状态更新。"""
    project = api.create_project(_name("inc2"))
    module = _create_module(api, project["id"], "支付模块")
    function = _create_function(api, project["id"], module["id"], "扫码支付")
    uploaded = _upload_and_activate(api, project["id"])
    _approve_snapshot(api, project["id"], make_user)

    admin_page.reload()
    _open_incremental(admin_page, project["name"])

    _pick(admin_page, "基线快照", "v1.0")
    _pick(admin_page, "文档版本", "支付需求 · V1")
    admin_page.get_by_test_id("incremental-create-btn").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("分析完成")

    analysis = _latest_analysis(api, project["id"])
    _open_detail(admin_page, analysis["id"])

    # 触发第二遍：Mock 默认返回 unchanged，能跑出裁决
    admin_page.get_by_test_id("incremental-second-pass-btn").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("第二遍完成")

    decision_table = admin_page.get_by_test_id("incremental-decision-table")
    expect(decision_table).to_be_visible()
    expect(admin_page.get_by_test_id("incremental-second-pass-stats")).to_contain_text(
        "供应商 mock"
    )
    shot(admin_page, "second-pass-done")

    # 冲突展示：按真实表结构补写一条冲突与一条新增
    seed_second_pass_rows(
        analysis["id"],
        decisions=[
            {
                "target_type": "function",
                "target_id": function["id"],
                "target_name": "扫码支付",
                "decision": "changed",
                "confidence": 0.9,
                "rationale": "支付接口新增字段",
            }
        ],
        conflicts=[
            {
                "target_type": "function",
                "target_id": function["id"],
                "target_name": "扫码支付",
                "conflict_type": "conflict",
                "candidates": [
                    {"label_type": "changed", "source": "point_pass"},
                    {"label_type": "unchanged", "source": "point_pass"},
                ],
            },
            {
                "target_type": "feature_point",
                "target_id": None,
                "target_name": "退款审核",
                "conflict_type": "new",
                "candidates": [{"label_type": "new", "source": "point_pass"}],
            },
        ],
    )

    _open_incremental(admin_page, project["name"])
    _open_detail(admin_page, analysis["id"])

    conflict_table = admin_page.get_by_test_id("incremental-conflict-table")
    expect(conflict_table).to_contain_text("证据冲突")
    expect(conflict_table).to_contain_text("新增")
    expect(conflict_table).to_contain_text("退款审核")
    shot(admin_page, "conflicts")

    # 确认第一条冲突
    conflict_id = _conflict_id(api, project["id"], analysis["id"])
    admin_page.get_by_test_id(f"incremental-conflict-resolve-btn-{conflict_id}").click()
    expect(admin_page.locator(".ant-modal:visible")).to_contain_text("确认冲突")
    admin_page.get_by_test_id("incremental-conflict-label-group").get_by_text("变更", exact=True).click()
    admin_page.get_by_test_id("incremental-conflict-confirm-submit").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("已确认该冲突")

    _open_incremental(admin_page, project["name"])
    _open_detail(admin_page, analysis["id"])
    expect(admin_page.get_by_test_id("incremental-conflict-table")).to_contain_text("已确认")
    shot(admin_page, "resolved")


def _conflict_id(api, project_id: int, analysis_id: int) -> int:
    response = api.ctx.get(
        f"/api/projects/{project_id}/incremental/analyses/{analysis_id}/conflicts"
        f"?conflict_type=conflict",
        headers=_headers(api),
    )
    assert response.status == 200, response.text()
    items = response.json()["items"]
    assert items, "应有一条待裁决的冲突"
    return items[0]["id"]


@pytest.mark.task("T77")
def test_ac_95_guest_readonly_second_pass(api, make_user, page_as, shot) -> None:
    """访客可看裁决与冲突，但没有触发 / 裁决入口。"""
    project = api.create_project(_name("inc2-guest"))
    guest = make_user()
    api.add_member(project["id"], guest["id"], "guest")

    page = page_as(guest["username"], path=f"/projects/{project['id']}")
    page.get_by_role("tab", name="增量分析").click()
    expect(page.get_by_test_id("incremental-analysis-table")).to_be_visible()
    expect(page.get_by_test_id("incremental-create-btn")).to_have_count(0)
    shot(page, "guest-readonly")


@pytest.mark.task("T77")
def test_ac_86_chapter_link_ui(admin_page: Page, api, make_user, shot) -> None:
    """文档版本行「引用图」入口 → 列表可见 → 管理员可补链。

    12.5 期把抽屉拆成「待评审」/「已生效」两张表，
    原本的 `chapter-link-table` 不再存在——这里定位**抽屉内容区**。
    """
    project = api.create_project(_name("inc2-links"))
    uploaded = _upload_and_activate(api, project["id"])
    version_id = uploaded["version"]["id"]
    document_id = uploaded["document"]["id"]

    chapters = _chapters(api, project["id"], document_id, version_id)
    assert len(chapters) >= 2, "文档应至少有两个章节"

    admin_page.reload()
    admin_page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
        "button", name="详情"
    ).click()
    admin_page.get_by_role("tab", name="文档").click()
    admin_page.get_by_test_id(f"versions-{document_id}").click()
    admin_page.get_by_test_id(f"chapter-link-btn-{version_id}").click()

    drawer_body = admin_page.locator(".ant-drawer-body")
    expect(drawer_body).to_be_visible()
    expect(drawer_body).to_contain_text("该版本还没有引用关系")

    # 补一条实体引用
    admin_page.get_by_test_id("chapter-link-from-select").click()
    admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option", has_text=chapters[0]["title"]
    ).first.click()
    admin_page.get_by_test_id("chapter-link-target-kind").get_by_text("实体名").click()
    admin_page.get_by_test_id("chapter-link-entity-input").fill("退款审核")
    admin_page.get_by_test_id("chapter-link-create-btn").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("已补一条引用关系")

    effective_table = admin_page.get_by_test_id("chapter-link-effective-table")
    expect(effective_table).to_contain_text("退款审核")
    expect(effective_table).to_contain_text("人工")
    shot(admin_page, "chapter-links")
