"""工作台待办卡片的前台核对（T110.5 · AC-193）。

卡片挂在**项目详情页的概览 Tab**里，不在「我的项目」列表页——
待办是项目内的事，挂在项目详情里上下文最准（见 `specs/09-automation/spec.md` §8.2）。

三条用例：
1. 三项数字与造数一致；
2. 点数字跳到对应 Tab（Tabs 为受控，`aria-selected` 要落到目标 Tab）；
3. 另一个项目的待办不串到本项目（项目隔离的前台口径）。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import unique_name as _name
from tests.e2e.support import seed_todo_counts

pytestmark = pytest.mark.e2e


def _open_detail(page: Page, project_name: str) -> None:
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()


@pytest.mark.task("T110.5")
def test_ac_193_todo_card_shows_three_counts(admin_page: Page, api, shot) -> None:
    """三项待办数字与造数一致，卡片出现在概览 Tab。"""
    project = api.create_project(_name("todos"))
    seed_todo_counts(
        project["id"], baseline_reviews=2, test_points=5, test_cases=8
    )
    admin_page.reload()
    _open_detail(admin_page, project["name"])

    expect(admin_page.get_by_test_id("todos-card")).to_be_visible()
    expect(admin_page.get_by_test_id("todo-baseline-reviews")).to_contain_text("2")
    expect(admin_page.get_by_test_id("todo-test-point-reviews")).to_contain_text("5")
    expect(admin_page.get_by_test_id("todo-test-case-reviews")).to_contain_text("8")
    # 三个标签都在
    expect(admin_page.get_by_test_id("todos-card")).to_contain_text("待审核基线")
    expect(admin_page.get_by_test_id("todos-card")).to_contain_text("待评审测试点")
    expect(admin_page.get_by_test_id("todos-card")).to_contain_text("待评审用例")
    shot(admin_page, "todo-card")


@pytest.mark.task("T110.5")
def test_ac_193_todo_card_navigates_to_tab(admin_page: Page, api, shot) -> None:
    """点待办数字跳到对应 Tab（Tabs 已是受控，选中态要真的切过去）。"""
    project = api.create_project(_name("todos-nav"))
    seed_todo_counts(project["id"], test_points=3, test_cases=4)
    admin_page.reload()
    _open_detail(admin_page, project["name"])

    admin_page.get_by_test_id("todo-test-point-reviews").click()
    expect(admin_page.get_by_role("tab", name="测试点")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(admin_page.get_by_test_id("test-point-analysis-table")).to_be_visible()

    # 回到概览，再跳用例
    admin_page.get_by_role("tab", name="概览").click()
    expect(admin_page.get_by_test_id("todos-card")).to_be_visible()
    admin_page.get_by_test_id("todo-test-case-reviews").click()
    expect(admin_page.get_by_role("tab", name="测试用例")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(admin_page.get_by_test_id("test-case-analysis-table")).to_be_visible()
    shot(admin_page, "todo-navigate")


@pytest.mark.task("T110.5")
def test_ac_193_todo_card_isolated_between_projects(
    admin_page: Page, api, shot
) -> None:
    """另一个项目的待办不串到本项目（项目隔离的前台口径）。"""
    project_a = api.create_project(_name("todos-iso-a"))
    project_b = api.create_project(_name("todos-iso-b"))
    seed_todo_counts(project_b["id"], baseline_reviews=7, test_points=9)
    admin_page.reload()

    _open_detail(admin_page, project_a["name"])
    expect(admin_page.get_by_test_id("todo-baseline-reviews")).to_contain_text("0")
    expect(admin_page.get_by_test_id("todo-test-point-reviews")).to_contain_text("0")
    expect(admin_page.get_by_test_id("todo-test-case-reviews")).to_contain_text("0")
    shot(admin_page, "todo-isolated")
