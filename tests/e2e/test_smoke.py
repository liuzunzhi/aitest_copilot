"""前台冒烟：登录 → 创建项目 → 概览/成员 → 归档（AC-31 / 33 / 35 / 40）。

用例只在开发库里创建一条 `e2e-project-*`，跑完顺手归档，不留进行中的脏数据。
"""

import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import ADMIN_USERNAME

pytestmark = pytest.mark.e2e


@pytest.mark.task("T31")
def test_login_and_project_list_ui(admin_page: Page, shot) -> None:
    expect(admin_page.get_by_role("heading", name="我的项目")).to_be_visible()
    expect(admin_page.get_by_test_id("current-username")).to_have_text(ADMIN_USERNAME)
    expect(admin_page.get_by_test_id("project-table")).to_be_visible()
    expect(admin_page.get_by_test_id("create-project")).to_be_visible()
    shot(admin_page, "project-list")


@pytest.mark.task("T28")
def test_ac_31_project_lifecycle_ui(admin_page: Page, shot) -> None:
    """创建 → 列表可见 → 概览 → 成员 → 归档（AC-31 / 33 / 35 / 40）。"""
    name = f"e2e-project-{uuid.uuid4().hex[:8]}"

    # 创建（AC-31）
    admin_page.get_by_test_id("create-project").click()
    admin_page.get_by_test_id("project-name").fill(name)
    admin_page.get_by_test_id("project-description").fill("Playwright 前台核对自动创建")
    admin_page.get_by_role("button", name="保存").click()

    row = admin_page.get_by_role("row").filter(has_text=name)
    expect(row).to_be_visible()
    expect(row).to_contain_text("进行中")
    expect(row).to_contain_text("项目管理员")
    shot(admin_page, "created")

    # 概览（AC-40）+ 成员（AC-35）
    admin_page.get_by_role("link", name=name).click()
    overview = admin_page.get_by_test_id("project-overview")
    expect(overview).to_be_visible()
    expect(overview).to_contain_text("成员数")
    expect(overview).to_contain_text("最近执行")
    expect(overview).to_contain_text("暂无")
    shot(admin_page, "overview")

    admin_page.get_by_role("tab", name="成员").click()
    member_table = admin_page.get_by_test_id("member-table")
    expect(member_table).to_be_visible()
    expect(member_table.get_by_role("columnheader", name="用户名")).to_be_visible()
    expect(member_table.get_by_role("columnheader", name="角色")).to_be_visible()
    expect(member_table).to_contain_text(ADMIN_USERNAME)
    expect(member_table).to_contain_text("项目管理员")
    # AC-35：前台不展示邮箱 / 手机号
    expect(admin_page.get_by_text("邮箱")).to_have_count(0)
    expect(admin_page.get_by_text("手机号")).to_have_count(0)
    shot(admin_page, "members")

    # 归档（AC-33）
    admin_page.get_by_role("link", name="我的项目").click()
    target_row = admin_page.get_by_role("row").filter(has_text=name)
    target_row.get_by_role("button", name="归档").click()
    # 必须限定在浮层内：列表有上百行时 .last 会在 Popconfirm 挂载前误点最后一行的按钮
    admin_page.locator(".ant-popover:visible").get_by_role("button", name="归档").click()

    expect(target_row).to_contain_text("已归档")
    shot(admin_page, "archived")


@pytest.mark.task("T39")
def test_admin_global_applications_ui(admin_page: Page, shot) -> None:
    admin_page.get_by_role("link", name="全局申请").click()

    expect(admin_page.get_by_role("heading", name="全局申请记录")).to_be_visible()
    expect(admin_page.get_by_test_id("admin-application-table")).to_be_visible()
    shot(admin_page, "admin-applications")
