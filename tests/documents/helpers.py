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
