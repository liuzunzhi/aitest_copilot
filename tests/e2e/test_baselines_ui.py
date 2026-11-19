"""功能基线管理页的前台核对（AC-62 ~ AC-72，T65）。

页面入口：项目详情 →「基线管理」Tab。
结构：模块 → 功能 → 功能点；标签挂在快照上，打标前要有审核通过的快照。
"""

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import (
    click_save as _save,
    expect_form_error as _form_error,
    expand_tree_node as _expand,
    modal_titled as _modal_titled,
    pick_select_option as _pick,
    tree_node as _tree_node,
    unique_name as _name,
    visible_modal as _modal,
    wait_modal_closed as _wait_modal_closed,
)

pytestmark = pytest.mark.e2e


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


def _filter_select(page: Page, index: int) -> Locator:
    """筛选区的第 index 个 Select：0 = 标签类型，1 = 来源类型。

    这些 Select 不在 Form.Item 里，`pick_select_option` 用不了，
    所以按「搜索框所在的 Space」定位，避免撞上页面下方的其他下拉。
    """
    bar = page.get_by_placeholder("搜索功能名").locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '),"
        " ' ant-space ')][1]"
    )
    return bar.locator(".ant-select").nth(index)


def _pick_filter(page: Page, select: Locator, option: str) -> None:
    select.click()
    page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option", has_text=option
    ).first.click()
    expect(page.locator(".ant-select-dropdown:visible")).to_have_count(0)


def _clear_filter(select: Locator) -> None:
    """清空 allowClear 的筛选 Select：悬停出清除图标再点掉。"""
    select.hover()
    select.locator(".ant-select-clear").click()
    expect(select.locator(".ant-select-selection-item")).to_have_count(0)


def _open_tree_readonly(page: Page, project_name: str) -> None:
    """成员 / 访客进入基线管理：这里没有「新增模块」，不能复用 `_open_management`。"""
    page.get_by_role("row").filter(has_text=project_name).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="基线管理").click()


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
    node.get_by_test_id(f"delete-module-{module['id']}").click()
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

    _tree_node(admin_page, "源模块").get_by_test_id(f"migrate-{source['id']}").click()
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


@pytest.mark.task("T66")
def test_ac_73_filter_ui(admin_page: Page, api, make_user, shot) -> None:
    """AC-73：树上标签 / 来源 / 关键词组合筛选，命中条数与库内一致。"""
    project = api.create_project(_name("bl-filter"))
    module = _create_module(api, project["id"], _name("检索模块"))
    changed = _create_function(api, project["id"], module["id"], _name("变更功能"))
    plain = _create_function(api, project["id"], module["id"], _name("未变更功能"))

    # 标签挂在审核通过的快照上，提交人与审核人不能是同一个
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
    labelled = api.ctx.post(
        f"/api/projects/{project['id']}/baselines/labels",
        data={
            "revision_id": pending["id"],
            "target_type": "function",
            "target_id": changed["id"],
            "label_type": "changed",
        },
        headers=_headers(api),
    )
    assert labelled.status == 201, labelled.text()

    admin_page.reload()
    _open_management(admin_page, project["name"])
    label_select = _filter_select(admin_page, 0)
    source_select = _filter_select(admin_page, 1)
    search = admin_page.get_by_placeholder("搜索功能名")
    version_tags = admin_page.locator(".ant-tag", has_text="第 1 版")

    # 不加筛选：两条功能都在，命中 2 条
    expect(_tree_node(admin_page, changed["name"])).to_be_visible()
    expect(_tree_node(admin_page, plain["name"])).to_be_visible()
    expect(version_tags).to_have_count(2)
    shot(admin_page, "filter-initial")

    # 标签类型 = 变更 → 只剩打过标的那条
    _pick_filter(admin_page, label_select, "变更")
    expect(_tree_node(admin_page, changed["name"])).to_be_visible()
    expect(_tree_node(admin_page, plain["name"])).to_have_count(0)
    expect(version_tags).to_have_count(1)
    shot(admin_page, "filter-label")

    # 标签 + 关键词叠加：搜另一条功能名 → 一条都不剩
    search.fill(plain["name"])
    search.press("Enter")
    expect(version_tags).to_have_count(0)
    expect(_tree_node(admin_page, changed["name"])).to_have_count(0)
    shot(admin_page, "filter-label-keyword")

    # 清掉标签，只留关键词 → 命中未变更的那条
    _clear_filter(label_select)
    expect(_tree_node(admin_page, plain["name"])).to_be_visible()
    expect(_tree_node(admin_page, changed["name"])).to_have_count(0)
    expect(version_tags).to_have_count(1)

    # 清掉关键词 → 两条都回来；再按来源类型筛选
    search.fill("")
    expect(version_tags).to_have_count(2)
    _pick_filter(admin_page, source_select, "文档解析")
    # 两条都是手工添加 → 功能行全部被过滤，模块骨架保留
    expect(version_tags).to_have_count(0)
    expect(_tree_node(admin_page, module["name"])).to_be_visible()
    shot(admin_page, "filter-source")

    # 清空筛选 → 两条功能都回来
    _clear_filter(source_select)
    expect(_tree_node(admin_page, changed["name"])).to_be_visible()
    expect(_tree_node(admin_page, plain["name"])).to_be_visible()
    expect(version_tags).to_have_count(2)
    shot(admin_page, "filter-cleared")


_DOC_MD = """# 支付需求

## 1. 概述

支付支持扫码与刷卡。

## 2. 流程

下单 → 支付 → 回调。
"""


def _upload_and_activate(api, project_id: int) -> dict:
    """上传一份 md 并确认生效（只有生效版本能推导基线）。"""
    response = api.ctx.post(
        f"/api/projects/{project_id}/documents",
        multipart={
            "file": {
                "name": "支付需求.md",
                "mimeType": "text/markdown",
                "buffer": _DOC_MD.encode("utf-8"),
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


def _derive_and_adopt(api, project_id: int, uploaded: dict) -> dict:
    """走真实推导 + 采纳链路，产出一条 `document_derived` 功能。"""
    templates = api.ctx.get(
        "/api/prompt-templates",
        params={"task_type": "document_parse"},
        headers=_headers(api),
    )
    assert templates.ok, templates.text()
    items = templates.json()["items"]
    assert items, "document_parse 提示词模板未播种"

    response = api.ctx.post(
        f"/api/projects/{project_id}/baselines/derive",
        data={
            "document_id": uploaded["document"]["id"],
            "document_version_id": uploaded["version"]["id"],
            "template_id": items[0]["id"],
        },
        headers=_headers(api),
    )
    assert response.status == 201, response.text()
    derive = response.json()
    assert derive["status"] == "succeeded", derive
    assert derive["candidates"], "推导没有产出候选"

    adopted = api.ctx.post(
        f"/api/projects/{project_id}/baselines/derive/{derive['id']}/adopt",
        data={
            "candidates": [
                {"candidate_id": root["id"], "action": "create"}
                for root in derive["candidates"]
            ]
        },
        headers=_headers(api),
    )
    assert adopted.status == 200, adopted.text()
    return adopted.json()


@pytest.mark.task("T66")
def test_ac_73_source_filter_document_derived(admin_page: Page, api, shot) -> None:
    """AC-73：来源筛选「文档解析」必须匹配后端的 `document_derived`。

    修复前的下拉值是 `'document'`，而结构表存的是 `'document_derived'`，
    选「文档解析」永远 0 条——所以这里必须造出一条真实的推导功能。
    """
    project = api.create_project(_name("bl-src"))
    module = _create_module(api, project["id"], _name("手工模块"))
    manual = _create_function(api, project["id"], module["id"], _name("手工功能"))

    uploaded = _upload_and_activate(api, project["id"])
    _derive_and_adopt(api, project["id"], uploaded)

    functions = api.ctx.get(
        f"/api/projects/{project['id']}/baselines/functions",
        headers=_headers(api),
    ).json()["items"]
    derived = [row for row in functions if row["source_type"] == "document_derived"]
    assert derived, "采纳后应有文档推导的功能"

    admin_page.reload()
    _open_management(admin_page, project["name"])
    source_select = _filter_select(admin_page, 1)

    # 文档解析 → 只剩推导出来的那条功能
    _pick_filter(admin_page, source_select, "文档解析")
    expect(_tree_node(admin_page, derived[0]["name"])).to_be_visible()
    expect(_tree_node(admin_page, manual["name"])).to_have_count(0)
    shot(admin_page, "filter-document-derived")

    # 手工添加 → 只剩手工建的那条
    _pick_filter(admin_page, source_select, "手工添加")
    expect(_tree_node(admin_page, manual["name"])).to_be_visible()
    expect(_tree_node(admin_page, derived[0]["name"])).to_have_count(0)
    shot(admin_page, "filter-manual")


@pytest.mark.task("T66")
def test_ac_74_permission_matrix_ui(api, make_user, page_as, shot) -> None:
    """AC-74：成员 / 访客只读，非成员读 403，member 写 403，归档项目写 409。"""
    from tests.e2e.support import USER_PASSWORD, token_for

    project = api.create_project(_name("bl-perm"))
    module = _create_module(api, project["id"], _name("权限模块"))
    function = _create_function(api, project["id"], module["id"], _name("权限功能"))
    member = make_user()
    guest = make_user()
    outsider = make_user()
    api.add_member(project["id"], member["id"], "member")
    api.add_member(project["id"], guest["id"], "guest")

    member_token = token_for(api.ctx, member["username"], USER_PASSWORD)
    guest_token = token_for(api.ctx, guest["username"], USER_PASSWORD)
    outsider_token = token_for(api.ctx, outsider["username"], USER_PASSWORD)

    # 读接口：成员（含访客）可读，系统管理员兜底
    for token in (member_token, guest_token, api.admin_token):
        readable = api.ctx.get(
            f"/api/projects/{project['id']}/baselines/modules",
            headers=_headers(api, token),
        )
        assert readable.status == 200, readable.text()

    # 非成员读 → 403 NOT_PROJECT_MEMBER
    denied = api.ctx.get(
        f"/api/projects/{project['id']}/baselines/functions",
        headers=_headers(api, outsider_token),
    )
    assert denied.status == 403
    assert denied.json()["code"] == "NOT_PROJECT_MEMBER"

    # 前台：两种身份都能看到树，但没有任何写入口
    for user, label in ((member, "member"), (guest, "guest")):
        page = page_as(user["username"])
        _open_tree_readonly(page, project["name"])
        expect(_tree_node(page, module["name"])).to_be_visible()
        expect(_tree_node(page, function["name"])).to_be_visible()
        expect(page.get_by_test_id("add-module")).to_have_count(0)
        expect(page.get_by_role("button", name="标签")).to_have_count(0)
        expect(page.get_by_role("button", name="清除")).to_have_count(0)
        shot(page, f"readonly-{label}")

    # 写接口：member / guest → 403 NOT_PROJECT_ADMIN
    for token in (member_token, guest_token):
        forbidden = api.ctx.post(
            f"/api/projects/{project['id']}/baselines/modules",
            data={"name": _name("越权模块")},
            headers=_headers(api, token),
        )
        assert forbidden.status == 403
        assert forbidden.json()["code"] == "NOT_PROJECT_ADMIN"

    # 归档项目内写接口 → 409（先判归档再判角色）
    api.archive_project(project["id"])
    archived = api.ctx.post(
        f"/api/projects/{project['id']}/baselines/modules",
        data={"name": _name("归档模块")},
        headers=_headers(api, member_token),
    )
    assert archived.status == 409
    assert archived.json()["code"] == "PROJECT_ARCHIVED"


@pytest.mark.task("T66")
def test_spec_23_archived_module_hidden_ui(admin_page: Page, api, shot) -> None:
    """spec §2.3 第 5 条：归档模块默认不展示，切换状态后可取消归档。"""
    project = api.create_project(_name("bl-archive"))
    module = _create_module(api, project["id"], _name("归档模块"))
    admin_page.reload()
    _open_management(admin_page, project["name"])

    node = _tree_node(admin_page, module["name"])
    expect(node).to_be_visible()
    node.get_by_test_id("baseline-module-archive").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("模块已归档")
    # 默认「在用」视图里归档模块消失
    expect(admin_page.locator(".ant-tree-treenode", has_text=module["name"])).to_have_count(0)
    shot(admin_page, "archived-hidden")

    status_filter = admin_page.get_by_test_id("baseline-status-filter")
    # 切「全部」→ 归档模块重新出现，操作变成「取消归档」
    status_filter.click()
    admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option", has_text="全部"
    ).first.click()
    expect(admin_page.locator(".ant-select-dropdown:visible")).to_have_count(0)
    node = _tree_node(admin_page, module["name"])
    expect(node).to_be_visible()
    expect(node.get_by_role("button", name="取消归档")).to_be_visible()
    shot(admin_page, "archived-in-all")

    node.get_by_test_id("baseline-module-archive").click()
    expect(admin_page.locator(".ant-message")).to_contain_text("模块已取消归档")
    expect(_tree_node(admin_page, module["name"])).to_be_visible()

    # 回到「在用」视图：模块可见且操作恢复为「归档」
    status_filter.click()
    admin_page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option", has_text="在用"
    ).first.click()
    expect(admin_page.locator(".ant-select-dropdown:visible")).to_have_count(0)
    active_node = _tree_node(admin_page, module["name"])
    expect(active_node).to_be_visible()
    expect(active_node.get_by_role("button", name="归档")).to_be_visible()
    shot(admin_page, "unarchived-active")
