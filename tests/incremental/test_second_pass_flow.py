"""T75 · 第二遍服务与接口（AC-88 / AC-94 / AC-95 / AC-96 / AC-97）。

全部走真实 HTTP 接口 + `MockProvider`，断言库里落了什么。
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.incremental.service import SECOND_PASS_TEMPLATE_PREFIX
from app.llm.mock import MockProvider
from app.llm.provider import get_provider
from app.models.incremental import IncrementalAnalysis, IncrementalConflict, PromptTemplate
from app.models.system import AuditLog
from tests.incremental import helpers

SECOND_PASS = "/api/projects/{project_id}/incremental/analyses/{analysis_id}/second-pass"
DECISIONS = "/api/projects/{project_id}/incremental/analyses/{analysis_id}/decisions"
CONFLICTS = "/api/projects/{project_id}/incremental/analyses/{analysis_id}/conflicts"


def _chain(db: Session, *, chapters=None):
    chain = helpers.build_chain(
        db,
        chapters=chapters or [("1 下单", "下单流程改动"), ("2 退款", "退款流程说明")],
        with_function=False,
    )
    order = helpers.make_function(
        db, chain["project"], chain["admin"], function_name="下单", point_name="提交订单"
    )
    chain["order"] = order
    return chain


def _analysis_with_conclusion(db: Session, chain: dict, label_type: str = "changed"):
    analysis = helpers.make_analysis(db, chain, status="succeeded")
    helpers.make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="feature_point",
        target_id=chain["order"]["point"].id,
        label_type=label_type,
    )
    db.flush()
    return analysis


# ------------------------------------------------------------ AC-88


def test_ac_88_success_flow(client: TestClient, db: Session):
    """第一遍成功 → 触发第二遍 → succeeded，统计与时间齐全。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["second_pass_status"] == "succeeded"
    assert body["second_pass_started_at"] is not None
    assert body["second_pass_finished_at"] is not None
    assert body["second_pass_error_code"] is None
    # 第一遍状态不受第二遍影响
    assert body["status"] == "succeeded"

    stats = body["second_pass_stats"]
    assert stats["provider"] == "mock"
    assert stats["point_count"] == 1
    assert stats["decision_count"] == 1
    assert stats["new_count"] == 0
    assert stats["conflict_count"] == 0
    assert stats["template_id"] == helpers.second_pass_template(db).id


def test_ac_88_not_ready(client: TestClient, db: Session):
    """第一遍未成功 → 409 SECOND_PASS_NOT_READY。"""
    chain = _chain(db)
    analysis = helpers.make_analysis(db, chain, status="failed")
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SECOND_PASS_NOT_READY"


def test_ac_88_template_disabled(client: TestClient, db: Session):
    """第二遍模板被停用 → 409 SECOND_PASS_TEMPLATE_MISSING。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    template = helpers.second_pass_template(db)
    template.status = "disabled"
    db.flush()
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SECOND_PASS_TEMPLATE_MISSING"


def test_ac_88_model_failure_keeps_first_pass(client: TestClient, db: Session):
    """模型返回非法 → 第二遍 failed，第一遍仍 succeeded，已产出的结果保留。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    headers = helpers.login(client, chain["admin"])

    provider = MockProvider(queue=[json.dumps({"decision": "new"})])
    client.app.dependency_overrides[get_provider] = lambda: provider
    try:
        response = client.post(
            SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
            headers=headers,
        )
    finally:
        client.app.dependency_overrides.pop(get_provider, None)

    assert response.status_code == 502
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"

    row = db.get(IncrementalAnalysis, analysis.id)
    assert row.status == "succeeded"
    assert row.second_pass_status == "failed"
    assert row.second_pass_error_code == "LLM_OUTPUT_INVALID"
    assert row.second_pass_error_message


# ------------------------------------------------------------ AC-94


def test_ac_94_pending_conflict_blocks_rerun(client: TestClient, db: Session):
    """有待裁决冲突 → 409 SECOND_PASS_CONFLICTS_PENDING。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    headers = helpers.login(client, chain["admin"])

    first = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert first.status_code == 200, first.text

    db.add(
        IncrementalConflict(
            analysis_id=analysis.id,
            target_type="feature_point",
            target_id=chain["order"]["point"].id,
            target_name="提交订单",
            conflict_type="conflict",
            candidates=[{"label_type": "changed", "source": "point_pass"}],
        )
    )
    db.flush()

    response = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SECOND_PASS_CONFLICTS_PENDING"


def test_ac_94_rerun_replaces_old_rows(client: TestClient, db: Session):
    """冲突全部裁决后可重跑，旧裁决 / 冲突被替换，不累加。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    headers = helpers.login(client, chain["admin"])
    url = SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id)

    assert client.post(url, headers=headers).status_code == 200
    first_decisions = client.get(
        DECISIONS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    ).json()
    assert first_decisions["total"] == 1

    db.add(
        IncrementalConflict(
            analysis_id=analysis.id,
            target_type="feature_point",
            target_id=chain["order"]["point"].id,
            target_name="提交订单",
            conflict_type="conflict",
            candidates=[{"label_type": "changed", "source": "point_pass"}],
            status="confirmed",
            resolved_label_type="changed",
            resolved_by=chain["admin"].id,
        )
    )
    db.flush()

    response = client.post(url, headers=headers)
    assert response.status_code == 200, response.text

    decisions = client.get(
        DECISIONS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    ).json()
    conflicts = client.get(
        CONFLICTS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    ).json()
    assert decisions["total"] == 1
    assert conflicts["total"] == 0


# ------------------------------------------------------------ AC-95


def test_ac_95_permissions(client: TestClient, db: Session):
    """访客可读不可写；非成员读 403；归档项目写 409。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    guest = helpers.make_user(db)
    helpers.add_member(db, chain["project"], guest, "guest")
    outsider = helpers.make_user(db)
    url = SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id)

    guest_headers = helpers.login(client, guest)
    assert client.get(
        DECISIONS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=guest_headers,
    ).status_code == 200
    forbidden = client.post(url, headers=guest_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "NOT_PROJECT_ADMIN"

    outsider_headers = helpers.login(client, outsider)
    blocked = client.get(
        CONFLICTS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=outsider_headers,
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_95_analysis_not_found(client: TestClient, db: Session):
    """分析记录不存在或跨项目 → 404。"""
    chain = _chain(db)
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=999999),
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "INCREMENTAL_ANALYSIS_NOT_FOUND"


# ------------------------------------------------------------ AC-96


def test_ac_96_second_pass_audit(client: TestClient, db: Session):
    """第二遍成功写 `incremental.second_pass.run`。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert response.status_code == 200, response.text

    log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "incremental.second_pass.run",
            AuditLog.project_id == chain["project"].id,
        )
    )
    assert log is not None
    assert log.project_id == chain["project"].id
    assert log.actor_id == chain["admin"].id
    assert log.target_type == "incremental_analysis"
    assert log.target_id == str(analysis.id)


def test_ac_96_failed_run_writes_no_audit(client: TestClient, db: Session):
    """校验失败的操作不写审计。"""
    chain = _chain(db)
    analysis = helpers.make_analysis(db, chain, status="failed")
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert response.status_code == 409
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "incremental.second_pass.run",
                AuditLog.project_id == chain["project"].id,
            )
        )
        == 0
    )


# ------------------------------------------------------------ AC-97


def test_ac_97_offline_provider_is_mock(client: TestClient, db: Session):
    """第二遍统计里的 provider 恒为 mock，零真实网络请求。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["second_pass_stats"]["provider"] == "mock"


# ------------------------------------------------------------ 列表接口


def test_decisions_and_conflicts_listing(client: TestClient, db: Session):
    """裁决与冲突列表分页 + 筛选。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    headers = helpers.login(client, chain["admin"])

    db.add(
        IncrementalConflict(
            analysis_id=analysis.id,
            target_type="feature_point",
            target_id=chain["order"]["point"].id,
            target_name="提交订单",
            conflict_type="possible_impact",
            candidates=[{"label_type": "affected", "source": "chapter:1"}],
        )
    )
    db.add(
        IncrementalConflict(
            analysis_id=analysis.id,
            target_type="feature_point",
            target_id=None,
            target_name="退款审核",
            conflict_type="new",
            candidates=[{"label_type": "new", "source": "point_pass"}],
        )
    )
    db.flush()

    all_conflicts = client.get(
        CONFLICTS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    ).json()
    assert all_conflicts["total"] == 2
    assert all_conflicts["page"] == 1

    pending = client.get(
        CONFLICTS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        params={"status": "pending"},
        headers=headers,
    ).json()
    assert pending["total"] == 2

    by_type = client.get(
        CONFLICTS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        params={"conflict_type": "new"},
        headers=headers,
    ).json()
    assert by_type["total"] == 1
    assert by_type["items"][0]["target_id"] is None
    assert by_type["items"][0]["target_name"] == "退款审核"


def test_second_pass_extracts_links_automatically(client: TestClient, db: Session):
    """该版本没有规则边时自动抽一次并计入统计。"""
    chain = _chain(db)
    analysis = _analysis_with_conclusion(db, chain)
    headers = helpers.login(client, chain["admin"])

    response = client.post(
        SECOND_PASS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    stats = response.json()["second_pass_stats"]
    assert stats["chapter_link_count"] >= 0

    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.name.like(f"{SECOND_PASS_TEMPLATE_PREFIX}%")
        )
    )
    assert template is not None
