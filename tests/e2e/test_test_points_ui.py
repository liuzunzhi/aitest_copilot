"""测试点前台核对（T103）。

页面入口：项目详情 →「测试点」Tab。
覆盖：发起生成 → 生成出的测试点出现在列表 → 评审通过 → 状态变「已通过」；
手工新增 → 编辑 → 删除；访客只读（无发起 / 评审 / 增删改入口）。

MockProvider 返回的占位 `target_id` 一定越界（不在依据清单内），
发起生成只会得到 `succeeded` + 0 条测试点；
测试点本体由 `support.seed_test_points` 按真实表结构补写后再核对展示，
评审 / 增删改仍走真实接口。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import pick_select_option as _pick
from tests.e2e.helpers import unique_name as _name
from tests.e2e.support import seed_analysis_conclusions, seed_test_points

pytestmark = pytest.mark.e2e

DOC_MD = """# 登录需求

## 1. 概述

支持账号密码与扫码登录。

## 2. 锁定策略

连续失败 5 次锁定 30 分钟。
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
                "name": "登录需求.md",
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
        data={"comment": "e2e 测试点造快照"},
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


def _first_pass_template(api) -> int:
    response = api.ctx.get(
        "/api/prompt-templates", params={"task_type": "incremental"}, headers=_headers(api)
    )
    assert response.status == 200, response.text()
    items = [item for item in response.json()["items"] if "第二遍" not in item["name"]]
    assert items, "应有第一遍增量分析模板"
    return items[0]["id"]


def _approved_revision(api, project_id: int) -> int:
    response = api.ctx.get(
        f"/api/projects/{project_id}/baselines/revisions?status=approved",
        headers=_headers(api),
    )
    assert response.status == 200, response.text()
    items = response.json()["items"]
    assert items, "应有审核通过的基线快照"
    return items[0]["id"]


def _create_incremental_analysis(api, project_id: int, version_id: int) -> dict:
    response = api.ctx.post(
        f"/api/projects/{project_id}/incremental/analyses",
        data={
            "template_id": _first_pass_template(api),
            "baseline_revision_id": _approved_revision(api, project_id),
            "document_version_id": version_id,
            "split_granularity": "chapter",
        },
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    return response.json()


def _latest_test_point_analysis(api, project_id: int) -> dict:
    response = api.ctx.get(
        f"/api/projects/{project_id}/test-points/analyses", headers=_headers(api)
    )
    assert response.status == 200, response.text()
    items = response.json()["items"]
    assert items, "测试点生成记录应已落库"
    return items[0]


def _point_by_name(api, project_id: int, name: str) -> dict:
    response = api.ctx.get(
        f"/api/projects/{project_id}/test-points/points?page_size=200",
        headers=_headers(api),
    )
    assert response.status == 200, response.text()
    for item in response.json()["items"]:
        if item["name"] == name:
            return item
    raise AssertionError(f"测试点 {name} 未落库")


def _open_test_points(page: Page, project_name: str) -> None:
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="测试点").click()
    expect(page.get_by_test_id("test-point-analysis-table")).to_be_visible()


@pytest.mark.task("T103")
def test_ac_157_generate_review_and_manual_crud_ui(
    admin_page: Page, api, make_user, shot
) -> None:
    """发起生成 → 列表出现 → 评审通过 → 手工新增 / 编辑 / 删除。"""
    project = api.create_project(_name("tp"))
    module = _create_module(api, project["id"], "登录模块")
    function = _create_function(api, project["id"], module["id"], "扫码登录")
    uploaded = _upload_and_activate(api, project["id"])
    _approve_snapshot(api, project["id"], make_user)

    # 没有生效标签时，增量结论就是唯一依据——先造一次成功的增量分析并补结论。
    analysis = _create_incremental_analysis(
        api, project["id"], uploaded["version"]["id"]
    )
    seed_analysis_conclusions(
        analysis["id"],
        [
            {
                "target_type": "function",
                "target_id": function["id"],
                "label_type": "changed",
                "rationale": "锁定策略变更",
            }
        ],
    )

    admin_page.reload()
    _open_test_points(admin_page, project["name"])

    # ---- 发起生成（模板取自数据库，依据选增量分析） ----
    admin_page.get_by_test_id("test-point-analysis-create-btn").click()
    _pick(admin_page, "模板", "测试点生成")
    _pick(admin_page, "增量分析记录", f"分析 #{analysis['id']}")
    admin_page.get_by_test_id("test-point-submit-btn").click()

    expect(admin_page.locator(".ant-message")).to_contain_text("生成完成")
    analysis_table = admin_page.get_by_test_id("test-point-analysis-table")
    expect(analysis_table.get_by_role("row").filter(has_text="成功")).to_be_visible()

    # Mock 只会产出越界目标（0 条），按真实表结构补写两条测试点后核对展示
    tp_analysis = _latest_test_point_analysis(api, project["id"])
    point_ids = seed_test_points(
        tp_analysis["id"],
        project["id"],
        [
            {
                "name": "扫码登录连续失败 5 次锁定",
                "target_type": "function",
                "target_id": function["id"],
                "target_name": "扫码登录",
                "priority": "high",
                "precondition": "账号已存在且未锁定",
                "verification": "连续输错 5 次，提示锁定 30 分钟",
            },
            {
                "name": "扫码登录成功回流",
                "target_type": "function",
                "target_id": function["id"],
                "target_name": "扫码登录",
                "priority": "medium",
            },
        ],
    )
    review_id, keep_id = point_ids

    admin_page.get_by_role("button", name="刷新").click()
    expect(admin_page.get_by_test_id(f"test-point-name-{review_id}")).to_contain_text(
        "扫码登录连续失败 5 次锁定"
    )
    expect(admin_page.get_by_test_id(f"test-point-status-{review_id}")).to_contain_text(
        "待评审"
    )
    shot(admin_page, "generated")

    # ---- 评审通过 ----
    admin_page.get_by_test_id(f"test-point-review-btn-{review_id}").click()
    expect(admin_page.get_by_test_id("test-point-drawer")).to_be_visible()
    expect(admin_page.get_by_test_id("test-point-drawer")).to_contain_text("功能")
    admin_page.get_by_test_id("test-point-review-comment").fill("e2e 通过")
    admin_page.get_by_test_id("test-point-approve-btn").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("已通过")
    expect(admin_page.get_by_test_id("test-point-review-status")).to_contain_text("已通过")
    admin_page.keyboard.press("Escape")
    expect(admin_page.get_by_test_id(f"test-point-status-{review_id}")).to_contain_text(
        "已通过"
    )
    shot(admin_page, "reviewed")

    # ---- 手工新增 ----
    manual_name = "人工补充：验证码错误提示"
    admin_page.get_by_test_id("test-point-create-btn").click()
    admin_page.get_by_test_id("test-point-name-input").fill(manual_name)
    admin_page.locator(".ant-form-item", has_text="目标 ID").locator("input").fill(
        str(function["id"])
    )
    admin_page.get_by_test_id("test-point-edit-submit-btn").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("测试点已新增")

    manual = _point_by_name(api, project["id"], manual_name)
    expect(admin_page.get_by_test_id(f"test-point-name-{manual['id']}")).to_contain_text(
        manual_name
    )

    # ---- 编辑 ----
    edited_name = "人工补充：验证码错误提示（已修订）"
    admin_page.get_by_test_id(f"test-point-edit-btn-{manual['id']}").click()
    admin_page.get_by_test_id("test-point-name-input").fill(edited_name)
    admin_page.get_by_test_id("test-point-edit-submit-btn").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("测试点已更新")
    expect(admin_page.get_by_test_id(f"test-point-name-{manual['id']}")).to_contain_text(
        edited_name
    )

    # ---- 删除 ----
    admin_page.get_by_test_id(f"test-point-delete-btn-{manual['id']}").click()
    admin_page.locator(".ant-popconfirm:visible").get_by_role("button", name="删除").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("测试点已删除")
    expect(admin_page.get_by_test_id(f"test-point-name-{manual['id']}")).to_have_count(0)
    expect(admin_page.get_by_test_id(f"test-point-name-{keep_id}")).to_be_visible()
    shot(admin_page, "manual-crud")


@pytest.mark.task("T103")
def test_ac_157_guest_readonly_ui(api, make_user, page_as, shot) -> None:
    """访客可看列表，但没有发起生成 / 评审 / 增删改入口。"""
    project = api.create_project(_name("tp-guest"))
    guest = make_user()
    api.add_member(project["id"], guest["id"], "guest")

    page = page_as(guest["username"], path=f"/projects/{project['id']}")
    page.get_by_role("tab", name="测试点").click()
    expect(page.get_by_test_id("test-point-analysis-table")).to_be_visible()
    expect(page.get_by_test_id("test-point-table")).to_be_visible()
    expect(page.get_by_test_id("test-point-analysis-create-btn")).to_have_count(0)
    expect(page.get_by_test_id("test-point-create-btn")).to_have_count(0)
    expect(page.get_by_text("只有项目管理员可以发起生成")).to_be_visible()
    shot(page, "guest-readonly")
