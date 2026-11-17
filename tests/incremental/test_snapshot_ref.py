"""AC-85：04 的快照引用解析器自动识别增量分析。"""

import json

from sqlalchemy import select

from app.models.baseline import BaselineRevision
from tests.incremental import helpers as H


def test_ac_85_snapshot_referenced_by_analysis(client, db, provider):
    chain = H.build_chain(db)
    headers = H.login(client, chain["admin"])
    provider.queue = [json.dumps({"conclusions": []})]

    created = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )
    assert created.status_code == 201, created.text

    response = client.delete(
        f"/api/projects/{chain['project'].id}/baselines/revisions/"
        f"{chain['revision'].id}",
        headers=headers,
    )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "SNAPSHOT_REFERENCED"
    refs = [
        ref
        for ref in body["refs"]
        if ref["source_type"] == "incremental_analysis"
    ]
    assert any(ref["target_id"] == created.json()["id"] for ref in refs)

    # 快照仍然存在
    assert (
        db.scalar(
            select(BaselineRevision).where(
                BaselineRevision.id == chain["revision"].id
            )
        )
        is not None
    )
