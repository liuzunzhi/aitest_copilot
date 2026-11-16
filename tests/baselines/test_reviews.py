"""审核与快照用例：AC-69 审核流程、AC-70 快照不可变与版本递增。"""

from fastapi.testclient import TestClient

from tests.baselines.helpers import (
    BASE,
    build_structure,
    create_function,
    make_snapshot,
    submit_review,
)

REVIEWS = BASE + "/reviews"
REVISIONS = BASE + "/revisions"


def test_ac_69_submit_review(client: TestClient, project, headers):
    """提交审核 → 生成 status='submitted' 的记录。"""
    build_structure(client, headers, project.id)

    response = client.post(
        REVIEWS.format(project_id=project.id) + "/submit",
        json={"comment": "请审核"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "submitted"
    assert body["version_no"] is None
    assert body["review_comment"] == "请审核"


def test_ac_69_approve_freezes(client: TestClient, project, headers, reviewer_headers):
    """审核通过 → approved、分配版本号、冻结结构。"""
    built = build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)

    response = client.post(
        REVIEWS.format(project_id=project.id)
        + f"/{submitted['id']}/approve",
        json={"comment": "通过"},
        headers=reviewer_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["version_no"] == 0
    assert body["module_count"] == 1
    assert body["function_count"] == 1
    assert body["feature_point_count"] == 1

    detail = client.get(
        REVISIONS.format(project_id=project.id)
        + f"/{submitted['id']}",
        headers=headers,
    ).json()
    structure = detail["structure"]
    assert structure[0]["name"] == "支付模块"
    assert structure[0]["functions"][0]["name"] == "下单"
    assert structure[0]["functions"][0]["feature_points"][0]["name"] == "填写收货地址"
    assert built["function"]["id"] == structure[0]["functions"][0]["id"]


def test_ac_69_reject_requires_comment(client: TestClient, project, headers, reviewer_headers):
    """驳回缺意见 → 400 REVIEW_COMMENT_REQUIRED，且不占版本号。"""
    build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)

    response = client.post(
        REVIEWS.format(project_id=project.id) + f"/{submitted['id']}/reject",
        json={"comment": "   "},
        headers=reviewer_headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "REVIEW_COMMENT_REQUIRED"

    detail = client.get(
        REVISIONS.format(project_id=project.id) + f"/{submitted['id']}", headers=headers
    ).json()
    assert detail["status"] == "submitted"
    assert detail["version_no"] is None


def test_ac_69_self_approval_forbidden(client: TestClient, project, headers):
    """提交者本人审核 → 403 SELF_APPROVAL_FORBIDDEN。"""
    build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)

    response = client.post(
        REVIEWS.format(project_id=project.id) + f"/{submitted['id']}/approve",
        json={},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "SELF_APPROVAL_FORBIDDEN"


def test_ac_69_duplicate_review(client: TestClient, project, headers, reviewer_headers):
    """重复审核同一条记录 → 409 INVALID_REVIEW_STATUS。"""
    build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)

    first = client.post(
        REVIEWS.format(project_id=project.id) + f"/{submitted['id']}/approve",
        json={},
        headers=reviewer_headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        REVIEWS.format(project_id=project.id) + f"/{submitted['id']}/approve",
        json={},
        headers=reviewer_headers,
    )
    assert second.status_code == 409
    assert second.json()["code"] == "INVALID_REVIEW_STATUS"


def test_ac_69_only_one_pending(client: TestClient, project, headers):
    """同一项目同时只允许一份审核中的记录。"""
    submit_review(client, headers, project.id)

    response = client.post(
        REVIEWS.format(project_id=project.id) + "/submit",
        json={},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_REVIEW_STATUS"


def test_ac_70_version_increments(client: TestClient, project, headers, reviewer_headers):
    """版本号项目内单调递增：v1.0 → v1.1。"""
    build_structure(client, headers, project.id)
    first = make_snapshot(client, headers, project.id, reviewer_headers)
    assert first["version_no"] == 0

    second = make_snapshot(client, headers, project.id, reviewer_headers)
    assert second["version_no"] == 1

    revisions = client.get(
        REVISIONS.format(project_id=project.id), headers=headers
    ).json()
    assert revisions["total"] == 2
    # 新版本在前
    assert [item["version_no"] for item in revisions["items"]] == [1, 0]


def test_ac_69_revisions_status_filter(
    client: TestClient, project, headers, reviewer_headers
):
    """`GET /revisions` 默认只列已通过；前台审核页要按状态取。"""
    build_structure(client, headers, project.id)
    make_snapshot(client, headers, project.id, reviewer_headers)
    submitted = submit_review(client, headers, project.id)

    def versions(status: str) -> list[int | None]:
        body = client.get(
            REVISIONS.format(project_id=project.id),
            params={"status": status},
            headers=headers,
        ).json()
        return [item["version_no"] for item in body["items"]]

    # 默认 approved：只看到已经生成的那份快照
    assert versions("approved") == [0]
    # 审核中：只有那条还没分配版本号的提交记录
    assert versions("submitted") == [None]
    # all：两份都在，新的在前
    assert versions("all") == [None, 0]
    assert submitted["status"] == "submitted"

    invalid = client.get(
        REVISIONS.format(project_id=project.id),
        params={"status": "draft"},
        headers=headers,
    )
    assert invalid.status_code == 422


def test_ac_70_snapshot_not_found(client: TestClient, project, headers):
    """同一张表两种语义：快照读取/删除 → SNAPSHOT_NOT_FOUND，审核动作 → REVIEW_NOT_FOUND。"""
    missing = 999999

    detail = client.get(REVISIONS.format(project_id=project.id) + f"/{missing}", headers=headers)
    assert detail.status_code == 404
    assert detail.json()["code"] == "SNAPSHOT_NOT_FOUND"

    deleted = client.delete(
        REVISIONS.format(project_id=project.id) + f"/{missing}", headers=headers
    )
    assert deleted.status_code == 404
    assert deleted.json()["code"] == "SNAPSHOT_NOT_FOUND"

    approved = client.post(
        REVIEWS.format(project_id=project.id) + f"/{missing}/approve",
        json={"comment": "通过"},
        headers=headers,
    )
    assert approved.status_code == 404
    assert approved.json()["code"] == "REVIEW_NOT_FOUND"


def test_ac_70_snapshot_immutable(client: TestClient, project, headers, reviewer_headers):
    """审核通过后继续编辑结构，快照不变。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    before = client.get(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}", headers=headers
    ).json()["structure"]

    # 通过后继续改结构
    client.patch(
        BASE.format(project_id=project.id)
        + f"/functions/{built['function']['id']}",
        json={"name": "提交订单"},
        headers=headers,
    )
    create_function(client, headers, project.id, built["module"]["id"], "退款")

    after = client.get(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}", headers=headers
    ).json()["structure"]

    assert after == before
    assert after[0]["functions"][0]["name"] == "下单"


def test_ac_70_no_update_endpoint(client: TestClient, project, headers, reviewer_headers):
    """快照没有更新接口，只有删除接口。"""
    build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    response = client.patch(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}",
        json={"version_no": 99},
        headers=headers,
    )
    assert response.status_code == 405


def test_ac_70_member_cannot_submit_review(client: TestClient, project, member_headers):
    """普通成员不能提交审核。"""
    response = client.post(
        REVIEWS.format(project_id=project.id) + "/submit",
        json={},
        headers=member_headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"
