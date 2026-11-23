"""关联功能基线（10-process-baseline T118 / AC-200）。

覆盖点：

- 一个场景可关联**多个**目标；
- `target_id` **列上没有外键**（`information_schema` 查不到指向
  `baseline_functions` 的约束）；
- `target_name` 由**服务端重查**写入（前端传错名字也被覆盖）；
- 关联不存在的目标 / 跨项目目标 / 已归档目标 / 重复目标 → 400
  `PROCESS_BASELINE_LINK_INVALID`，**不新增行**；
- **04 物理删除某功能后**：链接行仍在；详情返回 `target_deleted=true` 且
  `target_name` 仍是删除前的名称；**04 的删功能接口仍返回 204**；
- 关联的**空数组合法**（清空关联）——与步骤的空数组非法不同；
- 审计 `process_baseline.links.update` 含 `before_count` / `after_count`。
"""

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine

from app.models.baseline import BaselineFunction
from app.models.process_baseline import ProcessBaselineLink
from app.models.system import AuditLog

from tests.process_baselines.helpers import (
    BASELINES,
    SCENARIOS,
    create_scenario,
    login,
    make_chain,
    make_feature_point,
    make_function,
)


def _audits(db, project_id: int, action: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id, AuditLog.action == action
            )
        ).all()
    )


def _setup(db, client) -> tuple[dict, dict, int]:
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]
    return chain, headers, scenario_id


def _put_links(client, chain: dict, headers: dict, scenario_id: int, links: list[dict]):
    return client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/links",
        json={"links": links},
        headers=headers,
    )


# ------------------------------------------------------------- 成功路径


def test_ac_200_scenario_can_link_multiple_targets(db, client):
    """一个场景可关联**多个**目标（功能 + 功能点）。"""
    chain, headers, scenario_id = _setup(db, client)
    function = make_function(db, chain["project"], chain["user"])
    point = make_feature_point(db, chain["project"], chain["user"], function)

    response = _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [
            {"target_type": "function", "target_id": function.id},
            {"target_type": "feature_point", "target_id": point.id},
        ],
    )

    assert response.status_code == 200, response.text
    links = response.json()["links"]
    assert len(links) == 2
    assert {link["target_type"] for link in links} == {"function", "feature_point"}
    assert all(link["target_deleted"] is False for link in links)
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 2


def test_ac_200_target_id_column_has_no_foreign_key(engine: Engine):
    """`target_id` **列上没有外键**——04 物理删功能不能变 500。"""
    inspector = inspect(engine)
    foreign_keys = inspector.get_foreign_keys("process_baseline_links")
    referenced = {
        fk.get("referred_table") for fk in foreign_keys if fk.get("referred_table")
    }
    assert "baseline_functions" not in referenced
    assert "baseline_feature_points" not in referenced
    # 只剩指向自己的那一道外键
    assert referenced == {"process_baselines"}


def test_ac_200_target_name_is_requeried_on_server(db, client):
    """`target_name` 由**服务端重查**——前端传错名字也会被覆盖。"""
    chain, headers, scenario_id = _setup(db, client)
    function = make_function(
        db, chain["project"], chain["user"], name="用户扫码登录"
    )

    response = _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [
            {
                "target_type": "function",
                "target_id": function.id,
                "target_name": "前端乱传的名字",
            }
        ],
    )

    assert response.status_code == 200, response.text
    link = response.json()["links"][0]
    assert link["target_name"] == "用户扫码登录"

    row = db.scalar(
        select(ProcessBaselineLink).where(
            ProcessBaselineLink.baseline_id == scenario_id
        )
    )
    assert row.target_name == "用户扫码登录"


def test_ac_200_empty_links_clears_associations(db, client):
    """关联的**空数组合法**（清空关联）——与步骤的空数组非法不同。"""
    chain, headers, scenario_id = _setup(db, client)
    function = make_function(db, chain["project"], chain["user"])
    _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [{"target_type": "function", "target_id": function.id}],
    )
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 1

    response = _put_links(client, chain, headers, scenario_id, [])

    assert response.status_code == 200, response.text
    assert response.json()["links"] == []
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 0


def test_ac_200_audit_contains_before_and_after_count(db, client):
    """审计 `process_baseline.links.update` 含 `before_count` / `after_count`。"""
    chain, headers, scenario_id = _setup(db, client)
    function = make_function(db, chain["project"], chain["user"])

    response = _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [{"target_type": "function", "target_id": function.id}],
    )
    assert response.status_code == 200, response.text

    logs = _audits(db, chain["project"].id, "process_baseline.links.update")
    assert len(logs) == 1
    assert logs[0].before_data["before_count"] == 0
    assert logs[0].after_data["after_count"] == 1
    assert logs[0].actor_id == chain["user"].id


# ------------------------------------------------------------- 失败路径


def test_ac_200_unknown_target_returns_400_and_adds_no_row(db, client):
    """关联不存在的目标 → 400；**不新增行**。"""
    chain, headers, scenario_id = _setup(db, client)

    response = _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [{"target_type": "function", "target_id": 999999}],
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_LINK_INVALID"
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 0


def test_ac_200_target_of_other_project_returns_400(db, client):
    """关联**别的项目**的目标 → 400；不新增行。"""
    chain, headers, scenario_id = _setup(db, client)
    other = make_chain(db)
    foreign_function = make_function(db, other["project"], other["user"])

    response = _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [{"target_type": "function", "target_id": foreign_function.id}],
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_LINK_INVALID"
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 0


def test_ac_200_archived_target_returns_400(db, client):
    """关联**已归档**的功能 → 400；不新增行。"""
    chain, headers, scenario_id = _setup(db, client)
    archived = make_function(
        db, chain["project"], chain["user"], name="已归档的功能", status="archived"
    )

    response = _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [{"target_type": "function", "target_id": archived.id}],
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_LINK_INVALID"
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 0


def test_ac_200_duplicate_target_returns_400(db, client):
    """同一次提交里重复关联同一目标 → 400；不新增行。"""
    chain, headers, scenario_id = _setup(db, client)
    function = make_function(db, chain["project"], chain["user"])

    response = _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [
            {"target_type": "function", "target_id": function.id},
            {"target_type": "function", "target_id": function.id},
        ],
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_LINK_INVALID"
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 0


def test_ac_200_invalid_target_type_returns_400(db, client):
    """非法 `target_type` → 400。"""
    chain, headers, scenario_id = _setup(db, client)
    function = make_function(db, chain["project"], chain["user"])

    response = _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [{"target_type": "module", "target_id": function.id}],
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_LINK_INVALID"


def test_ac_200_failed_replace_writes_no_audit(db, client):
    """**失败操作不写审计**。"""
    chain, headers, scenario_id = _setup(db, client)

    response = _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [{"target_type": "function", "target_id": 999999}],
    )
    assert response.status_code == 400, response.text

    assert _audits(db, chain["project"].id, "process_baseline.links.update") == []


# ------------------------------------------------------------- 目标被删


def test_ac_200_link_survives_function_deletion(db, client):
    """04 **物理删除**功能后：链接行仍在，标 `target_deleted=true`，
    `target_name` 仍是删除前的名称快照，且 **04 的删功能接口仍返回成功**
    （不因流程基线的链接行变成 500）。

    注：spec 写「04 的删功能接口仍返回 204」，但 04 实际是
    `200 + DeleteResponse`（`app/baselines/router.py` 的 `delete_function`）——
    这里断言**真实契约**，AC-200 的要害是「不 500」。
    """
    chain, headers, scenario_id = _setup(db, client)
    function = make_function(
        db, chain["project"], chain["user"], name="用户扫码登录"
    )
    _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [{"target_type": "function", "target_id": function.id}],
    )
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 1

    # 04 的删功能接口（真实接口，不直接改库）
    delete_response = client.delete(
        BASELINES.format(project_id=chain["project"].id)
        + f"/functions/{function.id}",
        headers=headers,
    )
    assert delete_response.status_code == 200, delete_response.text

    assert db.get(BaselineFunction, function.id) is None
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 1

    detail = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    link = detail.json()["links"][0]
    assert link["target_deleted"] is True
    assert link["target_name"] == "用户扫码登录"
    assert link["target_id"] == function.id


def test_ac_200_feature_point_deletion_keeps_link(db, client):
    """功能点被删同样只标「目标已删除」，链接行不动。"""
    chain, headers, scenario_id = _setup(db, client)
    function = make_function(db, chain["project"], chain["user"])
    point = make_feature_point(
        db, chain["project"], chain["user"], function, name="展示扫码二维码"
    )
    _put_links(
        client,
        chain,
        headers,
        scenario_id,
        [{"target_type": "feature_point", "target_id": point.id}],
    )

    delete_response = client.delete(
        BASELINES.format(project_id=chain["project"].id)
        + f"/feature-points/{point.id}",
        headers=headers,
    )
    assert delete_response.status_code == 200, delete_response.text

    detail = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    ).json()
    link = detail["links"][0]
    assert link["target_deleted"] is True
    assert link["target_name"] == "展示扫码二维码"


def test_ac_200_baseline_tables_have_no_process_baseline_columns(db):
    """04 的 `baseline_functions` / `baseline_feature_points` **零改动**——
    流程基线不回写 04（单向关联）。"""
    rows = db.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name IN ('baseline_functions', 'baseline_feature_points') "
            "AND column_name LIKE '%process%'"
        )
    ).all()
    assert rows == []
