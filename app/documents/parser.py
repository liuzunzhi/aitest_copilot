"""文档解析：把上传文件拆成章节树（03-documents T46）。

纯函数，不碰数据库与网络，方便单测与后续比对段复用。

章节归属规则：`content` 只收「该标题到下一个标题之间」的正文，
子章节正文归子节点——这样树形预览展开时不会重复展示同一段文字。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.common.errors import DocumentParseFailed, EmptyDocument, UnsupportedDocType

SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".docx"})

_MD_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_DOCX_HEADING_RE = re.compile(r"^(?:Heading|标题)\s*([1-6])$")


@dataclass
class ChapterNode:
    """章节节点。`children` 为下级章节，顺序与文档一致。"""

    title: str
    level: int
    content: str = ""
    children: list["ChapterNode"] = field(default_factory=list)


class _TreeBuilder:
    """按标题层级维护节点栈，产出章节树。

    markdown 与 docx 的差异只在「怎么找到标题、怎么拿正文」，
    建树逻辑完全一致，所以抽到这里避免两套实现漂移。
    """

    def __init__(self) -> None:
        self.roots: list[ChapterNode] = []
        self.stack: list[ChapterNode] = []
        self.preamble: list[str] = []
        self.current: ChapterNode | None = None

    def add_heading(self, level: int, title: str) -> None:
        # 层级跳跃（h1 直接到 h3）时挂到最近的更高级祖先；
        # 同级或更高级则先出栈，保证兄弟顺序。
        while self.stack and self.stack[-1].level >= level:
            self.stack.pop()
        node = ChapterNode(title=title, level=level)
        if self.stack:
            self.stack[-1].children.append(node)
        else:
            self.roots.append(node)
        self.stack.append(node)
        self.current = node

    def add_text(self, line: str) -> None:
        if self.current is None:
            self.preamble.append(line)
        else:
            self.current.content += line + "\n"

    def build(self) -> list[ChapterNode]:
        preamble_text = "\n".join(self.preamble).strip()
        if not self.roots:
            # 全文没有任何标题：整文单章，标题用「全文」而不是「前言」。
            if not preamble_text:
                raise EmptyDocument()
            return [ChapterNode(title="全文", level=1, content=preamble_text)]
        if preamble_text:
            # 有标题时，首个标题之前的正文不能丢：单独成「前言」，与标题章节同级。
            self.roots.insert(0, ChapterNode(title="前言", level=1, content=preamble_text))
        for node in self._walk(self.roots):
            node.content = node.content.strip()
        return self.roots

    def _walk(self, nodes: list[ChapterNode]):
        for node in nodes:
            yield node
            yield from self._walk(node.children)


def parse(file_name: str, data: bytes) -> list[ChapterNode]:
    """按扩展名解析文件，返回根章节列表。

    失败一律抛 `AppError` 子类，由全局处理器转成 `{"code","message"}`。
    """
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocType()
    if not data:
        raise EmptyDocument()
    if suffix == ".docx":
        return _parse_docx(data)
    return _parse_text(_decode(data))


def _decode(data: bytes) -> str:
    """先按 UTF-8（去 BOM），失败再试 GB18030——国内需求文档常见编码。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseFailed("无法识别文件编码，请另存为 UTF-8 后重试")


def _parse_text(text: str) -> list[ChapterNode]:
    if not text.strip():
        raise EmptyDocument()

    builder = _TreeBuilder()
    in_code_block = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            builder.add_text(line)
            continue
        if not in_code_block:
            match = _MD_HEADING_RE.match(line)
            if match:
                builder.add_heading(len(match.group(1)), match.group(2))
                continue
        builder.add_text(line)

    if not builder.roots and builder.preamble and not "".join(builder.preamble).strip():
        raise EmptyDocument()
    return builder.build()


def _parse_docx(data: bytes) -> list[ChapterNode]:
    try:
        document = DocxDocument(io.BytesIO(data))
    except Exception as exc:  # python-docx 抛的异常类型不稳定，统一转业务错误
        raise DocumentParseFailed("Word 文档结构损坏，无法解析") from exc

    builder = _TreeBuilder()
    # 按 body 顺序遍历，保证段落与表格的相对位置与原文一致。
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = paragraph.style.name if paragraph.style is not None else ""
            match = _DOCX_HEADING_RE.match(style_name or "")
            if match:
                builder.add_heading(int(match.group(1)), text)
            else:
                builder.add_text(text)
        elif tag == "tbl":
            table = Table(child, document)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                builder.add_text(" | ".join(cells))

    if not builder.roots and not "".join(builder.preamble).strip():
        raise EmptyDocument()
    return builder.build()


__all__ = ["ChapterNode", "SUPPORTED_SUFFIXES", "parse"]
