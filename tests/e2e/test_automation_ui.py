"""自动化执行前台核对（T115 · AC-194）。

页面入口：项目详情 →「自动化执行」Tab（第 10 个，位于「测试用例」之后）。

覆盖 7 个前台核对点（tasks.md §4）：
1. 出现「自动化执行」Tab，位于「测试用例」之后；
2. 扫描 → 勾选 → 确认入库 → 资产表出现新行，置信度与用例数正确；
3. 关联用例 → 资产表显示关联的用例名；
4. 触发执行 → 执行记录新增一行；点开报告 → 明细、统计、追溯链正确；
5. Playwright 资产的执行按钮**置灰**，提示「Playwright 执行能力待后续期」；
6. 成员登录 → 无扫描 / 入库 / 执行按钮；资产与报告可读；
7. 概览 Tab「我的待办」卡片三个数字，点击可跳转。

**造数说明（这条最容易踩）**：
`AUTOMATION_ROOT` 默认是**相对项目根**的 `var/automation`，而 e2e 后端的
cwd 就是仓库根——所以扫描扫的是**仓库里的** `var/automation`。
不往那儿写样例 pytest 文件，扫描永远返回空清单。
样例文件由 `support.write_automation_samples` 写，用例收尾时删掉
（`var/automation/` 已进 `.gitignore`，不该进版本库）。

**执行是真的起子进程跑 pytest**：样例文件给 1 通过 + 1 失败，
所以 `status='succeeded'` 而 `exit_code=1`——这正是「用例失败 ≠ 执行失败」
的前台口径。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import unique_name as _name
from tests.e2e.helpers import wait_drawer_settled
from tests.e2e.support import (
    USER_PASSWORD,
    remove_automation_samples,
    seed_test_points,
    token_for,
    write_automation_samples,
)

pytestmark = pytest.mark.e2e

# 资产表与执行记录表列较多（文件名 / 框架 / 置信度 / 用例数 / 关联用例 / 状态 / 操作），
# 默认 1280 宽下操作列会被挤到视口外，截图看不全。
# 这里把视口放宽到 1600，让整张表与所有按钮都落在画面内。
VIEWPORT = {"width": 1600, "height": 900}

# 样例 pytest 文件：1 个通过 + 1 个失败 → 退出码 1（但进程正常跑完）。
PYTEST_SAMPLE = (
    "def test_ok():\n"
    "    assert True\n"
    "\n"
    "\n"
    "def test_bad():\n"
    "    assert 1 == 2\n"
)

# 样例 Playwright 文件：文件名匹配 + 含 `test(` → 置信度 0.95。
PLAYWRIGHT_SAMPLE = (
    "test('sample', async ({ page }) => {\n"
    "  await page.goto('http://example.com')\n"
    "})\n"
)

# 低置信度样例：文件名匹配但没有 `def test_` → 0.60（< 0.7，默认不勾选）。
LOW_CONFIDENCE_SAMPLE = "x = 1\n"


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


def _headers(api, token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or api.admin_token}"}


def _open_automation(page: Page, project_name: str) -> None:
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="自动化执行").click()
    expect(page.get_by_test_id("automation-asset-table")).to_be_visible()


def _seed_samples(directory: str) -> None:
    """往自动化根目录写三份样例文件（pytest / playwright / 低置信度）。"""
    write_automation_samples(
        directory,
        {
            "test_sample.py": PYTEST_SAMPLE,
            "sample.spec.ts": PLAYWRIGHT_SAMPLE,
            "helper_test.py": LOW_CONFIDENCE_SAMPLE,
        },
    )


def _assets_by_name(api, project_id: int) -> dict[str, dict]:
    response = api.ctx.get(
        f"/api/projects/{project_id}/automation/assets?page_size=200", headers=_headers(api)
    )
    assert response.status == 200, response.text()
    return {item["name"]: item for item in response.json()["items"]}


def _create_case(api, project_id: int, *, point_id: int, title: str) -> dict:
    """走真实接口手工新增用例（会写源测试点指纹）。"""
    response = api.ctx.post(
        f"/api/projects/{project_id}/test-cases/cases",
        data={
            "test_point_id": point_id,
            "title": title,
            "case_type": "functional",
            "priority": "high",
            "precondition": "账号已存在",
            "steps": [{"action": "输错密码 5 次", "expected": "账号被锁定"}],
        },
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    return response.json()


@pytest.mark.task("T115")
def test_ac_194_tab_position_and_scan_import_ui(
    wide_admin_page: Page, api, shot
) -> None:
    """Tab 位置 + 扫描 → 勾选 → 确认入库 → 资产表出现新行（置信度 / 用例数正确）。"""
    project = api.create_project(_name("auto-scan"))
    project_id = project["id"]
    directory = "e2e-scan"
    _seed_samples(directory)
    try:
        wide_admin_page.reload()
        wide_admin_page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
            "button", name="详情"
        ).click()

        # ---- 1. Tab 在「测试用例」之后 ----
        # 顶层 tablist 在 DOM 里排第一；裸 get_by_role("tab") 会把内层子 Tab 也数进去
        tabs = wide_admin_page.get_by_role("tablist").first.get_by_role("tab")
        expect(tabs).to_have_count(8)
        expect(tabs.nth(7)).to_contain_text("成员")
        expect(tabs.nth(6)).to_contain_text("自动化执行")
        wide_admin_page.get_by_role("tab", name="自动化执行").click()
        expect(wide_admin_page.get_by_test_id("automation-asset-table")).to_be_visible()
        # 空态：还没有资产
        expect(wide_admin_page.get_by_text("还没有自动化资产", exact=True)).to_be_visible()
        shot(wide_admin_page, "tab-empty")

        # ---- 2. 扫描 → 勾选 → 确认入库 ----
        wide_admin_page.get_by_test_id("automation-scan-btn").click()
        expect(wide_admin_page.get_by_test_id("automation-scan-modal")).to_be_visible()
        wide_admin_page.get_by_test_id("automation-scan-dir-input").fill(directory)
        wide_admin_page.get_by_test_id("automation-scan-run-btn").click()

        scan_table = wide_admin_page.get_by_test_id("automation-scan-table")
        expect(scan_table).to_be_visible()
        # 识别到 3 个（pytest / playwright / 低置信度 pytest）
        expect(scan_table.get_by_role("row")).to_have_count(4)  # 表头 + 3 行
        # 低置信度的默认不勾选，并标「低置信度，请人工确认」
        expect(
            wide_admin_page.get_by_test_id(
                f"automation-scan-low-{directory}/helper_test.py"
            )
        ).to_be_visible()
        shot(wide_admin_page, "scan-list", full_page=False)

        # 高置信度的 pytest 默认已勾选；显式再点 Playwright 那条（本期只读但可入库）
        wide_admin_page.get_by_test_id(
            f"automation-scan-check-{directory}/sample.spec.ts"
        ).check()
        wide_admin_page.get_by_test_id("automation-scan-confirm-btn").click()
        expect(wide_admin_page.locator(".ant-message")).to_contain_text("已入库")

        # ---- 3. 资产表出现新行，置信度与用例数正确 ----
        wide_admin_page.get_by_test_id("automation-refresh-btn").click()
        assets = _assets_by_name(api, project_id)
        assert "test_sample.py" in assets, "扫描入��的 pytest 资产应已落库"
        assert "sample.spec.ts" in assets, "扫描入库的 playwright 资产应已落库"
        sample = assets["test_sample.py"]
        # 服务端重扫重算：文件名匹配 + 有 `def test_` → 0.95，2 个用例函数
        assert sample["parse_confidence"] == 0.95, sample
        assert sample["detected_cases"] == 2, sample

        row = wide_admin_page.get_by_test_id(f"automation-asset-row-{sample['id']}")
        expect(row).to_be_visible()
        expect(row).to_contain_text("test_sample.py")
        expect(row).to_contain_text("0.95")
        expect(row).to_contain_text("2")
        expect(row).to_contain_text("Pytest")
        shot(wide_admin_page, "asset-imported")
    finally:
        remove_automation_samples(directory)


@pytest.mark.task("T115")
def test_ac_194_link_case_and_run_report_ui(wide_admin_page: Page, api, shot) -> None:
    """关联用例 → 执行 → 执行记录新增一行 → 报告里明细 / 统计 / 追溯链正确。"""
    project = api.create_project(_name("auto-run"))
    project_id = project["id"]
    directory = "e2e-run"
    _seed_samples(directory)
    try:
        # 造一条评审通过的测试点 + 用例（关联用）
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
        case = _create_case(
            api,
            project_id,
            point_id=point_ids[0],
            title="连续输错密码 5 次后账号锁定",
        )

        wide_admin_page.reload()
        _open_automation(wide_admin_page, project["name"])

        # ---- 扫描入库（只取 pytest 那个） ----
        wide_admin_page.get_by_test_id("automation-scan-btn").click()
        wide_admin_page.get_by_test_id("automation-scan-dir-input").fill(directory)
        wide_admin_page.get_by_test_id("automation-scan-run-btn").click()
        expect(wide_admin_page.get_by_test_id("automation-scan-table")).to_be_visible()
        # Playwright / 低置信度都不入库
        wide_admin_page.get_by_test_id(
            f"automation-scan-check-{directory}/helper_test.py"
        ).uncheck()
        wide_admin_page.get_by_test_id("automation-scan-confirm-btn").click()
        expect(wide_admin_page.locator(".ant-message")).to_contain_text("已入库")

        assets = _assets_by_name(api, project_id)
        sample = assets["test_sample.py"]

        # ---- 关联用例 ----
        wide_admin_page.get_by_test_id(f"automation-asset-link-btn-{sample['id']}").click()
        expect(wide_admin_page.get_by_test_id("automation-asset-link-select")).to_be_visible()
        # antd Select 的选项在下拉里，要先点开下拉才看得见
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
        shot(wide_admin_page, "linked")

        # ---- 触发执行 ----
        wide_admin_page.get_by_test_id("automation-run-btn").click()
        expect(wide_admin_page.locator(".ant-message")).to_contain_text("执行完成")

        runs = api.ctx.get(
            f"/api/projects/{project_id}/automation/runs", headers=_headers(api)
        )
        assert runs.status == 200, runs.text()
        run_items = runs.json()["items"]
        assert run_items, "执行记录应新增一行"
        run = run_items[0]
        # **状态语义**：退出码 1 只是「有测试失败」，进程正常跑完 → status='succeeded'
        assert run["status"] == "succeeded", run
        assert run["exit_code"] == 1, run
        assert run["stats"] == {"total": 1, "passed": 0, "failed": 1, "skipped": 0}, run

        wide_admin_page.get_by_test_id("automation-refresh-btn").click()
        expect(wide_admin_page.get_by_test_id(f"automation-run-status-{run['id']}")).to_contain_text(
            "执行完成"
        )
        expect(wide_admin_page.get_by_test_id(f"automation-run-stats-{run['id']}")).to_contain_text(
            "1 个资产"
        )
        shot(wide_admin_page, "run-record")

        # ---- 打开报告 ----
        wide_admin_page.get_by_test_id(f"automation-run-report-btn-{run['id']}").click()
        drawer = wide_admin_page.get_by_test_id("automation-report-drawer")
        expect(drawer).to_be_visible()
        wait_drawer_settled(wide_admin_page, drawer)
        expect(wide_admin_page.get_by_test_id("automation-report-status")).to_contain_text(
            "执行完成"
        )
        expect(wide_admin_page.get_by_test_id("automation-report-stats")).to_contain_text(
            "1 个资产"
        )
        # 明细：结果「失败」（用例级），追溯链四段齐全
        expect(
            wide_admin_page.get_by_test_id(f"automation-report-result-{sample['id']}")
        ).to_contain_text("失败")
        trace = wide_admin_page.get_by_test_id(f"automation-report-trace-{sample['id']}")
        expect(trace).to_contain_text("连续输错密码 5 次后账号锁定")
        expect(trace).to_contain_text("扫码登录连续失败 5 次锁定")
        expect(trace).to_contain_text("用户扫码登录")
        expect(trace).to_contain_text("4.2 登录失败次数限制")
        expect(wide_admin_page.get_by_test_id("automation-report-item-table")).to_be_visible()
        expect(wide_admin_page.get_by_test_id("automation-report-log")).to_be_visible()
        shot(wide_admin_page, "report", full_page=False)
    finally:
        remove_automation_samples(directory)


@pytest.mark.task("T115")
def test_ac_194_playwright_exec_disabled_ui(wide_admin_page: Page, api, shot) -> None:
    """Playwright 资产的执行按钮置灰，提示「Playwright 执行能力待后续期」。"""
    project = api.create_project(_name("auto-pw"))
    directory = "e2e-pw"
    write_automation_samples(directory, {"sample.spec.ts": PLAYWRIGHT_SAMPLE})
    try:
        wide_admin_page.reload()
        _open_automation(wide_admin_page, project["name"])

        wide_admin_page.get_by_test_id("automation-scan-btn").click()
        wide_admin_page.get_by_test_id("automation-scan-dir-input").fill(directory)
        wide_admin_page.get_by_test_id("automation-scan-run-btn").click()
        expect(wide_admin_page.get_by_test_id("automation-scan-table")).to_be_visible()
        wide_admin_page.get_by_test_id("automation-scan-confirm-btn").click()
        expect(wide_admin_page.locator(".ant-message")).to_contain_text("已入库")

        assets = _assets_by_name(api, project["id"])
        playwright_asset = assets["sample.spec.ts"]
        wide_admin_page.get_by_test_id("automation-refresh-btn").click()

        run_btn = wide_admin_page.get_by_test_id(
            f"automation-run-btn-{playwright_asset['id']}"
        )
        expect(run_btn).to_be_disabled()
        # tooltip：disabled 的按钮不派发鼠标事件，Tooltip 挂在外层 span 上
        run_btn.locator("xpath=..").hover()
        expect(
            wide_admin_page.get_by_text("Playwright 执行能力待后续期", exact=True)
        ).to_be_visible()
        shot(wide_admin_page, "playwright-disabled")
    finally:
        remove_automation_samples(directory)


@pytest.mark.task("T115")
def test_ac_194_member_readonly_ui(api, make_user, page_as, shot) -> None:
    """成员登录 → 无扫描 / 入库 / 执行按钮；资产与报告可读。"""
    project = api.create_project(_name("auto-member"))
    member = make_user()
    api.add_member(project["id"], member["id"], "member")

    directory = "e2e-member"
    write_automation_samples(directory, {"test_member.py": PYTEST_SAMPLE})
    try:
        # 先用管理员把资产入库，成员才有东西可读
        scan = api.ctx.post(
            f"/api/projects/{project['id']}/automation/scan",
            data={"directory": directory},
            headers=_headers(api),
        )
        assert scan.status == 200, scan.text()
        assert scan.json()["matched"] == 1, scan.text()
        created = api.ctx.post(
            f"/api/projects/{project['id']}/automation/assets",
            data={
                "assets": [
                    {
                        "file_path": f"{directory}/test_member.py",
                        "name": "test_member.py",
                        "framework": "pytest",
                    }
                ]
            },
            headers=_headers(api),
        )
        assert created.status == 201, created.text()

        asset_id = created.json()["items"][0]["asset_id"]
        assert asset_id

        page = page_as(member["username"], path=f"/projects/{project['id']}")
        page.get_by_role("tab", name="自动化执行").click()
        expect(page.get_by_test_id("automation-asset-table")).to_be_visible()
        expect(page.get_by_test_id("automation-run-table")).to_be_visible()
        # 写入口一个都不渲染
        expect(page.get_by_test_id("automation-scan-btn")).to_have_count(0)
        expect(page.get_by_test_id("automation-run-btn")).to_have_count(0)
        expect(page.get_by_test_id(f"automation-asset-link-btn-{asset_id}")).to_have_count(0)
        expect(page.get_by_test_id(f"automation-run-btn-{asset_id}")).to_have_count(0)
        # 只读提示
        expect(page.get_by_text("只有项目管理员可以扫描、入库与执行")).to_be_visible()
        shot(page, "member-readonly")
    finally:
        remove_automation_samples(directory)


@pytest.mark.task("T115")
def test_ac_194_todo_card_navigates_ui(admin_page: Page, api, shot) -> None:
    """概览 Tab「我的待办」卡片三个数字，点击可跳转（含跳到「自动化执行」）。"""
    from tests.e2e.support import seed_todo_counts

    project = api.create_project(_name("auto-todo"))
    seed_todo_counts(project["id"], baseline_reviews=2, test_points=5, test_cases=8)
    admin_page.reload()
    admin_page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
        "button", name="详情"
    ).click()

    expect(admin_page.get_by_test_id("todos-card")).to_be_visible()
    expect(admin_page.get_by_test_id("todo-baseline-reviews")).to_contain_text("2")
    expect(admin_page.get_by_test_id("todo-test-point-reviews")).to_contain_text("5")
    expect(admin_page.get_by_test_id("todo-test-case-reviews")).to_contain_text("8")

    admin_page.get_by_test_id("todo-test-case-reviews").click()
    expect(admin_page.get_by_role("tab", name="测试用例")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(admin_page.get_by_test_id("test-case-analysis-table")).to_be_visible()
    shot(admin_page, "todo-navigate")
