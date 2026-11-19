"""测试点的评审与手工增删改（07-test-points T101 / T102）。

覆盖点：

- 评审通过 / 驳回；已评审过 → 409（AC-147）；
- 手工新增：`source_type='manual'`、`analysis_id` 为 NULL（AC-148）；
- 手工改：**只接受 4 个字段**，传别的 → 400；
- 手工删：**物理删除**（AC-148）；
- 删除生成记录：有评审通过的测试点 → 409。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.test_point import TestPoint
from tests.test_points import helpers as H


def _chain(db: Session) -> dict:
    chain = H.build_chain(db)
    function = chain["structure"]["function"]
    H.make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
    )
    return chain


def _generate(client, db, provider, chain: dict) -> dict:
    """跑一次生成，返回响应体。"""
    function_id = chain["structure"]["function"].id
    headers = H.login(client, chain["admin"])
    provider.queue = [H.point_response(target_id=function_id)]
    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json={
            "template_id": chain["template"].id,
            "baseline_revision_id": chain["revision"].id,
            "document_version_id": chain["version"].id,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------- 评审


def test_ac_147_review_approve(client, db, provider):
    """评审通过 → `status='approved'`，记评审人与时间。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]
    headers = H.login(client, chain["admin"])
    base = H.POINTS.format(project_id=chain["project"].id)

    response = client.post(
        f"{base}/{point_id}/review",
        json={"action": "approve", "comment": "没问题"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["reviewed_by"] == chain["admin"].id
    assert body["reviewed_at"] is not None
    assert body["review_comment"] == "没问题"


def test_ac_147_review_reject(client, db, provider):
    """评审驳回 → `status='rejected'`。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]
    headers = H.login(client, chain["admin"])
    base = H.POINTS.format(project_id=chain["project"].id)

    response = client.post(
        f"{base}/{point_id}/review",
        json={"action": "reject", "comment": "场景不对"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"


def test_ac_147_review_twice_is_409(client, db, provider):
    """已评审过的不能重复评审 → 409。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]
    headers = H.login(client, chain["admin"])
    base = H.POINTS.format(project_id=chain["project"].id)

    first = client.post(
        f"{base}/{point_id}/review",
        json={"action": "approve"},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"{base}/{point_id}/review",
        json={"action": "reject"},
        headers=headers,
    )
    assert second.status_code == 409
    assert second.json()["code"] == "TEST_POINT_REVIEW_STATE_INVALID"


def test_ac_147_invalid_review_action_is_400(client, db, provider):
    """非法评审动作 → 400 `TEST_POINT_INVALID`。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]
    headers = H.login(client, chain["admin"])
    base = H.POINTS.format(project_id=chain["project"].id)

    response = client.post(
        f"{base}/{point_id}/review",
        json={"action": "maybe"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TEST_POINT_INVALID"


def test_ac_152_member_cannot_review(client, db, provider):
    """member 评审 → 403。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]
    member = H.make_user(db)
    H.add_member(db, chain["project"], member, "member")
    headers = H.login(client, member)
    base = H.POINTS.format(project_id=chain["project"].id)

    response = client.post(
        f"{base}/{point_id}/review",
        json={"action": "approve"},
        headers=headers,
    )
    assert response.status_code == 403


# --------------------------------------------------------------- 手工增删改


def test_ac_148_manual_create(client, db, provider):
    """手工新增 → `source_type='manual'`、`analysis_id` 为 NULL。"""
    chain = _chain(db)
    function = chain["structure"]["function"]
    headers = H.login(client, chain["admin"])
    base = H.POINTS.format(project_id=chain["project"].id)

    response = client.post(
        base,
        json={
            "name": "手工加的测试点",
            "target_type": "function",
            "target_id": function.id,
            "priority": "low",
            "precondition": "已登录",
            "verification": "点一下就报错",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_type"] == "manual"
    assert body["analysis_id"] is None
    assert body["status"] == "pending"
    assert body["target_name"] == function.name
    assert body["priority"] == "low"


def test_ac_148_manual_create_with_unknown_target_is_400(client, db, provider):
    """归属的功能不存在 → 400 `TEST_POINT_TARGET_NOT_FOUND`。"""
    chain = _chain(db)
    headers = H.login(client, chain["admin"])
    base = H.POINTS.format(project_id=chain["project"].id)

    response = client.post(
        base,
        json={
            "name": "挂不上的测试点",
            "target_type": "function",
            "target_id": 999999,
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TEST_POINT_TARGET_NOT_FOUND"


def test_ac_148_update_accepts_only_four_fields(client, db, provider):
    """手工改只接受 4 个字段；传别的 → 400。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]
    headers = H.login(client, chain["admin"])
    base = H.POINTS.format(project_id=chain["project"].id)

    ok = client.patch(
        f"{base}/{point_id}",
        json={"name": "改过的名字", "priority": "medium"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["name"] == "改过的名字"

    # 目标 / 状态 / 来源都不该手工改
    forbidden = client.patch(
        f"{base}/{point_id}",
        json={"status": "approved"},
        headers=headers,
    )
    assert forbidden.status_code == 400
    assert forbidden.json()["code"] == "TEST_POINT_INVALID"

    forbidden_target = client.patch(
        f"{base}/{point_id}",
        json={"target_id": 12345},
        headers=headers,
    )
    assert forbidden_target.status_code == 400


def test_ac_148_delete_is_physical(client, db, provider):
    """手工删 → 行真的没了（物理删除）。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]
    headers = H.login(client, chain["admin"])
    base = H.POINTS.format(project_id=chain["project"].id)

    before = db.scalar(select(func.count()).select_from(TestPoint))
    response = client.delete(f"{base}/{point_id}", headers=headers)
    assert response.status_code == 204, response.text

    after = db.scalar(select(func.count()).select_from(TestPoint))
    assert after == before - 1
    assert db.get(TestPoint, point_id) is None


def test_ac_148_member_cannot_write_manual(client, db, provider):
    """member 手工增删改 → 403。"""
    chain = _chain(db)
    headers = H.login(client, chain["admin"])
    base = H.POINTS.format(project_id=chain["project"].id)
    created = client.post(
        base,
        json={
            "name": "管理员加的",
            "target_type": "function",
            "target_id": chain["structure"]["function"].id,
        },
        headers=headers,
    ).json()

    member = H.make_user(db)
    H.add_member(db, chain["project"], member, "member")
    member_headers = H.login(client, member)

    assert (
        client.patch(
            f"{base}/{created['id']}", json={"name": "x"}, headers=member_headers
        ).status_code
        == 403
    )
    assert (
        client.delete(f"{base}/{created['id']}", headers=member_headers).status_code
        == 403
    )
    assert (
        client.post(
            base,
            json={
                "name": "y",
                "target_type": "function",
                "target_id": chain["structure"]["function"].id,
            },
            headers=member_headers,
        ).status_code
        == 403
    )


# --------------------------------------------------------------- 删生成记录


def test_ac_141_delete_analysis_removes_its_points(client, db, provider):
    """删生成记录 → 连带删掉它产出的测试点。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    headers = H.login(client, chain["admin"])
    base = H.BASE.format(project_id=chain["project"].id)

    before = db.scalar(select(func.count()).select_from(TestPoint))
    response = client.delete(f"{base}/analyses/{created['id']}", headers=headers)
    assert response.status_code == 204, response.text

    after = db.scalar(select(func.count()).select_from(TestPoint))
    assert after == before - 1


def test_ac_141_delete_analysis_with_approved_point_is_409(client, db, provider):
    """已有评审通过的测试点 → 409，不允许连带删除。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]
    headers = H.login(client, chain["admin"])
    base = H.BASE.format(project_id=chain["project"].id)

    approve = client.post(
        f"{H.POINTS.format(project_id=chain['project'].id)}/{point_id}/review",
        json={"action": "approve"},
        headers=headers,
    )
    assert approve.status_code == 200, approve.text

    response = client.delete(f"{base}/analyses/{created['id']}", headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "TEST_POINT_ANALYSIS_HAS_APPROVED"
