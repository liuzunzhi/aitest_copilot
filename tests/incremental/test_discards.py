"""AC-79 / AC-80：越界目标与 `new` 标签的丢弃留痕。"""

import json

from sqlalchemy import select

from app.models.incremental import IncrementalConclusion
from tests.incremental import helpers as H


def _run(client, db, provider, chain, conclusions: list[dict]) -> dict:
    headers = H.login(client, chain["admin"])
    provider.queue = [json.dumps({"conclusions": conclusions})]
    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )
    return {"response": response, "headers": headers}


def test_ac_79_out_of_baseline_discarded(client, db, provider):
    chain = H.build_chain(db)
    # 另一个项目的功能，不在本项目的比对基准内
    other_admin = H.make_user(db)
    other_project = H.make_project(db)
    H.add_member(db, other_project, other_admin, "project_admin")
    outsider = H.make_function(db, other_project, other_admin, function_name="越界功能")

    run = _run(
        client,
        db,
        provider,
        chain,
        [H.conclusion_payload(target_id=outsider["function"].id)],
    )
    response = run["response"]
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "succeeded"
    assert body["stats"]["discarded_count"] == 1
    assert len(body["stats"]["discarded"]) == 1
    item = body["stats"]["discarded"][0]
    assert item["code"] == "INCREMENTAL_TARGET_OUT_OF_BASELINE"
    assert item["chapter_id"] == chain["chapters"][0].id
    assert item["target_type"] == "function"
    assert item["target_id"] == outsider["function"].id

    assert (
        db.scalar(
            select(IncrementalConclusion).where(
                IncrementalConclusion.analysis_id == body["id"]
            )
        )
        is None
    )


def test_ac_80_new_label_discarded(client, db, provider):
    chain = H.build_chain(db)
    function_id = chain["structure"]["function"].id

    run = _run(
        client,
        db,
        provider,
        chain,
        [H.conclusion_payload(target_id=function_id, label_type="new")],
    )
    response = run["response"]
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "succeeded"
    assert body["stats"]["dropped_new_count"] == 1
    assert body["stats"]["discarded_count"] == 1
    assert body["stats"]["discarded"][0]["code"] == "INCREMENTAL_LABEL_NEW_DROPPED"

    assert (
        db.scalar(
            select(IncrementalConclusion).where(
                IncrementalConclusion.analysis_id == body["id"]
            )
        )
        is None
    )

    listing = client.get(
        H.ANALYSES.format(project_id=chain["project"].id)
        + f"/{body['id']}/conclusions",
        headers=run["headers"],
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 0
    assert all(row["label_type"] != "new" for row in listing.json()["items"])
