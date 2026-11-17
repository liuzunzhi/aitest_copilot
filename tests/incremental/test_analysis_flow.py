"""AC-77 / AC-78：章节局部结论落库、Prompt 来自数据库。"""

import json

from sqlalchemy import func, select

from app.models.incremental import IncrementalAnalysis, IncrementalConclusion
from tests.incremental import helpers as H


def _post_analysis(client, chain: dict, headers: dict, **overrides) -> dict:
    payload = H.analysis_payload(
        template_id=chain["template"].id,
        baseline_revision_id=chain["revision"].id,
        document_version_id=chain["version"].id,
        **overrides,
    )
    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=payload,
        headers=headers,
    )
    return {"response": response, "payload": payload}


def test_ac_77_conclusion_persisted(client, db, provider):
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])
    function_id = chain["structure"]["function"].id
    provider.queue = [
        json.dumps({"conclusions": [H.conclusion_payload(target_id=function_id)]})
    ]

    response = _post_analysis(client, chain, headers)["response"]
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "succeeded"
    assert body["started_at"] is not None
    assert body["finished_at"] is not None
    assert body["split_granularity"] == "chapter"
    assert body["baseline_revision_version"] == "v1.0"
    assert body["document_version_no"] == 1
    assert body["template_name"] == chain["template"].name
    assert body["stats"]["conclusion_count"] == 1
    assert body["stats"]["chapter_count"] == 1

    conclusion = db.scalar(
        select(IncrementalConclusion).where(
            IncrementalConclusion.analysis_id == body["id"]
        )
    )
    assert conclusion is not None
    assert conclusion.chapter_id == chain["chapters"][0].id
    assert conclusion.chapter_title == chain["chapters"][0].title
    assert conclusion.target_type == "function"
    assert conclusion.target_id == function_id
    assert conclusion.label_type == "changed"


def test_ac_77_empty_chapter_skipped_but_counted(client, db, provider):
    chain = H.build_chain(
        db, chapters=[("登录", "账号密码登录"), ("空章节", "")]
    )
    headers = H.login(client, chain["admin"])
    provider.queue = [json.dumps({"conclusions": []})]

    body = _post_analysis(client, chain, headers)["response"].json()

    assert len(provider.calls) == 1, "空章节不应调用模型"
    assert body["stats"]["chapter_count"] == 2
    assert body["stats"]["conclusion_count"] == 0


def test_ac_78_prompt_comes_from_database(client, db, provider):
    chain = H.build_chain(db, chapters=[("登录", "账号密码登录")])
    headers = H.login(client, chain["admin"])
    provider.queue = [json.dumps({"conclusions": []})]

    response = _post_analysis(client, chain, headers)["response"]
    assert response.status_code == 201, response.text

    assert len(provider.calls) == 1
    request = provider.calls[0]
    assert request.system == chain["template"].system_prompt
    assert request.user.startswith(chain["template"].user_prompt)
    assert "## 章节：登录" in request.user
    assert "账号密码登录" in request.user


def test_ac_78_template_missing_returns_404_without_record(client, db, provider):
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])
    before = db.scalar(select(func.count()).select_from(IncrementalAnalysis))

    payload = {
        "template_id": 99_999_999,
        "baseline_revision_id": chain["revision"].id,
        "document_version_id": chain["version"].id,
    }
    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=payload,
        headers=headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "TEMPLATE_NOT_FOUND"
    after = db.scalar(select(func.count()).select_from(IncrementalAnalysis))
    assert after == before


def test_ac_78_template_disabled_returns_409_without_record(client, db, provider):
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])
    chain["template"].status = "disabled"
    db.flush()
    before = db.scalar(select(func.count()).select_from(IncrementalAnalysis))

    response = _post_analysis(client, chain, headers)["response"]

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "TEMPLATE_DISABLED"
    after = db.scalar(select(func.count()).select_from(IncrementalAnalysis))
    assert after == before
