"""文档解析与基线的前台核对（AC-49 ~ AC-58，T54）。

md 内容同时覆盖：一级标题、层级跳跃之外的正常嵌套、代码块里的 `#` 不当作标题。
"""

import uuid

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

DOC_MD = """# 支付需求

## 1. 概述

支付支持扫码与刷卡。

```python
# 这不是标题
print(1)
```

## 2. 流程

下单 → 支付 → 回调。
"""


DOC_MD_V2 = """# 支付需求

## 1. 概述

第二版：新增退款。

## 2. 流程

下单 → 支付 → 回调 → 退款。
"""


def _name(prefix: str) -> str:
    return f"e2e-{prefix}-{uuid.uuid4().hex[:6]}"


def _sample_pdf() -> bytes:
    """现场拼一个最小 PDF——e2e 不往仓库塞二进制夹具。"""
    from tests.documents.helpers import make_pdf

    return make_pdf(
        [
            [("Chapter 1 Payment", 22, 72)],
            [("payment overview", 10, 72)],
            [("1.1 Refund", 16, 72)],
            [("refund body", 10, 72)],
        ]
    )


def _open_documents(page: Page, api, prefix: str) -> dict:
    project = api.create_project(_name(prefix))
    page.reload()
    page.get_by_role("row").filter(has_text=project["name"]).get_by_role(
        "button", name="详情"
    ).click()
    page.get_by_role("tab", name="文档").click()
    expect(page.get_by_test_id("document-table")).to_be_visible()
    return project


def _upload(page: Page, file_name: str = "支付需求.md") -> None:
    page.get_by_test_id("doc-file-input").set_input_files(
        {"name": file_name, "mimeType": "text/markdown", "buffer": DOC_MD.encode("utf-8")}
    )


def _open_versions(page: Page, row_text: str) -> None:
    page.get_by_role("row").filter(has_text=row_text).get_by_role(
        "button", name="版本"
    ).click()
    expect(page.get_by_test_id("version-table")).to_be_visible()


def _activate(page: Page) -> None:
    page.get_by_role("button", name="确认生效").click()
    # 文档列表行也会显示 V1 标签，断言必须限定在版本表内
    expect(page.get_by_test_id("version-table").get_by_role("row").filter(has_text="V1")).to_contain_text(
        "已生效"
    )


@pytest.mark.task("T54")
def test_ac_49_50_52_upload_then_preview_chapters(admin_page: Page, api, shot) -> None:
    _open_documents(admin_page, api, "doc")

    _upload(admin_page)

    row = admin_page.get_by_role("row").filter(has_text="支付需求")
    expect(row).to_be_visible()
    expect(row).to_contain_text("1")  # 版本数
    expect(row).to_contain_text("未生效")
    shot(admin_page, "uploaded")

    # AC-52：章节树可见，代码块里的 # 不算标题
    _open_versions(admin_page, "支付需求")
    admin_page.get_by_role("button", name="章节").click()
    tree = admin_page.get_by_test_id("chapter-tree")
    expect(tree).to_contain_text("支付需求")
    expect(tree).to_contain_text("1. 概述")
    expect(tree).to_contain_text("2. 流程")
    expect(tree).not_to_contain_text("这不是标题")
    shot(admin_page, "chapters")

    admin_page.locator(".ant-modal-close").last.click()
    admin_page.locator(".ant-modal-close").last.click()

    # 概览文档数同步
    admin_page.get_by_role("tab", name="概览").click()
    expect(admin_page.get_by_test_id("project-overview")).to_contain_text("文档数1")


@pytest.mark.task("T54")
def test_ac_55_activate_generates_baseline(admin_page: Page, api, shot) -> None:
    _open_documents(admin_page, api, "baseline")
    _upload(admin_page)

    _open_versions(admin_page, "支付需求")
    _activate(admin_page)
    shot(admin_page, "activated")
    admin_page.locator(".ant-modal-close").click()

    admin_page.get_by_role("tab", name="版本快照", exact=True).click()
    baseline_table = admin_page.get_by_test_id("baseline-table")
    expect(baseline_table).to_contain_text("V1")
    expect(baseline_table).to_contain_text("支付需求")
    expect(baseline_table).to_contain_text("2")  # 章节数
    shot(admin_page, "baseline")


@pytest.mark.task("T54")
def test_ac_55_void_pending_version(admin_page: Page, api, shot) -> None:
    _open_documents(admin_page, api, "void")
    _upload(admin_page)

    _open_versions(admin_page, "支付需求")
    admin_page.get_by_role("button", name="作废").click()
    admin_page.locator(".ant-popover:visible").get_by_role("button", name="作废").click()

    row = admin_page.get_by_test_id("version-table").get_by_role("row").filter(has_text="V1")
    expect(row).to_contain_text("已作废")
    expect(admin_page.get_by_role("button", name="确认生效")).to_have_count(0)
    shot(admin_page, "voided")


@pytest.mark.task("T54")
def test_ac_58_download_original(admin_page: Page, api, shot) -> None:
    _open_documents(admin_page, api, "download")
    _upload(admin_page)
    _open_versions(admin_page, "支付需求")
    _activate(admin_page)
    admin_page.locator(".ant-modal-close").click()

    with admin_page.expect_download() as info:
        admin_page.get_by_role("row").filter(has_text="支付需求").get_by_role(
            "button", name="下载"
        ).click()

    download = info.value
    assert download.suggested_filename == "支付需求.md"
    shot(admin_page, "downloaded")


@pytest.mark.task("T54")
def test_ac_54_new_version_archives_old_and_baseline_refreshes(
    admin_page: Page, api, shot
) -> None:
    """追加 V2 并确认：V1 变「已归档」，基线 Tab 无需刷新页面即出现 V2。"""
    _open_documents(admin_page, api, "version")
    _upload(admin_page)
    _open_versions(admin_page, "支付需求")
    _activate(admin_page)
    admin_page.locator(".ant-modal-close").click()

    # 先看一次基线，让组件挂载并缓存 V1
    admin_page.get_by_role("tab", name="版本快照", exact=True).click()
    expect(admin_page.get_by_test_id("baseline-table")).to_contain_text("V1")

    # 回文档页追加新版本
    admin_page.get_by_role("tab", name="文档").click()
    _open_versions(admin_page, "支付需求")
    admin_page.get_by_test_id("version-file-input").set_input_files(
        {"name": "支付需求.md", "mimeType": "text/markdown", "buffer": DOC_MD_V2.encode("utf-8")}
    )

    version_table = admin_page.get_by_test_id("version-table")
    expect(version_table.get_by_role("row").filter(has_text="V2")).to_contain_text("待确认")

    version_table.get_by_role("row").filter(has_text="V2").get_by_role(
        "button", name="确认生效"
    ).click()

    expect(version_table.get_by_role("row").filter(has_text="V2")).to_contain_text("已生效")
    expect(version_table.get_by_role("row").filter(has_text="V1")).to_contain_text("已归档")
    shot(admin_page, "v2-activated")
    admin_page.locator(".ant-modal-close").click()

    # 不刷新页面，基线 Tab 应已重载
    admin_page.get_by_role("tab", name="版本快照", exact=True).click()
    baseline_table = admin_page.get_by_test_id("baseline-table")
    expect(baseline_table).to_contain_text("V2")
    expect(baseline_table).to_contain_text("V1")
    shot(admin_page, "baseline-refreshed")


@pytest.mark.task("T84PDF")
def test_ac_119_pdf_upload_succeeds(admin_page: Page, api, shot) -> None:
    """PDF 现在受支持：上传后文档出现在列表里。"""
    _open_documents(admin_page, api, "pdf")

    admin_page.get_by_test_id("doc-file-input").set_input_files(
        {
            "name": "需求说明.pdf",
            "mimeType": "application/pdf",
            "buffer": _sample_pdf(),
        }
    )

    expect(admin_page.get_by_role("row").filter(has_text="需求说明")).to_be_visible()
    shot(admin_page, "pdf-uploaded")


@pytest.mark.task("T54")
def test_ac_50_unsupported_type_rejected(admin_page: Page, api, shot) -> None:
    """未知扩展名仍被拒，提示只支持那几种。"""
    _open_documents(admin_page, api, "unsupported")

    admin_page.get_by_test_id("doc-file-input").set_input_files(
        {"name": "需求.xlsx", "mimeType": "application/vnd.ms-excel", "buffer": b"PK\x03\x04"}
    )

    expect(admin_page.locator(".ant-message")).to_contain_text("只支持 .md / .docx / .txt / .pdf")
    expect(admin_page.get_by_role("row").filter(has_text="需求")).to_have_count(0)
    shot(admin_page, "unsupported-rejected")


@pytest.mark.task("T54")
def test_ac_49_duplicate_name_is_rejected(admin_page: Page, api, shot) -> None:
    _open_documents(admin_page, api, "duplicate")
    _upload(admin_page)
    expect(admin_page.get_by_role("row").filter(has_text="支付需求")).to_be_visible()

    _upload(admin_page)

    expect(admin_page.locator(".ant-message")).to_contain_text("同名文档已存在")
    expect(admin_page.get_by_role("row").filter(has_text="支付需求")).to_have_count(1)
    shot(admin_page, "duplicate")
