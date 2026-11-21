"""运行留痕（T107 / AC-175）。

`call_count` 必须是**本次**调用次数：跑前记基线、跑完相减。
连跑两次，两次都是 1——不累计。
"""

from sqlalchemy import select

from app.models.llm import LLMRunLog

from tests.test_cases.helpers import (
    ANALYSES,
    add_member,
    login,
    make_chapter,
    make_point,
    make_project,
    make_user,
    seed_template,
)


def _chain(db) -> dict:
    admin = make_user(db)
    project = make_project(db)
    add_member(db, project, admin, "project_admin")
    template = seed_template(db)
    chapter = make_chapter(db, project, admin)
    make_point(db, project, admin, chapter=chapter)
    return {"admin": admin, "project": project, "template": template}


def _post(client, chain: dict, headers: dict):
    return client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id},
        headers=headers,
    )


def _logs(db, project_id: int) -> list[LLMRunLog]:
    return list(
        db.scalars(
            select(LLMRunLog)
            .where(
                LLMRunLog.project_id == project_id,
                LLMRunLog.task_type == "test_case",
            )
            .order_by(LLMRunLog.id)
        ).all()
    )


def test_ac_175_call_count_is_per_run_not_cumulative(db, client, provider):
    """连跑两次：两次的 `call_count` 都是 1（Mock 的 `calls` 是累计的）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])

    first = _post(client, chain, headers)
    second = _post(client, chain, headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert len(provider.calls) == 2

    logs = _logs(db, chain["project"].id)
    assert len(logs) == 2
    assert [row.call_count for row in logs] == [1, 1]
    assert all(row.status == "succeeded" for row in logs)
    assert all(row.analysis_id is not None for row in logs)


def test_ac_175_failed_run_is_logged_with_error_code(db, client, provider):
    """失败一次同样留痕：`status='failed'` + `error_code`。"""
    chain = _chain(db)
    provider.queue = ["这不是 JSON"]
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers)
    assert response.status_code == 400

    logs = _logs(db, chain["project"].id)
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "failed"
    assert log.error_code == "TEST_CASE_INVALID"
    assert log.call_count == 1


def test_ac_175_run_log_has_no_prompt_or_key(db, client, provider):
    """留痕表不落 Prompt 正文：失败信息里也不夹带 Prompt 与 Key。"""
    chain = _chain(db)
    provider.queue = ["这不是 JSON"]
    headers = login(client, chain["admin"])
    _post(client, chain, headers)

    log = _logs(db, chain["project"].id)[0]
    columns = set(log.__table__.columns.keys())
    assert "system_prompt" not in columns
    assert "user_prompt" not in columns
    assert "api_key" not in columns
    message = log.error_message or ""
    assert "测试点" not in message
    assert chain["template"].system_prompt[:12] not in message
