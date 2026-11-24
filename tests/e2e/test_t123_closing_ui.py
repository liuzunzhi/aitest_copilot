"""10 期收尾的前台核对（T123 · AC-214）。

**三个核对点**（tasks.md §2 T123 的「前台核对点」）：
1. **10 个顶层 Tab 逐个点开无报错**——概览 / 成员 / 文档 / 版本快照 / 基线管理 /
   申请 / 增量分析 / 测试点 / 测试用例 / 自动化执行；
2. **「基线管理」内两个子 Tab 逐个点开**——「功能基线」/「流程基线」；
3. **流程基线完整走一遍**：新建 → 编辑步骤 → 关联 → 反推 → 提交审核 → 通过 → 看快照。

**为什么单独一个文件**：`test_tabs_ui.py` 的截图落在 `.screenshots/T110/`
（`shot` 夹具按 `@pytest.mark.task` 分目录），收尾的核对点要落在
`.screenshots/T123/`，所以这里另起一份。

**Tab 计数要限定顶层 tablist**：antd 的两层 `Tabs` **都**用 `role="tab"`——
进了「基线管理」之后直接 `get_by_role("tab")` 会数到 **10 + 2 = 12**。
断言顶层要写 `get_by_role("tablist").first.get_by_role("tab")`
（顶层 tablist 在 DOM 里排第一）。

**零真实 socket**：造数一律走 Playwright 的 `APIRequestContext`。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import unique_name as _name
from tests.e2e.helpers import wait_drawer_settled

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 1600, "height": 900}

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
    "自动化执行",
]

TAB_ANCHORS = {
    "概览": "project-overview",
    "成员": "member-table",
    "文档": "document-table",
    "版本快照": "baseline-table",
    "基线管理": "baseline-keyword",
    "申请": None,
    "增量分析": "incremental-analysis-table",
    "测试点": "test-point-analysis-table",
    "测试用例": "test-case-analysis-table",
    "自动化执行": "automation-asset-table",
}

# 反推用的文档正文（要能被切出带正文的章节，Mock provider 才有东西可读）。
DOC_MD = """# 支付需求

## 1. 概述

支付支持扫码与刷卡。

## 2. 流程

### 4.2 登录失败次数限制

连续 5 次输入错误密码后账号被锁定，锁定期间不允许再次登录。
"""


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


def _open_project(page: Page, project_name: str) -> None:
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()


def _create_baseline_function(api, project_id: int, name: str) -> dict:
    """建一个模块 + 一个功能（关联目标用）。"""
    module = api.ctx.post(
        f"/api/projects/{project_id}/baselines/modules",
        data={"name": "登录模块"},
        headers=_headers(api),
    )
    assert module.status in (200, 201), module.text()
    function = api.ctx.post(
        f"/api/projects/{project_id}/baselines/functions",
        data={"module_id": module.json()["id"], "name": name},
        headers=_headers(api),
    )
    assert function.status in (200, 201), function.text()
    return function.json()


def _upload_and_activate(api, project_id: int) -> dict:
    """上传一份 md 并确认生效（只有生效版本能反推）。"""
    response = api.ctx.post(
        f"/api/projects/{project_id}/documents",
        multipart={
            "file": {
                "name": "支付需求.md",
                "mimeType": "text/markdown",
                "buffer": DOC_MD.encode("utf-8"),
            }
        },
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    payload = response.json()
    activate = api.ctx.post(
        f"/api/projects/{project_id}/documents/{payload['document']['id']}"
        f"/versions/{payload['version']['id']}/activate",
        headers=_headers(api),
    )
    assert activate.status in (200, 201), activate.text()
    return payload


@pytest.mark.task("T123")
def test_ac_214_all_ten_tabs_and_two_subtabs_render(
    wide_admin_page: Page, api, shot
) -> None:
    """10 个顶层 Tab + 基线管理内 2 个子 Tab 逐个点开（收官核对点 1 与 2）。"""
    project = api.create_project(_name("t123-tabs"))
    wide_admin_page.reload()
    _open_project(wide_admin_page, project["name"])

    # ---- 顶层 10 个 Tab ----
    top_tabs = wide_admin_page.get_by_role("tablist").first.get_by_role("tab")
    expect(top_tabs).to_have_count(len(TAB_NAMES))
    for index, name in enumerate(TAB_NAMES):
        expect(top_tabs.nth(index)).to_contain_text(name)

    for name in TAB_NAMES:
        wide_admin_page.get_by_role("tab", name=name).click()
        anchor = TAB_ANCHORS[name]
        if anchor:
            expect(wide_admin_page.get_by_test_id(anchor)).to_be_visible()
        expect(wide_admin_page.get_by_role("tab", name=name)).to_have_attribute(
            "aria-selected", "true"
        )
        shot(wide_admin_page, f"tab-{name}")

    # 最后一个 Tab 仍是「自动化执行」——顺序不能被打乱
    expect(top_tabs.nth(9)).to_contain_text("自动化执行")
    expect(top_tabs.nth(8)).to_contain_text("测试用例")

    # ---- 「基线管理」内两个子 Tab ----
    wide_admin_page.get_by_role("tab", name="基线管理").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-subtab-function")).to_be_visible()
    expect(wide_admin_page.get_by_test_id("process-baseline-subtab-process")).to_be_visible()
    # 默认停在「功能基线」
    expect(wide_admin_page.get_by_test_id("baseline-keyword")).to_be_visible()
    expect(wide_admin_page.get_by_test_id("process-baseline-table")).to_have_count(0)
    shot(wide_admin_page, "subtab-function")

    wide_admin_page.get_by_test_id("process-baseline-subtab-process").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-table")).to_be_visible()
    shot(wide_admin_page, "subtab-process")


@pytest.mark.task("T123")
def test_ac_214_process_baseline_full_flow(wide_admin_page: Page, api, shot) -> None:
    """流程基线完整走一遍：新建 → 编辑步骤 → 关联 → 反推 → 提交审核 → 通过 → 看快照。"""
    project = api.create_project(_name("t123-flow"))
    project_id = project["id"]
    function = _create_baseline_function(api, project_id, "用户扫码登录")
    uploaded = _upload_and_activate(api, project_id)

    wide_admin_page.reload()
    _open_project(wide_admin_page, project["name"])
    wide_admin_page.get_by_role("tab", name="基线管理").click()
    wide_admin_page.get_by_test_id("process-baseline-subtab-process").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-table")).to_be_visible()

    # ---- 1. 新建场景（名称 + 前置条件 + 两步步骤 + 一条关联）----
    wide_admin_page.get_by_test_id("process-baseline-create-btn").click()
    drawer = wide_admin_page.get_by_test_id("process-baseline-drawer")
    expect(drawer).to_be_visible()
    wait_drawer_settled(wide_admin_page, drawer)

    wide_admin_page.get_by_test_id("process-baseline-name-input").fill("扫码登录连续失败 5 次后锁定")
    wide_admin_page.get_by_test_id("process-baseline-precondition-input").fill(
        "账号已注册且处于未锁定状态"
    )
    wide_admin_page.get_by_test_id("process-baseline-step-action-input-0").fill(
        "打开登录页并选择「扫码登录」"
    )
    wide_admin_page.get_by_test_id("process-baseline-step-expected-input-0").fill("展示扫码二维码")
    wide_admin_page.get_by_test_id("process-baseline-step-add-btn").click()
    wide_admin_page.get_by_test_id("process-baseline-step-action-input-1").fill(
        "连续 5 次输入错误密码"
    )
    wide_admin_page.get_by_test_id("process-baseline-step-expected-input-1").fill("提示账号已被锁定")
    wide_admin_page.get_by_test_id("process-baseline-link-select").click()
    wide_admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option",
        has_text="用户扫码登录",
    ).first.click()
    wide_admin_page.keyboard.press("Escape")
    wide_admin_page.get_by_test_id("process-baseline-link-confirm-btn").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-link-row-0")).to_be_visible()
    shot(wide_admin_page, "01-create", full_page=False)

    wide_admin_page.get_by_test_id("process-baseline-save-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已创建")

    wide_admin_page.get_by_test_id("process-baseline-refresh-btn").click()
    created = api.ctx.get(
        f"/api/projects/{project_id}/process-baselines/scenarios?status=all",
        headers=_headers(api),
    ).json()["items"]
    assert len(created) == 1, created
    scenario = created[0]
    assert scenario["step_count"] == 2, scenario
    assert scenario["link_count"] == 1, scenario
    expect(
        wide_admin_page.get_by_test_id(f"process-baseline-row-{scenario['id']}")
    ).to_be_visible()
    shot(wide_admin_page, "02-list")

    # ---- 2. 编辑步骤：上移第 2 步 → 保存 ----
    wide_admin_page.get_by_test_id(f"process-baseline-detail-btn-{scenario['id']}").click()
    drawer = wide_admin_page.get_by_test_id("process-baseline-drawer")
    expect(drawer).to_be_visible()
    wait_drawer_settled(wide_admin_page, drawer)
    shot(wide_admin_page, "03-detail", full_page=False)

    wide_admin_page.get_by_test_id("process-baseline-drawer-edit-btn").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-steps-editor")).to_be_visible()
    wide_admin_page.get_by_test_id("process-baseline-step-up-1").click()
    wide_admin_page.get_by_test_id("process-baseline-save-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已保存")
    shot(wide_admin_page, "04-steps-saved", full_page=False)

    # 库里顺序：服务端按数组顺序重排，前端不发 step_no
    detail = api.ctx.get(
        f"/api/projects/{project_id}/process-baselines/scenarios/{scenario['id']}",
        headers=_headers(api),
    ).json()
    assert [step["step_no"] for step in detail["steps"]] == [1, 2], detail["steps"]
    assert detail["steps"][0]["action"] == "连续 5 次输入错误密码", detail["steps"]
    assert detail["links"][0]["target_id"] == function["id"], detail["links"]
    expect(
        wide_admin_page.get_by_test_id("process-baseline-step-action-0")
    ).to_contain_text("连续 5 次输入错误密码")
    # 关掉抽屉，回到列表
    wide_admin_page.get_by_role("button", name="关闭").first.click()

    # ---- 3. 文档反推：选文档 + 生效版本 → 反推 → 勾选 → 采纳 ----
    wide_admin_page.get_by_test_id("process-baseline-derive-btn").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-derive-modal")).to_be_visible()
    wide_admin_page.get_by_test_id("process-baseline-derive-doc-select").click()
    wide_admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option",
        has_text="支付需求",
    ).first.click()
    version_select = wide_admin_page.get_by_test_id("process-baseline-derive-version-select")
    expect(version_select.locator(".ant-select-content-has-value")).to_have_count(1)
    wide_admin_page.get_by_test_id("process-baseline-derive-run-btn").click()

    derive_table = wide_admin_page.get_by_test_id("process-baseline-derive-table")
    expect(derive_table).to_be_visible()
    # 候选默认全不勾（PRD 1.4 原则二）
    expect(wide_admin_page.get_by_test_id("process-baseline-derive-check-0")).not_to_be_checked()
    shot(wide_admin_page, "05-derive", full_page=False)

    wide_admin_page.get_by_test_id("process-baseline-derive-check-0").check()
    wide_admin_page.get_by_test_id("process-baseline-derive-confirm-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已采纳")

    wide_admin_page.get_by_test_id("process-baseline-refresh-btn").click()
    items = api.ctx.get(
        f"/api/projects/{project_id}/process-baselines/scenarios?status=all",
        headers=_headers(api),
    ).json()["items"]
    assert len(items) == 2, items
    derived = next(item for item in items if item["source_type"] == "document_derived")
    assert derived["source_document_id"] == uploaded["document"]["id"], derived
    expect(
        wide_admin_page.get_by_test_id(f"process-baseline-row-{derived['id']}")
    ).to_contain_text("文档解析")
    shot(wide_admin_page, "06-derived")

    # ---- 4. 提交审核 → 通过 → 看快照 ----
    wide_admin_page.get_by_test_id("process-baseline-review-btn").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-review-table")).to_be_visible()
    wide_admin_page.get_by_test_id("process-baseline-review-submit-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已提交审核")

    pending = api.ctx.get(
        f"/api/projects/{project_id}/process-baselines/revisions?status=submitted",
        headers=_headers(api),
    ).json()["items"]
    assert len(pending) == 1, pending
    revision_id = pending[0]["id"]

    wide_admin_page.get_by_test_id(
        f"process-baseline-review-approve-btn-{revision_id}"
    ).click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("审核通过")
    expect(
        wide_admin_page.get_by_test_id("process-baseline-review-version-0")
    ).to_contain_text("v1.0")
    shot(wide_admin_page, "07-review", full_page=False)

    wide_admin_page.get_by_test_id(f"process-baseline-review-view-btn-{revision_id}").click()
    snapshot = wide_admin_page.get_by_test_id("process-baseline-snapshot-drawer")
    expect(snapshot).to_be_visible()
    wait_drawer_settled(wide_admin_page, snapshot)
    expect(wide_admin_page.get_by_test_id("process-baseline-snapshot-content")).to_be_visible()
    # 快照里有 2 个场景（手工的那个 + 反推的那个）
    expect(wide_admin_page.get_by_test_id("process-baseline-snapshot-scenario-0")).to_be_visible()
    expect(wide_admin_page.get_by_test_id("process-baseline-snapshot-scenario-1")).to_be_visible()
    shot(wide_admin_page, "08-snapshot", full_page=False)

    # 提交即冻结：通过后 structure_json 与 draft_snapshot 逐字节相同
    revision = api.ctx.get(
        f"/api/projects/{project_id}/process-baselines/revisions/{revision_id}",
        headers=_headers(api),
    ).json()
    assert revision["draft_snapshot"] == revision["structure_json"], revision
    assert revision["scenario_count"] == 2, revision
