"""AC-112 · 05 三段链路的运行留痕（06 期 T86）。

一条留痕 = **一次任务**（一次分析的第一遍 / 第二遍 / 一次连通性测试），
不是一次 HTTP 调用；`call_count` 记该任务内调了几次。

断言：
- 第一遍跑完 → 一条 `task_type='incremental_first'`；
- 第二遍跑完 → 一条 `task_type='incremental_second'`；
- 连通性测试 → 一条 `task_type='provider_test'`；
- 失败时 `status='failed'` + `error_code='LLM_CALL_FAILED'`；
- **表里不出现 token 金额、不出现 Prompt 正文**。
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.llm import LLMRunLog
from tests.incremental import helpers as H

SECOND_PASS = "/api/projects/{project_id}/incremental/analyses/{analysis_id}/second-pass"


def _run_logs(
    db: Session,
    task_type: str | None = None,
    *,
    project_id: int | None = None,
    analysis_id: int | None = None,
) -> list[LLMRunLog]:
    """查留痕行。

    **必须按项目 / 分析过滤**：开发库里可能有管理员手工跑的真实分析
    （L2 联调留下的行），全表查会把那些行算进来。
    """
    query = select(LLMRunLog)
    if task_type:
        query = query.where(LLMRunLog.task_type == task_type)
    if project_id is not None:
        query = query.where(LLMRunLog.project_id == project_id)
    if analysis_id is not None:
        query = query.where(LLMRunLog.analysis_id == analysis_id)
    return list(db.scalars(query.order_by(LLMRunLog.id)).all())


def _first_pass(client: TestClient, db: Session, provider, chain: dict):
    """跑一次第一遍。"""
    headers = H.login(client, chain["admin"])
    provider.queue = [json.dumps({"conclusions": []})]
    return client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )


# ------------------------------------------------------------ 第一遍


def test_ac_112_first_pass_writes_run_log(client: TestClient, db: Session, provider):
    """第一遍跑完 → 一条 `incremental_first`。"""
    chain = H.build_chain(db)

    response = _first_pass(client, db, provider, chain)

    assert response.status_code == 201, response.text
    logs = _run_logs(db, "incremental_first", project_id=chain["project"].id)
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "succeeded"
    assert log.latency_ms > 0
    assert log.call_count == 1
    assert log.project_id == chain["project"].id
    assert log.analysis_id == response.json()["id"]
    assert log.template_id == chain["template"].id
    assert log.template_version == chain["template"].version_no


def test_ac_112_first_pass_records_provider_identity(
    client: TestClient, db: Session, provider
):
    """留痕记供应商身份：Mock 降级时是 `mock`。"""
    chain = H.build_chain(db)

    _first_pass(client, db, provider, chain)

    log = _run_logs(db, "incremental_first", project_id=chain["project"].id)[0]
    assert log.provider_name == "mock"
    assert log.model == "mock"


def test_ac_112_call_count_is_per_task_not_cumulative(
    client: TestClient, db: Session, provider
):
    """**跑前记基线、跑完相减**——调用次数是「本次任务」的，不是累计的。

    同一个 Provider 连续跑两次分析，第二次的 `call_count` 仍是 1，
    不能是 2。
    """
    chain = H.build_chain(db)

    _first_pass(client, db, provider, chain)
    _first_pass(client, db, provider, chain)

    logs = _run_logs(db, "incremental_first", project_id=chain["project"].id)
    assert len(logs) == 2
    assert [log.call_count for log in logs] == [1, 1]


def test_ac_112_first_pass_failure_writes_failed_log(
    client: TestClient, db: Session, provider
):
    """第一遍失败 → `status='failed'` + 错误码。"""
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])
    provider.queue = ["这不是 JSON"]

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )

    assert response.status_code == 502
    logs = _run_logs(db, "incremental_first", project_id=chain["project"].id)
    assert len(logs) == 1
    assert logs[0].status == "failed"
    assert logs[0].error_code == "LLM_OUTPUT_INVALID"
    assert logs[0].error_message


def test_ac_112_provider_call_failure_writes_llm_call_failed(
    client: TestClient, db: Session, provider
):
    """模型调用炸了 → `error_code='LLM_CALL_FAILED'`。"""

    class BrokenProvider:
        name = "broken"
        calls: list = []

        def chat(self, req):
            raise RuntimeError("网络炸了")

    from app.llm.provider import get_provider

    client.app.dependency_overrides[get_provider] = lambda: BrokenProvider()
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )

    assert response.status_code == 502
    logs = _run_logs(db, "incremental_first", project_id=chain["project"].id)
    assert len(logs) == 1
    assert logs[0].status == "failed"
    assert logs[0].error_code == "LLM_CALL_FAILED"


# ------------------------------------------------------------ 第二遍


def _second_pass_chain(db: Session):
    """造一条「第一遍已成功、有结论可裁决」的分析。"""
    chain = H.build_chain(db, with_function=False)
    order = H.make_function(
        db,
        chain["project"],
        chain["admin"],
        function_name="下单",
        point_name="提交订单",
    )
    chain["order"] = order
    analysis = H.make_analysis(db, chain, status="succeeded")
    H.make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="feature_point",
        target_id=order["point"].id,
        label_type="changed",
    )
    db.flush()
    return chain, analysis


def test_ac_112_second_pass_writes_run_log(
    client: TestClient, db: Session, provider
):
    """第二遍跑完 → 一条 `incremental_second`。"""
    chain, analysis = _second_pass_chain(db)
    headers = H.login(client, chain["admin"])

    response = client.post(
        SECOND_PASS.format(
            project_id=chain["project"].id, analysis_id=analysis.id
        ),
        headers=headers,
    )

    assert response.status_code == 200, response.text
    logs = _run_logs(db, "incremental_second", project_id=chain["project"].id)
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "succeeded"
    assert log.latency_ms > 0
    assert log.call_count >= 1
    assert log.analysis_id == analysis.id
    assert log.project_id == chain["project"].id


def test_ac_112_second_pass_failure_writes_failed_log(
    client: TestClient, db: Session, provider
):
    """第二遍失败 → `status='failed'`。"""
    chain, analysis = _second_pass_chain(db)
    headers = H.login(client, chain["admin"])
    provider.queue = ["完全不是 JSON"]

    response = client.post(
        SECOND_PASS.format(
            project_id=chain["project"].id, analysis_id=analysis.id
        ),
        headers=headers,
    )

    assert response.status_code == 502
    logs = _run_logs(db, "incremental_second", project_id=chain["project"].id)
    assert len(logs) == 1
    assert logs[0].status == "failed"
    assert logs[0].error_code == "LLM_OUTPUT_INVALID"


def test_ac_112_first_and_second_pass_write_separate_logs(
    client: TestClient, db: Session, provider
):
    """第一遍与第二遍**各记一条**，不合并。"""
    # with_function=False：build_chain 默认建「支付模块」，
    # 这里要自己建结构，不能再让 helper 建一遍同名模块
    chain = H.build_chain(db, with_function=False)
    _first_pass(client, db, provider, chain)

    order = H.make_function(
        db, chain["project"], chain["admin"], function_name="下单"
    )
    analysis = H.make_analysis(db, chain, status="succeeded")
    H.make_conclusion(
        db,
        analysis,
        chapter_id=chain["chapters"][0].id,
        target_type="function",
        target_id=order["function"].id,
        label_type="changed",
    )
    db.flush()

    headers = H.login(client, chain["admin"])
    response = client.post(
        SECOND_PASS.format(
            project_id=chain["project"].id, analysis_id=analysis.id
        ),
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert len(_run_logs(db, "incremental_first", project_id=chain["project"].id)) == 1
    assert len(_run_logs(db, "incremental_second", project_id=chain["project"].id)) == 1


# ------------------------------------------------------------ 明文边界


def test_ac_112_run_log_has_no_prompt_body_or_tokens(
    client: TestClient, db: Session, provider
):
    """**表里不出现 Prompt 正文、不出现 token 金额。**"""
    chain = H.build_chain(db)

    _first_pass(client, db, provider, chain)

    log = _run_logs(db, "incremental_first", project_id=chain["project"].id)[0]
    blob = f"{log.error_message} {log.error_code} {log.provider_name} {log.model}"
    # Prompt 正文（模板里的独特标记）
    assert "[INCREMENTAL_SYSTEM]" not in blob
    assert chain["template"].system_prompt[:30] not in blob
    # token 金额
    assert "token" not in blob.lower()


def test_ac_112_run_log_table_has_no_prompt_or_token_columns():
    """表结构层面就没有这些列——不是靠代码自觉。"""
    column_names = {column.name for column in LLMRunLog.__table__.columns}

    assert "prompt" not in " ".join(column_names).lower()
    assert "token" not in " ".join(column_names).lower()
    assert "usage" not in " ".join(column_names).lower()


def test_ac_112_run_log_has_no_audit(client: TestClient, db: Session, provider):
    """写日志**不写审计**（日志不是业务写操作）。"""
    from app.models.system import AuditLog

    chain = H.build_chain(db)

    _first_pass(client, db, provider, chain)

    assert (
        db.scalar(
            select(AuditLog).where(AuditLog.action.like("llm.run%"))
        )
        is None
    )
