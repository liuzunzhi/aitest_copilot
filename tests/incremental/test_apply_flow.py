"""T81 · 产出服务与接口（AC-98 ~ AC-104）。

全部走真实 HTTP 接口，断言库里落了什么；产出段不调模型，零网络请求。
"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.baseline import BaselineLabel, BaselineRevision
from app.models.incremental import (
    IncrementalAnalysis,
    IncrementalConflict,
    IncrementalDecision,
)
from app.models.system import AuditLog
from tests.incremental import helpers

APPLY = "/api/projects/{project_id}/incremental/analyses/{analysis_id}/apply"
APPLIED = "/api/projects/{project_id}/incremental/analyses/{analysis_id}/applied-labels"
BASELINES = "/api/projects/{project_id}/baselines"


def _decision(
    db: Session,
    analysis: IncrementalAnalysis,
    *,
    target_type: str = "function",
    target_id: int,
    target_name: str = "下单",
    decision: str = "changed",
) -> IncrementalDecision:
    row = IncrementalDecision(
        analysis_id=analysis.id,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        decision=decision,
    )
    db.add(row)
    db.flush()
    return row


def _conflict(
    db: Session,
    analysis: IncrementalAnalysis,
    *,
    target_type: str = "function",
    target_id: int | None,
    target_name: str = "下单",
    conflict_type: str = "conflict",
    status: str = "confirmed",
    resolved_label_type: str | None = "changed",
) -> IncrementalConflict:
    row = IncrementalConflict(
        analysis_id=analysis.id,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        conflict_type=conflict_type,
        candidates=[{"label_type": "changed"}],
        status=status,
        resolved_label_type=resolved_label_type,
        resolved_by=analysis.created_by if status != "pending" else None,
    )
    db.add(row)
    db.flush()
    return row


def _ready(db: Session, chain: dict) -> IncrementalAnalysis:
    analysis = helpers.make_analysis(db, chain)
    analysis.second_pass_status = "succeeded"
    db.flush()
    return analysis


def _structure_with_point(db: Session, chain: dict) -> dict:
    return helpers.make_function(
        db,
        chain["project"],
        chain["admin"],
        module_name="会员模块",
        function_name="开通会员",
        point_name="支付会费",
    )


def _apply(client: TestClient, chain: dict, analysis: IncrementalAnalysis, headers):
    return client.post(
        APPLY.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )


# ------------------------------------------------------------ AC-98


def test_ac_98_apply_writes_labels(client: TestClient, db: Session):
    """第二遍成功 → 应用产出写标签 + 映射；unchanged 不产生标签。"""
    chain = helpers.build_chain(db)
    extra = _structure_with_point(db, chain)
    analysis = _ready(db, chain)
    _decision(
        db,
        analysis,
        target_id=chain["structure"]["function"].id,
        target_name="下单",
        decision="changed",
    )
    _decision(
        db,
        analysis,
        target_type="feature_point",
        target_id=extra["point"].id,
        target_name="支付会费",
        decision="affected",
    )
    _decision(
        db,
        analysis,
        target_type="function",
        target_id=999999,
        target_name="退款",
        decision="unchanged",
    )
    headers = helpers.login(client, chain["admin"])

    response = _apply(client, chain, analysis, headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["apply_status"] == "succeeded"
    assert body["apply_revision_id"] is not None
    stats = body["apply_stats"]
    assert stats["label_count"] == 2
    assert stats["changed_count"] == 1
    assert stats["affected_count"] == 1
    assert stats["unchanged_count"] == 1
    assert stats["skipped_missing_count"] == 0
    assert stats["skipped_new_count"] == 0
    assert stats["conflict_label_count"] == 0
    assert len(body["labels"]) == 2
    assert {item["target_name"] for item in body["labels"]} == {"下单", "支付会费"}

    revision = db.get(BaselineRevision, body["apply_revision_id"])
    assert revision.status == "submitted"
    assert revision.version_no is None

    labels = db.scalars(
        select(BaselineLabel).where(BaselineLabel.source_analysis_id == analysis.id)
    ).all()
    assert len(labels) == 2
    assert {label.target_type for label in labels} == {"function", "feature_point"}
    assert all(label.status == "active" for label in labels)
    assert all(label.revision_id == revision.id for label in labels)

    row = db.get(IncrementalAnalysis, analysis.id)
    assert row.apply_status == "succeeded"
    assert row.apply_revision_id == revision.id
    assert row.apply_finished_at is not None


def test_ac_98_conflict_labels_and_skipped_new(client: TestClient, db: Session):
    """已确认冲突落标签；new 冲突无实体，计入 skipped_new_count。"""
    chain = helpers.build_chain(db)
    extra = _structure_with_point(db, chain)
    analysis = _ready(db, chain)
    _conflict(
        db,
        analysis,
        target_type="function",
        target_id=extra["function"].id,
        target_name="开通会员",
        resolved_label_type="changed",
    )
    _conflict(
        db,
        analysis,
        target_id=None,
        target_name="新增：开票",
        conflict_type="new",
        resolved_label_type="changed",
    )
    headers = helpers.login(client, chain["admin"])

    response = _apply(client, chain, analysis, headers)
    assert response.status_code == 200, response.text
    stats = response.json()["apply_stats"]

    assert stats["label_count"] == 1
    assert stats["conflict_label_count"] == 1
    assert stats["skipped_new_count"] == 1
    assert response.json()["labels"][0]["target_name"] == "开通会员"


def test_ac_98_missing_target_is_skipped(client: TestClient, db: Session):
    """目标已删除 → 跳过并计入 skipped_missing_count，不报错。"""
    chain = helpers.build_chain(db)
    analysis = _ready(db, chain)
    _decision(db, analysis, target_id=chain["structure"]["function"].id)
    _decision(db, analysis, target_id=999999, target_name="已删除功能")
    headers = helpers.login(client, chain["admin"])

    response = _apply(client, chain, analysis, headers)
    assert response.status_code == 200, response.text
    stats = response.json()["apply_stats"]
    assert stats["label_count"] == 1
    assert stats["skipped_missing_count"] == 1


# ------------------------------------------------------------ AC-99


def test_ac_99_reuses_existing_submitted_revision(client: TestClient, db: Session):
    """项目内已有 submitted 记录时复用，不新建第二条，也不自动批准。"""
    chain = helpers.build_chain(db)
    analysis = _ready(db, chain)
    _decision(db, analysis, target_id=chain["structure"]["function"].id)
    existing = helpers.make_revision(
        db, chain["project"], status="submitted", version_no=None
    )
    headers = helpers.login(client, chain["admin"])

    response = _apply(client, chain, analysis, headers)
    assert response.status_code == 200, response.text

    assert response.json()["apply_revision_id"] == existing.id
    db.refresh(existing)
    assert existing.status == "submitted"
    total = db.scalar(
        select(func.count())
        .select_from(BaselineRevision)
        .where(
            BaselineRevision.project_id == chain["project"].id,
            BaselineRevision.status == "submitted",
        )
    )
    assert total == 1


# ------------------------------------------------------------ AC-100


def test_ac_100_apply_twice_does_not_accumulate(client: TestClient, db: Session):
    """连跑两次：生效标签不累加，旧行保留为 cleared，映射可追溯。"""
    chain = helpers.build_chain(db)
    extra = _structure_with_point(db, chain)
    analysis = _ready(db, chain)
    _decision(db, analysis, target_id=chain["structure"]["function"].id)
    _decision(
        db,
        analysis,
        target_type="feature_point",
        target_id=extra["point"].id,
        target_name="支付会费",
        decision="affected",
    )
    headers = helpers.login(client, chain["admin"])

    first = _apply(client, chain, analysis, headers)
    assert first.status_code == 200, first.text
    second = _apply(client, chain, analysis, headers)
    assert second.status_code == 200, second.text

    assert second.json()["apply_stats"]["label_count"] == first.json()["apply_stats"][
        "label_count"
    ] == 2

    active = int(
        db.scalar(
            select(func.count())
            .select_from(BaselineLabel)
            .where(
                BaselineLabel.source_analysis_id == analysis.id,
                BaselineLabel.status == "active",
            )
        )
        or 0
    )
    total = int(
        db.scalar(
            select(func.count())
            .select_from(BaselineLabel)
            .where(BaselineLabel.source_analysis_id == analysis.id)
        )
        or 0
    )
    assert active == 2
    assert total == 4, "旧标签行不允许被物理删除"

    cleared = db.scalars(
        select(BaselineLabel).where(
            BaselineLabel.source_analysis_id == analysis.id,
            BaselineLabel.status == "cleared",
        )
    ).all()
    assert len(cleared) == 2
    assert all(row.clear_reason == "misjudged" for row in cleared)
    assert all(row.cleared_by == chain["admin"].id for row in cleared)
    assert all(row.cleared_at is not None for row in cleared)

    listed = client.get(
        APPLIED.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["labels"]) == 4
    assert listed.json()["revoked"] is False


# ------------------------------------------------------------ AC-101


def test_ac_101_manual_clear_marks_revoked(client: TestClient, db: Session):
    """人工清除产出标签：行带清除信息；全部清除后 revoked=true，记录保留。"""
    chain = helpers.build_chain(db)
    extra = _structure_with_point(db, chain)
    analysis = _ready(db, chain)
    _decision(db, analysis, target_id=chain["structure"]["function"].id)
    _decision(
        db,
        analysis,
        target_type="feature_point",
        target_id=extra["point"].id,
        target_name="支付会费",
        decision="affected",
    )
    headers = helpers.login(client, chain["admin"])

    applied = _apply(client, chain, analysis, headers)
    assert applied.status_code == 200, applied.text
    label_ids = [item["baseline_label_id"] for item in applied.json()["labels"]]
    assert len(label_ids) == 2

    def _clear(label_id: int):
        response = client.post(
            BASELINES.format(project_id=chain["project"].id)
            + f"/labels/{label_id}/clear",
            json={"clear_reason": "requirement_done"},
            headers=headers,
        )
        assert response.status_code == 200, response.text

    _clear(label_ids[0])
    partial = client.get(
        APPLIED.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    ).json()
    assert partial["revoked"] is False
    cleared = [item for item in partial["labels"] if item["status"] == "cleared"]
    assert len(cleared) == 1
    assert cleared[0]["cleared_by"] == chain["admin"].id
    assert cleared[0]["cleared_at"] is not None
    assert cleared[0]["clear_reason"] == "requirement_done"

    _clear(label_ids[1])
    revoked = client.get(
        APPLIED.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    ).json()
    assert revoked["revoked"] is True
    # 记录本身不删除、不改状态
    assert client.get(
        f"/api/projects/{chain['project'].id}/incremental/analyses/{analysis.id}",
        headers=headers,
    ).status_code == 200


# ------------------------------------------------------------ AC-102


def test_ac_102_validation_order(client: TestClient, db: Session):
    """第二遍未成功 / 有 pending 冲突 / 无可落标签 → 各自 409。"""
    chain = helpers.build_chain(db)
    headers = helpers.login(client, chain["admin"])

    not_ready = helpers.make_analysis(db, chain)
    _decision(db, not_ready, target_id=chain["structure"]["function"].id)
    response = _apply(client, chain, not_ready, headers)
    assert response.status_code == 409
    assert response.json()["code"] == "APPLY_NOT_READY"

    pending = _ready(db, chain)
    _decision(db, pending, target_id=chain["structure"]["function"].id)
    _conflict(db, pending, target_id=None, conflict_type="new", status="pending")
    response = _apply(client, chain, pending, headers)
    assert response.status_code == 409
    assert response.json()["code"] == "APPLY_CONFLICTS_PENDING"

    nothing = _ready(db, chain)
    _decision(
        db,
        nothing,
        target_id=chain["structure"]["function"].id,
        decision="unchanged",
    )
    response = _apply(client, chain, nothing, headers)
    assert response.status_code == 409
    assert response.json()["code"] == "APPLY_NO_LABELABLE_TARGET"


def test_ac_102_permissions_and_archive(client: TestClient, db: Session):
    """member / guest 不可应用；非成员不可读；归档项目 409；跨项目 404。"""
    chain = helpers.build_chain(db)
    analysis = _ready(db, chain)
    _decision(db, analysis, target_id=chain["structure"]["function"].id)

    guest = helpers.make_user(db)
    helpers.add_member(db, chain["project"], guest, "guest")
    member = helpers.make_user(db)
    helpers.add_member(db, chain["project"], member, "member")
    outsider = helpers.make_user(db)

    guest_headers = helpers.login(client, guest)
    assert client.get(
        APPLIED.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=guest_headers,
    ).status_code == 200
    assert _apply(client, chain, analysis, guest_headers).json()["code"] == (
        "NOT_PROJECT_ADMIN"
    )
    assert _apply(client, chain, analysis, helpers.login(client, member)).json()[
        "code"
    ] == "NOT_PROJECT_ADMIN"
    assert client.get(
        APPLIED.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=helpers.login(client, outsider),
    ).json()["code"] == "NOT_PROJECT_MEMBER"

    headers = helpers.login(client, chain["admin"])
    assert _apply(client, chain, analysis, headers).status_code == 200

    chain["project"].status = "archived"
    db.flush()
    archived = _apply(client, chain, analysis, headers)
    assert archived.status_code == 409
    assert archived.json()["code"] == "PROJECT_ARCHIVED"

    missing = client.post(
        APPLY.format(project_id=chain["project"].id, analysis_id=999999),
        headers=headers,
    )
    # 归档先于分析记录校验
    assert missing.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_102_analysis_not_found(client: TestClient, db: Session):
    chain = helpers.build_chain(db)
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        APPLY.format(project_id=chain["project"].id, analysis_id=999999),
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "INCREMENTAL_ANALYSIS_NOT_FOUND"


# ------------------------------------------------------------ AC-103


def test_ac_103_apply_audit(client: TestClient, db: Session):
    """产出成功写 `incremental.apply.run`，校验失败不写审计。"""
    chain = helpers.build_chain(db)
    analysis = _ready(db, chain)
    _decision(db, analysis, target_id=chain["structure"]["function"].id)
    headers = helpers.login(client, chain["admin"])

    response = _apply(client, chain, analysis, headers)
    assert response.status_code == 200, response.text

    log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "incremental.apply.run",
            AuditLog.project_id == chain["project"].id,
        )
    )
    assert log is not None
    assert log.actor_id == chain["admin"].id
    assert log.target_type == "incremental_analysis"
    assert log.target_id == str(analysis.id)

    failed = helpers.make_analysis(db, chain)
    assert _apply(client, chain, failed, headers).status_code == 409
    count = db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "incremental.apply.run",
            AuditLog.project_id == chain["project"].id,
        )
    )
    assert count == 1
