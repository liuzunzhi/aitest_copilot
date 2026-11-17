"""PDF 文本提取与章节切分（T84-PDF）。

单独成文件的原因：PDF 的提取逻辑与 md / docx 的差异很大（要处理字号、列间隙、
扫描件），塞进 `parser.py` 会把那个「三种格式共用一套建树」的清晰结构搅浑。

切分靠**两条硬条件同时成立**：

1. **字号**大于正文字号——正文字号取全文字号分布的众数；
2. 标题行**命中编号正则**（`第X章` 或 `1.2.3` 这类层级编号）。

只靠字号会把「恰好排得大一点的正文」误判成标题；只靠编号会把正文里的
「1. 某某说明」列表项误判成标题。两条都满足才判标题，宁可少切也不乱切。

提取不到任何文字（扫描件 / 无字体层）时**不报错**，降级成整文单章——
和「txt 无标题整文单章」是同一口径。
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass

import pdfplumber

from app.common.errors import DocumentParseFailed

# 同一行内字符的 top 允许的偏差（pt）。PDF 里同一行的字形基线会有细微浮动，
# 按 top 完全相等分组会漏字；±2pt 足够宽松又不会把相邻两行并到一起。
LINE_TOLERANCE = 2.0

# 字号高于「正文字号 + 该值」才算标题档。0.6pt 的缓冲用来吸收
# 「同层级标题字号被排版工具微调」的情况。
SIZE_MARGIN = 0.6

# 标题行的最长字数：超过就不像标题了（多半是被放大的正文）
MAX_HEADING_CHARS = 40

# 相邻两列之间的横向间隙超过该值（pt）就认为是表格的列边界。
# 正文行实测间隙 ≤ 6pt，表格列间隙普遍 ≥ 20pt，取 10pt 留足余量。
COLUMN_GAP = 10.0

# 编号正则：中文的「第X章/篇/部」、英文的 `Chapter N`，
# 与西文的「1.1 / 2.4.2」这类**多级**编号。
# 刻意**不匹配单级编号**（`1` / `2`）：正文里的列表项「1. 防止SQL注入：……」
# 是「数字 + 点 + 空格」，点后不是数字，用单级编号会把它们全判成标题。
_HEADING_NUM = re.compile(
    r"^(第[一二三四五六七八九十百零〇\d]+[章篇部]"
    r"|[Cc]hapter\s+\d+"
    r"|\d+(?:\.\d+)+)"
)

# 多级编号正则：单独用于「字号与正文相同但加粗」的小节标题，
# 层级由编号深度决定（`6.1` → level 2，`2.4.2` → level 3）。
# 结尾用 `(?!\d)` 而不是 `\b`：编号后面常直接跟汉字或字母
# （`6.1WEB攻击防御手段`），数字与字母之间**没有词边界**，
# 用 `\b` 会导致这种标题匹配不上。
_MULTI_NUM = re.compile(r"^(\d+(?:\.\d+)+)(?!\d)")

# 字体名里的加粗标记。pdfplumber 给出的字体名形如 `MicrosoftYaHei-Bold`、
# `OpenSans-BoldItalic`，中文文档常用「微软雅黑 Bold」这类命名，
# 所以同时认 `Bold` 与「加粗」。
_BOLD_RE = re.compile(r"Bold|加粗", re.IGNORECASE)


@dataclass
class PdfLine:
    """PDF 里的一行：文本 + 该行最大字号 + 是否含加粗字形。

    `text` 里若检测到表格列边界，列与列之间用 ` | ` 分隔——
    这样表格文字天然就是「管道分隔」的形式，与 docx 的表格处理同构，
    不需要再单独跑一遍表格识别（那会与正文流重复）。

    `bold` 表示该行含加粗字形：有些文档的小节标题**字号与正文相同、只靠加粗区分**，
    只看字号会漏掉它们。
    """

    text: str
    size: float
    bold: bool = False


def extract_lines(data: bytes) -> list[PdfLine]:
    """把 PDF 拆成「行」序列，每行带字号与加粗标记。

    逐页取**字符** → 按 top 容差聚成行 → 行内按 x0 排序 →
    按横向间隙切列（表格还原成 `a | b`）→ 行字号取行内最大字号。

    为什么用字符而不是 `extract_words`：`extract_words` 按空格切词，
    会**丢掉 PDF 里真实的空格字符**——`APP Application` 会粘成 `APPApplication`，
    英文术语与中文混排的需求文档里这会明显降低可读性。
    """
    lines: list[PdfLine] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                lines.extend(_page_lines(page))
    except DocumentParseFailed:
        raise
    except Exception as exc:  # pdfplumber 抛的异常类型不稳定，统一转业务错误
        raise DocumentParseFailed(f"PDF 文档结构损坏，无法解析：{exc}") from exc
    return lines


def _page_lines(page) -> list[PdfLine]:
    """单页拆行。"""
    try:
        chars = page.chars
    except Exception as exc:  # noqa: BLE001 - 单页解析失败不该毁掉整份文档
        raise DocumentParseFailed(f"PDF 页面解析失败：{exc}") from exc

    rows: list[dict] = []
    for char in chars:
        text = char.get("text") or ""
        if not text:
            continue
        size = float(char.get("size") or 0.0)
        top = float(char.get("top") or 0.0)
        x0 = float(char.get("x0") or 0.0)
        x1 = float(char.get("x1") or 0.0)
        font = str(char.get("fontname") or "")
        for row in rows:
            if abs(row["top"] - top) <= LINE_TOLERANCE:
                row["chars"].append((x0, x1, text, size, font))
                break
        else:
            rows.append({"top": top, "chars": [(x0, x1, text, size, font)]})

    result: list[PdfLine] = []
    for row in sorted(rows, key=lambda item: item["top"]):
        parts = sorted(row["chars"], key=lambda item: item[0])
        text = _join_columns(parts).strip()
        if not text:
            continue
        result.append(
            PdfLine(
                text=text,
                size=max(part[3] for part in parts),
                bold=any(_BOLD_RE.search(part[4]) for part in parts),
            )
        )
    return result


def _join_columns(parts: list[tuple[float, float, str, float, str]]) -> str:
    """行内按横向间隙切列。

    - 间隙小于 `COLUMN_GAP`：同一格的连续文字，直接拼；
    - 间隙超过 `COLUMN_GAP`：表格的列边界，断开并补 ` | `；
    - PDF 里真实的空格字符原样保留（`APP Application` 不会被粘成 `APPApplication`）。
    """
    cells: list[str] = []
    current: list[str] = []
    for index, part in enumerate(parts):
        if index > 0:
            previous_x1 = parts[index - 1][1]
            if part[0] - previous_x1 > COLUMN_GAP:
                cells.append("".join(current))
                current = []
        current.append(part[2])
    cells.append("".join(current))
    return " | ".join(cell.strip() for cell in cells if cell.strip())


def heading_levels(lines: list[PdfLine]) -> dict[float, int]:
    """字号 → 层级（1 起）。

    **正文字号怎么定**——不能简单取全文字号的众数：标题行可能比正文行还多
    （目录页、短文档），那时众数会被标题字号占据，导致「没有标题档」。
    所以正文字号取**非加粗行**的字号众数——正文通常不加粗，加粗的是标题。
    并列时取**最小**的那个（并列说明两者都是正文尺寸）。

    标题档则从**全部**字号里取：大于「正文字号 + SIZE_MARGIN」的即是标题，
    按字号降序映射 level 1、2、3…
    """
    if not lines:
        return {}
    plain = Counter(round(line.size, 1) for line in lines if not line.bold)
    all_sizes = Counter(round(line.size, 1) for line in lines)
    reference = plain or all_sizes
    max_count = max(reference.values())
    body_size = min(size for size, count in reference.items() if count == max_count)
    heading_sizes = sorted(
        (size for size in all_sizes if size > body_size + SIZE_MARGIN), reverse=True
    )
    return {size: index + 1 for index, size in enumerate(heading_sizes)}


def is_heading(line: PdfLine, levels: dict[float, int]) -> bool:
    """是否标题行。

    两条判据，**任一成立**即算标题：

    1. **字号更大** + 命中编号正则（章 / 多级编号）——常规标题；
    2. **加粗 + 命中多级编号**——有些文档的小节标题字号与正文相同，
       只靠加粗区分（如 `6.1 WEB攻击防御手段`），只看字号会漏掉。

    两种判据都要求命中编号正则：不然正文里的加粗强调句、
    列表项「1. 防止SQL注入」都会被误判成标题。
    """
    text = line.text.strip()
    if len(text) > MAX_HEADING_CHARS:
        return False
    if not _HEADING_NUM.match(text):
        return False
    if round(line.size, 1) in levels:
        return True
    return line.bold and bool(_MULTI_NUM.match(text))


def heading_level(line: PdfLine, levels: dict[float, int]) -> int:
    """标题层级。

    字号能定档就用字号（更可靠）；只有加粗 + 多级编号的小标题，
    层级由**编号深度**决定（`6.1` → 2，`2.4.2` → 3），
    并至少为 2——它总归在某个大标题下面。
    """
    size_level = levels.get(round(line.size, 1))
    if size_level is not None:
        return size_level
    match = _MULTI_NUM.match(line.text.strip())
    if match is None:
        return 1
    depth = match.group(1).count(".") + 1
    return max(2, depth)


__all__ = [
    "COLUMN_GAP",
    "LINE_TOLERANCE",
    "MAX_HEADING_CHARS",
    "SIZE_MARGIN",
    "PdfLine",
    "extract_lines",
    "heading_level",
    "heading_levels",
    "is_heading",
]
