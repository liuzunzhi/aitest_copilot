"""用户管理页：全局角色分配与即时生效（AC-45 / AC-46）。"""

import pytest
from playwright.sync_api import expect

from tests.e2e.support import ADMIN_USERNAME


@pytest.mark.e2e
@pytest.mark.task("T41")
def test_ac_45_promote_and_demote_global_role_ui(api, make_user, admin_page, shot):
    """系统管理员在用户管理页提升 / 降级全局角色，标签即时更新；自己不可改。"""
    user = make_user()
    username = user["username"]

    admin_page.goto("/admin/users")
    expect(admin_page.get_by_role("heading", name="用户管理")).to_be_visible()
    admin_page.get_by_test_id("user-search").fill(username)
    row = admin_page.locator("tr").filter(has_text=username)
    expect(row).to_be_visible()
    expect(row.locator(".ant-tag")).to_have_text("普通用户")

    row.get_by_test_id(f"promote-{username}").click()
    expect(admin_page.get_by_text("已提升为系统管理员")).to_be_visible()
    expect(row.locator(".ant-tag")).to_have_text("系统管理员")
    shot(admin_page, "promoted")

    row.get_by_test_id(f"demote-{username}").click()
    expect(admin_page.get_by_text("已降为普通用户")).to_be_visible()
    expect(row.locator(".ant-tag")).to_have_text("普通用户")
    shot(admin_page, "demoted")

    # 自己的全局角色不可改：行内只显示「当前账号」，没有角色按钮。
    admin_page.get_by_test_id("user-search").fill(ADMIN_USERNAME)
    self_row = admin_page.locator("tr").filter(has_text=ADMIN_USERNAME).first
    expect(self_row.get_by_text("当前账号")).to_be_visible()
    expect(self_row.get_by_test_id(f"promote-{ADMIN_USERNAME}")).to_have_count(0)
    expect(self_row.get_by_test_id(f"demote-{ADMIN_USERNAME}")).to_have_count(0)


@pytest.mark.e2e
@pytest.mark.task("T41")
def test_ac_46_role_change_effective_without_relogin_ui(api, make_user, page_as, shot):
    """提升后原会话刷新即可见管理入口；降级后同一会话访问被拒（AC-46）。"""
    user = make_user()
    page = page_as(user["username"], path="/projects")

    expect(page.get_by_test_id("current-username")).to_have_text(user["username"])
    expect(page.get_by_role("link", name="用户管理")).to_have_count(0)

    api.set_role(user["id"], "system_admin")
    page.reload()
    expect(page.get_by_role("link", name="用户管理")).to_be_visible()
    shot(page, "promoted-menu")

    page.goto("/admin/users")
    expect(page.get_by_role("heading", name="用户管理")).to_be_visible()
    expect(page.get_by_test_id("user-table")).to_be_visible()
    shot(page, "promoted-page")

    api.set_role(user["id"], "user")
    page.goto("/admin/users")
    expect(page.get_by_text("无权访问")).to_be_visible()
    expect(page.get_by_text("仅系统管理员可管理用户")).to_be_visible()
    expect(page.get_by_role("link", name="用户管理")).to_have_count(0)
    shot(page, "demoted-403")
