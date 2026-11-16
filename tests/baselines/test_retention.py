"""保留策略与快照删除用例：AC-71 保留上限、AC-72 被引用即保护。"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.system import AuditLog
from tests.baselines.helpers import (
    BASE,
    build_structure,
    make_snapshot,
)

RETENTION = BASE + "/retention"
REVISIONS = BASE + "/revisions"


def _set_max(client, headers, project_id, max_count):
    response = client.patch(
        RETENTION.format(project_id=project_id),
        json={"max_count": max_count},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_ac_71_retention_default_off(client: TestClient, project, headers, reviewer_headers):
    """默认不上限 → 所有快照永久保留，候选为空。"""
    build_structure(client, headers, project.id)
    make_snapshot(client, headers, project.id, reviewer_headers)

    body = client.get(RETENTION.format(project_id=project.id), headers=headers).json()
    assert body["max_count"] is None
    assert body["enabled"] is False
    assert body["snapshot_count"] == 1
    assert body["candidates"] == []
    assert body["warnings"] == []


def test_ac_71_candidates_generated(client: TestClient, project, headers, reviewer_headers):
    """设为 2 且已有 3 份快照 → 最旧 1 份进候选，不自动删除。"""
    build_structure(client, headers, project.id)
    for _ in range(3):
        make_snapshot(client, headers, project.id, reviewer_headers)

    body = _set_max(client, headers, project.id, 2)
    assert body["enabled"] is True
    assert body["snapshot_count"] == 3
    assert body["keep_count"] == 2
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["version_no"] == 0

    # 不自动删
    revisions = client.get(
        REVISIONS.format(project_id=project.id), headers=headers
    ).json()
    assert revisions["total"] == 3


def test_ac_71_turn_off(client: TestClient, project, headers, reviewer_headers):
    """置空 → 关闭策略，候选清空。"""
    build_structure(client, headers, project.id)
    for _ in range(3):
        make_snapshot(client, headers, project.id, reviewer_headers)

    _set_max(client, headers, project.id, 2)
    body = _set_max(client, headers, project.id, None)
    assert body["enabled"] is False
    assert body["candidates"] == []


def test_ac_72_referenced_snapshot_protected(
    client: TestClient, project, headers, reviewer_headers
):
    """被标签引用的快照禁止删除，响应带引用来源明细。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    labeled = client.post(
        BASE.format(project_id=project.id) + "/labels",
        json={
            "revision_id": snapshot["id"],
            "target_type": "function",
            "target_id": built["function"]["id"],
            "label_type": "changed",
        },
        headers=headers,
    )
    assert labeled.status_code == 201, labeled.text

    response = client.delete(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}",
        headers=headers,
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "SNAPSHOT_REFERENCED"
    assert body["referenced_count"] == 1
    assert body["refs"][0]["target_id"] == built["function"]["id"]
    assert body["refs"][0]["source_type"] == "baseline_function"


def test_ac_72_delete_unreferenced(client: TestClient, project, headers, reviewer_headers, db):
    """未被引用的快照可删，并写审计 baseline.snapshot.delete。"""
    build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    response = client.delete(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True

    logs = db.scalars(
        select(AuditLog).where(AuditLog.action == "baseline.snapshot.delete")
    ).all()
    assert len(logs) == 1
    assert logs[0].project_id == project.id
    assert logs[0].target_id == str(snapshot["id"])


def test_ac_72_warning_message(client: TestClient, project, headers, reviewer_headers):
    """达到上限但存在被引用快照 → 告警并列出引用来源。"""
    built = build_structure(client, headers, project.id)
    first = make_snapshot(client, headers, project.id, reviewer_headers)
    make_snapshot(client, headers, project.id, reviewer_headers)
    make_snapshot(client, headers, project.id, reviewer_headers)

    labeled = client.post(
        BASE.format(project_id=project.id) + "/labels",
        json={
            "revision_id": first["id"],
            "target_type": "function",
            "target_id": built["function"]["id"],
            "label_type": "changed",
        },
        headers=headers,
    )
    assert labeled.status_code == 201, labeled.text

    body = _set_max(client, headers, project.id, 2)
    assert len(body["candidates"]) == 1
    candidate = body["candidates"][0]
    assert candidate["referenced_count"] == 1
    assert candidate["refs"][0]["target_id"] == built["function"]["id"]
    assert body["warnings"]
    assert "保留上限" in body["warnings"][0]
    assert "被引用" in body["warnings"][0]
