"""AC-154：测试点生成的运行留痕。

留痕记的是「**本次任务**」的调用次数——
`provider.calls` 是累计的，所以必须「跑前记基线、跑完相减」。
直接取 `len(calls)` 会把历史调用也算进来。

这条口径由 06 期 T86 定下（`tests/llm/test_run_logs.py` 有同款用例），
07 沿用同一写法。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.llm import LLMRunLog
from tests.test_points import helpers as H


def _payload(chain: dict) -> dict:
    return {
        "template_id": chain["template"].id,
        "baseline_revision_id": chain["revision"].id,
        "document_version_id": chain["version"].id,
    }


def _label_chain(db: Session, chain: dict) -> int:
    function = chain["structure"]["function"]
    H.make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_type="function",
        target_id=function.id,
        label_type="changed",
    )
    return function.id


def _logs(db: Session, project_id: int) -> list[LLMRunLog]:
    return list(
        db.scalars(
            select(LLMRunLog)
            .where(LLMRunLog.project_id == project_id)
            .order_by(LLMRunLog.id)
        ).all()
    )


def test_ac_154_successful_run_writes_run_log(client, db, provider):
    """成功 → 一条 `task_type='test_point'` 的留痕。"""
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

    logs = _logs(db, chain["project"].id)
    assert len(logs) == 1
    log = logs[0]
    assert log.task_type == "test_point"
    assert log.status == "succeeded"
    assert log.call_count == 1
    assert log.latency_ms >= 1
    assert log.template_id == chain["template"].id
    assert log.template_version == chain["template"].version_no
    assert log.project_id == chain["project"].id


def test_ac_154_failed_run_writes_failed_log(client, db, provider):
    """失败 → 留痕 `status='failed'` + 错误码。"""
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

    logs = _logs(db, chain["project"].id)
    assert len(logs) == 1
    assert logs[0].status == "failed"
    assert logs[0].error_code == "TEST_POINT_INVALID"


def test_ac_154_call_count_is_per_task_not_cumulative(client, db, provider):
    """**跑前记基线、跑完相减**：连续两次生成，各自只记自己的调用次数。

    `provider.calls` 是累计的——第二次跑完 `len(calls)` 是 2，
    但这次任务只调了 1 次。留痕必须记 1。
    """
    chain = H.build_chain(db)
    function_id = _label_chain(db, chain)
    headers = H.login(client, chain["admin"])

    provider.queue = [H.point_response(target_id=function_id)]
    first = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert first.status_code == 201, first.text

    provider.queue = [H.point_response(target_id=function_id)]
    second = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert second.status_code == 201, second.text

    logs = _logs(db, chain["project"].id)
    assert len(logs) == 2
    assert [log.call_count for log in logs] == [1, 1]


def test_ac_154_run_log_has_no_prompt_or_key(client, db, provider):
    """留痕表里**没有** Prompt 正文与 API Key 列——不是靠代码自觉，是表结构保证。"""
    chain = H.build_chain(db)
    function_id = _label_chain(db, chain)
    headers = H.login(client, chain["admin"])
    provider.queue = [H.point_response(target_id=function_id)]

    client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )

    log = _logs(db, chain["project"].id)[0]
    columns = {c.name for c in LLMRunLog.__table__.columns}
    assert "prompt" not in " ".join(columns)
    assert "api_key" not in " ".join(columns)
    assert "token" not in " ".join(columns)
    # 错误消息也不该带 Key
    assert log.error_message is None or "sk-" not in log.error_message
