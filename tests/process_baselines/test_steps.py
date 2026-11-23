"""步骤整体覆盖（10-process-baseline T118 / AC-199）。

覆盖点：

- 空数组 → 400 `PROCESS_BASELINE_STEP_INVALID`；**旧步骤原样保留**；
- 101 步 → 400；旧步骤原样保留；
- 某步 `action` 空白 → 400；**整组拒**（旧步骤原样保留）；
- 成功 → `step_no` 重排为 1..n；**传入的 `step_no` 被忽略**；
- `action` / `expected` 超 1000 字被截断；
- 审计 `process_baseline.steps.update` 含 `before_count` / `after_count`；
- **失败操作不写审计**。
"""

from sqlalchemy import func, select

from app.models.process_baseline import ProcessBaselineStep
from app.models.system import AuditLog

from tests.process_baselines.helpers import (
    SCENARIOS,
    create_scenario,
    login,
    make_chain,
)


def _steps(client, chain: dict, headers: dict, scenario_id: int) -> list[dict]:
    response = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["steps"]


def _db_steps(db, scenario_id: int) -> list[tuple[int, str, str]]:
    rows = list(
        db.scalars(
            select(ProcessBaselineStep)
            .where(ProcessBaselineStep.baseline_id == scenario_id)
            .order_by(ProcessBaselineStep.step_no)
        ).all()
    )
    return [(row.step_no, row.action, row.expected) for row in rows]


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


# ------------------------------------------------------------- 成功路径


def test_ac_199_replace_steps_renumbers_from_one(db, client):
    """成功覆盖 → `step_no` 重排为 1..n。"""
    chain, headers, scenario_id = _setup(db, client)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={
            "steps": [
                {"action": "第一步", "expected": "结果一"},
                {"action": "第二步", "expected": "结果二"},
            ]
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [step["step_no"] for step in body["steps"]] == [1, 2]
    assert [step["action"] for step in body["steps"]] == ["第一步", "第二步"]
    assert _db_steps(db, scenario_id) == [
        (1, "第一步", "结果一"),
        (2, "第二步", "结果二"),
    ]


def test_ac_199_client_step_no_is_ignored(db, client):
    """客户端传的 `step_no` 被**忽略**，服务端按数组顺序重排。"""
    chain, headers, scenario_id = _setup(db, client)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={
            "steps": [
                {"step_no": 99, "action": "第一步", "expected": "结果一"},
                {"step_no": 5, "action": "第二步", "expected": "结果二"},
            ]
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert [step["step_no"] for step in response.json()["steps"]] == [1, 2]
    assert _db_steps(db, scenario_id) == [
        (1, "第一步", "结果一"),
        (2, "第二步", "结果二"),
    ]


def test_ac_199_long_text_is_truncated(db, client):
    """`action` / `expected` 超 1000 字被截断到 1000。"""
    chain, headers, scenario_id = _setup(db, client)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={
            "steps": [
                {"action": "操" * 1200, "expected": "期" * 1500},
            ]
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    step = response.json()["steps"][0]
    assert len(step["action"]) == 1000
    assert len(step["expected"]) == 1000


def test_ac_199_audit_contains_before_and_after_count(db, client):
    """审计 `process_baseline.steps.update` 含 `before_count` / `after_count`。"""
    chain, headers, scenario_id = _setup(db, client)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={"steps": [{"action": "第一步", "expected": "结果一"}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    logs = _audits(db, chain["project"].id, "process_baseline.steps.update")
    assert len(logs) == 1
    assert logs[0].before_data["before_count"] == 2
    assert logs[0].after_data["after_count"] == 1
    assert logs[0].actor_id == chain["user"].id
    assert logs[0].target_id == str(scenario_id)


# ------------------------------------------------------------- 失败路径


def test_ac_199_empty_steps_returns_400_and_keeps_old_steps(db, client):
    """空数组 → 400；**旧步骤原样保留**（行数与内容逐字节不变）。"""
    chain, headers, scenario_id = _setup(db, client)
    before = _db_steps(db, scenario_id)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={"steps": []},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_STEP_INVALID"
    assert _db_steps(db, scenario_id) == before
    assert len(_steps(client, chain, headers, scenario_id)) == 2


def test_ac_199_too_many_steps_returns_400_and_keeps_old_steps(db, client):
    """101 步 → 400；旧步骤原样保留。"""
    chain, headers, scenario_id = _setup(db, client)
    before = _db_steps(db, scenario_id)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={"steps": [{"action": f"第 {index} 步"} for index in range(101)]},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_STEP_INVALID"
    assert _db_steps(db, scenario_id) == before


def test_ac_199_blank_action_returns_400_and_keeps_old_steps(db, client):
    """第 2 步 `action` 空白 → 400；**整组拒**（旧步骤原样保留）。"""
    chain, headers, scenario_id = _setup(db, client)
    before = _db_steps(db, scenario_id)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={
            "steps": [
                {"action": "第一步", "expected": "结果一"},
                {"action": "   ", "expected": "结果二"},
            ]
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_STEP_INVALID"
    assert _db_steps(db, scenario_id) == before


def test_ac_199_failed_replace_writes_no_audit(db, client):
    """**失败操作不写审计**。"""
    chain, headers, scenario_id = _setup(db, client)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={"steps": []},
        headers=headers,
    )
    assert response.status_code == 400, response.text

    assert _audits(db, chain["project"].id, "process_baseline.steps.update") == []


def test_ac_199_max_100_steps_is_accepted(db, client):
    """100 步（上限）→ 200。"""
    chain, headers, scenario_id = _setup(db, client)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={"steps": [{"action": f"第 {index} 步"} for index in range(100)]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["step_count"] == 100
    assert (
        db.scalar(select(func.count()).select_from(ProcessBaselineStep)) == 100
    )


def test_ac_199_replace_steps_bumps_version_no(db, client):
    """步骤是场景的组成部分——改了步骤等于改了场景 → `version_no` +1。"""
    chain, headers, scenario_id = _setup(db, client)
    before = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    ).json()["version_no"]

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={"steps": [{"action": "换了内容", "expected": "结果"}]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["version_no"] == before + 1
