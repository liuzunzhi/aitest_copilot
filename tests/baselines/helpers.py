"""功能基线用例的造数与登录辅助。"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.project import Project, ProjectMember
from app.models.user import User

PASSWORD = "BaselinePass1"
# bcrypt 很慢，模块级算一次，所有用例共用同一个 hash
PASSWORD_HASH = hash_password(PASSWORD)

BASE = "/api/projects/{project_id}/baselines"


def make_user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"bl-{uuid.uuid4().hex[:10]}",
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


def make_project(db: Session, *, name: str = "基线项目") -> Project:
    project = Project(name=name)
    db.add(project)
    db.flush()
    return project


def add_member(
    db: Session, project: Project, user: User, role: str = "member"
) -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


# ------------------------------------------------------------ HTTP 造数工具


def create_module(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    name: str,
    **extra: object,
) -> dict:
    response = client.post(
        BASE.format(project_id=project_id) + "/modules",
        json={"name": name, **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_function(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    module_id: int,
    name: str,
    **extra: object,
) -> dict:
    response = client.post(
        BASE.format(project_id=project_id) + "/functions",
        json={"module_id": module_id, "name": name, **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_feature_point(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    function_id: int,
    name: str,
    **extra: object,
) -> dict:
    response = client.post(
        BASE.format(project_id=project_id) + f"/functions/{function_id}/feature-points",
        json={"name": name, **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def submit_review(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    comment: str | None = None,
) -> dict:
    response = client.post(
        BASE.format(project_id=project_id) + "/reviews/submit",
        json={"comment": comment},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def approve_review(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    revision_id: int,
    comment: str | None = None,
) -> dict:
    response = client.post(
        BASE.format(project_id=project_id) + f"/reviews/{revision_id}/approve",
        json={"comment": comment},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def reject_review(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    revision_id: int,
    comment: str | None = None,
) -> dict:
    response = client.post(
        BASE.format(project_id=project_id) + f"/reviews/{revision_id}/reject",
        json={"comment": comment},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def make_snapshot(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    reviewer_headers: dict[str, str],
) -> dict:
    """走一遍「提交 → 审核通过」，产出一份已通过的快照。

    提交者与审核者必须不是同一个人——自审会被 403 拦下。
    """
    submitted = submit_review(client, headers, project_id)
    return approve_review(
        client, reviewer_headers, project_id, submitted["id"]
    )


def build_structure(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    *,
    module_name: str = "支付模块",
    function_name: str = "下单",
    point_name: str = "填写收货地址",
) -> dict:
    """建出模块 → 功能 → 功能点三级，返回三层的 id。"""
    module = create_module(client, headers, project_id, module_name)
    function = create_function(
        client, headers, project_id, module["id"], function_name
    )
    point = create_feature_point(
        client, headers, project_id, function["id"], point_name
    )
    return {
        "module": module,
        "function": function,
        "point": point,
    }
