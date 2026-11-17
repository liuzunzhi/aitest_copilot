"""AC-81：分析记录状态流转、失败留痕与状态筛选。"""

import json

import pytest
from sqlalchemy import func, select

from app.llm.provider import get_provider
from app.main import app as fastapi_app
from app.models.incremental import IncrementalAnalysis, IncrementalConclusion
from tests.incremental import helpers as H


def _count_analyses(db) -> int:
    return db.scalar(select(func.count()).select_from(IncrementalAnalysis)) or 0


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("missing_revision", "BASELINE_REVISION_REQUIRED"),
        ("unapproved_revision", "BASELINE_REVISION_REQUIRED"),
        ("missing_version", "NO_ACTIVE_DOCUMENT_VERSION"),
        ("pending_version", "DOCUMENT_VERSION_NOT_ANALYZABLE"),
    ],
)
def test_ac_81_precheck_failure_creates_no_record(
    client, db, provider, case, expected_code
):
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])

    revision_id = chain["revision"].id
    version_id = chain["version"].id
    if case == "missing_revision":
        revision_id = None
    elif case == "unapproved_revision":
        chain["revision"].status = "submitted"
        db.flush()
    elif case == "missing_version":
        version_id = 99_999_999
    elif case == "pending_version":
        chain["version"].status = "pending"
        db.flush()

    before = _count_analyses(db)
    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=revision_id,
            document_version_id=version_id,
        ),
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == expected_code
    assert _count_analyses(db) == before, "校验失败不得产生分析记录"


def test_ac_81_invalid_split_granularity(client, db, provider):
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])
    before = _count_analyses(db)

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
            split_granularity="paragraph",
        ),
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_SPLIT_GRANULARITY"
    assert _count_analyses(db) == before


def test_ac_81_invalid_json_fails_and_keeps_prior_chapter(client, db, provider):
    chain = H.build_chain(
        db, chapters=[("登录", "账号密码登录"), ("支付", "支付流程调整")]
    )
    headers = H.login(client, chain["admin"])
    function_id = chain["structure"]["function"].id
    provider.queue = [
        json.dumps({"conclusions": [H.conclusion_payload(target_id=function_id)]}),
        "not-a-json",
    ]

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )

    assert response.status_code == 502, response.text
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"

    analysis = db.scalar(
        select(IncrementalAnalysis).order_by(IncrementalAnalysis.id.desc())
    )
    assert analysis.status == "failed"
    assert analysis.error_code == "LLM_OUTPUT_INVALID"
    assert analysis.error_message
    assert analysis.finished_at is not None
    # 单章失败立即中止：第二章不再调用
    assert len(provider.calls) == 2
    # 第一章已落库的结论保留
    rows = db.scalars(
        select(IncrementalConclusion).where(
            IncrementalConclusion.analysis_id == analysis.id
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].chapter_id == chain["chapters"][0].id
    assert analysis.stats["failed_chapter_id"] == chain["chapters"][1].id


def test_ac_81_provider_exception_marks_failed(client, db, provider):
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])

    class BrokenProvider:
        name = "mock"

        def chat(self, request):  # noqa: ARG002 - 只为触发异常
            raise RuntimeError("upstream boom")

    fastapi_app.dependency_overrides[get_provider] = lambda: BrokenProvider()

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )

    assert response.status_code == 502, response.text
    assert response.json()["code"] == "LLM_CALL_FAILED"

    analysis = db.scalar(
        select(IncrementalAnalysis).order_by(IncrementalAnalysis.id.desc())
    )
    assert analysis.status == "failed"
    assert analysis.error_code == "LLM_CALL_FAILED"
    assert analysis.finished_at is not None


def test_ac_81_status_filter_matches_database(client, db, provider):
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])
    payload = H.analysis_payload(
        template_id=chain["template"].id,
        baseline_revision_id=chain["revision"].id,
        document_version_id=chain["version"].id,
    )
    url = H.ANALYSES.format(project_id=chain["project"].id)

    provider.queue = [json.dumps({"conclusions": []})]
    success = client.post(url, json=payload, headers=headers)
    assert success.status_code == 201, success.text

    provider.queue = ["broken"]
    failed = client.post(url, json=payload, headers=headers)
    assert failed.status_code == 502, failed.text

    succeeded_list = client.get(url, params={"status": "succeeded"}, headers=headers)
    failed_list = client.get(url, params={"status": "failed"}, headers=headers)
    assert succeeded_list.status_code == 200
    assert failed_list.status_code == 200
    assert succeeded_list.json()["total"] == 1
    assert failed_list.json()["total"] == 1
    assert succeeded_list.json()["items"][0]["status"] == "succeeded"
    assert failed_list.json()["items"][0]["status"] == "failed"
