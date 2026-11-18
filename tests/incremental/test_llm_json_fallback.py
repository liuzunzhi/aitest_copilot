"""AC-120 · 05 两段的 JSON 容错（Markdown 围栏）。

真实模型必然返回带围栏的 JSON。改造前裸 `json.loads` 会让整次分析
直接 502；改造后（只换解析入口）结论照样落库。

这里断言两件事：

1. **第一遍**（`engine.py`）喂带围栏的响应 → 结论正常落库；
2. **第二遍**（`second_pass.py`）喂带围栏的响应 → 裁决正常落库。

同时确认**判定逻辑零改动**：字段校验、标签分类、丢弃规则、错误码
全部保持原样——本文件里的期望值与 05 原有用例完全一致。
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.incremental import IncrementalAnalysis, IncrementalConclusion
from tests.incremental import helpers as H

SECOND_PASS = "/api/projects/{project_id}/incremental/analyses/{analysis_id}/second-pass"
DECISIONS = "/api/projects/{project_id}/incremental/analyses/{analysis_id}/decisions"


def _fenced(payload: dict) -> str:
    """把 payload 包成真实模型会返回的样子。"""
    return f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


def _fenced_plain(payload: dict) -> str:
    """无语言标记的围栏（另一种真实返回形态）。"""
    return f"```\n{json.dumps(payload, ensure_ascii=False)}\n```"


# ------------------------------------------------------------ 第一遍


def test_ac_120_first_pass_with_json_fence(client: TestClient, db: Session, provider):
    """第一遍收到带围栏的 JSON → 结论照常落库，不再 502。"""
    chain = H.build_chain(db)
    function_id = chain["structure"]["function"].id
    headers = H.login(client, chain["admin"])
    provider.queue = [
        _fenced({"conclusions": [H.conclusion_payload(target_id=function_id)]})
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

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["stats"]["conclusion_count"] == 1

    conclusion = db.scalar(
        select(IncrementalConclusion).where(
            IncrementalConclusion.analysis_id == body["id"]
        )
    )
    assert conclusion is not None
    assert conclusion.target_id == function_id
    assert conclusion.label_type == "changed"
    assert conclusion.chapter_id == chain["chapters"][0].id


def test_ac_120_first_pass_with_plain_fence(client: TestClient, db: Session, provider):
    """无语言标记的围栏同样能读出来。"""
    chain = H.build_chain(db)
    function_id = chain["structure"]["function"].id
    headers = H.login(client, chain["admin"])
    provider.queue = [
        _fenced_plain({"conclusions": [H.conclusion_payload(target_id=function_id)]})
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

    assert response.status_code == 201, response.text
    assert response.json()["stats"]["conclusion_count"] == 1


def test_ac_120_first_pass_with_leading_explanation(
    client: TestClient, db: Session, provider
):
    """前面带一句说明文字（平衡括号兜底）也能读出来。"""
    chain = H.build_chain(db)
    function_id = chain["structure"]["function"].id
    headers = H.login(client, chain["admin"])
    provider.queue = [
        "好的，分析结果如下：\n"
        + json.dumps(
            {"conclusions": [H.conclusion_payload(target_id=function_id)]},
            ensure_ascii=False,
        )
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

    assert response.status_code == 201, response.text
    assert response.json()["stats"]["conclusion_count"] == 1


def test_ac_120_first_pass_discards_still_work(client: TestClient, db: Session, provider):
    """判定逻辑零改动：`new` 标签照样被丢弃（容错只放宽「怎么读」）。"""
    chain = H.build_chain(db)
    function_id = chain["structure"]["function"].id
    headers = H.login(client, chain["admin"])
    provider.queue = [
        _fenced(
            {
                "conclusions": [
                    H.conclusion_payload(target_id=function_id, label_type="new")
                ]
            }
        )
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

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["stats"]["dropped_new_count"] == 1
    assert body["stats"]["discarded"][0]["code"] == "INCREMENTAL_LABEL_NEW_DROPPED"
    assert (
        db.scalar(
            select(IncrementalConclusion).where(
                IncrementalConclusion.analysis_id == body["id"]
            )
        )
        is None
    )


def test_ac_120_first_pass_broken_json_still_fails(client: TestClient, db: Session, provider):
    """坏 JSON 仍然报错——容错不做「智能修复」。"""
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
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"

    row = db.scalar(
        select(IncrementalAnalysis).where(
            IncrementalAnalysis.project_id == chain["project"].id
        )
    )
    assert row is not None
    assert row.status == "failed"
    assert row.error_code == "LLM_OUTPUT_INVALID"


# ------------------------------------------------------------ 第二遍


def _second_pass_chain(db: Session):
    """造一条「第一遍已成功、有结论可裁决」的分析。

    `with_function=False`：`build_chain` 默认会建一个「支付模块」，
    这里要自己建带功能点的结构，不能再让 helper 建一遍同名模块。
    """
    chain = H.build_chain(db, with_function=False)
    order = H.make_function(
        db, chain["project"], chain["admin"], function_name="下单", point_name="提交订单"
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


def test_ac_120_second_pass_with_json_fence(client: TestClient, db: Session, provider):
    """第二遍收到带围栏的 JSON → 裁决照常落库。"""
    chain, analysis = _second_pass_chain(db)
    headers = H.login(client, chain["admin"])
    provider.queue = [
        _fenced(
            {
                "decision": "changed",
                "confidence": 0.85,
                "rationale": "带围栏也能解析",
                "new_points": [],
            }
        )
    ]

    response = client.post(
        SECOND_PASS.format(
            project_id=chain["project"].id, analysis_id=analysis.id
        ),
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["second_pass_status"] == "succeeded"
    assert body["second_pass_stats"]["decision_count"] == 1

    decisions = client.get(
        DECISIONS.format(project_id=chain["project"].id, analysis_id=analysis.id),
        headers=headers,
    ).json()
    assert decisions["total"] == 1
    assert decisions["items"][0]["decision"] == "changed"
    assert decisions["items"][0]["target_id"] == chain["order"]["point"].id


def test_ac_120_second_pass_with_plain_fence(client: TestClient, db: Session, provider):
    """无语言标记的围栏同样能读出来。"""
    chain, analysis = _second_pass_chain(db)
    headers = H.login(client, chain["admin"])
    provider.queue = [
        _fenced_plain(
            {
                "decision": "changed",
                "confidence": 0.85,
                "rationale": "无语言标记",
                "new_points": [],
            }
        )
    ]

    response = client.post(
        SECOND_PASS.format(
            project_id=chain["project"].id, analysis_id=analysis.id
        ),
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["second_pass_stats"]["decision_count"] == 1


def test_ac_120_second_pass_broken_json_still_fails(
    client: TestClient, db: Session, provider
):
    """第二遍的坏 JSON 仍然是 LLM_OUTPUT_INVALID，判定逻辑没被放宽。"""
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
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"

    row = db.get(IncrementalAnalysis, analysis.id)
    assert row.second_pass_status == "failed"
    assert row.second_pass_error_code == "LLM_OUTPUT_INVALID"


def test_ac_120_second_pass_illegal_decision_still_rejected(
    client: TestClient, db: Session, provider
):
    """decision 非法照样被拒——围栏能被剥掉，但取值校验一点没松。"""
    chain, analysis = _second_pass_chain(db)
    headers = H.login(client, chain["admin"])
    provider.queue = [_fenced({"decision": "maybe", "confidence": 0.5})]

    response = client.post(
        SECOND_PASS.format(
            project_id=chain["project"].id, analysis_id=analysis.id
        ),
        headers=headers,
    )

    assert response.status_code == 502
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"
