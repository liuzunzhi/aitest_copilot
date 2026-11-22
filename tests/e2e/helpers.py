"""前台用例共用的页面操作（antd v6 + rc-tree 的通用坑都在这里）。

这些 helper 原来散在 `test_baselines_ui.py` 里，按「下一个页面用例必然再抄一遍」
提到公共模块。业务相关的造数（建模块/功能/功能点）仍留在各自用例文件里。

约定：
- 定位优先 `get_by_test_id`，antd 内部类名兜底时必须限定 `:visible`；
- 不做 `wait_for_timeout` 硬等，一律用 `expect(...)` 等状态变化。
"""

from __future__ import annotations

import re
import time
import uuid

from playwright.sync_api import Locator, Page, expect


def unique_name(prefix: str) -> str:
    """`e2e-` 前缀的统一命名——收尾清理 fixture 靠这个前缀回收数据。"""
    return f"e2e-{prefix}-{uuid.uuid4().hex[:6]}"


def tree_node(page: Page, node_text: str) -> Locator:
    """按可见文本定位树节点（只取标题节点，避免命中祖先容器）。"""
    return page.locator(".ant-tree-treenode", has_text=node_text).first


def expand_tree_node(page: Page, node_text: str) -> None:
    """展开某个树节点。

    antd v6 的 DOM 是 `.ant-tree-treenode > .ant-tree-switcher`，
    收起/展开状态类是 `ant-tree-switcher_close` / `ant-tree-switcher_open`。
    """
    switcher = tree_node(page, node_text).locator("> .ant-tree-switcher").first
    if switcher.count() == 0:
        return
    classes = switcher.get_attribute("class") or ""
    if "ant-tree-switcher_close" in classes:
        switcher.click()
        expect(switcher).to_have_class(re.compile("ant-tree-switcher_open"))


def pick_select_option(page: Page, label: str, option: str) -> None:
    """在 antd Select 里选一项。

    多选 Select 选完不会自己收起，dropdown 浮在 Modal 之上会挡住按钮；
    但单选的 dropdown 选完就关了，这时再按 Esc 会把整个 Modal 也关掉，
    所以只在 dropdown 还开着的时候才收。

    **先等 Select 可用再点**：有些 Select 的选项是**异步加载**的
    （比如「模板」下拉要等 `listAvailablePromptTemplates` 回来才不 disabled）。
    Select 处于 disabled 时点击是**静默无效**的——dropdown 永远不开，
    后面等选项就会超时。这是个**已存在的竞态**，机器一慢就暴露
    （T115 加了会真起 pytest 子进程的 e2e 用例后跑过一次）。
    所以这里先等 `.ant-select-disabled` 消失再点。
    """
    select = page.locator(".ant-form-item", has_text=label).locator(".ant-select").first
    # 等选项异步加载完（disabled 期间点击无效）
    expect(select).not_to_have_class(re.compile(r"ant-select-disabled"))
    select.click()
    page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option", has_text=option
    ).first.click()
    dropdown = page.locator(".ant-select-dropdown:visible")
    if dropdown.count():
        page.keyboard.press("Escape")
    expect(dropdown).to_have_count(0)


def visible_modal(page: Page) -> Locator:
    return page.locator(".ant-modal:visible").last


def modal_titled(page: Page, title: str) -> Locator:
    """按标题定位弹窗。

    标签弹窗与「清除标签」弹窗会叠在一起，`.last` 未必是最上层，
    按标题取才不会点错。
    """
    return page.locator(".ant-modal:visible").filter(has_text=title).last


def click_save(page: Page) -> None:
    """弹窗里的「保存」——限定在可见弹窗内，避免撞上保留策略的保存按钮。"""
    visible_modal(page).get_by_role("button", name="保存").click()


def expect_form_error(page: Page, text: str) -> None:
    """表单校验提示就地渲染在字段下方，不是 toast。"""
    expect(page.locator(".ant-form-item-explain-error").filter(has_text=text)).to_be_visible()


def wait_modal_closed(page: Page) -> None:
    """等弹窗关掉——弹窗的遮罩会挡住底下的树节点。"""
    expect(page.locator(".ant-modal:visible")).to_have_count(0)


def wait_drawer_settled(page: Page, anchor: Locator, timeout: float = 5.0) -> None:
    """等抽屉滑入动画结束。

    antd 的 Drawer 用 `transform: translateX()` 滑入，**动画期间元素已在 DOM 里、
    Playwright 也认为它「可见」**——此时截图会拍到半截抽屉（右侧被裁掉）。

    这里不猜 antd 的内部类名，直接盯住抽屉里的锚点：
    等它完整落在视口内（`x + width <= 视口宽`），说明动画已经走完。
    """
    viewport_width = page.viewport_size["width"] if page.viewport_size else 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        box = anchor.bounding_box()
        if box is not None and box["x"] + box["width"] <= viewport_width + 1:
            return
        page.wait_for_timeout(100)
