"""文档用例的造数与登录辅助。"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.project import Project, ProjectMember
from app.models.user import User

PASSWORD = "DocPassw0rd1"
# bcrypt 很慢，模块级算一次，所有用例共用同一个 hash
PASSWORD_HASH = hash_password(PASSWORD)


def make_user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"doc-{uuid.uuid4().hex[:10]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def login(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_project(db: Session, *, name: str = "文档项目") -> Project:
    project = Project(name=name)
    db.add(project)
    db.flush()
    return project


def add_member(db: Session, project: Project, user: User, role: str = "member") -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def md_payload(body: str, name: str = "支付需求.md") -> dict:
    return {"file": (name, body.encode("utf-8"), "text/markdown")}


SAMPLE_MD = "\n".join(["# 支付", "总述", "## 下单", "下单正文", "## 退款", "退款正文"])


# ---------------------------------------------------------------- PDF 造数
#
# pdfplumber 只能读不能写，所以这里手工拼一个最小可用的 PDF。
# 目的：让 PDF 用例不依赖仓库里的二进制夹具（也不依赖本机的样本文档），
# 每个用例现场生成自己需要的排版。
#
# 生成的 PDF 用 Type1 基础字体（Helvetica / Helvetica-Bold），
# 文本用 latin-1 编码——所以只能写 ASCII。中文标题的用例走真实样本文件。


def _pdf_escape(text: str) -> str:
    """PDF 字符串字面量转义（括号与反斜杠）。"""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(
    rows: list[list[tuple]],
    *,
    page_width: float = 595,
    page_height: float = 842,
    line_height: float = 28,
) -> bytes:
    """生成一个单页 PDF。

    `rows` 是**行**的列表，每行是一组元素；元素可以是

    - `(文本, 字号, x 起点)`：默认按字号决定字重（≥13 用粗体）；
    - `(文本, 字号, x 起点, 是否粗体)`：显式指定，用来造
      「字号与正文相同、只靠加粗区分」的标题。

    同一行里的多个元素落在同一个 y 上——x 起点不同就是表格的不同列。

    竖直方向按 `line_height` 从上往下排。
    """
    content_parts: list[bytes] = []
    y = page_height - 60
    for row in rows:
        for item in row:
            text, size, x = item[0], item[1], item[2]
            bold = item[3] if len(item) > 3 else size >= 13
            font = "F2" if bold else "F1"
            content_parts.append(
                f"BT /{font} {size:g} Tf {x:g} {y:g} Td ({_pdf_escape(text)}) Tj ET".encode(
                    "latin-1"
                )
            )
        y -= line_height
    content = b"\n".join(content_parts) + b"\n"

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {page_width:g} {page_height:g}] "
            "/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> "
            "/Contents 4 0 R >>"
        ).encode("latin-1"),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_offset = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        out += ("%010d 00000 n \n" % offset).encode("latin-1")
    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


def pdf_payload(data: bytes, name: str = "需求.pdf") -> dict:
    return {"file": (name, data, "application/pdf")}
