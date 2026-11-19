"""发起测试点生成的全链路（07-test-points T101）。

覆盖点：

- 发起生成 → 生成记录 `succeeded` + 测试点落库（AC-141）；
- **校验顺序**：404 → 409 → 403 → 400（AC-152 / AC-153）；
- 输入为空 → 400，**不产生生成记录**（AC-142）；
- 增量结论全部撤销 → 400（AC-143）；
- 模板停用 / 类型不对 → 400，**不产生生成记录**（AC-156）；
- 坏 JSON → 生成记录 `failed`（AC-145）；
- 越界目标被丢弃（AC-144）。
"""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.test_point import TestPoint, TestPointAnalysis
from tests.test_points import helpers as H


def _payload(chain: dict, **overrides) -> dict:
    payload = {
        "template_id": chain["template"].id,
        "baseline_revision_id": chain["revision"].id,
        "document_version_id": chain["version"].id,
    }
    payload.update(overrides)
    return payload


def _label_chain(db: Session, chain: dict) -> int:
    """给链上的功能打一条生效标签，返回功能 id。"""
    function = chain["structure"]["function"]
    H.make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
    )
    return function.id


# --------------------------------------------------------------- 正常路径


def test_ac_141_generate_persists_analysis_and_points(client, db, provider):
    """发起生成 → 记录 succeeded + 测试点落库，响应直接带回测试点。"""
    chain = H.build_chain(db)
    function_id = _label_chain(db, chain)
    headers = H.login(client, chain["admin"])
    provider.queue = [H.point_response(target_id=function_id)]

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "succeeded"
    assert body["stats"]["test_point_count"] == 1
    assert len(body["points"]) == 1

    point = body["points"][0]
    assert point["target_id"] == function_id
    assert point["target_name"] == chain["structure"]["function"].name
    assert point["status"] == "pending"
    assert point["source_type"] == "llm"
    assert point["source_label_id"] is not None

    # 库里也要真的落了
    assert db.scalar(select(func.count()).select_from(TestPointAnalysis)) == 1
    assert db.scalar(select(func.count()).select_from(TestPoint)) == 1


def test_ac_141_list_and_detail(client, db, provider):
    """生成记录列表 + 详情 + 该次生成的测试点列表。"""
    chain = H.build_chain(db)
    function_id = _label_chain(db, chain)
    headers = H.login(client, chain["admin"])
    provider.queue = [H.point_response(target_id=function_id)]

    created = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    ).json()

    base = H.BASE.format(project_id=chain["project"].id)

    listed = client.get(f"{base}/analyses", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == created["id"]

    detail = client.get(f"{base}/analyses/{created['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["points"]) == 1

    points = client.get(
        f"{base}/analyses/{created['id']}/points", headers=headers
    )
    assert points.status_code == 200, points.text
    assert len(points.json()) == 1

    all_points = client.get(f"{base}/points", headers=headers)
    assert all_points.status_code == 200, all_points.text
    assert all_points.json()["total"] == 1


def test_ac_141_point_detail_and_filters(client, db, provider):
    """测试点详情 + 按状态 / 目标筛选。"""
    chain = H.build_chain(db)
    function_id = _label_chain(db, chain)
    headers = H.login(client, chain["admin"])
    provider.queue = [H.point_response(target_id=function_id)]

    created = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    ).json()
    point_id = created["points"][0]["id"]
    base = H.BASE.format(project_id=chain["project"].id)

    detail = client.get(f"{base}/points/{point_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == point_id

    pending = client.get(f"{base}/points?status=pending", headers=headers)
    assert pending.json()["total"] == 1
    approved = client.get(f"{base}/points?status=approved", headers=headers)
    assert approved.json()["total"] == 0

    by_target = client.get(
        f"{base}/points?target_type=function&target_id={function_id}",
        headers=headers,
    )
    assert by_target.json()["total"] == 1


def test_ac_146_fenced_response_is_accepted(client, db, provider):
    """带 Markdown 围栏的响应 → 照常落库。"""
    chain = H.build_chain(db)
    function_id = _label_chain(db, chain)
    headers = H.login(client, chain["admin"])
    provider.queue = [
        H.fenced_response(H.point_response(target_id=function_id))
    ]

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "succeeded"
    assert response.json()["stats"]["test_point_count"] == 1


def test_ac_144_out_of_baseline_point_is_not_stored(client, db, provider):
    """越界目标 → 不落库，记进 discarded。"""
    chain = H.build_chain(db)
    _label_chain(db, chain)
    headers = H.login(client, chain["admin"])
    provider.queue = [H.point_response(target_id=999999)]

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["stats"]["test_point_count"] == 0
    assert body["stats"]["discarded_count"] == 1
    assert (
        body["stats"]["discarded"][0]["code"] == "TEST_POINT_TARGET_OUT_OF_BASELINE"
    )
    assert db.scalar(select(func.count()).select_from(TestPoint)) == 0


# --------------------------------------------------------------- 校验顺序


def test_ac_152_missing_project_is_404(client, db, provider):
    """项目不存在 → 404 `PROJECT_NOT_FOUND`。"""
    headers = H.login(client, H.make_user(db))
    response = client.post(
        H.ANALYSES.format(project_id=99_999_999),
        json={"template_id": 1},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


def test_ac_153_archived_project_is_409(client, db, provider):
    """归档项目写接口 → 409 `PROJECT_ARCHIVED`。"""
    chain = H.build_chain(db, project_status="archived")
    function_id = _label_chain(db, chain)
    headers = H.login(client, chain["admin"])
    provider.queue = [H.point_response(target_id=function_id)]

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_153_archived_project_read_still_works(client, db, provider):
    """归档项目读接口正常。"""
    chain = H.build_chain(db, project_status="archived")
    headers = H.login(client, chain["admin"])

    response = client.get(
        H.BASE.format(project_id=chain["project"].id) + "/analyses",
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_ac_152_member_cannot_generate(client, db, provider):
    """member 发起生成 → 403 `NOT_PROJECT_ADMIN`。"""
    chain = H.build_chain(db)
    _label_chain(db, chain)
    member = H.make_user(db)
    H.add_member(db, chain["project"], member, "member")
    headers = H.login(client, member)

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_142_input_empty_is_rejected(client, db, provider):
    """没有标签也没有增量结论 → 400，**不产生生成记录**。"""
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TEST_POINT_INPUT_EMPTY"
    assert db.scalar(select(func.count()).select_from(TestPointAnalysis)) == 0


def test_ac_142_no_input_at_all_is_rejected(client, db, provider):
    """既不给增量记录也不给快照 → 400（没有输入就没有依据）。"""
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TEST_POINT_INPUT_EMPTY"
    assert db.scalar(select(func.count()).select_from(TestPointAnalysis)) == 0


def test_ac_143_fully_revoked_analysis_is_rejected(client, db, provider):
    """增量结论已全部撤销 → 400，不产生生成记录。"""
    chain = H.build_chain(db)
    function = chain["structure"]["function"]
    analysis = H.make_analysis(db, chain)
    H.make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
        status="cleared",
        source_analysis_id=analysis.id,
    )
    headers = H.login(client, chain["admin"])

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain, analysis_id=analysis.id),
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TEST_POINT_INPUT_EMPTY"
    assert db.scalar(select(func.count()).select_from(TestPointAnalysis)) == 0


def test_ac_156_disabled_template_is_rejected(client, db, provider):
    """模板停用 → 400 `TEST_POINT_TEMPLATE_INVALID`，不产生生成记录。"""
    chain = H.build_chain(db)
    _label_chain(db, chain)
    headers = H.login(client, chain["admin"])

    chain["template"].status = "disabled"
    db.flush()

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TEST_POINT_TEMPLATE_INVALID"
    assert db.scalar(select(func.count()).select_from(TestPointAnalysis)) == 0


def test_ac_156_wrong_task_type_template_is_rejected(client, db, provider):
    """模板类型不是 `test_point` → 400，不产生生成记录。"""
    chain = H.build_chain(db)
    _label_chain(db, chain)
    headers = H.login(client, chain["admin"])

    chain["template"].task_type = "incremental"
    db.flush()

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TEST_POINT_TEMPLATE_INVALID"
    assert db.scalar(select(func.count()).select_from(TestPointAnalysis)) == 0


# --------------------------------------------------------------- 失败处理


def test_ac_145_bad_output_marks_analysis_failed(client, db, provider):
    """坏 JSON → 生成记录 `failed`，不产生测试点。"""
    chain = H.build_chain(db)
    _label_chain(db, chain)
    headers = H.login(client, chain["admin"])
    provider.queue = ["not json at all"]

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TEST_POINT_INVALID"

    analysis = db.scalar(select(TestPointAnalysis))
    assert analysis is not None
    assert analysis.status == "failed"
    assert analysis.error_code == "TEST_POINT_INVALID"
    assert db.scalar(select(func.count()).select_from(TestPoint)) == 0

