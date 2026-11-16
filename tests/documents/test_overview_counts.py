"""概览中的文档 / 基线真实计数（T52 / AC-40 扩展）。"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.documents.helpers import (
    SAMPLE_MD,
    add_member,
    login,
    make_project,
    make_user,
    md_payload,
)


def _setup(client: TestClient, db: Session):
    user = make_user(db)
    project = make_project(db)
    add_member(db, project, user, role="project_admin")
    return project, login(client, user)


def _upload(client: TestClient, project, headers, *, name: str = "支付需求.md"):
    response = client.post(
        f"/api/projects/{project.id}/documents",
        files=md_payload(SAMPLE_MD, name),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _overview(client: TestClient, project, headers) -> dict:
    response = client.get(f"/api/projects/{project.id}/overview", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_ac_40_counts_documents_and_baselines(client: TestClient, db: Session, upload_root):
    """文档数按文档算（不是版本）；基线数只算已审核通过的功能基线快照。"""
    project, headers = _setup(client, db)
    first = _upload(client, project, headers)
    _upload(client, project, headers, name="退款需求.md")

    before = _overview(client, project, headers)
    assert before["document_count"] == 2
    assert before["baseline_count"] == 0

    client.post(
        f"/api/projects/{project.id}/documents/{first['document']['id']}"
        f"/versions/{first['version']['id']}/activate",
        headers=headers,
    )

    after = _overview(client, project, headers)
    assert after["document_count"] == 2
    # 文档基线快照不再计入概览（03 的「版本快照」Tab 自己展示）
    assert after["baseline_count"] == 0


def test_ac_40_counts_scoped_to_project(client: TestClient, db: Session, upload_root):
    """别的项目的文档与基线不计入当前项目。"""
    project, headers = _setup(client, db)
    _upload(client, project, headers)

    other_user = make_user(db)
    other = make_project(db, name="另一个项目")
    add_member(db, other, other_user, role="member")
    other_upload = _upload(client, other, login(client, other_user))
    client.post(
        f"/api/projects/{other.id}/documents/{other_upload['document']['id']}"
        f"/versions/{other_upload['version']['id']}/activate",
        headers=login(client, other_user),
    )

    body = _overview(client, project, headers)
    assert body["document_count"] == 1
    assert body["baseline_count"] == 0


def test_ac_40_voided_version_adds_no_baseline(client: TestClient, db: Session, upload_root):
    """作废的版本不产生基线，但文档本身仍计入。"""
    project, headers = _setup(client, db)
    uploaded = _upload(client, project, headers)

    client.post(
        f"/api/projects/{project.id}/documents/{uploaded['document']['id']}"
        f"/versions/{uploaded['version']['id']}/void",
        headers=headers,
    )

    body = _overview(client, project, headers)
    assert body["document_count"] == 1
    assert body["baseline_count"] == 0
