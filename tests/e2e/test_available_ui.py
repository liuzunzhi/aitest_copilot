"""可申请项目页：归档后立即消失（AC-33 的前台缺口）+ 提交申请（AC-13）。

页面之前不存在，AC-33 只核对了「已归档」标记与归档入口消失；
补页后在这里补上「从可申请列表消失」这一条。
"""

import uuid

import pytest
from playwright.sync_api import expect


@pytest.mark.e2e
@pytest.mark.task("T30")
def test_ac_33_archived_project_leaves_available_list_ui(api, make_user, page_as, shot):
    """归档后项目从可申请列表消失；未归档的对照项目仍在。"""
    user = make_user()
    archived_name = f"e2e-avail-{uuid.uuid4().hex[:8]}"
    control_name = f"e2e-keep-{uuid.uuid4().hex[:8]}"
    project = api.create_project(archived_name, "待归档，验证从可申请列表消失")
    api.create_project(control_name, "对照项目，归档后仍应可见")

    page = page_as(user["username"], path="/projects/available")
    expect(page.get_by_role("heading", name="可申请项目")).to_be_visible()
    expect(page.get_by_test_id(f"available-{archived_name}")).to_be_visible()
    expect(page.get_by_test_id(f"available-{control_name}")).to_be_visible()
    shot(page, "before-archive")

    api.archive_project(project["id"])
    page.reload()
    expect(page.get_by_role("heading", name="可申请项目")).to_be_visible()
    # 先等对照项目渲染完成，避免「列表还没加载完」被误判成「已消失」。
    expect(page.get_by_test_id(f"available-{control_name}")).to_be_visible()
    expect(page.get_by_test_id(f"available-{archived_name}")).to_have_count(0)
    shot(page, "after-archive")


@pytest.mark.e2e
@pytest.mark.task("T20")
def test_ac_13_submit_application_from_available_page_ui(api, make_user, page_as, shot):
    """在可申请页提交申请 → 提示成功 → 我的申请出现待审批记录。"""
    user = make_user()
    name = f"e2e-apply-{uuid.uuid4().hex[:8]}"
    api.create_project(name, "可申请页提交申请核对")

    page = page_as(user["username"], path="/projects/available")
    row = page.locator("tr").filter(has_text=name)
    expect(row).to_be_visible()
    row.get_by_role("button", name="申请加入").click()

    expect(page.get_by_text(f"申请加入「{name}」")).to_be_visible()
    page.get_by_test_id("apply-reason").fill("前台提交申请的核对")
    page.get_by_test_id("modal-ok").click()
    expect(page.get_by_text("申请已提交，等待项目管理员审批")).to_be_visible()
    shot(page, "submitted")

    page.goto("/applications/mine")
    expect(page.get_by_role("heading", name="我的申请")).to_be_visible()
    expect(page.locator("tr").filter(has_text=name)).to_be_visible()
    expect(page.locator("tr").filter(has_text="待审批")).to_be_visible()
    shot(page, "my-applications")
