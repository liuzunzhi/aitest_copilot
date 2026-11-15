"""前台权限边界（AC-47 / 48）。

非成员、member 两种身份检查项目内管理入口，普通用户检查 /admin 页面。
"""

import uuid

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def _name(prefix: str) -> str:
    return f"e2e-{prefix}-{uuid.uuid4().hex[:6]}"


@pytest.mark.task("T42")
def test_ac_47_member_sees_no_manage_entry_ui(api, make_user, page_as, shot) -> None:
    project = api.create_project(_name("access"))
    member = make_user()
    api.add_member(project["id"], member["id"], "member")

    page = page_as(member["username"])
    row = page.get_by_role("row").filter(has_text=project["name"])
    expect(row).to_be_visible()
    expect(row).to_contain_text("成员")
    expect(row.get_by_role("button", name="编辑")).to_have_count(0)
    expect(row.get_by_role("button", name="归档")).to_have_count(0)
    # 侧边栏不应出现系统管理入口
    expect(page.get_by_role("link", name="全局申请")).to_have_count(0)
    shot(page, "member-project-list")

    row.get_by_role("button", name="详情").click()
    page.get_by_role("tab", name="成员").click()
    expect(page.get_by_test_id("member-table")).to_be_visible()
    expect(page.get_by_role("button", name="添加成员")).to_have_count(0)
    shot(page, "member-detail")


@pytest.mark.task("T42")
def test_ac_48_user_blocked_from_admin_ui(make_user, page_as, shot) -> None:
    user = make_user()

    page = page_as(user["username"], path="/admin/applications")
    expect(page.get_by_text("无权访问")).to_be_visible()
    expect(page.get_by_text("仅系统管理员可查看全局申请记录")).to_be_visible()
    shot(page, "admin-403")
