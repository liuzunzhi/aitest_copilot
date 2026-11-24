"""流程基线前台核对（T122 · AC-212 / AC-213）。

页面入口：项目详情 →「基线管理」Tab → 二级子 Tab「流程基线」。

覆盖 8 个前台核对点（tasks.md §2 T122 的表格）：
1. 基线管理内出现「功能基线」/「流程基线」两个子 Tab，**默认停在「功能基线」**，
   功能基线树与快照面板照常显示；
2. **顶层仍然是 10 个 Tab**，「自动化执行」仍是最后一个（内层子 Tab 不计入顶层）；
3. 新建场景（名称 + 前置条件 + 两步步骤 + 一条关联）→ 列表出现新行；
4. 打开详情抽屉 → 元数据、**2 行步骤**、1 条关联都正确显示；
5. 抽屉里「上移」第 2 步 → 保存 → 只读步骤表与库里顺序一致
   （**前端不发 `step_no`**）；
6. 从文档反推 → 候选表出现候选 → 勾选 → 采纳 → 列表出现新场景，来源显示「文档解析」；
7. 提交审核 → 通过 → 快照列表出现 `v1.0`；点开能看到场景集合；
8. 成员登录 → **无**新建 / 反推 / 编辑 / 删除 / 关联 / 审核按钮，
   场景与快照可读，显示只读提示。

**零真实 socket**：造数一律走 Playwright 的 `APIRequestContext`（浏览器进程内），
不引入任何网络客户端。
"""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import unique_name as _name
from tests.e2e.helpers import wait_drawer_settled

pytestmark = pytest.mark.e2e

# 场景表列较多（名称 / 来源 / 状态 / 步骤数 / 关联数 / 修订次数 / 更新时间 / 操作），
# 默认 1280 宽下操作列会被挤到视口外，截图看不全。
# 这里把视口放宽到 1600，让整张表与所有按钮都落在画面内。
VIEWPORT = {"width": 1600, "height": 900}

# 反推用的文档正文（要能被切出带正文的章节，Mock provider 才有东西可读）。
DOC_MD = """# 支付需求

## 1. 概述

支付支持扫码与刷卡。

## 2. 登录失败次数限制

### 4.2 登录失败次数限制

连续 5 次输入错误密码后账号被锁定，锁定期间不允许再次登录。
"""

SCENARIO_NAME = "扫码登录连续失败 5 次后锁定"


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


def _open_process_tab(page: Page) -> None:
    """切到「基线管理」→「流程基线」子 Tab。"""
    page.get_by_role("tab", name="基线管理").click()
    page.get_by_test_id("process-baseline-subtab-process").click()
    expect(page.get_by_test_id("process-baseline-table")).to_be_visible()


def _create_baseline_function(api, project_id: int, name: str) -> dict:
    """建一个模块 + 一个功能（关联目标用）。"""
    module = api.ctx.post(
        f"/api/projects/{project_id}/baselines/modules",
        data={"name": "登录模块"},
        headers=_headers(api),
    )
    assert module.status in (200, 201), module.text()
    module_id = module.json()["id"]
    function = api.ctx.post(
        f"/api/projects/{project_id}/baselines/functions",
        data={"module_id": module_id, "name": name},
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


def _scenarios(api, project_id: int) -> list[dict]:
    response = api.ctx.get(
        f"/api/projects/{project_id}/process-baselines/scenarios?status=all&page_size=200",
        headers=_headers(api),
    )
    assert response.status == 200, response.text()
    return response.json()["items"]


@pytest.mark.task("T122")
def test_ac_212_subtab_and_top_level_tabs_ui(wide_admin_page: Page, api, shot) -> None:
    """AC-212：二级子菜单 + 顶层仍是 10 个 Tab + 默认停在「功能基线」。"""
    project = api.create_project(_name("pb-subtab"))
    wide_admin_page.reload()
    _open_project(wide_admin_page, project["name"])
    wide_admin_page.get_by_role("tab", name="基线管理").click()

    # ---- 1. 二级子 Tab 出现，默认停在「功能基线」 ----
    expect(wide_admin_page.get_by_test_id("process-baseline-subtab")).to_be_visible()
    expect(wide_admin_page.get_by_test_id("process-baseline-subtab-function")).to_be_visible()
    expect(wide_admin_page.get_by_test_id("process-baseline-subtab-process")).to_be_visible()
    expect(wide_admin_page.get_by_test_id("process-baseline-subtab-function")).to_contain_text(
        "功能基线"
    )
    expect(wide_admin_page.get_by_test_id("process-baseline-subtab-process")).to_contain_text(
        "流程基线"
    )
    # 默认停在「功能基线」——功能基线树与快照面板照常渲染
    expect(wide_admin_page.get_by_test_id("baseline-keyword")).to_be_visible()
    expect(wide_admin_page.get_by_test_id("process-baseline-table")).to_have_count(0)
    shot(wide_admin_page, "subtab-default-function")

    # ---- 2. 顶层仍然是 10 个 Tab，「自动化执行」仍是最后一个 ----
    # 顶层 Tab 的计数**只看顶层 tablist**——内层二级 Tabs 也有 role="tab"，
    # 进了「基线管理」之后直接 `get_by_role("tab")` 会数到 10 + 2 = 12。
    # 顶层 tablist 在 DOM 里排第一（内层那个在它的 content 里），
    # 所以按 tablist 取第一个即可。
    top_tabs = wide_admin_page.get_by_role("tablist").first.get_by_role("tab")
    expect(top_tabs).to_have_count(10)
    expect(top_tabs.nth(9)).to_contain_text("自动化执行")
    expect(top_tabs.nth(8)).to_contain_text("测试用例")

    # ---- 3. 切到「流程基线」→ 列表渲染出来 ----
    wide_admin_page.get_by_test_id("process-baseline-subtab-process").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-table")).to_be_visible()
    expect(wide_admin_page.get_by_text("还没有流程基线场景", exact=True)).to_be_visible()
    shot(wide_admin_page, "subtab-process")


@pytest.mark.task("T122")
def test_ac_213_create_scenario_and_edit_steps_ui(wide_admin_page: Page, api, shot) -> None:
    """AC-213：新建场景（名称 + 前置条件 + 两步 + 一条关联）→ 抽屉核对 → 上移保存。"""
    project = api.create_project(_name("pb-create"))
    project_id = project["id"]
    function = _create_baseline_function(api, project_id, "用户扫码登录")

    wide_admin_page.reload()
    _open_project(wide_admin_page, project["name"])
    _open_process_tab(wide_admin_page)

    # ---- 1. 新建场景 ----
    wide_admin_page.get_by_test_id("process-baseline-create-btn").click()
    drawer = wide_admin_page.get_by_test_id("process-baseline-drawer")
    expect(drawer).to_be_visible()
    wait_drawer_settled(wide_admin_page, drawer)

    wide_admin_page.get_by_test_id("process-baseline-name-input").fill(SCENARIO_NAME)
    wide_admin_page.get_by_test_id("process-baseline-precondition-input").fill(
        "账号已注册且处于未锁定状态"
    )
    # 两步步骤：第一行已有（默认给一行），再加一行
    wide_admin_page.get_by_test_id("process-baseline-step-action-input-0").fill(
        "打开登录页并选择「扫码登录」"
    )
    wide_admin_page.get_by_test_id("process-baseline-step-expected-input-0").fill("展示扫码二维码")
    wide_admin_page.get_by_test_id("process-baseline-step-add-btn").click()
    wide_admin_page.get_by_test_id("process-baseline-step-action-input-1").fill(
        "连续 5 次输入错误密码"
    )
    wide_admin_page.get_by_test_id("process-baseline-step-expected-input-1").fill("提示账号已被锁定")
    # 一条关联：多选下拉 → 选功能 → 「加入关联」
    wide_admin_page.get_by_test_id("process-baseline-link-select").click()
    wide_admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option",
        has_text="用户扫码登录",
    ).first.click()
    wide_admin_page.keyboard.press("Escape")
    wide_admin_page.get_by_test_id("process-baseline-link-confirm-btn").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-link-row-0")).to_be_visible()
    shot(wide_admin_page, "create-form", full_page=False)

    wide_admin_page.get_by_test_id("process-baseline-save-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已创建")

    # ---- 2. 列表出现新行 ----
    wide_admin_page.get_by_test_id("process-baseline-refresh-btn").click()
    items = _scenarios(api, project_id)
    assert len(items) == 1, items
    created = items[0]
    assert created["name"] == SCENARIO_NAME, created
    assert created["step_count"] == 2, created
    assert created["link_count"] == 1, created
    row = wide_admin_page.get_by_test_id(f"process-baseline-row-{created['id']}")
    expect(row).to_be_visible()
    expect(row).to_contain_text(SCENARIO_NAME)
    expect(row).to_contain_text("手工添加")
    expect(row).to_contain_text("在用")

    # ---- 3. 详情抽屉：元数据、2 行步骤、1 条关联 ----
    wide_admin_page.get_by_test_id(f"process-baseline-detail-btn-{created['id']}").click()
    drawer = wide_admin_page.get_by_test_id("process-baseline-drawer")
    expect(drawer).to_be_visible()
    wait_drawer_settled(wide_admin_page, drawer)
    expect(wide_admin_page.get_by_test_id("process-baseline-meta-view")).to_contain_text(
        SCENARIO_NAME
    )
    expect(wide_admin_page.get_by_test_id("process-baseline-meta-view")).to_contain_text(
        "账号已注册且处于未锁定状态"
    )
    expect(wide_admin_page.get_by_test_id("process-baseline-steps-readonly")).to_be_visible()
    expect(
        wide_admin_page.get_by_test_id("process-baseline-step-action-0")
    ).to_contain_text("打开登录页并选择「扫码登录」")
    expect(
        wide_admin_page.get_by_test_id("process-baseline-step-action-1")
    ).to_contain_text("连续 5 次输入错误密码")
    expect(wide_admin_page.get_by_test_id("process-baseline-links-table")).to_contain_text(
        "用户扫码登录"
    )
    shot(wide_admin_page, "detail-readonly", full_page=False)

    # ---- 4. 「上移」第 2 步 → 保存 → 只读步骤表与库里顺序一致 ----
    wide_admin_page.get_by_test_id("process-baseline-drawer-edit-btn").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-steps-editor")).to_be_visible()
    wide_admin_page.get_by_test_id("process-baseline-step-up-1").click()
    wide_admin_page.get_by_test_id("process-baseline-save-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已保存")

    # 库里顺序：服务端按数组顺序重排，前端不发 step_no
    detail = api.ctx.get(
        f"/api/projects/{project_id}/process-baselines/scenarios/{created['id']}",
        headers=_headers(api),
    )
    assert detail.status == 200, detail.text()
    steps = detail.json()["steps"]
    assert [step["step_no"] for step in steps] == [1, 2], steps
    assert steps[0]["action"] == "连续 5 次输入错误密码", steps
    assert steps[1]["action"] == "打开登录页并选择「扫码登录」", steps
    expect(
        wide_admin_page.get_by_test_id("process-baseline-step-action-0")
    ).to_contain_text("连续 5 次输入错误密码")
    shot(wide_admin_page, "steps-reordered", full_page=False)

    # ---- 5. 关联的目标是真的关联上了 ----
    assert detail.json()["links"][0]["target_id"] == function["id"], detail.json()["links"]
    assert detail.json()["links"][0]["target_type"] == "function", detail.json()["links"]


@pytest.mark.task("T122")
def test_ac_213_derive_and_review_ui(wide_admin_page: Page, api, shot) -> None:
    """AC-213：从文档反推 → 勾选 → 采纳；提交审核 → 通过 → 看快照。"""
    project = api.create_project(_name("pb-derive"))
    project_id = project["id"]
    uploaded = _upload_and_activate(api, project_id)

    wide_admin_page.reload()
    _open_project(wide_admin_page, project["name"])
    _open_process_tab(wide_admin_page)

    # ---- 1. 从文档反推 ----
    wide_admin_page.get_by_test_id("process-baseline-derive-btn").click()
    modal = wide_admin_page.get_by_test_id("process-baseline-derive-modal")
    expect(modal).to_be_visible()
    wide_admin_page.get_by_test_id("process-baseline-derive-doc-select").click()
    wide_admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option",
        has_text="支付需求",
    ).first.click()
    # 版本选项是**异步加载**的（`listVersions` 回来才有选项）。
    # 选完文档后版本下拉会自动带出生效版本——等它不再 disabled 且有值。
    version_select = wide_admin_page.get_by_test_id("process-baseline-derive-version-select")
    expect(version_select).not_to_have_class(re.compile(r"ant-select-disabled"))
    expect(version_select.locator(".ant-select-content-has-value")).to_have_count(1)
    wide_admin_page.get_by_test_id("process-baseline-derive-run-btn").click()

    table = wide_admin_page.get_by_test_id("process-baseline-derive-table")
    expect(table).to_be_visible()
    # 候选默认全不勾（PRD 1.4 原则二：高风险行为人工确认）
    expect(wide_admin_page.get_by_test_id("process-baseline-derive-check-0")).not_to_be_checked()
    shot(wide_admin_page, "derive-candidates", full_page=False)

    # ---- 2. 勾选 → 采纳 ----
    wide_admin_page.get_by_test_id("process-baseline-derive-check-0").check()
    wide_admin_page.get_by_test_id("process-baseline-derive-confirm-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已采纳")

    wide_admin_page.get_by_test_id("process-baseline-refresh-btn").click()
    items = _scenarios(api, project_id)
    assert len(items) == 1, items
    derived = items[0]
    assert derived["source_type"] == "document_derived", derived
    assert derived["source_document_id"] == uploaded["document"]["id"], derived
    assert derived["source_version_id"] == uploaded["version"]["id"], derived
    row = wide_admin_page.get_by_test_id(f"process-baseline-row-{derived['id']}")
    expect(row).to_contain_text("文档解析")

    # ---- 3. 提交审核 → 通过 ----
    wide_admin_page.get_by_test_id("process-baseline-review-btn").click()
    expect(wide_admin_page.get_by_test_id("process-baseline-review-table")).to_be_visible()
    wide_admin_page.get_by_test_id("process-baseline-review-submit-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已提交审核")

    # 关掉快照抽屉 → 审核期锁定：写入口禁用 + 提示
    wide_admin_page.get_by_role("button", name="关闭").first.click()
    # antd Drawer 默认**不销毁**内容（关闭后只是隐藏），所以断言「不可见」而不是「不存在」。
    expect(wide_admin_page.get_by_test_id("process-baseline-review-drawer")).to_be_hidden()
    expect(wide_admin_page.get_by_text("审核中，暂不可编辑", exact=True)).to_be_visible()
    expect(wide_admin_page.get_by_test_id("process-baseline-create-btn")).to_be_disabled()
    expect(wide_admin_page.get_by_test_id("process-baseline-derive-btn")).to_be_disabled()
    shot(wide_admin_page, "in-review-locked")

    revisions = api.ctx.get(
        f"/api/projects/{project_id}/process-baselines/revisions?status=submitted",
        headers=_headers(api),
    )
    assert revisions.status == 200, revisions.text()
    pending = revisions.json()["items"]
    assert len(pending) == 1, pending
    revision_id = pending[0]["id"]

    wide_admin_page.get_by_test_id("process-baseline-review-btn").click()
    approve_btn = wide_admin_page.get_by_test_id(
        f"process-baseline-review-approve-btn-{revision_id}"
    )
    expect(approve_btn).to_be_visible()
    approve_btn.click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("审核通过")

    # ---- 4. 快照列表出现 v1.0，点开能看到场景集合 ----
    expect(
        wide_admin_page.get_by_test_id("process-baseline-review-version-0")
    ).to_contain_text("v1.0")
    wide_admin_page.get_by_test_id(f"process-baseline-review-view-btn-{revision_id}").click()
    snapshot = wide_admin_page.get_by_test_id("process-baseline-snapshot-drawer")
    expect(snapshot).to_be_visible()
    wait_drawer_settled(wide_admin_page, snapshot)
    expect(wide_admin_page.get_by_test_id("process-baseline-snapshot-content")).to_be_visible()
    expect(wide_admin_page.get_by_test_id("process-baseline-snapshot-scenario-0")).to_contain_text(
        "mock 流程场景"
    )
    shot(wide_admin_page, "snapshot", full_page=False)

    # 提交即冻结：通过后 structure_json 与 draft_snapshot 逐字节相同
    detail = api.ctx.get(
        f"/api/projects/{project_id}/process-baselines/revisions/{revision_id}",
        headers=_headers(api),
    )
    assert detail.status == 200, detail.text()
    payload = detail.json()
    assert payload["draft_snapshot"] == payload["structure_json"], payload


@pytest.mark.task("T122")
def test_ac_213_member_readonly_ui(api, make_user, page_as, shot) -> None:
    """AC-213 成员只读：无新建 / 反推 / 编辑 / 删除 / 关联 / 审核按钮，场景与快照可读。"""
    project = api.create_project(_name("pb-member"))
    project_id = project["id"]
    member = make_user()
    api.add_member(project_id, member["id"], "member")

    # 管理员先造一条场景，成员才有东西可读
    created = api.ctx.post(
        f"/api/projects/{project_id}/process-baselines/scenarios",
        data={
            "scenarios": [
                {
                    "name": "成员可见的场景",
                    "precondition": "账号已注册",
                    "source_type": "manual",
                    "steps": [{"action": "打开登录页", "expected": "展示登录页"}],
                    "links": [],
                }
            ]
        },
        headers=_headers(api),
    )
    assert created.status == 201, created.text()
    scenario_id = created.json()["items"][0]["id"]

    page = page_as(member["username"], path=f"/projects/{project_id}")
    page.get_by_role("tab", name="基线管理").click()
    page.get_by_test_id("process-baseline-subtab-process").click()
    expect(page.get_by_test_id("process-baseline-table")).to_be_visible()

    # 写入口一个都不渲染
    expect(page.get_by_test_id("process-baseline-create-btn")).to_have_count(0)
    expect(page.get_by_test_id("process-baseline-derive-btn")).to_have_count(0)
    expect(page.get_by_test_id(f"process-baseline-edit-btn-{scenario_id}")).to_have_count(0)
    expect(page.get_by_test_id(f"process-baseline-delete-btn-{scenario_id}")).to_have_count(0)
    # 只读提示
    expect(
        page.get_by_text("只有项目管理员可以新建、反推与编辑流程基线")
    ).to_be_visible()

    # 详情可读（抽屉里也没有保存入口）
    page.get_by_test_id(f"process-baseline-detail-btn-{scenario_id}").click()
    drawer = page.get_by_test_id("process-baseline-drawer")
    expect(drawer).to_be_visible()
    wait_drawer_settled(page, drawer)
    expect(page.get_by_test_id("process-baseline-meta-view")).to_contain_text("成员可见的场景")
    expect(page.get_by_test_id("process-baseline-save-btn")).to_have_count(0)
    shot(page, "member-readonly", full_page=False)
