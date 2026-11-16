"""概览计数用例：AC-76 baseline_count 改为已审核通过的功能基线快照数。"""

from fastapi.testclient import TestClient

from tests.baselines.helpers import (
    approve_review,
    build_structure,
    make_snapshot,
    submit_review,
)


def _overview(client: TestClient, project, headers) -> dict:
    response = client.get(f"/api/projects/{project.id}/overview", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_ac_76_counts_approved_snapshots(
    client: TestClient, project, headers, reviewer_headers
):
    """只算审核通过的快照，审核中的不算。"""
    build_structure(client, headers, project.id)

    assert _overview(client, project, headers)["baseline_count"] == 0

    # 审核中
    submitted = submit_review(client, headers, project.id)
    assert _overview(client, project, headers)["baseline_count"] == 0

    # 审核通过
    approve_review(client, reviewer_headers, project.id, submitted["id"])
    assert _overview(client, project, headers)["baseline_count"] == 1

    # 再来一份
    make_snapshot(client, headers, project.id, reviewer_headers)
    assert _overview(client, project, headers)["baseline_count"] == 2


def test_ac_76_rejected_snapshot_not_counted(
    client: TestClient, project, headers, reviewer_headers
):
    """被驳回的快照不计入。"""
    build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)

    response = client.post(
        f"/api/projects/{project.id}/baselines/reviews/{submitted['id']}/reject",
        json={"comment": "结构不对"},
        headers=reviewer_headers,
    )
    assert response.status_code == 200, response.text

    assert _overview(client, project, headers)["baseline_count"] == 0


def test_ac_76_scoped_to_project(
    client: TestClient, project, headers, reviewer_headers, db
):
    """别的项目的快照不计入当前项目。"""
    from tests.baselines.helpers import add_member, login, make_project, make_user

    build_structure(client, headers, project.id)

    other_user = make_user(db)
    other_reviewer = make_user(db)
    other = make_project(db, name="另一个项目")
    add_member(db, other, other_user, "project_admin")
    add_member(db, other, other_reviewer, "project_admin")
    other_headers = login(client, other_user)
    other_reviewer_headers = login(client, other_reviewer)
    build_structure(client, other_headers, other.id)
    make_snapshot(client, other_headers, other.id, other_reviewer_headers)

    assert _overview(client, project, headers)["baseline_count"] == 0
    assert _overview(client, other, other_headers)["baseline_count"] == 1
