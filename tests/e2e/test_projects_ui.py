"""项目生命周期与成员管理的前台核对（AC-32 / 33 / 34 / 35 / 36 / 37 / 38）。

数据用 API 造，UI 只验证被检查的那一步。每个用例自建项目，互不依赖。
"""

import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import ADMIN_USERNAME

pytestmark = pytest.mark.e2e


def _name(prefix: str) -> str:
    return f"e2e-{prefix}-{uuid.uuid4().hex[:6]}"


def _open_detail(page: Page, project_name: str) -> None:
    row = page.get_by_role("row").filter(has_text=project_name)
    row.get_by_role("button", name="详情").click()


@pytest.mark.task("T29")
def test_ac_32_edit_project_ui(admin_page: Page, api, shot) -> None:
    project = api.create_project(_name("edit"), "原简介")
    admin_page.reload()

    admin_page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
        "button", name="编辑"
    ).click()

    new_name = _name("edited")
    admin_page.get_by_test_id("project-name").fill(new_name)
    admin_page.get_by_test_id("project-description").fill('')
    admin_page.get_by_test_id("modal-ok").click()

    new_row = admin_page.get_by_role("row").filter(has_text=new_name)
    expect(new_row).to_be_visible()
    expect(new_row).to_contain_text('—')  # 简介清空后展示占位
    expect(admin_page.get_by_role("row").filter(has_text=project["name"])).to_have_count(0)
    shot(admin_page, "edited")


@pytest.mark.task("T30")
def test_ac_33_34_archived_project_ui(admin_page: Page, api, shot) -> None:
    project = api.create_project(_name("archived"))
    api.archive_project(project["id"])
    admin_page.reload()

    row = admin_page.get_by_role("row").filter(has_text=project["name"])
    expect(row).to_contain_text("已归档")
    # AC-33：重复归档入口消失，不再产生第二条记录
    expect(row.get_by_role("button", name="归档")).to_have_count(0)
    expect(row.get_by_role("button", name="编辑")).to_have_count(0)
    expect(admin_page.get_by_role("row").filter(has_text=project["name"])).to_have_count(1)
    shot(admin_page, "archived-list")

    # AC-34：概览仍可看，写操作被拒绝并给出中文提示
    _open_detail(admin_page, project["name"])
    expect(admin_page.get_by_test_id("project-overview")).to_be_visible()
    admin_page.get_by_role("tab", name="成员").click()
    admin_page.get_by_role("button", name="添加成员").click()
    admin_page.get_by_label("用户 ID").fill('1')
    admin_page.get_by_test_id("modal-ok").click()

    expect(admin_page.locator(".ant-message")).to_contain_text("项目已归档")
    shot(admin_page, "archived-readonly")


@pytest.mark.task("T32")
def test_ac_35_to_38_member_management_ui(admin_page: Page, api, make_user, shot) -> None:
    project = api.create_project(_name("member"))
    member = make_user()
    admin_page.reload()

    _open_detail(admin_page, project["name"])
    admin_page.get_by_role("tab", name="成员").click()
    table = admin_page.get_by_test_id("member-table")

    # AC-35：只展示用户名与角色
    expect(table.get_by_role("columnheader", name="用户名")).to_be_visible()
    expect(table.get_by_role("columnheader", name="角色")).to_be_visible()
    expect(table).to_contain_text(ADMIN_USERNAME)
    expect(admin_page.get_by_text("邮箱")).to_have_count(0)
    expect(admin_page.get_by_text("手机号")).to_have_count(0)
    shot(admin_page, "members-initial")

    # AC-36：添加成员
    admin_page.get_by_role("button", name="添加成员").click()
    admin_page.get_by_label("用户 ID").fill(str(member["id"]))
    admin_page.get_by_test_id("modal-ok").click()

    row = table.get_by_role("row").filter(has_text=member["username"])
    expect(row).to_be_visible()
    expect(row).to_contain_text("成员")
    shot(admin_page, "member-added")

    # AC-37：改角色
    row.get_by_role("combobox").click()
    admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option", has_text="访客"
    ).click()
    expect(row).to_contain_text("访客")
    shot(admin_page, "member-role-changed")

    # AC-38：移除
    row.get_by_role("button", name="移除").click()
    admin_page.locator("button:visible", has_text="移除").last.click()
    expect(row).to_have_count(0)
    shot(admin_page, "member-removed")
