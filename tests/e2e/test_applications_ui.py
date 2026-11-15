"""申请队列与代审批的前台核对（AC-41 / 42 / 43 / 44）。"""

import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.support import token_for

pytestmark = pytest.mark.e2e


def _name(prefix: str) -> str:
    return f"e2e-{prefix}-{uuid.uuid4().hex[:6]}"


@pytest.mark.task("T37")
def test_ac_41_to_44_applications_ui(
    admin_page: Page, api, make_user, page_as, shot
) -> None:
    project = api.create_project(_name("apply"))
    applicant = make_user()
    token = token_for(api.ctx, applicant["username"], applicant["password"])
    api.submit_application(project["id"], token, reason="e2e 申请理由")

    # AC-41：项目内申请列表
    admin_page.reload()
    admin_page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
        "button", name="详情"
    ).click()
    admin_page.get_by_role("tab", name="申请").click()
    project_row = admin_page.get_by_role("row").filter(has_text=applicant["username"])
    expect(project_row).to_be_visible()
    expect(project_row).to_contain_text("待审批")
    expect(project_row).to_contain_text("e2e 申请理由")
    shot(admin_page, "project-applications")

    # AC-42：我的申请（申请人视角）
    applicant_page = page_as(applicant["username"], path="/applications/mine")
    expect(applicant_page.get_by_role("heading", name="我的申请")).to_be_visible()
    mine = applicant_page.get_by_role("row").filter(has_text=project["name"])
    expect(mine).to_be_visible()
    expect(mine).to_contain_text("待审批")
    shot(applicant_page, "my-applications")

    # AC-43：全局申请记录
    admin_page.get_by_role("link", name="全局申请").click()
    expect(admin_page.get_by_role("heading", name="全局申请记录")).to_be_visible()
    global_row = admin_page.get_by_role("row").filter(has_text=applicant["username"])
    expect(global_row).to_be_visible()
    expect(global_row).to_contain_text(project["name"])
    shot(admin_page, "admin-applications-pending")

    # AC-44：代审批，状态即时流转
    global_row.get_by_role("button", name="通过").click()
    expect(admin_page.get_by_role("row").filter(has_text=applicant["username"])).to_have_count(0)

    admin_page.get_by_role("combobox").first.click()
    admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option", has_text="已通过"
    ).click()
    approved_row = admin_page.get_by_role("row").filter(has_text=applicant["username"])
    expect(approved_row).to_be_visible()
    expect(approved_row).to_contain_text("已通过")
    shot(admin_page, "admin-applications-approved")
