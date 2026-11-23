"""审核流程与「提交即冻结」的版本快照（10-process-baseline T120 / AC-204、AC-205、AC-206）。

覆盖点：

**AC-204 提交即冻结 + 审核期锁定**

- 提交后 `draft_snapshot` **非空**、`structure_json` 为 **NULL**、
  `version_no` 为 **NULL**；三个计数与实际一致；
- 快照里的场景含 `steps` 与 `links`；
- 提交后改名称 / 改步骤 / 改关联 / 删场景 → **409
  `PROCESS_BASELINE_IN_REVIEW`**，**内容逐字节未变**；
- 已有审核中快照时再提交 → 409 `PROCESS_BASELINE_IN_REVIEW`，**不新建快照**；
- 没有 active 场景时提交 → 400 `PROCESS_BASELINE_INVALID`，**不新建快照**；
- 审计 `process_baseline.review.submit` 含三个计数。

**AC-205 通过转正与版本号**

- 通过后 `status='approved'`、`version_no=0`（展示为 `v1.0`）；
- **`structure_json` 与 `draft_snapshot` 逐字节相同**（不是「内容相等」）；
- 三个计数与 `draft_snapshot` 里的 `counts` 一致；
- 再走一轮提交 → 通过 → 第二份 `version_no=1`（`v1.1`），**不覆盖**第一份；
- **两套版本号互不干扰**：功能基线发过 `v1.0` 后，流程基线**仍发 `v1.0`**；
- 通过后场景**解锁**；
- 审计 `process_baseline.review.approve` 含 `version_no` 与三个计数。

**AC-206 驳回**

- 驳回不传意见 → 400 `REVIEW_COMMENT_REQUIRED`，状态**不变**；
- 传意见 → `status='rejected'`、`version_no` 仍 **NULL**、`structure_json` 仍 **NULL**、
  `draft_snapshot` **保留**；场景**解锁**；
- 对已驳回的快照再点通过 → 409 `PROCESS_BASELINE_REVIEW_STATUS_INVALID`；
- 审计 `process_baseline.review.reject` 含 `comment`；
- **失败操作不写审计**。

**零真实 socket**：本文件不引入任何网络客户端，
请求全部走 `fastapi.testclient.TestClient`（进程内 ASGI）。
"""

import json

import pytest
from sqlalchemy import func, select

from app.common.settings import invalidate, set_setting
from app.models.process_baseline import (
    ProcessBaseline,
    ProcessBaselineLink,
    ProcessBaselineRevision,
    ProcessBaselineStep,
)
from app.models.system import AuditLog, SystemSetting

from tests.process_baselines.helpers import (
    BASE,
    BASELINES,
    SCENARIOS,
    create_scenario,
    login,
    make_chain,
    make_function,
)

REVIEWS = BASE + "/reviews"
REVISIONS = BASE + "/revisions"

# ---------------------------------------------------------------- 辅助


def _submit(client, chain: dict, headers: dict[str, str], comment: str | None = None):
    """提交审核。"""
    body = {} if comment is None else {"comment": comment}
    response = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json=body,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _revision_row(db, revision_id: int) -> ProcessBaselineRevision:
    return db.get(ProcessBaselineRevision, revision_id)


def _audits(db, project_id: int, action: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id, AuditLog.action == action
            )
        ).all()
    )


def _snapshot_of(row: ProcessBaselineRevision) -> dict:
    """把 `draft_snapshot` 原文解成 dict。"""
    return json.loads(row.draft_snapshot)


# ---------------------------------------------------------------- AC-204


def test_ac_204_submit_freezes_snapshot(db, client):
    """提交即冻结：`draft_snapshot` 非空、`structure_json`/`version_no` 为 NULL。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)

    body = _submit(client, chain, headers, comment="请审核")

    assert body["status"] == "submitted"
    assert body["version_no"] is None
    assert body["scenario_count"] == 1
    assert body["step_count"] == 2
    assert body["link_count"] == 0

    row = _revision_row(db, body["id"])
    assert row.draft_snapshot is not None and row.draft_snapshot != ""
    assert row.structure_json is None
    assert row.version_no is None
    assert row.status == "submitted"
    assert row.scenario_count == 1
    assert row.step_count == 2
    assert row.link_count == 0


def test_ac_204_snapshot_contains_steps_and_links(db, client):
    """快照里的场景含 `steps` 与 `links`，`counts` 与三列计数一致。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    function = make_function(db, chain["project"], chain["user"])
    scenario_id = create_scenario(
        client,
        chain,
        headers,
        links=[{"target_type": "function", "target_id": function.id}],
    )["items"][0]["id"]

    body = _submit(client, chain, headers)
    row = _revision_row(db, body["id"])
    snapshot = _snapshot_of(row)

    assert snapshot["counts"] == {"scenarios": 1, "steps": 2, "links": 1}
    assert snapshot["counts"]["scenarios"] == row.scenario_count
    assert snapshot["counts"]["steps"] == row.step_count
    assert snapshot["counts"]["links"] == row.link_count

    item = snapshot["scenarios"][0]
    assert item["id"] == scenario_id
    assert item["name"] == "扫码登录连续失败 5 次后锁定"
    assert item["source_type"] == "manual"
    assert item["status"] == "active"
    assert [step["step_no"] for step in item["steps"]] == [1, 2]
    assert item["steps"][0]["action"] == "打开登录页并选择「扫码登录」"
    assert item["links"] == [
        {
            "target_type": "function",
            "target_id": function.id,
            "target_name": "用户扫码登录",
        }
    ]


def test_ac_204_archived_scenario_not_in_snapshot(db, client):
    """**归档场景不参与快照**：计数不含它，步骤与关联计数也不含。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    function = make_function(db, chain["project"], chain["user"])

    active_id = create_scenario(
        client, chain, headers, name="在用场景"
    )["items"][0]["id"]
    archived_id = create_scenario(
        client,
        chain,
        headers,
        name="归档场景",
        links=[{"target_type": "function", "target_id": function.id}],
    )["items"][0]["id"]

    # 把归档场景连同步骤、关联一起归档
    archived = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{archived_id}",
        json={"status": "archived"},
        headers=headers,
    )
    assert archived.status_code == 200, archived.text

    body = _submit(client, chain, headers)
    row = _revision_row(db, body["id"])
    snapshot = _snapshot_of(row)

    assert snapshot["counts"] == {"scenarios": 1, "steps": 2, "links": 0}
    assert row.scenario_count == 1
    assert row.step_count == 2
    assert row.link_count == 0

    ids = [item["id"] for item in snapshot["scenarios"]]
    assert ids == [active_id]
    assert archived_id not in ids


def test_ac_204_in_review_blocks_update_scenario(db, client):
    """提交后改名称 → 409 `PROCESS_BASELINE_IN_REVIEW`，**内容未变**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]
    before = db.get(ProcessBaseline, scenario_id)

    _submit(client, chain, headers)

    response = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        json={"name": "改名之后的名字"},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_IN_REVIEW"

    after = db.get(ProcessBaseline, scenario_id)
    assert after.name == before.name
    assert after.version_no == before.version_no


def test_ac_204_in_review_blocks_replace_steps(db, client):
    """提交后改步骤 → 409，**旧步骤逐字节未变**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]
    before = list(
        db.scalars(
            select(ProcessBaselineStep)
            .where(ProcessBaselineStep.baseline_id == scenario_id)
            .order_by(ProcessBaselineStep.step_no)
        ).all()
    )

    _submit(client, chain, headers)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={"steps": [{"action": "新步骤", "expected": "新预期"}]},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_IN_REVIEW"

    after = list(
        db.scalars(
            select(ProcessBaselineStep)
            .where(ProcessBaselineStep.baseline_id == scenario_id)
            .order_by(ProcessBaselineStep.step_no)
        ).all()
    )
    assert [(row.step_no, row.action, row.expected) for row in after] == [
        (row.step_no, row.action, row.expected) for row in before
    ]


def test_ac_204_in_review_blocks_replace_links(db, client):
    """提交后改关联 → 409，**旧关联逐字节未变**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    function = make_function(db, chain["project"], chain["user"])
    scenario_id = create_scenario(
        client,
        chain,
        headers,
        links=[{"target_type": "function", "target_id": function.id}],
    )["items"][0]["id"]
    before = list(
        db.scalars(
            select(ProcessBaselineLink).where(
                ProcessBaselineLink.baseline_id == scenario_id
            )
        ).all()
    )

    _submit(client, chain, headers)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/links",
        json={"links": []},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_IN_REVIEW"

    after = list(
        db.scalars(
            select(ProcessBaselineLink).where(
                ProcessBaselineLink.baseline_id == scenario_id
            )
        ).all()
    )
    assert [(row.target_type, row.target_id, row.target_name) for row in after] == [
        (row.target_type, row.target_id, row.target_name) for row in before
    ]


def test_ac_204_in_review_blocks_delete_scenario(db, client):
    """提交后删场景 → 409，**场景仍在**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]
    _submit(client, chain, headers)

    response = client.delete(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_IN_REVIEW"
    assert db.get(ProcessBaseline, scenario_id) is not None


def test_ac_204_duplicate_submit_returns_409_and_adds_no_row(db, client):
    """已有审核中快照时再提交 → 409，**不新建快照**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    first = _submit(client, chain, headers)

    before = db.scalar(
        select(func.count())
        .select_from(ProcessBaselineRevision)
        .where(ProcessBaselineRevision.project_id == chain["project"].id)
    )

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_IN_REVIEW"

    after = db.scalar(
        select(func.count())
        .select_from(ProcessBaselineRevision)
        .where(ProcessBaselineRevision.project_id == chain["project"].id)
    )
    assert after == before == 1
    assert _revision_row(db, first["id"]).status == "submitted"


def test_ac_204_submit_without_active_scenario_returns_400(db, client):
    """没有 active 场景时提交 → 400 `PROCESS_BASELINE_INVALID`，**不新建快照**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"
    assert (
        db.scalar(select(func.count()).select_from(ProcessBaselineRevision)) == 0
    )


def test_ac_204_archived_only_project_cannot_submit(db, client):
    """只有归档场景时提交 → 400（归档场景不参与快照，等于没有可审的场景）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]

    archived = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        json={"status": "archived"},
        headers=headers,
    )
    assert archived.status_code == 200, archived.text

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"
    assert (
        db.scalar(select(func.count()).select_from(ProcessBaselineRevision)) == 0
    )


def test_ac_204_submit_writes_audit(db, client):
    """审计 `process_baseline.review.submit` 含三个计数。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)

    body = _submit(client, chain, headers, comment="请审核")

    logs = _audits(db, chain["project"].id, "process_baseline.review.submit")
    assert len(logs) == 1
    after = logs[0].after_data
    assert after["revision_id"] == body["id"]
    assert after["scenario_count"] == 1
    assert after["step_count"] == 2
    assert after["link_count"] == 0
    assert after["comment"] == "请审核"
    assert logs[0].target_type == "process_baseline_revision"
    assert logs[0].target_id == str(body["id"])


def test_ac_204_failed_submit_writes_no_audit(db, client):
    """**失败操作不写审计**（重复提交 / 没有可审的场景）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    _submit(client, chain, headers)

    client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={},
        headers=headers,
    )
    assert len(_audits(db, chain["project"].id, "process_baseline.review.submit")) == 1

    # 另一个项目：没有场景 → 400
    other = make_chain(db)
    other_headers = login(client, other["user"])
    failed = client.post(
        REVIEWS.format(project_id=other["project"].id) + "/submit",
        json={},
        headers=other_headers,
    )
    assert failed.status_code == 400, failed.text
    assert (
        _audits(db, other["project"].id, "process_baseline.review.submit") == []
    )


def test_ac_204_submit_unknown_field_returns_400(db, client):
    """多余字段 → 400（不是静默丢弃）。

    入参模型是 `extra="allow"`：多余字段要活到服务层才能被判 400
    （pydantic 默认的 `ignore` 会把它们悄悄丢掉，接口返回 200，
    用户以为提交了，其实什么都没提交）。
    """
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={"comment": "请审核", "items": [{"decision": "approved"}]},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"
    assert (
        db.scalar(select(func.count()).select_from(ProcessBaselineRevision)) == 0
    )
    assert _audits(db, chain["project"].id, "process_baseline.review.submit") == []


# ---------------------------------------------------------------- AC-205


def test_ac_205_approve_promotes_snapshot_byte_identical(db, client):
    """通过转正：`structure_json` 与 `draft_snapshot` **逐字节相同**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={"comment": "通过"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["version_no"] == 0

    row = _revision_row(db, submitted["id"])
    assert row.structure_json is not None
    # 逐字节相同——不是「内容相等」
    assert row.structure_json.encode("utf-8") == row.draft_snapshot.encode("utf-8")
    assert row.structure_json == row.draft_snapshot

    # 三个计数与 `draft_snapshot` 里的 `counts` 一致
    snapshot = _snapshot_of(row)
    assert row.scenario_count == snapshot["counts"]["scenarios"]
    assert row.step_count == snapshot["counts"]["steps"]
    assert row.link_count == snapshot["counts"]["links"]


def test_ac_205_revision_detail_returns_both_snapshots(db, client):
    """快照详情**同时给** `draft_snapshot` 与 `structure_json` 原文。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    detail = client.get(
        REVISIONS.format(project_id=chain["project"].id) + f"/{submitted['id']}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["draft_snapshot"]
    assert body["structure_json"] is None

    client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={},
        headers=headers,
    )

    detail = client.get(
        REVISIONS.format(project_id=chain["project"].id) + f"/{submitted['id']}",
        headers=headers,
    )
    body = detail.json()
    assert body["status"] == "approved"
    assert body["version_no"] == 0
    assert body["structure_json"].encode("utf-8") == body["draft_snapshot"].encode(
        "utf-8"
    )


def test_ac_205_second_snapshot_version_increments(db, client):
    """再走一轮提交 → 通过：第二份 `version_no=1`（`v1.1`），**不覆盖**第一份**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)

    first = _submit(client, chain, headers)
    client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{first['id']}/approve",
        json={},
        headers=headers,
    )

    # 通过后场景解锁 → 可以继续编辑 → 再提交一轮
    renamed = client.patch(
        SCENARIOS.format(project_id=chain["project"].id)
        + f"/{_snapshot_of(_revision_row(db, first['id']))['scenarios'][0]['id']}",
        json={"name": "改过名字的场景"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text

    second = _submit(client, chain, headers)
    approved = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{second['id']}/approve",
        json={},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["version_no"] == 1

    first_row = _revision_row(db, first["id"])
    second_row = _revision_row(db, second["id"])
    assert first_row.version_no == 0
    assert second_row.version_no == 1
    assert first_row.id != second_row.id
    # 第一份的内容不被第二份覆盖
    assert "扫码登录连续失败 5 次后锁定" in first_row.structure_json
    assert "改过名字的场景" in second_row.structure_json


def test_ac_205_version_sequence_is_independent_from_function_baseline(db, client):
    """**两套版本号互不干扰**：功能基线发过 v1.0 后，流程基线**仍发 v1.0**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    # 04 的功能基线：建模块 + 功能 + 功能点，走一遍「提交 → 通过」拿到 v1.0
    module = client.post(
        BASELINES.format(project_id=chain["project"].id) + "/modules",
        json={"name": "支付模块"},
        headers=headers,
    )
    assert module.status_code == 201, module.text
    function = client.post(
        BASELINES.format(project_id=chain["project"].id) + "/functions",
        json={"module_id": module.json()["id"], "name": "下单"},
        headers=headers,
    )
    assert function.status_code == 201, function.text
    point = client.post(
        BASELINES.format(project_id=chain["project"].id)
        + f"/functions/{function.json()['id']}/feature-points",
        json={"name": "填写收货地址"},
        headers=headers,
    )
    assert point.status_code == 201, point.text

    function_submitted = client.post(
        BASELINES.format(project_id=chain["project"].id) + "/reviews/submit",
        json={},
        headers=headers,
    )
    assert function_submitted.status_code == 201, function_submitted.text
    function_approved = client.post(
        BASELINES.format(project_id=chain["project"].id)
        + f"/reviews/{function_submitted.json()['id']}/approve",
        json={},
        headers=headers,
    )
    assert function_approved.status_code == 200, function_approved.text
    assert function_approved.json()["version_no"] == 0

    # 流程基线：**同一个项目**里，版本号仍从 0 开始
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)
    approved = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["version_no"] == 0


def test_ac_205_approve_unlocks_scenarios(db, client):
    """通过后场景**解锁**（可再次编辑）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]
    submitted = _submit(client, chain, headers)

    client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={},
        headers=headers,
    )

    response = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        json={"name": "通过之后改名"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "通过之后改名"


def test_ac_205_approve_writes_audit(db, client):
    """审计 `process_baseline.review.approve` 含 `version_no` 与三个计数。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={"comment": "通过"},
        headers=headers,
    )

    logs = _audits(db, chain["project"].id, "process_baseline.review.approve")
    assert len(logs) == 1
    after = logs[0].after_data
    assert after["revision_id"] == submitted["id"]
    assert after["version_no"] == 0
    assert after["scenario_count"] == 1
    assert after["step_count"] == 2
    assert after["link_count"] == 0
    assert "self_approved" in after
    assert logs[0].target_type == "process_baseline_revision"


def test_ac_205_approve_missing_revision_returns_404(db, client):
    """快照不存在 → 404 `PROCESS_BASELINE_REVISION_NOT_FOUND`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/999999/approve",
        json={},
        headers=headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_REVISION_NOT_FOUND"
    assert (
        _audits(db, chain["project"].id, "process_baseline.review.approve") == []
    )


def test_ac_205_revisions_list_filters_by_status(db, client):
    """快照列表支持状态筛选与分页（照抄 04 的口径）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)
    client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={},
        headers=headers,
    )

    def versions(status: str) -> list[int | None]:
        response = client.get(
            REVISIONS.format(project_id=chain["project"].id),
            params={"status": status},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return [item["version_no"] for item in response.json()["items"]]

    assert versions("approved") == [0]
    assert versions("submitted") == []
    assert versions("all") == [0]

    invalid = client.get(
        REVISIONS.format(project_id=chain["project"].id),
        params={"status": "draft"},
        headers=headers,
    )
    assert invalid.status_code == 422


# ---------------------------------------------------------------- AC-206


def test_ac_206_reject_without_comment_returns_400(db, client):
    """驳回不传意见 → 400 `REVIEW_COMMENT_REQUIRED`，**状态不变**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/reject",
        json={},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "REVIEW_COMMENT_REQUIRED"

    row = _revision_row(db, submitted["id"])
    assert row.status == "submitted"
    assert row.version_no is None
    assert (
        _audits(db, chain["project"].id, "process_baseline.review.reject") == []
    )


def test_ac_206_reject_with_blank_comment_returns_400(db, client):
    """意见只有空白 → 同样 400（意见必填）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/reject",
        json={"comment": "   "},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "REVIEW_COMMENT_REQUIRED"
    assert _revision_row(db, submitted["id"]).status == "submitted"


def test_ac_206_reject_keeps_version_and_snapshot(db, client):
    """驳回：`version_no` 仍 NULL、`structure_json` 仍 NULL、`draft_snapshot` 保留。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)
    draft_before = _revision_row(db, submitted["id"]).draft_snapshot

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/reject",
        json={"comment": "步骤写漏了"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "rejected"
    assert body["version_no"] is None
    assert body["review_comment"] == "步骤写漏了"

    row = _revision_row(db, submitted["id"])
    assert row.version_no is None
    assert row.structure_json is None
    assert row.draft_snapshot == draft_before
    assert row.draft_snapshot is not None and row.draft_snapshot != ""


def test_ac_206_reject_unlocks_scenarios(db, client):
    """驳回后场景**解锁**（可编辑）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]
    submitted = _submit(client, chain, headers)

    client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/reject",
        json={"comment": "步骤写漏了"},
        headers=headers,
    )

    response = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        json={"name": "驳回之后改名"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "驳回之后改名"


def test_ac_206_resubmit_after_reject_is_allowed(db, client):
    """驳回后可以重新提交（历史两份 `draft_snapshot` 都保留供追溯）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/reject",
        json={"comment": "步骤写漏了"},
        headers=headers,
    )

    again = _submit(client, chain, headers)
    assert again["status"] == "submitted"
    assert again["id"] != submitted["id"]

    rows = list(
        db.scalars(
            select(ProcessBaselineRevision)
            .where(ProcessBaselineRevision.project_id == chain["project"].id)
            .order_by(ProcessBaselineRevision.id)
        ).all()
    )
    assert len(rows) == 2
    assert [row.status for row in rows] == ["rejected", "submitted"]
    assert all(row.version_no is None for row in rows)


def test_ac_206_approve_rejected_revision_returns_409(db, client):
    """对已驳回的快照再点通过 → 409 `PROCESS_BASELINE_REVIEW_STATUS_INVALID`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/reject",
        json={"comment": "步骤写漏了"},
        headers=headers,
    )

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_REVIEW_STATUS_INVALID"
    assert _revision_row(db, submitted["id"]).status == "rejected"
    assert (
        _audits(db, chain["project"].id, "process_baseline.review.approve") == []
    )


def test_ac_206_approve_approved_revision_returns_409(db, client):
    """对已通过的快照再点通过 → 409 `PROCESS_BASELINE_REVIEW_STATUS_INVALID`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    first = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={},
        headers=headers,
    )

    assert second.status_code == 409, second.text
    assert second.json()["code"] == "PROCESS_BASELINE_REVIEW_STATUS_INVALID"
    assert _revision_row(db, submitted["id"]).version_no == 0


def test_ac_206_reject_writes_audit(db, client):
    """审计 `process_baseline.review.reject` 含 `comment`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/reject",
        json={"comment": "步骤写漏了"},
        headers=headers,
    )

    logs = _audits(db, chain["project"].id, "process_baseline.review.reject")
    assert len(logs) == 1
    assert logs[0].after_data["revision_id"] == submitted["id"]
    assert logs[0].after_data["comment"] == "步骤写漏了"
    assert logs[0].target_type == "process_baseline_revision"


# ---------------------------------------------------------------- 自审开关


@pytest.fixture(autouse=True)
def _restore_self_approval_cache():
    """自审开关的**进程级缓存**用完要失效。

    `app/common/settings.py` 的 `get_setting` 缓存 60s；
    用例里把开关改成 False 会把 False 一起缓存住，
    而外层事务回滚只还原数据库、**还原不了缓存**——
    后面的用例会读到过期的 False（表现成莫名的 403）。
    """
    yield
    invalidate("allow_baseline_self_approval")


def test_ac_209_self_approval_forbidden_when_switch_off(db, client):
    """开关关掉 → 提交者本人审核 → 403 `SELF_APPROVAL_FORBIDDEN`。

    开关是 `system_settings.allow_baseline_self_approval`（迁移 0018 播种，
    默认 True）。关掉时提交者不能审自己的提交——**双人复核**的强制口径。
    """
    set_setting(db, "allow_baseline_self_approval", False)
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={},
        headers=headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "SELF_APPROVAL_FORBIDDEN"
    # 状态没变，也没写审计
    assert _revision_row(db, submitted["id"]).status == "submitted"
    assert _audits(db, chain["project"].id, "process_baseline.review.approve") == []


def test_ac_209_self_approval_allowed_when_switch_on(db, client):
    """开关打开 → 自审放行，且审计的 `after_data` 含 `self_approved=true`。

    PRD 要求双人复核，但内部环境常常只有一个管理员账号，
    规则会变成死锁——所以开关默认 True（迁移 0018 播种）。
    """
    # 迁移 0018 播种的默认值是 True——**直接读库**，
    # 不走 `get_setting`（它有 60s 的进程级缓存，读到的可能是别的用例留下的值）
    assert db.get(SystemSetting, "allow_baseline_self_approval").value is True

    set_setting(db, "allow_baseline_self_approval", True)
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)
    submitted = _submit(client, chain, headers)

    response = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted['id']}/approve",
        json={"comment": "单人环境自审放行"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["version_no"] == 0

    # 审计里标记 `self_approved`，事后能分辨「双人复核」与「单人兜底」
    logs = _audits(db, chain["project"].id, "process_baseline.review.approve")
    assert len(logs) == 1
    assert logs[0].after_data["self_approved"] is True
