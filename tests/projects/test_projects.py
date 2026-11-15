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


def _create(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "项目",
    description: str | None = None,
) -> dict:
    response = client.post(
        PROJECTS,
        json={"name": name, "description": description},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def _join(db: Session, project_id: int, user_id: int, role: str) -> None:
    db.add(ProjectMember(project_id=project_id, user_id=user_id, role=role))
    db.flush()


def test_ac_32_update_name_and_description(client: TestClient, db: Session):
    """项目管理员可编辑名称与简介，并留下 before / after 审计。"""
    admin = _user(db, global_role="system_admin")
    headers = _auth(client, admin)
    project = _create(client, headers, name="旧名称", description="旧简介")

    response = client.patch(
        f"{PROJECTS}/{project['id']}",
        json={"name": "新名称", "description": "新简介"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["name"] == "新名称"
    assert response.json()["description"] == "新简介"

    db.expire_all()
    row = db.get(Project, project["id"])
    assert (row.name, row.description) == ("新名称", "新简介")

    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "project.update")
    ).scalar_one()
    assert audit.actor_id == admin.id
    assert audit.before_data == {"name": "旧名称", "description": "旧简介"}
    assert audit.after_data == {"name": "新名称", "description": "新简介"}


def test_ac_32_partial_update_keeps_description(client: TestClient, db: Session):
    """未传的字段保持不变。"""
    admin = _user(db, global_role="system_admin")
    headers = _auth(client, admin)
    project = _create(client, headers, name="旧名称", description="原简介")

    response = client.patch(
        f"{PROJECTS}/{project['id']}", json={"name": "只改名"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "只改名"
    assert response.json()["description"] == "原简介"


def test_ac_32_explicit_null_clears_description(client: TestClient, db: Session):
    """显式传 null 才清空简介，与「未传」区分。"""
    admin = _user(db, global_role="system_admin")
    headers = _auth(client, admin)
    project = _create(client, headers, name="保留名称", description="待清空")

    response = client.patch(
        f"{PROJECTS}/{project['id']}", json={"description": None}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["description"] is None


def test_ac_32_archived_project_is_read_only(client: TestClient, db: Session):
    admin = _user(db, global_role="system_admin")
    headers = _auth(client, admin)
    project = _create(client, headers, name="将归档")
    db.get(Project, project["id"]).status = "archived"
    db.flush()

    response = client.patch(
        f"{PROJECTS}/{project['id']}", json={"name": "改名"}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_32_member_cannot_edit(client: TestClient, db: Session):
    admin = _user(db, global_role="system_admin")
    project = _create(client, _auth(client, admin), name="成员不可改")
    member = _user(db)
    _join(db, project["id"], member.id, "member")

    response = client.patch(
        f"{PROJECTS}/{project['id']}",
        json={"name": "越权改名"},
        headers=_auth(client, member),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_32_non_member_cannot_edit(client: TestClient, db: Session):
    admin = _user(db, global_role="system_admin")
    project = _create(client, _auth(client, admin), name="非成员不可改")
    outsider = _user(db)

    response = client.patch(
        f"{PROJECTS}/{project['id']}",
        json={"name": "越权改名"},
        headers=_auth(client, outsider),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_32_empty_name_rejected(client: TestClient, db: Session):
    admin = _user(db, global_role="system_admin")
    headers = _auth(client, admin)
    project = _create(client, headers, name="原名")

    response = client.patch(
        f"{PROJECTS}/{project['id']}", json={"name": "   "}, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["code"] == "PROJECT_NAME_REQUIRED"


def test_ac_32_system_admin_can_edit_without_membership(client: TestClient, db: Session):
    """系统管理员走全局旁路，不需要是该项目的成员。"""
    creator = _user(db, global_role="system_admin")
    project = _create(client, _auth(client, creator), name="系统可改")
    other_admin = _user(db, global_role="system_admin")

    response = client.patch(
        f"{PROJECTS}/{project['id']}",
        json={"description": "系统管理员修改"},
        headers=_auth(client, other_admin),
    )

    assert response.status_code == 200
    assert response.json()["description"] == "系统管理员修改"


def test_ac_34_archived_project_rejects_edit(client: TestClient, db: Session):
    """归档项目不可编辑：409 且数据保持不变。"""
    admin = _user(db, global_role="system_admin")
    headers = _auth(client, admin)
    project = _create(client, headers, name="归档前名称")
    db.get(Project, project["id"]).status = "archived"
    db.flush()

    response = client.patch(
        f"{PROJECTS}/{project['id']}", json={"name": "归档后改名"}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"

    db.expire_all()
    assert db.get(Project, project["id"]).name == "归档前名称"


def test_ac_34_edit_missing_project(client: TestClient, db: Session):
    admin = _user(db, global_role="system_admin")

    response = client.patch(
        f"{PROJECTS}/999999999", json={"name": "不存在"}, headers=_auth(client, admin)
    )

    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


def test_ac_34_read_still_works_after_archive(client: TestClient, db: Session):
    """读接口不受归档影响：我的项目仍能看到，可申请列表不再出现。"""
    admin = _user(db, global_role="system_admin")
    headers = _auth(client, admin)
    project = _create(client, headers, name="归档可读")
    db.get(Project, project["id"]).status = "archived"
    db.flush()

    mine = client.get(PROJECTS, headers=headers)
    available = client.get(f"{PROJECTS}/available", headers=headers)

    assert mine.status_code == 200
    assert mine.json() == [
        {
            "id": project["id"],
            "name": "归档可读",
            "description": None,
            "status": "archived",
            "role": "project_admin",
        }
    ]
    assert available.status_code == 200
    assert project["id"] not in [row["id"] for row in available.json()]
