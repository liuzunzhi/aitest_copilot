"""测试用例前台核对（T109 · AC-178 / AC-171 / AC-177）。

页面入口：项目详情 →「测试用例」Tab（第 9 个，位于「测试点」之后）。

覆盖：
- 发起生成 → 生成记录变「成功」→ 用例出现在列表；
- 详情抽屉：步骤表、来源追溯（所属测试点 / 功能）；
- 评审通过 → 状态变「已通过」、评审入口消失；
- 手工新增 + 编辑步骤（含上移 / 下移）→ 保存后步骤表与编辑结果一致；
- 源测试点被改 → 出现「待复核」→ 确认已复核后消失；
- 导出 Excel → 下载 `.xlsx`，首行表头正确。

**造数说明**：MockProvider 对 `[TEST_CASE_SYSTEM]` 返回**一条带 2 步骤的用例**，
且输出契约里没有测试点 id（服务端按当前测试点绑定），所以默认响应可直接用。
需要指定内容时用**真实接口** `POST /test-cases/cases` 手工新增——
它会写源测试点指纹（`source_point_fingerprint`），直写库的话指纹是 NULL，
待复核派生会失真。
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import unique_name as _name
from tests.e2e.helpers import wait_drawer_settled
from tests.e2e.support import seed_test_points

pytestmark = pytest.mark.e2e

# 用例表的列较多（用例名称 / 所属测试点 / 类型 / 优先级 / 步骤 / 状态 / 来源 / 操作），
# 默认 1280 宽下操作列会被挤到视口外，截图看不全。
# 这里把视口放宽到 1600，让整张表与 5 个操作按钮都落在画面内。
VIEWPORT = {"width": 1600, "height": 900}


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


def _make_approved_point(api, project_id: int, name: str, target_name: str) -> int:
    """造一条评审通过的测试点（生成只吃 approved 的点）。"""
    ids = seed_test_points(
        None,
        project_id,
        [
            {
                "name": name,
                "target_type": "function",
                "target_id": 1,
                "target_name": target_name,
                "priority": "high",
                "precondition": "账号已存在且未锁定",
                "verification": "连续输错 5 次，提示锁定 30 分钟",
                "status": "approved",
            }
        ],
    )
    return ids[0]


def _create_case(
    api,
    project_id: int,
    *,
    point_id: int,
    title: str,
    steps: list[dict],
    case_type: str = "functional",
    priority: str = "medium",
    precondition: str = "账号已存在",
) -> dict:
    """走真实接口手工新增用例（会写源测试点指纹）。"""
    response = api.ctx.post(
        f"/api/projects/{project_id}/test-cases/cases",
        data={
            "test_point_id": point_id,
            "title": title,
            "case_type": case_type,
            "priority": priority,
            "precondition": precondition,
            "steps": steps,
        },
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    return response.json()


def _cases_by_title(api, project_id: int) -> dict[str, dict]:
    response = api.ctx.get(
        f"/api/projects/{project_id}/test-cases/cases?page_size=200", headers=_headers(api)
    )
    assert response.status == 200, response.text()
    return {item["title"]: item for item in response.json()["items"]}


def _open_test_cases(page: Page, project_name: str) -> None:
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="测试用例").click()
    expect(page.get_by_test_id("test-case-analysis-table")).to_be_visible()


@pytest.mark.task("T109")
def test_ac_178_tab_generate_list_detail_review_ui(wide_admin_page: Page, api, shot) -> None:
    """Tab → 发起生成 → 列表出现 → 详情步骤 → 评审通过 → 状态变「已通过」。"""
    project = api.create_project(_name("tc"))
    project_id = project["id"]
    point_id = _make_approved_point(api, project_id, "扫码登录连续失败 5 次锁定", "扫码登录")

    wide_admin_page.reload()
    _open_test_cases(wide_admin_page, project["name"])

    # ---- 发起生成（Mock 默认返回一条带 2 步骤的用例） ----
    wide_admin_page.get_by_test_id("test-case-analysis-create-btn").click()
    # 等模板默认值落位再提交——否则「模板必填」校验会静默拦下这次提交。
    expect(wide_admin_page.get_by_test_id("test-case-template-select")).to_contain_text(
        "测试用例生成"
    )
    wide_admin_page.get_by_test_id("test-case-submit-btn").click()

    expect(wide_admin_page.locator(".ant-message")).to_contain_text("生成完成")
    analysis_table = wide_admin_page.get_by_test_id("test-case-analysis-table")
    expect(analysis_table.get_by_role("row").filter(has_text="成功")).to_be_visible()

    # ---- 用例出现在列表 ----
    cases = _cases_by_title(api, project_id)
    assert cases, "生成后应有至少一条用例"
    case = next(iter(cases.values()))
    case_id = case["id"]
    assert case["test_point_id"] == point_id, "用例必须挂在刚造的测试点上"

    wide_admin_page.get_by_test_id("test-case-refresh-btn").click()
    expect(wide_admin_page.get_by_test_id(f"test-case-title-{case_id}")).to_be_visible()
    expect(wide_admin_page.get_by_test_id(f"test-case-status-{case_id}")).to_contain_text(
        "待评审"
    )
    expect(wide_admin_page.get_by_test_id(f"test-case-title-{case_id}")).to_contain_text(
        "mock 生成用例"
    )
    shot(wide_admin_page, "generated")

    # ---- 详情抽屉：步骤表 + 来源追溯 ----
    wide_admin_page.get_by_test_id(f"test-case-detail-btn-{case_id}").click()
    expect(wide_admin_page.get_by_test_id("test-case-drawer")).to_be_visible()
    # 抽屉是滑入动画，等它走完再断言 / 截图，否则拍到半截。
    wait_drawer_settled(wide_admin_page, wide_admin_page.get_by_test_id("test-case-drawer"))
    expect(wide_admin_page.get_by_test_id("test-case-steps-readonly").get_by_role("row")).to_have_count(
        3  # 表头 + 2 个步骤
    )
    expect(wide_admin_page.get_by_test_id("test-case-step-action-0")).to_contain_text(
        "mock 第一步"
    )
    expect(wide_admin_page.get_by_test_id("test-case-step-action-1")).to_contain_text(
        "mock 第二步"
    )
    # 来源追溯：所属测试点与功能
    expect(wide_admin_page.get_by_test_id("test-case-source-point")).to_contain_text(
        f"#{point_id}"
    )
    expect(wide_admin_page.get_by_test_id("test-case-source-point")).to_contain_text(
        "扫码登录连续失败 5 次锁定"
    )
    shot(wide_admin_page, "detail", full_page=False)

    # ---- 评审通过 ----
    wide_admin_page.get_by_test_id("test-case-review-comment").fill("e2e 通过")
    wide_admin_page.get_by_test_id("test-case-approve-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已通过")
    expect(wide_admin_page.get_by_test_id("test-case-review-status")).to_contain_text("已通过")
    # 抽屉收起后再看列表：整页截图时 fixed 定位的抽屉会被裁掉半截。
    wide_admin_page.keyboard.press("Escape")
    expect(wide_admin_page.get_by_test_id("test-case-drawer")).not_to_be_visible()

    expect(wide_admin_page.get_by_test_id(f"test-case-status-{case_id}")).to_contain_text(
        "已通过"
    )
    # 评审过的用例不再有「评审」入口
    expect(wide_admin_page.get_by_test_id(f"test-case-review-btn-{case_id}")).to_have_count(0)
    shot(wide_admin_page, "reviewed")


@pytest.mark.task("T109")
def test_ac_178_manual_case_and_step_reorder_ui(wide_admin_page: Page, api, shot) -> None:
    """手工新增 → 编辑步骤（上移 / 下移）→ 保存 → 步骤表与编辑结果一致。"""
    project = api.create_project(_name("tc-manual"))
    project_id = project["id"]
    point_id = _make_approved_point(api, project_id, "验证码错误提示", "验证码登录")

    wide_admin_page.reload()
    _open_test_cases(wide_admin_page, project["name"])

    # ---- 手工新增 ----
    wide_admin_page.get_by_test_id("test-case-create-btn").click()
    wide_admin_page.get_by_test_id("test-case-title-input").fill("人工补录：验证码错误提示")
    wide_admin_page.locator(
        ".ant-form-item", has_text="所属测试点"
    ).locator(".ant-select").first.click()
    wide_admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option", has_text=f"#{point_id}"
    ).first.click()
    wide_admin_page.keyboard.press("Escape")

    # 两行步骤
    wide_admin_page.get_by_test_id("test-case-step-action-input-0").fill("输入错误验证码")
    wide_admin_page.get_by_test_id("test-case-step-expected-input-0").fill("提示验证码错误")
    wide_admin_page.get_by_test_id("test-case-step-add-btn").click()
    wide_admin_page.get_by_test_id("test-case-step-action-input-1").fill("重新获取验证码")
    wide_admin_page.get_by_test_id("test-case-step-expected-input-1").fill("验证码刷新成功")

    wide_admin_page.get_by_test_id("test-case-edit-submit-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("用例已新增")

    manual = _cases_by_title(api, project_id)["人工补录：验证码错误提示"]
    manual_id = manual["id"]
    expect(wide_admin_page.get_by_test_id(f"test-case-title-{manual_id}")).to_be_visible()

    # ---- 编辑步骤：把第 2 步上移到第 1 位 ----
    wide_admin_page.get_by_test_id(f"test-case-detail-btn-{manual_id}").click()
    expect(wide_admin_page.get_by_test_id("test-case-drawer")).to_be_visible()
    wait_drawer_settled(wide_admin_page, wide_admin_page.get_by_test_id("test-case-drawer"))
    wide_admin_page.get_by_test_id("test-case-steps-edit-btn").click()

    editor = wide_admin_page.get_by_test_id("test-case-steps-editor")
    expect(editor.get_by_role("row")).to_have_count(3)  # 表头 + 2 步
    wide_admin_page.get_by_test_id("test-case-step-up-1").click()
    # 上移后第 1 行变成「重新获取验证码」
    expect(wide_admin_page.get_by_test_id("test-case-step-action-input-0")).to_have_value(
        "重新获取验证码"
    )
    expect(wide_admin_page.get_by_test_id("test-case-step-action-input-1")).to_have_value(
        "输入错误验证码"
    )
    shot(wide_admin_page, "steps-reorder", full_page=False)

    wide_admin_page.get_by_test_id("test-case-steps-save-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("步骤已保存")

    # ---- 保存后的顺序与编辑结果一致 ----
    reloaded = _cases_by_title(api, project_id)["人工补录：验证码错误提示"]
    assert [step["step_no"] for step in reloaded["steps"]] == [1, 2]
    assert [step["action"] for step in reloaded["steps"]] == [
        "重新获取验证码",
        "输入错误验证码",
    ]

    # 抽屉里的只读步骤表也同步了
    expect(wide_admin_page.get_by_test_id("test-case-step-action-0")).to_contain_text(
        "重新获取验证码"
    )
    expect(wide_admin_page.get_by_test_id("test-case-step-action-1")).to_contain_text(
        "输入错误验证码"
    )
    shot(wide_admin_page, "steps-saved", full_page=False)


@pytest.mark.task("T109")
def test_ac_171_needs_review_and_ack_ui(wide_admin_page: Page, api, shot) -> None:
    """改源测试点 → 出现「待复核」→ 确认已复核后消失。"""
    project = api.create_project(_name("tc-review"))
    project_id = project["id"]
    point_id = _make_approved_point(api, project_id, "锁定策略提示", "登录锁定")

    # 造一条用例（走真实接口，指纹正确）
    case = _create_case(
        api,
        project_id,
        point_id=point_id,
        title="锁定后再次登录被拒",
        steps=[{"action": "被锁定后再次登录", "expected": "提示账号已锁定"}],
    )
    case_id = case["id"]

    wide_admin_page.reload()
    _open_test_cases(wide_admin_page, project["name"])
    wide_admin_page.get_by_test_id("test-case-refresh-btn").click()
    expect(wide_admin_page.get_by_test_id(f"test-case-title-{case_id}")).to_be_visible()

    # 还没改源测试点时不该有待复核
    expect(wide_admin_page.get_by_test_id(f"test-case-title-{case_id}")).not_to_contain_text(
        "待复核"
    )

    # ---- 改源测试点（改内容，不改 updated_at） ----
    update = api.ctx.patch(
        f"/api/projects/{project_id}/test-points/points/{point_id}",
        data={"name": "锁定策略提示（已修订）"},
        headers=_headers(api),
    )
    assert update.status == 200, update.text()

    wide_admin_page.get_by_test_id("test-case-refresh-btn").click()
    expect(wide_admin_page.get_by_test_id(f"test-case-title-{case_id}")).to_contain_text(
        "待复核"
    )
    shot(wide_admin_page, "needs-review")

    # 详情抽屉里有告警条与「确认已复核」
    wide_admin_page.get_by_test_id(f"test-case-detail-btn-{case_id}").click()
    expect(wide_admin_page.get_by_test_id("test-case-drawer")).to_be_visible()
    wait_drawer_settled(wide_admin_page, wide_admin_page.get_by_test_id("test-case-drawer"))
    expect(wide_admin_page.get_by_test_id("test-case-needs-review-alert")).to_be_visible()
    expect(wide_admin_page.get_by_test_id("test-case-needs-review-alert")).to_contain_text(
        "所属测试点已变更"
    )
    wide_admin_page.get_by_test_id("test-case-ack-btn").click()
    expect(wide_admin_page.locator(".ant-message")).to_contain_text("已确认复核")
    expect(wide_admin_page.get_by_test_id("test-case-needs-review-alert")).to_have_count(0)
    wide_admin_page.keyboard.press("Escape")

    expect(wide_admin_page.get_by_test_id(f"test-case-title-{case_id}")).not_to_contain_text(
        "待复核"
    )
    shot(wide_admin_page, "acked")


@pytest.mark.task("T109")
def test_ac_177_export_excel_ui(wide_admin_page: Page, api, shot, tmp_path) -> None:
    """导出 Excel：下载 `.xlsx`，首行表头与列名一致。"""
    project = api.create_project(_name("tc-export"))
    project_id = project["id"]
    point_id = _make_approved_point(api, project_id, "导出用的测试点", "导出功能")

    _create_case(
        api,
        project_id,
        point_id=point_id,
        title="导出的用例",
        case_type="api",
        priority="high",
        steps=[
            {"action": "第一步", "expected": "预期一"},
            {"action": "第二步", "expected": "预期二"},
            {"action": "第三步", "expected": "预期三"},
        ],
    )

    wide_admin_page.reload()
    _open_test_cases(wide_admin_page, project["name"])

    with wide_admin_page.expect_download() as info:
        wide_admin_page.get_by_test_id("test-case-export-btn").click()

    download = info.value
    assert download.suggested_filename.startswith(f"test-cases-{project_id}-")
    assert download.suggested_filename.endswith(".xlsx")

    # 用 Excel 打开核对表头与行数：3 个步骤 → 3 行
    # Playwright 的临时文件没有扩展名，openpyxl 按后缀判类型——
    # 先原样落盘成 `.xlsx` 再读。
    from openpyxl import load_workbook

    saved = tmp_path / download.suggested_filename
    download.save_as(str(saved))
    workbook = load_workbook(saved)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][0] == "用例ID"
    assert rows[0][1] == "用例名称"
    assert "步骤序号" in rows[0]
    assert "操作步骤" in rows[0]
    assert "预期结果" in rows[0]
    assert len(rows) == 4  # 表头 + 3 个步骤
    assert [row[8] for row in rows[1:]] == [1, 2, 3]
    assert rows[1][2] == "接口"
    assert rows[1][3] == "高"
    assert rows[1][11] == "待评审"
    shot(wide_admin_page, "exported")
