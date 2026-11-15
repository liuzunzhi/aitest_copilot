"""章节解析器（T46 / AC-52）。

解析是纯函数，所以这里全部走内存数据，不碰数据库。
docx 用 python-docx 现场生成，避免往仓库塞二进制夹具。
"""

import io

import pytest
from docx import Document as DocxDocument

from app.common.errors import (
    DocumentParseFailed,
    EmptyDocument,
    UnsupportedDocType,
)
from app.documents.parser import ChapterNode, parse


def _shape(nodes: list[ChapterNode]) -> list[dict]:
    """把树转成 dict，断言层级与正文归属时更直观。"""
    return [
        {
            "title": node.title,
            "level": node.level,
            "content": node.content,
            "children": _shape(node.children),
        }
        for node in nodes
    ]


def _docx_bytes(build) -> bytes:
    document = DocxDocument()
    build(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_ac_52_markdown_tree():
    """三级标题成树，正文只归最近的标题，兄弟顺序与原文一致。"""
    text = "\n".join(
        [
            "# 支付",
            "总述",
            "## 下单",
            "下单正文",
            "### 校验",
            "校验正文",
            "## 退款",
            "退款正文",
            "# 附录",
            "附录正文",
        ]
    )

    roots = parse("支付需求.md", text.encode())

    assert _shape(roots) == [
        {
            "title": "支付",
            "level": 1,
            "content": "总述",
            "children": [
                {
                    "title": "下单",
                    "level": 2,
                    "content": "下单正文",
                    "children": [
                        {
                            "title": "校验",
                            "level": 3,
                            "content": "校验正文",
                            "children": [],
                        }
                    ],
                },
                {"title": "退款", "level": 2, "content": "退款正文", "children": []},
            ],
        },
        {"title": "附录", "level": 1, "content": "附录正文", "children": []},
    ]


def test_ac_52_markdown_code_fence_ignored():
    """代码块里的 `#` 不是标题。"""
    text = "\n".join(
        ["# 真标题", "```", "# 假标题", "正文", "```", "收尾"]
    )

    roots = parse("需求.md", text.encode())

    assert [node.title for node in roots] == ["真标题"]
    assert roots[0].content == "```\n# 假标题\n正文\n```\n收尾"


def test_ac_52_markdown_level_jump():
    """h1 直接跳到 h3 时，h3 挂到 h1 下，不丢节点。"""
    text = "\n".join(["# 一级", "## 正常", "### 深一层", "正文"])

    roots = parse("需求.md", text.encode())

    assert roots[0].children[0].title == "正常"
    assert roots[0].children[0].children[0].title == "深一层"
    assert roots[0].children[0].children[0].content == "正文"


def test_ac_52_markdown_preamble():
    """首个标题之前的正文单独成「前言」，不丢内容。"""
    text = "文档说明\n\n# 第一章\n正文"

    roots = parse("需求.md", text.encode())

    assert [node.title for node in roots] == ["前言", "第一章"]
    assert roots[0].content == "文档说明"


def test_ac_52_txt_single_chapter():
    """txt 没有标题语义，整文单章。"""
    roots = parse("需求.txt", "第一行\n第二行".encode())

    assert len(roots) == 1
    assert roots[0].title == "全文"
    assert roots[0].level == 1
    assert roots[0].content == "第一行\n第二行"


def test_ac_52_docx_headings_and_table():
    """docx 按 Heading 样式成树，表格文本并入当前章节。"""

    def build(document: DocxDocument) -> None:
        document.add_heading("支付需求", level=1)
        document.add_paragraph("总述")
        document.add_heading("范围", level=2)
        document.add_paragraph("范围说明")
        table = document.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "字段"
        table.rows[0].cells[1].text = "说明"

    roots = parse("支付需求.docx", _docx_bytes(build))

    assert roots[0].title == "支付需求"
    assert roots[0].content == "总述"
    scope = roots[0].children[0]
    assert scope.title == "范围"
    assert scope.content == "范围说明\n字段 | 说明"


def test_ac_52_docx_without_heading_single_chapter():
    """docx 没有任何标题样式时整文单章，不误拆。"""

    def build(document: DocxDocument) -> None:
        document.add_paragraph("第一段")
        document.add_paragraph("第二段")

    roots = parse("普通.docx", _docx_bytes(build))

    assert len(roots) == 1
    assert roots[0].title == "全文"
    assert roots[0].content == "第一段\n第二段"


@pytest.mark.parametrize(
    ("file_name", "data", "error"),
    [
        ("需求.pdf", b"%PDF-1.4", UnsupportedDocType),
        ("需求.md", b"", EmptyDocument),
        ("需求.md", b"   \n\n", EmptyDocument),
        ("需求.docx", b"not a docx", DocumentParseFailed),
        ("需求.md", b"\xff\xfe\x00\x00", DocumentParseFailed),
    ],
)
def test_ac_52_invalid_input(file_name, data, error):
    """不支持的类型、空文件、损坏 docx、无法解码都转业务错误。"""
    with pytest.raises(error):
        parse(file_name, data)
