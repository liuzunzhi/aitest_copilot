"""功能基线管理页的前台核对（AC-62 ~ AC-72，T65）。

页面入口：项目详情 →「基线管理」Tab。
结构：模块 → 功能 → 功能点；标签挂在快照上，打标前要有审核通过的快照。
"""

import uuid

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e


def _name(prefix: str) -> str:
    return f"e2e-{prefix}-{uuid.uuid4().hex[:6]}"


def _headers(api, token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or api.admin_token}"}


def _create_module(api, project_id: int, name: str) -> dict:
    response = api.ctx.post(
        f"/api/projects/{project_id}/baselines/modules",
        data={"name": name},
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    return response.json()


def _create_function(api, project_id: int, module_id: int, name: str) -> dict:
    response = api.ctx.post(
        f"/api/projects/{project_id}/baselines/functions",
        data={"module_id": module_id, "name": name},
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    return response.json()


def _create_point(api, project_id: int, function_id: int, name: str) -> dict:
    response = api.ctx.post(
        f"/api/projects/{project_id}/baselines/functions/{function_id}/feature-points",
        data={"name": name},
        headers=_headers(api),
    )
    assert response.status in (200, 201), response.text()
    return response.json()


def _submit_review(api, project_id: int, token: str | None = None) -> dict:
    response = api.ctx.post(
        f"/api/projects/{project_id}/baselines/reviews/submit",
        data={"comment": "e2e 前台核对"},
        headers=_headers(api, token),
    )
    assert response.status in (200, 201), response.text()
    return response.json()


def _pending_revision(api, project_id: int) -> dict:
    pending = api.ctx.get(
        f"/api/projects/{project_id}/baselines/revisions?status=submitted",
        headers=_headers(api),
    ).json()["items"]
    assert pending, "应有一条审核中的记录"
    return pending[0]


def _open_management(page: Page, project_name: str) -> None:
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="基线管理").click()
    expect(page.get_by_test_id("add-module")).to_be_visible()


def _tree_node(page: Page, node_text: str) -> Locator:
    """按可见文本定位树节点（只取标题节点，避免命中祖先容器）。"""
    return page.locator(".ant-tree-treenode", has_text=node_text).first


def _expand(page: Page, node_text: str) -> None:
    """展开某个树节点。

    antd v6 的 DOM 是 `.ant-tree-treenode > .ant-tree-switcher`，
    收起/展开状态类是 `ant-tree-switcher_close` / `ant-tree-switcher_open`。
    """
    switcher = _tree_node(page, node_text).locator("> .ant-tree-switcher").first
    if switcher.count() == 0:
        return
    classes = switcher.get_attribute("class") or ""
    if "ant-tree-switcher_close" in classes:
        switcher.click()
        page.wait_for_timeout(400)


def _pick(page: Page, label: str, option: str) -> None:
    """在 antd Select 里选一项。

    多选 Select 选完不会自己收起，dropdown 浮在 Modal 之上会挡住按钮；
    但单选的 dropdown 选完就关了，这时再按 Esc 会把整个 Modal 也关掉，
    所以只在 dropdown 还开着的时候才收。
    """
    page.locator(".ant-form-item", has_text=label).locator(".ant-select").first.click()
    page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option", has_text=option
    ).first.click()
    page.wait_for_timeout(200)
    if page.locator(".ant-select-dropdown:visible").count():
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)


def _modal(page: Page) -> Locator:
    return page.locator(".ant-modal:visible").last


def _modal_titled(page: Page, title: str) -> Locator:
    """按标题定位弹窗。

    标签弹窗与「清除标签」弹窗会叠在一起，`.last` 未必是最上层，
    按标题取才不会点错。
    """
    return page.locator(".ant-modal:visible").filter(has_text=title).last


def _save(page: Page) -> None:
    """弹窗里的「保存」——限定在可见弹窗内，避免撞上保留策略的保存按钮。"""
    _modal(page).get_by_role("button", name="保存").click()


def _form_error(page: Page, text: str) -> None:
    """表单校验提示就地渲染在字段下方，不是 toast。"""
    expect(page.locator(".ant-form-item-explain-error").filter(has_text=text)).to_be_visible()


def _wait_modal_closed(page: Page) -> None:
    """等弹窗关掉——弹窗的遮罩会挡住底下的树节点。"""
    expect(page.locator(".ant-modal:visible")).to_have_count(0)


@pytest.mark.task("T65")
def test_ac_62_three_level_structure_ui(admin_page: Page, api, shot) -> None:
    """AC-62：模块 → 功能 → 功能点三级，树上逐级可见。"""
    project = api.create_project(_name("bl-struct"))
    admin_page.reload()
    _open_management(admin_page, project["name"])

    admin_page.get_by_test_id("add-module").click()
    admin_page.get_by_label("模块名").fill("支付模块")
    _save(admin_page)
    expect(admin_page.locator(".ant-message")).to_contain_text("模块已创建")

    # 模块层默认展开，功能行直接可见
    module_node = _tree_node(admin_page, "支付模块")
    expect(module_node).to_be_visible()
    module_node.get_by_role("button", name="新增功能").click()
    admin_page.get_by_label("功能名").fill("提交订单")
    _save(admin_page)
    expect(admin_page.locator(".ant-message")).to_contain_text("功能已创建")

    function_node = _tree_node(admin_page, "提交订单")
    expect(function_node).to_be_visible()
    function_node.get_by_role("button", name="新增功能点").click()
    admin_page.get_by_label("功能点名").fill("填写收货地址")
    _save(admin_page)
    expect(admin_page.locator(".ant-message")).to_contain_text("功能点已创建")

    expect(_tree_node(admin_page, "支付模块")).to_be_visible()
    expect(_tree_node(admin_page, "提交订单")).to_be_visible()
    # AC-63：来源只展示（手工），不可编辑
    expect(admin_page.locator(".ant-tree-treenode", has_text="手工").first).to_be_visible()
    shot(admin_page, "three-level")

    _expand(admin_page, "提交订单")
    expect(_tree_node(admin_page, "填写收货地址")).to_be_visible()
    shot(admin_page, "feature-point")


@pytest.mark.task("T65")
def test_ac_64_module_not_empty_gives_two_actions(admin_page: Page, api, shot) -> None:
    """AC-64：模块下有功能时不给删，给「迁移功能」「删除功能」两个入口。"""
    project = api.create_project(_name("bl-delete"))
    module = _create_module(api, project["id"], "待删模块")
    _create_function(api, project["id"], module["id"], "待删功能")
    admin_page.reload()
    _open_management(admin_page, project["name"])

    node = _tree_node(admin_page, "待删模块")
    node.get_by_role("button", name="删除").first.click()
    admin_page.locator(".ant-popover:visible").get_by_role("button", name="删除").click()

    expect(admin_page.get_by_text("模块下还有功能")).to_be_visible()
    expect(admin_page.get_by_test_id("not-empty-migrate")).to_be_visible()
    expect(admin_page.get_by_test_id("not-empty-delete-functions")).to_be_visible()
    shot(admin_page, "module-not-empty")

    # 走「删除功能并删除模块」这条路，模块最终消失
    admin_page.get_by_test_id("not-empty-delete-functions").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("模块已删除")
    expect(admin_page.locator(".ant-tree-treenode", has_text="待删模块")).to_have_count(0)
    shot(admin_page, "module-deleted")


@pytest.mark.task("T65")
def test_ac_65_migrate_functions_ui(admin_page: Page, api, shot) -> None:
    """AC-65：功能迁移到另一模块，保留来源模块标记。"""
    project = api.create_project(_name("bl-migrate"))
    source = _create_module(api, project["id"], "源模块")
    target = _create_module(api, project["id"], "目标模块")
    _create_function(api, project["id"], source["id"], "要迁移的功能")
    admin_page.reload()
    _open_management(admin_page, project["name"])

    _tree_node(admin_page, "源模块").get_by_role("button", name="迁移功能").click()
    _pick(admin_page, "目标模块", "目标模块")
    _pick(admin_page, "要迁移的功能", "要迁移的功能")
    _modal(admin_page).get_by_role("button", name="迁移").click()

    expect(admin_page.locator(".ant-message")).to_contain_text("功能已迁移")
    # 功能节点是独立的 treenode（不在模块行里），断言落在功能行上。
    migrated_node = _tree_node(admin_page, "要迁移的功能")
    expect(migrated_node).to_be_visible()
    expect(migrated_node).to_contain_text("来自源模块")
    shot(admin_page, "migrated")


@pytest.mark.task("T65")
def test_ac_66_67_label_and_clear_ui(
    admin_page: Page, api, make_user, shot
) -> None:
    """AC-66 两级打标互不汇总；AC-67 清除留痕、原因必填、「其他」要备注。"""
    project = api.create_project(_name("bl-label"))
    module = _create_module(api, project["id"], "标签模块")
    function = _create_function(api, project["id"], module["id"], "被打标的功能")
    point = _create_point(api, project["id"], function["id"], "被打标的功能点")

    # 打标需要快照：提交后由另一位项目管理员审核通过
    reviewer = make_user()
    api.add_member(project["id"], reviewer["id"], "project_admin")
    from tests.e2e.support import USER_PASSWORD, token_for

    reviewer_token = token_for(api.ctx, reviewer["username"], USER_PASSWORD)
    _submit_review(api, project["id"])
    pending = _pending_revision(api, project["id"])
    approve = api.ctx.post(
        f"/api/projects/{project['id']}/baselines/reviews/{pending['id']}/approve",
        data={"comment": "e2e 通过"},
        headers=_headers(api, reviewer_token),
    )
    assert approve.status == 200, approve.text()

    admin_page.reload()
    _open_management(admin_page, project["name"])

    # 给功能打「变更」
    _tree_node(admin_page, "被打标的功能").get_by_role("button", name="标签").click()
    _pick(admin_page, "标签类型", "变更")
    admin_page.get_by_test_id("submit-label").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("标签已打上")
    shot(admin_page, "label-function")
    _wait_modal_closed(admin_page)

    # 给功能点打「新增」
    _expand(admin_page, "被打标的功能")
    _tree_node(admin_page, "被打标的功能点").get_by_role("button", name="标签").click()
    _pick(admin_page, "标签类型", "新增")
    admin_page.get_by_test_id("submit-label").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("标签已打上")
    _wait_modal_closed(admin_page)

    # AC-66：功能行的标签只来自功能自身，不汇总功能点标签
    fn_node = _tree_node(admin_page, "被打标的功能")
    fn_tags = fn_node.locator(".ant-tag")
    expect(fn_tags.filter(has_text="变更")).to_have_count(1)
    expect(fn_tags.filter(has_text="新增")).to_have_count(0)
    shot(admin_page, "label-two-levels")

    # AC-67：清除必须选原因
    fn_node.get_by_role("button", name="标签").click()
    label_modal = _modal_titled(admin_page, "标签 ·")
    clear_modal = _modal_titled(admin_page, "清除标签")
    label_modal.get_by_role("button", name="清除").first.click()
    expect(clear_modal).to_be_visible()
    clear_modal.get_by_role("button", name="清除").click()
    _form_error(admin_page, "请选择清除原因")
    shot(admin_page, "clear-reason-required")

    # 选「其他」→ 必须填备注
    _pick(admin_page, "清除原因", "其他")
    clear_modal.get_by_role("button", name="清除").click()
    _form_error(admin_page, "必须填写备注")
    shot(admin_page, "clear-note-required")

    clear_modal.locator(".ant-form-item", has_text="备注").locator("textarea").fill(
        "判断有误"
    )
    clear_modal.get_by_role("button", name="清除").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("标签已清除")
    # 历史留痕：行还在，状态是「已清除」
    expect(label_modal).to_contain_text("已清除")
    shot(admin_page, "label-cleared")


@pytest.mark.task("T65")
def test_ac_69_70_review_and_snapshot_ui(
    admin_page: Page, api, make_user, page_as, shot
) -> None:
    """AC-69 提交→审核中→他人通过；AC-70 版本号 +1、快照结构冻结。"""
    project = api.create_project(_name("bl-review"))
    module = _create_module(api, project["id"], "审核模块")
    _create_function(api, project["id"], module["id"], "审核功能")
    admin_page.reload()
    _open_management(admin_page, project["name"])

    admin_page.get_by_test_id("submit-review").click()
    _modal(admin_page).get_by_role("button", name="提交").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("已提交审核")
    expect(admin_page.get_by_text("审核中")).to_be_visible()
    shot(admin_page, "submitted")

    # 另一位项目管理员审核通过
    reviewer = make_user()
    api.add_member(project["id"], reviewer["id"], "project_admin")
    from tests.e2e.support import USER_PASSWORD

    reviewer_page = page_as(
        reviewer["username"], USER_PASSWORD, path=f"/projects/{project['id']}"
    )
    reviewer_page.get_by_role("tab", name="基线管理").click()
    expect(reviewer_page.get_by_text("审核中")).to_be_visible()
    reviewer_page.get_by_role("button", name="通过").first.click()
    _modal(reviewer_page).get_by_role("button", name="通过").click()
    expect(reviewer_page.locator(".ant-message")).to_contain_text("审核通过")
    # 版本号从 v1.0 起递增（spec §2.3.1）
    expect(reviewer_page.locator(".ant-table-row", has_text="v1.0")).to_be_visible()
    shot(reviewer_page, "approved-v1")

    # 再来一份 → v1.1
    admin_page.get_by_role("tab", name="基线管理").click()
    admin_page.get_by_test_id("submit-review").click()
    _modal(admin_page).get_by_role("button", name="提交").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("已提交审核")
    reviewer_page.reload()
    reviewer_page.get_by_role("tab", name="基线管理").click()
    reviewer_page.get_by_role("button", name="通过").first.click()
    _modal(reviewer_page).get_by_role("button", name="通过").click()
    expect(reviewer_page.locator(".ant-message")).to_contain_text("审核通过")
    expect(reviewer_page.locator(".ant-table-row", has_text="v1.1")).to_be_visible()
    shot(reviewer_page, "approved-v2")

    # 查看结构：v1.0 快照里是审核通过那一刻的模块树
    admin_page.reload()
    admin_page.get_by_role("tab", name="基线管理").click()
    admin_page.get_by_role("button", name="查看结构").first.click()
    structure = admin_page.locator(".ant-modal").locator(".ant-tree")
    expect(structure).to_contain_text("审核模块")
    expect(structure).to_contain_text("审核功能")
    shot(admin_page, "snapshot-structure")


@pytest.mark.task("T65")
def test_ac_71_72_retention_ui(admin_page: Page, api, make_user, shot) -> None:
    """AC-71 保留上限出现待清理候选；AC-72 被引用快照禁止删除并提示引用来源。"""
    project = api.create_project(_name("bl-retention"))
    module = _create_module(api, project["id"], "保留模块")
    function = _create_function(api, project["id"], module["id"], "保留功能")

    from tests.e2e.support import USER_PASSWORD, token_for

    # 提交人不能自己审核 → 造一位项目管理员来审
    reviewer = make_user()
    api.add_member(project["id"], reviewer["id"], "project_admin")
    reviewer_token = token_for(api.ctx, reviewer["username"], USER_PASSWORD)

    # 两份审核通过的快照
    for _ in range(2):
        _submit_review(api, project["id"])
        pending = _pending_revision(api, project["id"])
        approve = api.ctx.post(
            f"/api/projects/{project['id']}/baselines/reviews/{pending['id']}/approve",
            data={"comment": "e2e 通过"},
            headers=_headers(api, reviewer_token),
        )
        assert approve.status == 200, approve.text()

    # 给 v1.0 打一个标签 → 它被引用，删不掉
    revisions = api.ctx.get(
        f"/api/projects/{project['id']}/baselines/revisions?status=approved",
        headers=_headers(api),
    ).json()["items"]
    first = next(item for item in revisions if item["version_no"] == 0)
    labelled = api.ctx.post(
        f"/api/projects/{project['id']}/baselines/labels",
        data={
            "revision_id": first["id"],
            "target_type": "function",
            "target_id": function["id"],
            "label_type": "changed",
        },
        headers=_headers(api),
    )
    assert labelled.status == 201, labelled.text()

    admin_page.reload()
    _open_management(admin_page, project["name"])

    # 设保留上限 1 → 超出的那份进入待清理候选
    admin_page.get_by_role("spinbutton").fill("1")
    admin_page.get_by_test_id("save-retention").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("保留策略已更新")
    expect(admin_page.get_by_text("待清理候选")).to_be_visible()
    expect(admin_page.get_by_text("引用来源")).to_be_visible()
    shot(admin_page, "retention-candidates")

    # AC-72：删被引用的快照 → 409，提示不能删
    admin_page.locator(".ant-table-row", has_text="v1.0").get_by_role(
        "button", name="删除"
    ).click()
    admin_page.locator(".ant-popover:visible").get_by_role("button", name="删除").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("仍被标签引用")
    shot(admin_page, "snapshot-referenced")
