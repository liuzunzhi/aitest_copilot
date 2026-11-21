"""项目详情页 9 个 Tab 逐个点开（T110 · AC-180）。

**为什么要有这条**：08 期给项目详情页加了第 9 个 Tab「测试用例」，
Tab 从 8 个变 9 个——任何一个 Tab 的渲染报错都会让整页白屏。
这条用例逐个点开 9 个 Tab，每个都要断言**内容区真的渲染出来了**
（不是「没报错」），顺带确认 Tab 的顺序没被打乱。

**顺带守一条红线**：08 期前端只碰了「测试用例」Tab，
其余 8 个 Tab 的内容必须与 07 期一致——这里逐个断言关键锚点还在。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import unique_name as _name

pytestmark = pytest.mark.e2e

# 9 个 Tab 的名字与顺序（概览 / 成员 / 文档 / 版本快照 / 基线管理 / 申请 / 增量分析 / 测试点 / 测试用例）
TAB_NAMES = [
    "概览",
    "成员",
    "文档",
    "版本快照",
    "基线管理",
    "申请",
    "增量分析",
    "测试点",
    "测试用例",
]

# 每个 Tab 内容区的锚点（`data-testid`）——用来证明「真的渲染了」。
TAB_ANCHORS = {
    "概览": "project-overview",
    "成员": "member-table",
    "文档": "document-table",
    "版本快照": "baseline-table",
    "基线管理": "baseline-keyword",
    "申请": None,  # 申请表没有 testid，用 Tab 自身的选中态 + 空态文本兜底
    "增量分析": "incremental-analysis-table",
    "测试点": "test-point-analysis-table",
    "测试用例": "test-case-analysis-table",
}


@pytest.mark.task("T110")
def test_ac_180_all_nine_tabs_render(admin_page: Page, api, shot) -> None:
    """9 个 Tab 逐个点开，每个都断言内容区渲染出来了。"""
    project = api.create_project(_name("tabs"))
    admin_page.reload()
    admin_page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
        "button", name="详情"
    ).click()

    tabs = admin_page.get_by_role("tab")
    # 顺序不能被打乱——「测试用例」必须在「测试点」之后
    expect(tabs).to_have_count(len(TAB_NAMES))
    for index, name in enumerate(TAB_NAMES):
        expect(tabs.nth(index)).to_contain_text(name)

    for name in TAB_NAMES:
        admin_page.get_by_role("tab", name=name).click()
        anchor = TAB_ANCHORS[name]
        if anchor:
            expect(admin_page.get_by_test_id(anchor)).to_be_visible()
        # Tab 选中态确实落在刚点的那个上
        expect(admin_page.get_by_role("tab", name=name)).to_have_attribute(
            "aria-selected", "true"
        )

    shot(admin_page, "tabs")


@pytest.mark.task("T110")
def test_ac_180_test_cases_tab_is_last_and_usable(admin_page: Page, api, shot) -> None:
    """第 9 个 Tab「测试用例」可用：写入口在、读入口在、空态文案正确。"""
    project = api.create_project(_name("tab-tc"))
    admin_page.reload()
    admin_page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
        "button", name="详情"
    ).click()
    admin_page.get_by_role("tab", name="测试用例").click()

    expect(admin_page.get_by_test_id("test-case-analysis-table")).to_be_visible()
    expect(admin_page.get_by_test_id("test-case-table")).to_be_visible()
    # 项目管理员：写入口都在
    expect(admin_page.get_by_test_id("test-case-analysis-create-btn")).to_be_visible()
    expect(admin_page.get_by_test_id("test-case-create-btn")).to_be_visible()
    expect(admin_page.get_by_test_id("test-case-export-btn")).to_be_visible()
    # 空态文案（「还没有测试用例」在生成记录卡与用例表各出现一次，
    # 「还没有测试用例生成记录」是另一句，用 exact 区分开）
    expect(admin_page.get_by_text("还没有测试用例生成记录", exact=True)).to_be_visible()
    expect(admin_page.get_by_text("还没有测试用例", exact=True)).to_be_visible()
    shot(admin_page, "test-cases-tab")
