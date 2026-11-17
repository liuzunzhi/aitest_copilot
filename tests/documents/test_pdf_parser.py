"""PDF 章节解析（T84-PDF / AC-119）。

PDF 与 md / docx 的最大差别：没有结构标记，只能靠**字号 + 编号**推断层级。
所以这里重点覆盖三件事：

- 层级推断对不对（多级标题、正文不被误判）；
- 内容会不会丢（表格还原、真实空格保留）；
- 坏输入会不会炸（损坏 PDF、扫描件降级）。
"""

import pytest

from app.common.errors import DocumentParseFailed, EmptyDocument
from app.documents.parser import parse
from tests.documents.helpers import make_pdf


def _shape(nodes):
    return [
        {
            "title": node.title,
            "level": node.level,
            "content": node.content,
            "children": _shape(node.children),
        }
        for node in nodes
    ]


def test_ac_119_pdf_heading_levels():
    """三级标题成树，正文只归最近的标题。"""
    data = make_pdf(
        [
            [("Chapter 1 Payment", 22, 72)],
            [("body text here", 10, 72)],
            [("1.1 Overview", 16, 72)],
            [("overview body", 10, 72)],
            [("1.1.1 Detail", 13, 72)],
            [("detail body", 10, 72)],
        ]
    )

    roots = parse("需求.pdf", data)

    assert _shape(roots) == [
        {
            "title": "Chapter 1 Payment",
            "level": 1,
            "content": "body text here",
            "children": [
                {
                    "title": "1.1 Overview",
                    "level": 2,
                    "content": "overview body",
                    "children": [
                        {
                            "title": "1.1.1 Detail",
                            "level": 3,
                            "content": "detail body",
                            "children": [],
                        }
                    ],
                }
            ],
        }
    ]


def test_ac_119_pdf_body_not_mistaken_for_heading():
    """正文的编号列表项不是标题：`1. 防止SQL注入` 点后不是数字。"""
    data = make_pdf(
        [
            [("1.1 Security", 16, 72)],
            [("1. Prevent SQL injection by using prepared statements.", 10, 72)],
            [("2. Reset session id on every login.", 10, 72)],
        ]
    )

    roots = parse("需求.pdf", data)

    assert [node.title for node in roots] == ["1.1 Security"]
    content = roots[0].content
    assert "Prevent SQL injection" in content
    assert "Reset session id" in content


def test_ac_119_pdf_table_becomes_pipe_rows():
    """表格按横向间隙切成 `a | b`，与 docx 的表格处理同构。"""
    data = make_pdf(
        [
            [("1.1 Terms", 16, 72)],
            [("Code", 10, 72), ("Meaning", 10, 200)],
            [("APP", 10, 72), ("Application", 10, 200)],
        ]
    )

    roots = parse("需求.pdf", data)

    content = roots[0].content
    assert "Code | Meaning" in content
    assert "APP | Application" in content


def test_ac_119_pdf_keeps_real_spaces():
    """PDF 里真实的空格字符要保留：`APP Application` 不能粘成 `APPApplication`。"""
    data = make_pdf(
        [
            [("1.1 Terms", 16, 72)],
            [("APP Application Program", 10, 72)],
        ]
    )

    roots = parse("需求.pdf", data)

    assert "APP Application Program" in roots[0].content


def test_ac_119_pdf_bold_only_heading_uses_number_depth():
    """字号与正文相同、只靠加粗区分的小节标题，靠编号深度定层级。"""
    data = make_pdf(
        [
            [("Chapter 1 Payment", 22, 72)],
            [("plain body", 10, 72)],
            [("1.1 Section", 16, 72)],
            [("plain body again", 10, 72)],
            [("1.1.1 Bold child", 10, 72, True)],
        ]
    )

    roots = parse("需求.pdf", data)

    child = roots[0].children[0].children[0]
    assert child.title == "1.1.1 Bold child"
    assert child.level == 3


def test_ac_119_pdf_without_heading_single_chapter():
    """没有任何标题层级时整文单章，不误拆。"""
    data = make_pdf(
        [
            [("just some body text", 10, 72)],
            [("and another line", 10, 72)],
        ]
    )

    roots = parse("需求.pdf", data)

    assert len(roots) == 1
    assert roots[0].title == "全文"
    assert roots[0].level == 1
    assert "just some body text" in roots[0].content


def test_ac_119_pdf_corrupted_raises_parse_failed():
    """扩展名是 .pdf 但内容不是 PDF → 400 DOCUMENT_PARSE_FAILED。"""
    with pytest.raises(DocumentParseFailed):
        parse("需求.pdf", b"%PDF-1.4 broken content")


def test_ac_119_pdf_empty_raises_empty_document():
    """0 字节 → EMPTY_DOCUMENT（走 parse() 的前置校验）。"""
    with pytest.raises(EmptyDocument):
        parse("需求.pdf", b"")
