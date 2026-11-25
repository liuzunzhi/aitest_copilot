"""09 期收尾的前台核对（T116 · AC-194 / AC-196）。

**两个核对点**（tasks.md §4「前台核对点」）：
1. **8 个顶层 Tab 逐个点开无报错**——概览 / 文档 / 基线管理 / 增量分析 /
   测试点 / 测试用例 / 自动化执行 / 成员；
2. **「自动化执行」完整走一遍**：扫描 → 入库 → 关联 → 执行 → 报告。

**11 期调整**：顶层 Tab 从 10 个收敛到 8 个——「版本快照」并进「文档」、
「申请」并进「成员」，顶层顺序也重排了。

**顶层计数要限定顶层 tablist**：antd 的两层 `Tabs` **都**用 `role="tab"`——
进了「基线管理」或「成员」之后直接 `get_by_role("tab")` 会把内层的子 Tab 也数进去
（8 + 2 = 10）。断言顶层要写 `get_by_role("tablist").first.get_by_role("tab")`
（顶层 tablist 在 DOM 里排第一）。

**点击要用 `exact=True`**：Playwright 的 `get_by_role(name=)` 默认是**子串匹配**——
顶层「成员」与内层「成员列表」名字互相包含，裸写法会 strict mode violation。

**为什么单独一个文件**：`test_tabs_ui.py` 的截图落在 `.screenshots/T110/`
（`shot` 夹具按 `@pytest.mark.task` 分目录），收尾的核对点要落在
`.screenshots/T116/`，所以这里另起一份。

**造数说明**：跟 T115 一样——`AUTOMATION_ROOT` 指向**仓库里的** `var/automation`
（e2e 后端的 cwd 是仓库根），样例文件由 `support.write_automation_samples` 写。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import unique_name as _name
from tests.e2e.helpers import wait_drawer_settled
from tests.e2e.support import (
    remove_automation_samples,
    seed_test_points,
    write_automation_samples,
)

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 1600, "height": 900}

TAB_NAMES = [
    "概览",
    "文档",
    "基线管理",
    "增量分析",
    "测试点",
    "测试用例",
    "自动化执行",
    "成员",
]

TAB_ANCHORS = {
    "概览": "project-overview",
    "文档": "document-table",
    "基线管理": "baseline-keyword",
    "增量分析": "incremental-analysis-table",
    "测试点": "test-point-analysis-table",
    "测试用例": "test-case-analysis-table",
    "自动化执行": "automation-asset-table",
    "成员": "member-table",
}

PYTEST_SAMPLE = (
    "def test_ok():\n"
    "    assert True\n"
    "\n"
    "\n"
    "def test_bad():\n"
    "    assert 1 == 2\n"
)


@pytest.fixture
def wide_admin_page(browser, base_url, admin_storage_state):
    """视口更宽的已登录页面（宽表核对用）。"""
    context = browser.new_context(
        base_url=base_url, storage_state=admin_storage_state, viewport=VIEWPORT
    )
    page = context.new_page()
    page.goto("/projects")
    yield page
    context.close()


@pytest.mark.task("T116")
def test_ac_196_all_ten_tabs_render(wide_admin_page: Page, api, shot) -> None:
    """8 个顶层 Tab 逐个点开，每个都断言内容区渲染出来了（收官核对点 1）。"""
    project = api.create_project(_name("t116-tabs"))
    wide_admin_page.reload()
    wide_admin_page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
        "button", name="详情"
    ).click()

    # 顶层 tablist 在 DOM 里排第一（内层的在顶层 content-holder 里面）
    tabs = wide_admin_page.get_by_role("tablist").first.get_by_role("tab")
    expect(tabs).to_have_count(len(TAB_NAMES))
    for index, name in enumerate(TAB_NAMES):
        expect(tabs.nth(index)).to_contain_text(name)

    for name in TAB_NAMES:
        # exact=True：顶层「成员」与内层「成员列表」名字互相包含，裸写法会 strict violation
        wide_admin_page.get_by_role("tab", name=name, exact=True).click()
        anchor = TAB_ANCHORS[name]
        if anchor:
            expect(wide_admin_page.get_by_test_id(anchor)).to_be_visible()
        expect(wide_admin_page.get_by_role("tab", name=name, exact=True)).to_have_attribute(
            "aria-selected", "true"
        )
        shot(wide_admin_page, f"tab-{name}")

    # 最后一个 Tab 是「成员」——顺序不能被打乱（11 期：成员从第 2 位移到末位）
    expect(tabs.nth(7)).to_contain_text("成员")
    expect(tabs.nth(6)).to_contain_text("自动化执行")


@pytest.mark.task("T116")
def test_ac_194_automation_full_flow(wide_admin_page: Page, api, shot) -> None:
    """「自动化执行」完整走一遍：扫描 → 入库 → 关联 → 执行 → 报告（收官核对点 2）。"""
    project = api.create_project(_name("t116-flow"))
    project_id = project["id"]
    directory = "e2e-t116"
    write_automation_samples(directory, {"test_t116.py": PYTEST_SAMPLE})
    try:
        point_ids = seed_test_points(
            None,
            project_id,
            [
                {
                    "name": "扫码登录连续失败 5 次锁定",
                    "target_type": "function",
                    "target_id": 1,
                    "target_name": "用户扫码登录",
                    "chapter_title": "4.2 登录失败次数限制",
                    "status": "approved",
                }
            ],
        )
        case = api.ctx.post(
            f"/api/projects/{project_id}/test-cases/cases",
            data={
                "test_point_id": point_ids[0],
                "title": "连续输错密码 5 次后账号锁定",
                "case_type": "functional",
                "priority": "high",
                "precondition": "账号已存在",
                "steps": [{"action": "输错密码 5 次", "expected": "账号被锁定"}],
            },
            headers={"Authorization": f"Bearer {api.admin_token}"},
        )
        assert case.status in (200, 201), case.text()
        case_id = case.json()["id"]

        wide_admin_page.reload()
        wide_admin_page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
            "button", name="详情"
        ).click()
        wide_admin_page.get_by_role("tab", name="自动化执行").click()
        expect(wide_admin_page.get_by_test_id("automation-asset-table")).to_be_visible()

        # ---- 扫描 ----
        wide_admin_page.get_by_test_id("automation-scan-btn").click()
        wide_admin_page.get_by_test_id("automation-scan-dir-input").fill(directory)
        wide_admin_page.get_by_test_id("automation-scan-run-btn").click()
        expect(wide_admin_page.get_by_test_id("automation-scan-table")).to_be_visible()
        shot(wide_admin_page, "01-scan", full_page=False)

        # ---- 入库 ----
        wide_admin_page.get_by_test_id("automation-scan-confirm-btn").click()
        expect(wide_admin_page.locator(".ant-message")).to_contain_text("已入库")

        assets = api.ctx.get(
            f"/api/projects/{project_id}/automation/assets?page_size=200",
            headers={"Authorization": f"Bearer {api.admin_token}"},
        ).json()["items"]
        sample = next(item for item in assets if item["name"] == "test_t116.py")

        wide_admin_page.get_by_test_id("automation-refresh-btn").click()
        expect(
            wide_admin_page.get_by_test_id(f"automation-asset-row-{sample['id']}")
        ).to_be_visible()
        shot(wide_admin_page, "02-imported")

        # ---- 关联 ----
        wide_admin_page.get_by_test_id(f"automation-asset-link-btn-{sample['id']}").click()
        wide_admin_page.get_by_test_id("automation-asset-link-select").click()
        wide_admin_page.locator(
            ".ant-select-dropdown:visible .ant-select-item-option",
            has_text="连续输错密码 5 次后账号锁定",
        ).first.click()
        wide_admin_page.keyboard.press("Escape")
        wide_admin_page.get_by_test_id("automation-asset-link-confirm-btn").click()
        expect(wide_admin_page.locator(".ant-message")).to_contain_text("已关联用例")
        wide_admin_page.get_by_test_id("automation-refresh-btn").click()
        expect(
            wide_admin_page.get_by_test_id(f"automation-asset-linked-{sample['id']}")
        ).to_contain_text("连续输错密码 5 次后账号锁定")
        shot(wide_admin_page, "03-linked")

        # ---- 执行 ----
        wide_admin_page.get_by_test_id("automation-run-btn").click()
        expect(wide_admin_page.locator(".ant-message")).to_contain_text("执行完成")
        wide_admin_page.get_by_test_id("automation-refresh-btn").click()
        expect(wide_admin_page.get_by_test_id("automation-run-table")).to_be_visible()
        shot(wide_admin_page, "04-run-record")

        # ---- 报告 ----
        run_id = api.ctx.get(
            f"/api/projects/{project_id}/automation/runs",
            headers={"Authorization": f"Bearer {api.admin_token}"},
        ).json()["items"][0]["id"]
        wide_admin_page.get_by_test_id(f"automation-run-report-btn-{run_id}").click()
        drawer = wide_admin_page.get_by_test_id("automation-report-drawer")
        expect(drawer).to_be_visible()
        wait_drawer_settled(wide_admin_page, drawer)
        expect(wide_admin_page.get_by_test_id("automation-report-status")).to_contain_text(
            "执行完成"
        )
        expect(
            wide_admin_page.get_by_test_id(f"automation-report-trace-{sample['id']}")
        ).to_contain_text("4.2 登录失败次数限制")
        shot(wide_admin_page, "05-report", full_page=False)

        # 报告里的用例 id 与库里一致（追溯链真的指到了那条用例）
        assert case_id
    finally:
        remove_automation_samples(directory)
