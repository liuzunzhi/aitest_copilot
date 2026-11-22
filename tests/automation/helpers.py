"""自动化用例的造数与登录辅助。"""

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.project import Project, ProjectMember
from app.models.user import User

PASSWORD = "AutomationPass1"
PASSWORD_HASH = hash_password(PASSWORD)

BASE = "/api/projects/{project_id}/automation"
ASSETS = BASE + "/assets"
SCAN = BASE + "/scan"
RUNS = BASE + "/runs"


def make_user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"au-{uuid.uuid4().hex[:10]}",
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


def make_project(db: Session, *, status: str = "active") -> Project:
    project = Project(name=f"自动化项目-{uuid.uuid4().hex[:6]}", status=status)
    db.add(project)
    db.flush()
    return project


def add_member(db: Session, project: Project, user: User, role: str = "member") -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def make_case(
    db: Session,
    project: Project,
    user: User,
    *,
    title: str = "连续输错密码 5 次后账号锁定",
) -> int:
    """造一条测试用例（关联资产用）。

    只插库里真正被用到的字段——`test_cases` 的必填列不少，
    这里用 ORM 直接建，避开 08 的服务层（本期不依赖 08 的接口）。
    """
    from app.models.test_case import TestCase

    case = TestCase(
        project_id=project.id,
        analysis_id=None,
        test_point_id=1,
        test_point_name="扫码登录连续失败 5 次后锁定",
        title=title,
        case_type="functional",
        priority="high",
        precondition="账号已存在且未锁定",
        target_type="function",
        target_id=10096,
        target_name="用户扫码登录",
        chapter_id=None,
        chapter_title="4.2 登录失败次数限制",
        status="approved",
        source_type="manual",
        created_by=user.id,
    )
    db.add(case)
    db.flush()
    return case.id


def seed_root(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    """造一个扫描根目录，返回它的绝对路径。

    文件内容默认给空——调用方按需覆盖。
    """
    root = tmp_path / "automation"
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in (files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def pytest_file(cases: int = 2) -> str:
    """一个含 N 个测试函数的 pytest 文件。"""
    body = "".join(
        f"def test_case_{index}():\n    assert True\n\n\n" for index in range(cases)
    )
    return body


def mixed_pytest_file() -> str:
    """1 个通过 + 1 个失败 → 退出码 1。"""
    return (
        "def test_ok():\n"
        "    assert True\n"
        "\n"
        "\n"
        "def test_bad():\n"
        "    assert 1 == 2\n"
    )


def skipped_pytest_file() -> str:
    """全部跳过。"""
    return (
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.mark.skip(reason='demo')\n"
        "def test_skipped():\n"
        "    assert True\n"
    )


__all__ = [
    "ASSETS",
    "BASE",
    "PASSWORD",
    "RUNS",
    "SCAN",
    "add_member",
    "login",
    "make_case",
    "make_project",
    "make_user",
    "mixed_pytest_file",
    "pytest_file",
    "seed_root",
    "skipped_pytest_file",
]
