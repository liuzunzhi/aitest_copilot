"""项目创建（T28，AC-31）。"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.system import AuditLog
from app.models.user import User

PROJECTS = "/api/projects"
PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"proj-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _auth(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_ac_31_create_project(client: TestClient, db: Session):
    """创建成功、创建人自动成为项目管理员、审计落库。"""
    admin = _user(db, global_role="system_admin")

    response = client.post(
        PROJECTS,
        json={"name": "支付中台", "description": "支付相关需求"},
        headers=_auth(client, admin),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "支付中台"
    assert body["description"] == "支付相关需求"
    assert body["status"] == "active"

    project_id = body["id"]
    member = db.get(ProjectMember, (project_id, admin.id))
    assert member is not None
    assert member.role == "project_admin"

    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "project.create")
    ).scalar_one()
    assert audit.actor_id == admin.id
    assert audit.project_id == project_id
    assert audit.after_data["name"] == "支付中台"


def test_ac_31_list_projects_includes_description(client: TestClient, db: Session):
    """成员列表补上简介，前端不再需要额外请求。"""
    admin = _user(db, global_role="system_admin")
    headers = _auth(client, admin)
    created = client.post(
        PROJECTS, json={"name": "基线项目", "description": "简介"}, headers=headers
    )
    assert created.status_code == 201

    response = client.get(PROJECTS, headers=headers)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": created.json()["id"],
            "name": "基线项目",
            "description": "简介",
            "status": "active",
            "role": "project_admin",
        }
    ]


def test_ac_31_name_required(client: TestClient, db: Session):
    admin = _user(db, global_role="system_admin")

    response = client.post(PROJECTS, json={"name": "   "}, headers=_auth(client, admin))

    assert response.status_code == 400
    assert response.json()["code"] == "PROJECT_NAME_REQUIRED"


def test_ac_31_name_too_long(client: TestClient, db: Session):
    admin = _user(db, global_role="system_admin")

    response = client.post(
        PROJECTS, json={"name": "项" * 129}, headers=_auth(client, admin)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PROJECT_NAME"


def test_ac_31_description_too_long(client: TestClient, db: Session):
    admin = _user(db, global_role="system_admin")

    response = client.post(
        PROJECTS,
        json={"name": "有效名称", "description": "简" * 501},
        headers=_auth(client, admin),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PROJECT_DESCRIPTION"


def test_ac_31_requires_system_admin(client: TestClient, db: Session):
    user = _user(db)

    response = client.post(
        PROJECTS, json={"name": "无权创建"}, headers=_auth(client, user)
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_ac_31_creator_can_review_immediately(client: TestClient, db: Session):
    """创建人拿到的是真实项目管理员身份，可以直接审批申请（AC-23）。"""
    admin = _user(db, global_role="system_admin")
    applicant = _user(db)
    headers = _auth(client, admin)

    created = client.post(PROJECTS, json={"name": "可审批项目"}, headers=headers)
    project_id = created.json()["id"]
    application = ProjectApplication(
        project_id=project_id,
        applicant_id=applicant.id,
        reason="需要加入",
        desired_role="member",
        status="pending",
    )
    db.add(application)
    db.flush()

    response = client.post(
        f"{PROJECTS}/{project_id}/applications/{application.id}/approve",
        json={"role": "member"},
        headers=headers,
    )

    assert response.status_code == 200
    db.expire_all()
    assert db.get(ProjectMember, (project_id, applicant.id)).role == "member"
    assert db.get(Project, project_id).status == "active"
