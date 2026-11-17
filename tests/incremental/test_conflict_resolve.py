"""T76 · 人工裁决接口（AC-93）。

核心红线：裁决只改冲突行，**不写 `baseline_labels`**。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.baseline import BaselineLabel
from app.models.incremental import IncrementalConflict
from app.models.system import AuditLog
from tests.incremental import helpers

CONFLICTS = "/api/projects/{project_id}/incremental/analyses/{analysis_id}/conflicts"
RESOLVE = CONFLICTS + "/{conflict_id}/resolve"


def _setup(db: Session, *, conflict_type: str = "conflict"):
    chain = helpers.build_chain(
        db, chapters=[("1 下单", "下单改动")], with_function=False
    )
    order = helpers.make_function(
        db, chain["project"], chain["admin"], function_name="下单", point_name="提交订单"
    )
    analysis = helpers.make_analysis(db, chain, status="succeeded")
    # `new` 没有基线 id，target_id 必须为 NULL（DB CHECK 约束）
    target_id = None if conflict_type == "new" else order["point"].id
    target_name = "退款审核" if conflict_type == "new" else "提交订单"
    conflict = IncrementalConflict(
        analysis_id=analysis.id,
        target_type="feature_point",
        target_id=target_id,
        target_name=target_name,
        conflict_type=conflict_type,
        candidates=[{"label_type": "changed", "source": "point_pass"}],
    )
    db.add(conflict)
    db.flush()
    return chain, analysis, conflict


def _label_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(BaselineLabel)).scalar_one()


def _url(chain: dict, analysis, conflict) -> str:
    return RESOLVE.format(
        project_id=chain["project"].id,
        analysis_id=analysis.id,
        conflict_id=conflict.id,
    )


# ------------------------------------------------------------ AC-93


def test_ac_93_confirmed_resolution(client: TestClient, db: Session):
    """确认裁决 → status/resolved_* 落库，且 `baseline_labels` 行数不变。"""
    chain, analysis, conflict = _setup(db)
    headers = helpers.login(client, chain["admin"])
    before = _label_count(db)

    response = client.post(
        _url(chain, analysis, conflict),
        json={"decision": "confirmed", "label_type": "changed"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["resolved_label_type"] == "changed"
    assert body["resolved_by"] == chain["admin"].id
    assert body["resolved_at"] is not None

    db.expire_all()
    assert _label_count(db) == before


def test_ac_93_rejected_resolution(client: TestClient, db: Session):
    """驳回裁决 → status='rejected'、`resolved_label_type IS NULL`。"""
    chain, analysis, conflict = _setup(db)
    headers = helpers.login(client, chain["admin"])
    before = _label_count(db)

    response = client.post(
        _url(chain, analysis, conflict),
        json={"decision": "rejected"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "rejected"
    assert body["resolved_label_type"] is None
    assert body["resolved_at"] is not None

    db.expire_all()
    assert _label_count(db) == before


def test_ac_93_already_resolved(client: TestClient, db: Session):
    """已裁决再裁决 → 409 CONFLICT_ALREADY_RESOLVED。"""
    chain, analysis, conflict = _setup(db)
    headers = helpers.login(client, chain["admin"])
    url = _url(chain, analysis, conflict)

    assert client.post(
        url, json={"decision": "confirmed", "label_type": "changed"}, headers=headers
    ).status_code == 200

    again = client.post(
        url, json={"decision": "rejected"}, headers=headers
    )
    assert again.status_code == 409
    assert again.json()["code"] == "CONFLICT_ALREADY_RESOLVED"


def test_ac_93_conflict_not_found(client: TestClient, db: Session):
    """冲突不存在 → 404 CONFLICT_NOT_FOUND。"""
    chain, analysis, conflict = _setup(db)
    headers = helpers.login(client, chain["admin"])

    missing = RESOLVE.format(
        project_id=chain["project"].id, analysis_id=analysis.id, conflict_id=999999
    )
    response = client.post(
        missing, json={"decision": "rejected"}, headers=headers
    )
    assert response.status_code == 404
    assert response.json()["code"] == "CONFLICT_NOT_FOUND"


def test_ac_93_conflict_from_other_analysis(client: TestClient, db: Session):
    """冲突属于同项目的另一条分析 → 404。"""
    chain, analysis, conflict = _setup(db)
    # 同项目内的另一条分析：分析能找到，但冲突不在这条分析下
    other_analysis = helpers.make_analysis(db, chain, status="succeeded")
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        RESOLVE.format(
            project_id=chain["project"].id,
            analysis_id=other_analysis.id,
            conflict_id=conflict.id,
        ),
        json={"decision": "rejected"},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "CONFLICT_NOT_FOUND"


def test_ac_93_analysis_from_other_project(client: TestClient, db: Session):
    """分析记录不属于本项目 → 404 INCREMENTAL_ANALYSIS_NOT_FOUND。"""
    chain, analysis, conflict = _setup(db)
    other_chain = helpers.build_chain(
        db, chapters=[("1 其他", "别的分析")], with_function=False
    )
    other_analysis = helpers.make_analysis(db, other_chain, status="succeeded")
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        RESOLVE.format(
            project_id=chain["project"].id,
            analysis_id=other_analysis.id,
            conflict_id=conflict.id,
        ),
        json={"decision": "rejected"},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "INCREMENTAL_ANALYSIS_NOT_FOUND"


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"decision": "done"}, "decision 非法"),
        ({"decision": "confirmed"}, "confirmed 缺 label_type"),
        ({"decision": "confirmed", "label_type": "new"}, "label_type 非法"),
        ({"decision": "rejected", "label_type": "changed"}, "rejected 带了 label_type"),
    ],
)
def test_ac_93_invalid_resolution(client: TestClient, db: Session, payload: dict, reason: str):
    """非法入参 → 400 INVALID_CONFLICT_RESOLUTION，且冲突仍是 pending。"""
    chain, analysis, conflict = _setup(db)
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        _url(chain, analysis, conflict), json=payload, headers=headers
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_CONFLICT_RESOLUTION"

    db.expire_all()
    assert db.get(IncrementalConflict, conflict.id).status == "pending"


def test_ac_93_permissions(client: TestClient, db: Session):
    """访客不可裁决（403）；非成员不可读（403）。"""
    chain, analysis, conflict = _setup(db)
    guest = helpers.make_user(db)
    helpers.add_member(db, chain["project"], guest, "guest")
    outsider = helpers.make_user(db)
    url = _url(chain, analysis, conflict)

    guest_headers = helpers.login(client, guest)
    forbidden = client.post(
        url, json={"decision": "rejected"}, headers=guest_headers
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "NOT_PROJECT_ADMIN"

    outsider_headers = helpers.login(client, outsider)
    blocked = client.get(
        CONFLICTS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=outsider_headers,
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_93_archived_project(client: TestClient, db: Session):
    """归档项目 → 409 PROJECT_ARCHIVED（先于角色判定）。"""
    chain, analysis, conflict = _setup(db)
    chain["project"].status = "archived"
    db.flush()
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        _url(chain, analysis, conflict),
        json={"decision": "rejected"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_93_resolution_writes_audit(client: TestClient, db: Session):
    """裁决写 `incremental.conflict.resolve`。"""
    chain, analysis, conflict = _setup(db)
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        _url(chain, analysis, conflict),
        json={"decision": "confirmed", "label_type": "affected"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    log = db.scalar(
        select(AuditLog).where(AuditLog.action == "incremental.conflict.resolve")
    )
    assert log is not None
    assert log.project_id == chain["project"].id
    assert log.actor_id == chain["admin"].id
    assert log.target_type == "incremental_conflict"
    assert log.target_id == str(conflict.id)


def test_ac_93_failed_resolution_writes_no_audit(client: TestClient, db: Session):
    """校验失败不写审计。"""
    chain, analysis, conflict = _setup(db)
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        _url(chain, analysis, conflict),
        json={"decision": "confirmed"},
        headers=headers,
    )
    assert response.status_code == 400
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "incremental.conflict.resolve")
        )
        == 0
    )


def test_resolved_conflict_visible_in_list(client: TestClient, db: Session):
    """裁决后列表按 `status` 筛选能区分开。"""
    chain, analysis, conflict = _setup(db)
    headers = helpers.login(client, chain["admin"])
    url = CONFLICTS.format(project_id=chain["project"].id, analysis_id=analysis.id)

    assert client.post(
        _url(chain, analysis, conflict),
        json={"decision": "confirmed", "label_type": "changed"},
        headers=headers,
    ).status_code == 200

    pending = client.get(url, params={"status": "pending"}, headers=headers).json()
    confirmed = client.get(url, params={"status": "confirmed"}, headers=headers).json()
    assert pending["total"] == 0
    assert confirmed["total"] == 1
    assert confirmed["items"][0]["resolved_label_type"] == "changed"


def test_new_conflict_can_be_rejected(client: TestClient, db: Session):
    """新增（new）冲突同样可裁决，`target_id` 保持 NULL。"""
    chain, analysis, conflict = _setup(db, conflict_type="new")
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        _url(chain, analysis, conflict),
        json={"decision": "rejected"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "rejected"
    assert body["target_id"] is None
    assert body["target_name"] == "退款审核"
