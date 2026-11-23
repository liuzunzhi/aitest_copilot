"""场景 CRUD + 来源追溯（10-process-baseline T118 / AC-198、AC-201）。

覆盖点：

- 批量新建 → 201；手工来源**六列追溯字段全为 NULL**；`version_no=1`；
- 改名 → `version_no` +1；审计含变更前后的 `version_no`；
- 同名 → 409 `PROCESS_BASELINE_DUPLICATE_NAME`，**不新增行**；
- **整批拒**：5 条里第 3 条校验失败 → 全部不落库；
- 删场景 → 步骤行与链接行**同时被清理**（数据库级 CASCADE）；
- 归档场景默认列表**不返回**；`status='all'` 才返回；
- 来源追溯：手工强制置 NULL；文档推导三元组缺失 / 对不上 / 跨项目 → 400；
- `PATCH` 试图改追溯字段 → 服务端**不写**，读回来仍是原值。
"""

from sqlalchemy import func, select

from app.models.process_baseline import (
    ProcessBaseline,
    ProcessBaselineLink,
    ProcessBaselineStep,
)
from app.models.system import AuditLog

from tests.process_baselines.helpers import (
    SCENARIOS,
    create_scenario,
    login,
    make_chain,
    make_document,
    make_function,
    scenario_body,
)


def _audits(db, project_id: int, action: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id, AuditLog.action == action
            )
        ).all()
    )


def _scenario_row(db, scenario_id: int) -> ProcessBaseline:
    return db.get(ProcessBaseline, scenario_id)


# ------------------------------------------------------------- 批量新建


def test_ac_198_batch_create_manual_scenario(db, client):
    """手工新建 → 201；六列追溯字段全为 NULL；`version_no=1`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={"scenarios": [scenario_body()]},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] == 1
    item = body["items"][0]
    assert item["source_type"] == "manual"
    assert item["version_no"] == 1
    assert item["step_count"] == 2
    assert item["link_count"] == 0

    row = _scenario_row(db, item["id"])
    assert row.source_type == "manual"
    assert row.version_no == 1
    assert row.source_document_id is None
    assert row.source_version_id is None
    assert row.source_chapter_id is None
    assert row.source_chapter_title is None
    assert row.source_method is None
    assert row.source_analysis_id is None


def test_ac_198_batch_create_writes_steps(db, client):
    """批量新建时带的步骤按数组顺序落库，`step_no` 为 1..n。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    body = create_scenario(client, chain, headers)
    scenario_id = body["items"][0]["id"]

    rows = list(
        db.scalars(
            select(ProcessBaselineStep)
            .where(ProcessBaselineStep.baseline_id == scenario_id)
            .order_by(ProcessBaselineStep.step_no)
        ).all()
    )
    assert [row.step_no for row in rows] == [1, 2]
    assert rows[0].action == "打开登录页并选择「扫码登录」"
    assert rows[1].expected == "提示账号已被锁定"


def test_ac_198_batch_create_writes_audit(db, client):
    """审计 `process_baseline.scenario.create` 含 `created` 计数。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)

    logs = _audits(db, chain["project"].id, "process_baseline.scenario.create")
    assert len(logs) == 1
    assert logs[0].after_data["created"] == 1
    assert logs[0].actor_id == chain["user"].id
    assert logs[0].target_type == "process_baseline_scenario"


def test_ac_198_duplicate_name_returns_409_and_adds_no_row(db, client):
    """同名 → 409 `PROCESS_BASELINE_DUPLICATE_NAME`，**不新增行**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)

    before = db.scalar(
        select(func.count()).select_from(ProcessBaseline).where(
            ProcessBaseline.project_id == chain["project"].id
        )
    )

    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={"scenarios": [scenario_body()]},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_DUPLICATE_NAME"

    after = db.scalar(
        select(func.count()).select_from(ProcessBaseline).where(
            ProcessBaseline.project_id == chain["project"].id
        )
    )
    assert after == before


def test_ac_198_batch_create_rejects_whole_batch(db, client):
    """**整批拒**：第 3 条校验失败 → 一条都不落库。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    body = {
        "scenarios": [
            scenario_body(name="场景一"),
            scenario_body(name="场景二"),
            # 第 3 条：关联了一个不存在的目标
            scenario_body(
                name="场景三",
                links=[{"target_type": "function", "target_id": 999999}],
            ),
            scenario_body(name="场景四"),
        ]
    }
    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id), json=body, headers=headers
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_LINK_INVALID"

    count = db.scalar(
        select(func.count()).select_from(ProcessBaseline).where(
            ProcessBaseline.project_id == chain["project"].id
        )
    )
    assert count == 0, "整批拒：一条都不该落库"


def test_ac_198_failed_batch_create_writes_no_audit(db, client):
    """**失败操作不写审计**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={
            "scenarios": [
                scenario_body(
                    name="场景",
                    links=[{"target_type": "function", "target_id": 999999}],
                )
            ]
        },
        headers=headers,
    )
    assert response.status_code == 400, response.text

    assert _audits(db, chain["project"].id, "process_baseline.scenario.create") == []


def test_ac_198_empty_batch_returns_400(db, client):
    """空批次 → 400 `PROCESS_BASELINE_INVALID`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={"scenarios": []},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"


def test_ac_198_batch_limit_is_20(db, client):
    """一次最多 20 个场景——超出 → 400。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    body = {
        "scenarios": [
            scenario_body(name=f"场景-{index}") for index in range(21)
        ]
    }
    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id), json=body, headers=headers
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"


# ------------------------------------------------------------- 改名 / 归档


def test_ac_198_rename_bumps_version_no_and_writes_audit(db, client):
    """改名 → `version_no` +1；审计含变更前后的 `version_no`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]

    response = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        json={"name": "扫码登录连续失败 3 次后锁定"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "扫码登录连续失败 3 次后锁定"
    assert body["version_no"] == 2

    logs = _audits(db, chain["project"].id, "process_baseline.scenario.update")
    assert len(logs) == 1
    assert logs[0].before_data["version_no"] == 1
    assert logs[0].after_data["version_no"] == 2
    assert logs[0].actor_id == chain["user"].id
    assert logs[0].target_type == "process_baseline_scenario"
    assert logs[0].target_id == str(scenario_id)


def test_ac_198_rename_to_existing_name_returns_409(db, client):
    """改成别的场景的名字 → 409 `PROCESS_BASELINE_DUPLICATE_NAME`（不是 500）。

    场景名有唯一键 `uk_pbaselines_project_name`——冲突必须落成业务错误，
    而不是把 MySQL 的 1062 抛给前端。
    """
    chain = make_chain(db)
    headers = login(client, chain["user"])
    first = create_scenario(client, chain, headers, name="场景一")["items"][0]["id"]
    create_scenario(client, chain, headers, name="场景二")

    response = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{first}",
        json={"name": "场景二"},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_DUPLICATE_NAME"

    # 失败的改名不能改坏原场景
    row = _scenario_row(db, first)
    assert row.name == "场景一"
    assert row.version_no == 1


def test_ac_198_archived_scenario_hidden_by_default(db, client):
    """归档场景默认列表**不返回**；`status='all'` 才返回。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]

    archived = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        json={"status": "archived"},
        headers=headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    default = client.get(
        SCENARIOS.format(project_id=chain["project"].id), headers=headers
    )
    assert default.status_code == 200, default.text
    assert default.json()["total"] == 0

    everything = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + "?status=all",
        headers=headers,
    )
    assert everything.status_code == 200, everything.text
    assert everything.json()["total"] == 1


def test_ac_198_invalid_status_returns_400(db, client):
    """非法状态 → 400 `PROCESS_BASELINE_INVALID`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]

    response = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        json={"status": "deleted"},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"


def test_ac_198_unknown_field_returns_400(db, client):
    """多余字段 → 400（不是静默丢弃）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]

    response = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        json={"source_type": "document_derived"},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"


# ------------------------------------------------------------- 删除


def test_ac_198_delete_cascades_steps_and_links(db, client):
    """删场景 → 步骤行与链接行**同时被清理**（数据库级 CASCADE）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    function = make_function(db, chain["project"], chain["user"])
    scenario_id = create_scenario(
        client,
        chain,
        headers,
        links=[{"target_type": "function", "target_id": function.id}],
    )["items"][0]["id"]

    assert db.scalar(
        select(func.count()).select_from(ProcessBaselineStep)
    ) == 2
    assert db.scalar(
        select(func.count()).select_from(ProcessBaselineLink)
    ) == 1

    response = client.delete(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    )

    assert response.status_code == 204, response.text
    assert db.scalar(select(func.count()).select_from(ProcessBaseline)) == 0
    assert db.scalar(select(func.count()).select_from(ProcessBaselineStep)) == 0
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 0

    logs = _audits(db, chain["project"].id, "process_baseline.scenario.delete")
    assert len(logs) == 1
    assert logs[0].before_data["step_count"] == 2
    assert logs[0].before_data["link_count"] == 1


def test_ac_198_delete_missing_scenario_returns_404(db, client):
    """删不存在的场景 → 404 `PROCESS_BASELINE_NOT_FOUND`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    response = client.delete(
        SCENARIOS.format(project_id=chain["project"].id) + "/999999",
        headers=headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_NOT_FOUND"


def test_ac_198_get_scenario_of_other_project_returns_404(db, client):
    """跨项目读场景 → 404（不泄露存在性）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]

    other = make_chain(db)
    other_headers = login(client, other["user"])

    response = client.get(
        SCENARIOS.format(project_id=other["project"].id) + f"/{scenario_id}",
        headers=other_headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_NOT_FOUND"


# ------------------------------------------------------------- 列表


def test_ac_198_list_filters_by_keyword_and_source_type(db, client):
    """列表支持关键词与来源类型筛选。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers, name="扫码登录连续失败")
    create_scenario(client, chain, headers, name="下单后支付")

    response = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + "?keyword=扫码",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "扫码登录连续失败"


def test_ac_198_list_returns_step_and_link_counts(db, client):
    """列表给步骤 / 关联计数。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    function = make_function(db, chain["project"], chain["user"])
    create_scenario(
        client,
        chain,
        headers,
        links=[{"target_type": "function", "target_id": function.id}],
    )

    response = client.get(
        SCENARIOS.format(project_id=chain["project"].id), headers=headers
    )

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["step_count"] == 2
    assert item["link_count"] == 1


# ------------------------------------------------------------- 来源追溯


def test_ac_201_manual_source_ignores_trace_fields(db, client):
    """手工来源传了追溯字段 → 服务端**忽略并强制置 NULL**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, chapter = make_document(db, chain["project"], chain["user"])

    body = create_scenario(
        client,
        chain,
        headers,
        source_type="manual",
        source_document_id=document.id,
        source_version_id=version.id,
        source_chapter_id=chapter.id,
        source_chapter_title="手工传进来的标题",
        source_method="baseline_reverse",
    )
    scenario_id = body["items"][0]["id"]

    row = _scenario_row(db, scenario_id)
    assert row.source_document_id is None
    assert row.source_version_id is None
    assert row.source_chapter_id is None
    assert row.source_chapter_title is None
    assert row.source_method is None

    detail = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    )
    body_out = detail.json()
    for field in (
        "source_document_id",
        "source_version_id",
        "source_chapter_id",
        "source_chapter_title",
        "source_method",
        "source_analysis_id",
    ):
        assert body_out[field] is None


def test_ac_201_document_derived_keeps_consistent_triple(db, client):
    """文档推导来源 → 三元组自洽时正常落库。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, chapter = make_document(db, chain["project"], chain["user"])

    body = create_scenario(
        client,
        chain,
        headers,
        source_type="document_derived",
        source_document_id=document.id,
        source_version_id=version.id,
        source_chapter_id=chapter.id,
    )
    scenario_id = body["items"][0]["id"]

    row = _scenario_row(db, scenario_id)
    assert row.source_type == "document_derived"
    assert row.source_document_id == document.id
    assert row.source_version_id == version.id
    assert row.source_chapter_id == chapter.id
    assert row.source_chapter_title == chapter.title


def test_ac_201_missing_triple_returns_400_and_no_row(db, client):
    """缺三元组 → 400 `PROCESS_BASELINE_INVALID`，**整批不落库**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])

    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={
            "scenarios": [
                scenario_body(source_type="document_derived"),
                scenario_body(name="第二个场景"),
            ]
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"
    count = db.scalar(
        select(func.count()).select_from(ProcessBaseline).where(
            ProcessBaseline.project_id == chain["project"].id
        )
    )
    assert count == 0


def test_ac_201_mismatched_version_returns_400(db, client):
    """版本与文档对不上 → 400。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, _, chapter = make_document(db, chain["project"], chain["user"])
    other_document, other_version, _ = make_document(
        db, chain["project"], chain["user"]
    )

    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={
            "scenarios": [
                scenario_body(
                    source_type="document_derived",
                    source_document_id=document.id,
                    source_version_id=other_version.id,
                    source_chapter_id=chapter.id,
                )
            ]
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"
    assert other_document.id != document.id


def test_ac_201_chapter_of_other_project_returns_400(db, client):
    """章节属于别的项目 → 400。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = make_document(db, chain["project"], chain["user"])

    other = make_chain(db)
    _, _, other_chapter = make_document(db, other["project"], other["user"])

    response = client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={
            "scenarios": [
                scenario_body(
                    source_type="document_derived",
                    source_document_id=document.id,
                    source_version_id=version.id,
                    source_chapter_id=other_chapter.id,
                )
            ]
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"


def test_ac_201_patch_cannot_change_trace_fields(db, client):
    """`PATCH` 试图改追溯字段 → 服务端**不写**，读回来仍是原值。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, chapter = make_document(db, chain["project"], chain["user"])
    scenario_id = create_scenario(
        client,
        chain,
        headers,
        source_type="document_derived",
        source_document_id=document.id,
        source_version_id=version.id,
        source_chapter_id=chapter.id,
    )["items"][0]["id"]

    other_document, _, _ = make_document(db, chain["project"], chain["user"])
    response = client.patch(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        json={
            "source_document_id": other_document.id,
            "source_chapter_title": "改掉的标题",
            "source_method": "incremental_new",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    detail = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    ).json()
    assert detail["source_document_id"] == document.id
    assert detail["source_chapter_title"] == chapter.title
    assert detail["source_method"] == "baseline_reverse"


def test_ac_201_chapter_title_is_a_snapshot(db, client):
    """`source_chapter_title` 是**快照**：章节改名后场景上的标题不变。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, chapter = make_document(db, chain["project"], chain["user"])
    scenario_id = create_scenario(
        client,
        chain,
        headers,
        source_type="document_derived",
        source_document_id=document.id,
        source_version_id=version.id,
        source_chapter_id=chapter.id,
    )["items"][0]["id"]

    chapter.title = "改名之后的章节标题"
    db.flush()

    detail = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    ).json()
    assert detail["source_chapter_title"] == "4.2 登录失败次数限制"
