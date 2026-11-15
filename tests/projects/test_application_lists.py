"""申请列表（T37 AC-41 / T38 AC-42 / T39 AC-43 / T40 AC-44）。"""

import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.system import AuditLog
from app.models.user import User

PASSWORD = "Passw0rd"
PASSWORD_HASH = hash_password(PASSWORD)

ITEM_KEYS = {
    "id",
    "applicant",
    "reason",
    "desired_role",
    "status",
    "created_at",
    "reviewer",
    "reviewed_at",
    "reject_reason",
    "closed_reason",
}


def _user(db: Session, *, global_role: str = "user") -> User:
    user = User(
        username=f"apps-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role=global_role,
    )
    db.add(user)
    db.flush()
    return user


def _project(db: Session, *, status: str = "active") -> Project:
    project = Project(name=f"apps-{uuid.uuid4().hex[:6]}", status=status)
    db.add(project)
    db.flush()
    return project


def _join(db: Session, project: Project, user: User, role: str) -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    db.flush()


def _application(
    db: Session,
    project: Project,
    applicant: User,
    *,
    status: str = "pending",
    created_at: datetime | None = None,
    reviewer: User | None = None,
    reject_reason: str | None = None,
    closed_reason: str | None = None,
) -> ProjectApplication:
    application = ProjectApplication(
        project_id=project.id,
        applicant_id=applicant.id,
        reason="需要加入",
        desired_role="member",
        status=status,
        reviewer_id=None if reviewer is None else reviewer.id,
        reviewed_at=None if reviewer is None else datetime(2026, 1, 5),
        reject_reason=reject_reason,
        closed_reason=closed_reason,
    )
    if created_at is not None:
        application.created_at = created_at
    db.add(application)
    db.flush()
    return application


def _auth(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _url(project: Project) -> str:
    return f"/api/projects/{project.id}/applications"


def test_ac_41_list_defaults_to_all_statuses(client: TestClient, db: Session) -> None:
    """不传 status 返回全部状态，按 created_at 降序，含申请人/审批人摘要。"""
    project = _project(db)
    admin = _user(db)
    reviewer = _user(db)
    _join(db, project, admin, "project_admin")
    oldest = _application(
        db, project, _user(db), created_at=datetime(2026, 1, 1, 0, 0, 0)
    )
    newest = _application(
        db,
        project,
        _user(db),
        status="approved",
        created_at=datetime(2026, 1, 3, 0, 0, 0),
        reviewer=reviewer,
    )
    middle = _application(
        db,
        project,
        _user(db),
        status="rejected",
        created_at=datetime(2026, 1, 2, 0, 0, 0),
        reviewer=reviewer,
        reject_reason="资料不全",
    )

    response = client.get(_url(project), headers=_auth(client, admin))

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (3, 1, 20)
    assert [item["id"] for item in body["items"]] == [
        newest.id,
        middle.id,
        oldest.id,
    ]
    assert set(body["items"][0]) == ITEM_KEYS
    assert body["items"][0]["applicant"]["username"]
    assert body["items"][0]["reviewer"]["id"] == reviewer.id
    assert body["items"][2]["reviewer"] is None
    assert body["items"][1]["reject_reason"] == "资料不全"
    assert body["items"][2]["closed_reason"] is None


def test_ac_41_filter_by_status(client: TestClient, db: Session) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    pending = _application(db, project, _user(db))
    _application(db, project, _user(db), status="withdrawn")

    response = client.get(
        _url(project), params={"status": "pending"}, headers=_auth(client, admin)
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [pending.id]


def test_ac_41_invalid_status(client: TestClient, db: Session) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")

    response = client.get(
        _url(project), params={"status": "unknown"}, headers=_auth(client, admin)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_APPLICATION_STATUS"


def test_ac_41_pagination(client: TestClient, db: Session) -> None:
    project = _project(db)
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    for day in (1, 2, 3):
        _application(
            db, project, _user(db), created_at=datetime(2026, 1, day, 0, 0, 0)
        )
    headers = _auth(client, admin)

    first = client.get(_url(project), params={"page": 1, "page_size": 2}, headers=headers)
    second = client.get(
        _url(project), params={"page": 2, "page_size": 2}, headers=headers
    )

    assert first.status_code == 200
    assert (first.json()["total"], first.json()["page"], first.json()["page_size"]) == (
        3,
        1,
        2,
    )
    assert len(first.json()["items"]) == 2
    assert len(second.json()["items"]) == 1
    assert second.json()["page"] == 2


def test_ac_41_system_admin_can_list_without_membership(
    client: TestClient, db: Session
) -> None:
    project = _project(db)
    _application(db, project, _user(db))
    admin = _user(db, global_role="system_admin")

    response = client.get(_url(project), headers=_auth(client, admin))

    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_ac_41_member_cannot_list(client: TestClient, db: Session) -> None:
    project = _project(db)
    member = _user(db)
    _join(db, project, member, "member")

    response = client.get(_url(project), headers=_auth(client, member))

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_41_archived_project_still_readable(
    client: TestClient, db: Session
) -> None:
    project = _project(db, status="archived")
    admin = _user(db)
    _join(db, project, admin, "project_admin")
    _application(db, project, _user(db), status="closed", closed_reason="project_archived")

    response = client.get(_url(project), headers=_auth(client, admin))

    assert response.status_code == 200
    assert response.json()["items"][0]["closed_reason"] == "project_archived"


def test_ac_41_requires_login(client: TestClient, db: Session) -> None:
    project = _project(db)

    response = client.get(_url(project))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


MY_ITEM_KEYS = {
    "id",
    "project",
    "reason",
    "desired_role",
    "status",
    "created_at",
    "reviewed_at",
    "reject_reason",
    "closed_reason",
}


def test_ac_42_only_my_applications(client: TestClient, db: Session) -> None:
    """只返回本人记录，按时间降序，带项目名称。"""
    user = _user(db)
    other = _user(db)
    first_project = _project(db)
    second_project = _project(db)
    older = _application(
        db,
        first_project,
        user,
        created_at=datetime(2026, 2, 1, 0, 0, 0),
    )
    newer = _application(
        db,
        second_project,
        user,
        status="approved",
        reviewer=_user(db),
        created_at=datetime(2026, 2, 2, 0, 0, 0),
    )
    _application(db, first_project, other)

    response = client.get("/api/applications/mine", headers=_auth(client, user))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [newer.id, older.id]
    assert set(body["items"][0]) == MY_ITEM_KEYS
    assert body["items"][0]["project"] == {
        "id": second_project.id,
        "name": second_project.name,
    }
    assert body["items"][1]["project"]["name"] == first_project.name


def test_ac_42_status_filter(client: TestClient, db: Session) -> None:
    user = _user(db)
    project = _project(db)
    rejected = _application(
        db, project, user, status="rejected", reject_reason="资料不全"
    )
    _application(db, project, user, status="withdrawn")

    response = client.get(
        "/api/applications/mine",
        params={"status": "rejected"},
        headers=_auth(client, user),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [rejected.id]
    assert response.json()["items"][0]["reject_reason"] == "资料不全"


def test_ac_42_invalid_status(client: TestClient, db: Session) -> None:
    user = _user(db)

    response = client.get(
        "/api/applications/mine",
        params={"status": "unknown"},
        headers=_auth(client, user),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_APPLICATION_STATUS"


def test_ac_42_requires_login(client: TestClient, db: Session) -> None:
    response = client.get("/api/applications/mine")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


ADMIN_ITEM_KEYS = MY_ITEM_KEYS | {"applicant", "reviewer"}


def test_ac_43_system_admin_sees_all(client: TestClient, db: Session) -> None:
    """全局列表跨项目，按时间降序，带项目 / 申请人 / 审批人摘要。"""
    admin = _user(db, global_role="system_admin")
    reviewer = _user(db, global_role="system_admin")
    first_project = _project(db)
    second_project = _project(db)
    older = _application(
        db, first_project, _user(db), created_at=datetime(2026, 3, 1, 0, 0, 0)
    )
    newer = _application(
        db,
        second_project,
        _user(db),
        status="approved",
        reviewer=reviewer,
        created_at=datetime(2026, 3, 2, 0, 0, 0),
    )

    response = client.get("/api/admin/applications", headers=_auth(client, admin))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [newer.id, older.id]
    assert set(body["items"][0]) == ADMIN_ITEM_KEYS
    assert body["items"][0]["project"] == {
        "id": second_project.id,
        "name": second_project.name,
    }
    assert body["items"][0]["reviewer"]["username"] == reviewer.username
    assert body["items"][1]["reviewer"] is None


def test_ac_43_filters_combine(client: TestClient, db: Session) -> None:
    admin = _user(db, global_role="system_admin")
    headers = _auth(client, admin)
    first_project = _project(db)
    second_project = _project(db)
    target_user = _user(db)
    hit = _application(db, first_project, target_user, status="rejected")
    _application(db, first_project, _user(db), status="rejected")
    _application(db, second_project, target_user, status="pending")

    by_project = client.get(
        "/api/admin/applications",
        params={"project_id": first_project.id},
        headers=headers,
    )
    by_applicant = client.get(
        "/api/admin/applications",
        params={"applicant_id": target_user.id},
        headers=headers,
    )
    combined = client.get(
        "/api/admin/applications",
        params={
            "project_id": first_project.id,
            "status": "rejected",
            "applicant_id": target_user.id,
        },
        headers=headers,
    )

    assert by_project.json()["total"] == 2
    assert by_applicant.json()["total"] == 2
    assert [item["id"] for item in combined.json()["items"]] == [hit.id]


def test_ac_43_invalid_status(client: TestClient, db: Session) -> None:
    admin = _user(db, global_role="system_admin")

    response = client.get(
        "/api/admin/applications",
        params={"status": "unknown"},
        headers=_auth(client, admin),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_APPLICATION_STATUS"


def test_ac_43_non_admin_forbidden(client: TestClient, db: Session) -> None:
    user = _user(db)

    response = client.get("/api/admin/applications", headers=_auth(client, user))

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_ac_43_requires_login(client: TestClient, db: Session) -> None:
    response = client.get("/api/admin/applications")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_ac_44_system_admin_approves_from_global_list(
    client: TestClient, db: Session
) -> None:
    """全局列表 → 审批 → 状态回写全局列表；系统管理员不需要是项目成员。"""
    admin = _user(db, global_role="system_admin")
    applicant = _user(db)
    project = _project(db)
    application = _application(db, project, applicant)
    headers = _auth(client, admin)

    pending = client.get(
        "/api/admin/applications", params={"status": "pending"}, headers=headers
    )
    assert [item["id"] for item in pending.json()["items"]] == [application.id]

    response = client.post(
        f"/api/projects/{project.id}/applications/{application.id}/approve",
        json={"role": "member"},
        headers=headers,
    )
    assert response.status_code == 200

    approved = client.get(
        "/api/admin/applications",
        params={"project_id": project.id, "status": "approved"},
        headers=headers,
    )
    assert approved.status_code == 200
    item = approved.json()["items"][0]
    assert item["id"] == application.id
    assert item["reviewer"]["username"] == admin.username
    assert item["reviewed_at"] is not None

    db.expire_all()
    assert db.get(ProjectMember, (project.id, applicant.id)).role == "member"
    audit = db.execute(
        select(AuditLog).where(AuditLog.action == "project.apply.approve")
    ).scalar_one()
    assert audit.actor_role == "system_admin"
    assert audit.actor_id == admin.id


def test_ac_44_system_admin_rejects_from_global_list(
    client: TestClient, db: Session
) -> None:
    admin = _user(db, global_role="system_admin")
    project = _project(db)
    application = _application(db, project, _user(db))
    headers = _auth(client, admin)

    response = client.post(
        f"/api/projects/{project.id}/applications/{application.id}/reject",
        json={"reason": "不符合项目方向"},
        headers=headers,
    )
    assert response.status_code == 200

    rejected = client.get(
        "/api/admin/applications", params={"status": "rejected"}, headers=headers
    )
    item = rejected.json()["items"][0]
    assert item["id"] == application.id
    assert item["reject_reason"] == "不符合项目方向"
    assert item["reviewer"]["username"] == admin.username

    db.expire_all()
    assert db.get(ProjectMember, (project.id, application.applicant_id)) is None
