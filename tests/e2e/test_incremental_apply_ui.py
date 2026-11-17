"""增量分析第三期前台核对（T82）。

页面入口：项目详情 →「增量分析」Tab → 详情抽屉 →「应用产出」区块。
覆盖：管理员应用产出 → 产出标签可见（生效）→ 人工清除后显示「结论已全部撤销」；
访客只读（无应用产出入口）。

Mock 第二遍默认返回 `unchanged`，`unchanged` 不落标签；能落标签的
`changed` 裁决由 `support.seed_second_pass_rows` 按真实表结构补写，
应用产出与清除标签都走真实接口。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import pick_select_option as _pick
from tests.e2e.helpers import unique_name as _name
from tests.e2e.support import seed_second_pass_rows

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
        data={"comment": "e2e 产出段造快照"},
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


def _applied_labels(api, project_id: int, analysis_id: int) -> dict:
    response = api.ctx.get(
        f"/api/projects/{project_id}/incremental/analyses/{analysis_id}/applied-labels",
        headers=_headers(api),
    )
    assert response.status == 200, response.text()
    return response.json()


def _open_incremental(page: Page, project_name: str) -> None:
    """从项目列表进入项目的「增量分析」Tab（详情页是 SPA 路由，先回列表）。"""
    page.goto("/projects")
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="增量分析").click()
    expect(page.get_by_test_id("incremental-analysis-table")).to_be_visible()


def _open_detail(page: Page, analysis_id: int) -> None:
    page.get_by_test_id(f"incremental-detail-btn-{analysis_id}").click()
    expect(page.get_by_test_id("incremental-conclusion-table")).to_be_visible()


@pytest.mark.task("T82")
def test_ac_98_101_apply_then_revoke_ui(admin_page: Page, api, make_user, shot) -> None:
    """应用产出 → 标签生效可见 → 人工清除 → 撤销标记。"""
    project = api.create_project(_name("inc3"))
    module = _create_module(api, project["id"], "支付模块")
    function = _create_function(api, project["id"], module["id"], "扫码支付")
    _upload_and_activate(api, project["id"])
    _approve_snapshot(api, project["id"], make_user)

    admin_page.reload()
    _open_incremental(admin_page, project["name"])
    _pick(admin_page, "基线快照", "v1.0")
    _pick(admin_page, "文档版本", "支付需求 · V1")
    admin_page.get_by_test_id("incremental-create-btn").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("分析完成")

    analysis = _latest_analysis(api, project["id"])
    _open_detail(admin_page, analysis["id"])

    # 第二遍先跑成功，才有应用产出的前提
    admin_page.get_by_test_id("incremental-second-pass-btn").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("第二遍完成")

    # Mock 第二遍默认 unchanged（不落标签），补一条 changed 裁决供产出段落标
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
    )

    _open_incremental(admin_page, project["name"])
    _open_detail(admin_page, analysis["id"])
    applied_table = admin_page.get_by_test_id("incremental-applied-label-table")
    expect(applied_table).to_be_visible()
    expect(applied_table).to_contain_text("还没有产出标签")

    admin_page.get_by_test_id("incremental-apply-btn").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("产出完成")

    expect(applied_table).to_contain_text("扫码支付")
    expect(applied_table).to_contain_text("变更")
    expect(applied_table).to_contain_text("生效")
    expect(admin_page.get_by_test_id("incremental-apply-stats")).to_contain_text("快照 #")
    expect(admin_page.get_by_test_id("incremental-apply-btn")).to_contain_text("重跑产出")
    shot(admin_page, "applied")

    # 人工清除本次产出的全部标签 → 派生「结论已全部撤销」
    applied = _applied_labels(api, project["id"], analysis["id"])
    assert applied["labels"], "产出后应有标签"
    for label in applied["labels"]:
        cleared = api.ctx.post(
            f"/api/projects/{project['id']}/baselines/labels/"
            f"{label['baseline_label_id']}/clear",
            data={"clear_reason": "misjudged"},
            headers=_headers(api),
        )
        assert cleared.status == 200, cleared.text()

    _open_incremental(admin_page, project["name"])
    _open_detail(admin_page, analysis["id"])
    expect(admin_page.get_by_test_id("incremental-apply-revoked")).to_be_visible()
    expect(admin_page.get_by_test_id("incremental-apply-revoked")).to_contain_text(
        "结论已全部撤销"
    )
    expect(admin_page.get_by_test_id("incremental-applied-label-table")).to_contain_text(
        "已清除"
    )
    shot(admin_page, "revoked")


@pytest.mark.task("T82")
def test_ac_102_guest_cannot_apply_ui(api, make_user, page_as, shot) -> None:
    """访客可看产出标签，但没有「应用产出」入口。"""
    project = api.create_project(_name("inc3-guest"))
    module = _create_module(api, project["id"], "支付模块")
    _create_function(api, project["id"], module["id"], "扫码支付")
    uploaded = _upload_and_activate(api, project["id"])
    approved = _approve_snapshot(api, project["id"], make_user)

    created = api.ctx.post(
        f"/api/projects/{project['id']}/incremental/analyses",
        data={
            "template_id": 1,
            "baseline_revision_id": approved["id"],
            "document_version_id": uploaded["version"]["id"],
            "split_granularity": "chapter",
        },
        headers=_headers(api),
    )
    assert created.status in (200, 201), created.text()
    analysis_id = created.json()["id"]

    guest = make_user()
    api.add_member(project["id"], guest["id"], "guest")

    page = page_as(guest["username"], path=f"/projects/{project['id']}")
    page.get_by_role("tab", name="增量分析").click()
    expect(page.get_by_test_id("incremental-analysis-table")).to_be_visible()
    page.get_by_test_id(f"incremental-detail-btn-{analysis_id}").click()
    expect(page.get_by_test_id("incremental-applied-label-table")).to_be_visible()
    expect(page.get_by_test_id("incremental-apply-btn")).to_have_count(0)
    expect(page.get_by_text("只有项目管理员可以应用产出")).to_be_visible()
    shot(page, "guest-readonly")
