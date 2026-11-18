"""T87 · 系统设置页 + 05 动态模板下拉（AC-116 / AC-117）。

覆盖点：

- 系统管理员新建大模型配置：接口地址故意填不可达端口，**Key 只显示掩码**；
- 点「测试连通性」：后端返回 200 + `ok=false`，页面按失败原因展示，
  不是 502 报错；
- 编辑提示词模板正文 → 版本号 +1（只改正文才 +1）；
- 05 项目页的模板下拉动态出现该模板；
- 普通成员看不到「系统设置」菜单，直连路由只能看到 403。

造数只走真实接口 + 直接写 e2e 库（用户没有注册接口）；页面只承载被验证的那一步。
"""

import uuid

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import text

from tests.e2e.support import _session

pytestmark = pytest.mark.e2e

PROVIDER_PREFIX = "e2e-llm-"
FAKE_KEY = "sk-e2e-secret-1234"
TEMPLATE_SUFFIX = "\n（T87 e2e 追加）"


def _cleanup_providers() -> None:
    """清掉用例造的大模型配置与它的留痕（不碰手工数据）。"""
    session = _session()
    try:
        session.execute(
            text("DELETE FROM llm_run_logs WHERE provider_name LIKE :p"),
            {"p": f"{PROVIDER_PREFIX}%"},
        )
        session.execute(
            text("DELETE FROM llm_providers WHERE name LIKE :p"),
            {"p": f"{PROVIDER_PREFIX}%"},
        )
        session.commit()
    finally:
        session.close()


def _first_pass_template(api) -> dict:
    response = api.ctx.get(
        "/api/admin/prompt-templates",
        params={"task_type": "incremental", "page_size": 100},
        headers=api._headers(),
    )
    assert response.ok, response.text()
    items = response.json()["items"]
    return next(item for item in items if "第一遍" in item["name"])


@pytest.mark.task("T87")
def test_ac_116_ac_117_settings_ui(admin_page: Page, api, shot):
    """管理员：建配置（掩码）→ 连通性失败仍 200 → 模板正文改动升版本 → 05 下拉可见。"""
    page = admin_page
    provider_name = f"{PROVIDER_PREFIX}{uuid.uuid4().hex[:6]}"
    template = _first_pass_template(api)
    template_id = template["id"]

    # 读一次模板原文，用例结束无论成败都还原，避免 e2e 库越跑越脏
    detail = api.ctx.get(
        f"/api/admin/prompt-templates/{template_id}", headers=api._headers()
    ).json()
    original_system = detail["system_prompt"]
    original_version = detail["version_no"]

    try:
        # ---------------- 大模型配置 ----------------
        page.goto("/admin/settings")
        expect(page.get_by_role("heading", name="系统设置")).to_be_visible()
        # 侧边栏出现「系统设置」入口
        expect(page.get_by_role("link", name="系统设置")).to_be_visible()

        page.get_by_test_id("llm-provider-create-btn").click()
        page.get_by_test_id("llm-provider-form-name").fill(provider_name)
        page.get_by_test_id("llm-provider-form-base-url").fill("http://127.0.0.1:9")
        page.get_by_test_id("llm-provider-form-api-key").fill(FAKE_KEY)
        page.get_by_test_id("llm-provider-form-model").fill("deepseek-chat")
        page.get_by_test_id("llm-provider-form-timeout").fill("1")
        page.get_by_test_id("llm-provider-submit").click()

        row = page.get_by_role("row").filter(has_text=provider_name)
        expect(row).to_be_visible()
        # 只给掩码：完整 Key 绝不能出现在页面上
        expect(row).to_contain_text("sk-****1234")
        expect(row).not_to_contain_text(FAKE_KEY)
        shot(page, "provider-masked")

        # 不可达地址 → 连通失败，但页面拿到的是 200 + ok=false 的业务结果
        row.get_by_role("button", name="测试连通性").click()
        expect(page.get_by_text("连通失败", exact=False)).to_be_visible()
        expect(row.get_by_text("失败")).to_be_visible()
        shot(page, "provider-test-failed")

        # ---------------- 提示词模板 ----------------
        page.get_by_role("tab", name="提示词模板").click()
        page.get_by_test_id(f"prompt-template-edit-{template_id}").click()

        system_box = page.get_by_test_id("prompt-template-form-system")
        expect(system_box).to_be_visible()
        assert system_box.input_value() == original_system
        system_box.fill(original_system + TEMPLATE_SUFFIX)
        page.get_by_test_id("prompt-template-save").click()

        expect(
            page.get_by_text(f"已保存，当前版本 v{original_version + 1}")
        ).to_be_visible()
        expect(
            page.get_by_test_id(f"prompt-template-version-{template_id}")
        ).to_have_text(f"v{original_version + 1}")
        shot(page, "template-version-bumped")

        # ---------------- 05 动态模板下拉 ----------------
        project = api.create_project(f"e2e-t87-{uuid.uuid4().hex[:6]}")
        page.goto(f"/projects/{project['id']}")
        page.get_by_role("tab", name="增量分析").click()
        select = page.get_by_test_id("incremental-template-select")
        expect(select).to_be_visible()
        # 展开下拉，选项里必须能看到系统设置里新建的那条模板。
        # 刚切到 Tab 时首点可能被重渲染吞掉，没开就再点一次。
        selector = page.locator(".ant-form-item", has_text="模板").locator(".ant-select").first
        dropdown = page.locator(".ant-select-dropdown:visible")
        selector.click()
        page.wait_for_timeout(600)
        if dropdown.count() == 0:
            selector.click()
            page.wait_for_timeout(600)
        expect(dropdown).to_be_visible()
        option = dropdown.locator(".ant-select-item-option", has_text=template["name"])
        expect(option.first).to_be_visible()
        option.first.click()
        expect(
            page.locator(".ant-form-item", has_text="模板")
        ).to_contain_text(template["name"])
        shot(page, "incremental-template-dropdown")
    finally:
        # 还原模板正文（会再 +1 版本，但内容回到原样，避免正文无限增长）
        api.ctx.put(
            f"/api/admin/prompt-templates/{template_id}",
            data={"system_prompt": original_system},
            headers=api._headers(),
        )
        _cleanup_providers()


@pytest.mark.task("T87")
def test_ac_116_member_cannot_see_settings_menu(page_as, make_user, shot):
    """普通成员：菜单没有「系统设置」，直连路由只看到 403。"""
    user = make_user()
    page = page_as(user["username"], path="/projects")

    expect(page.get_by_role("link", name="用户管理")).to_have_count(0)
    expect(page.get_by_role("link", name="系统设置")).to_have_count(0)

    page.goto("/admin/settings")
    expect(page.get_by_text("无权访问")).to_be_visible()
    shot(page, "member-403")
