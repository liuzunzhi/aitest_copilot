"""增量分析前台核对（T70）。

页面入口：项目详情 →「增量分析」Tab。
覆盖：项目管理员发起分析 → 列表出现「成功」记录 → 详情抽屉看到结论与丢弃明细；
访客无发起入口（只读记录列表）。

本期模型侧只有 MockProvider，发起分析只会产出空结论；
结论 / 丢弃明细由 `support.seed_analysis_conclusions` 按真实表结构补写后再核对展示。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import pick_select_option as _pick
from tests.e2e.helpers import unique_name as _name
from tests.e2e.support import seed_analysis_conclusions

pytestmark = pytest.mark.e2e

DOC_MD = """# 支付需求

## 1. 概述

支付支持扫码与刷卡。

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
    """上传一份 md 并确认生效（生效版本才能参与分析）。"""
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
    """提交基线审核并由另一位项目管理员通过，得到 approved 快照。"""
    from tests.e2e.support import USER_PASSWORD, token_for

    reviewer = make_user()
    api.add_member(project_id, reviewer["id"], "project_admin")
    reviewer_token = token_for(api.ctx, reviewer["username"], USER_PASSWORD)

    submit = api.ctx.post(
        f"/api/projects/{project_id}/baselines/reviews/submit",
        data={"comment": "e2e 增量分析造快照"},
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


def _open_incremental(page: Page, project_name: str) -> None:
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="增量分析").click()
    expect(page.get_by_test_id("incremental-analysis-table")).to_be_visible()


@pytest.mark.task("T70")
def test_ac_77_79_create_then_detail_ui(admin_page: Page, api, make_user, shot) -> None:
    """发起分析 → 列表出现 succeeded → 详情抽屉结论 / 丢弃明细可见。"""
    project = api.create_project(_name("inc"))
    module = _create_module(api, project["id"], "支付模块")
    function = _create_function(api, project["id"], module["id"], "扫码支付")
    _upload_and_activate(api, project["id"])
    _approve_snapshot(api, project["id"], make_user)

    admin_page.reload()
    _open_incremental(admin_page, project["name"])
    expect(admin_page.get_by_test_id("incremental-create-btn")).to_be_visible()

    _pick(admin_page, "基线快照", "v1.0")
    _pick(admin_page, "文档版本", "支付需求 · V1")
    admin_page.get_by_test_id("incremental-create-btn").click()

    expect(admin_page.locator(".ant-message")).to_contain_text("分析完成")
    table = admin_page.get_by_test_id("incremental-analysis-table")
    expect(table.get_by_role("row").filter(has_text="成功")).to_be_visible()
    stats = admin_page.locator("[data-testid^='incremental-stats-']").first
    expect(stats).to_contain_text("/ 0 / 0")
    shot(admin_page, "created")

    # Mock 只返回空结论，按真实表结构补写结论与丢弃明细后再核对展示
    analysis = _latest_analysis(api, project["id"])
    seed_analysis_conclusions(
        analysis["id"],
        [
            {
                "target_type": "function",
                "target_id": function["id"],
                "label_type": "changed",
                "rationale": "支付接口新增字段",
            },
            {
                "target_type": "function",
                "target_id": function["id"],
                "label_type": "affected",
                "rationale": "回调流程受影响",
            },
            {
                "target_type": "function",
                "target_id": 999999,
                "label_type": "changed",
                "discard": True,
                "code": "INCREMENTAL_TARGET_OUT_OF_BASELINE",
            },
        ],
    )

    admin_page.get_by_test_id(f"incremental-detail-btn-{analysis['id']}").click()
    conclusions = admin_page.get_by_test_id("incremental-conclusion-table")
    expect(conclusions).to_contain_text("支付接口新增字段")
    expect(conclusions).to_contain_text("受影响")
    expect(conclusions).to_contain_text(f"功能 #{function['id']}")
    discarded = admin_page.get_by_test_id("incremental-discarded-table")
    expect(discarded).to_contain_text("目标不在基线内")
    expect(discarded).to_contain_text("功能 #999999")
    shot(admin_page, "detail")


@pytest.mark.task("T70")
def test_ac_82_guest_has_no_create_entry_ui(api, make_user, page_as, shot) -> None:
    """访客可看记录列表，但没有「发起分析」入口。"""
    project = api.create_project(_name("inc-guest"))
    guest = make_user()
    api.add_member(project["id"], guest["id"], "guest")

    page = page_as(guest["username"], path=f"/projects/{project['id']}")
    page.get_by_role("tab", name="增量分析").click()
    expect(page.get_by_test_id("incremental-analysis-table")).to_be_visible()
    expect(page.get_by_test_id("incremental-create-btn")).to_have_count(0)
    expect(page.get_by_test_id("incremental-baseline-select")).to_have_count(0)
    expect(page.get_by_text("只有项目管理员可以发起增量分析")).to_be_visible()
    shot(page, "guest-readonly")
