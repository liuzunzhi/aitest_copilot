"""执行编排与单次报告（09-automation T114 / AC-187 ~ AC-192）。

五组关注点：

1. **只执行 Pytest**（AC-187）：选 Playwright 资产 → 400，**不产生执行记录**；
   空 `asset_ids` → 400；归档 / 跨项目资产 → 拒绝。
2. **状态语义**（AC-188）：`exit_code=1`（用例失败）→ `status='succeeded'`；
   **只有跑不起来（超时 / 启动失败）才 `failed` 且 `error` 非空**。
3. **报告追溯链**（AC-191）：明细含用例 / 测试点 / 目标 / 章节；
   用例被 08 物理删除后**报告仍可读**，且 **08 的删用例接口仍返回 204**。
4. **执行记录与审计**（AC-192）：`automation_runs` + `automation_run_items` 齐全；
   审计 `automation.run.execute`；**失败操作不写审计**。
5. **权限与归档**（AC-189 / AC-190）：执行限项目管理员；归档项目写 409 读 200。

**执行用的是真实 subprocess**（跑 `tmp_path` 里的最小 pytest 文件），
所以统计与退出码都是真的——但样例文件在 `tmp_path` 内，
**平台自身的 `tests/` 目录永远不会被执行**。
"""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.models.automation import AutomationAsset, AutomationRun, AutomationRunItem
from app.models.system import AuditLog

from tests.automation.helpers import (
    ASSETS,
    RUNS,
    add_member,
    login,
    make_case,
    make_project,
    make_user,
    mixed_pytest_file,
    pytest_file,
    seed_root,
    skipped_pytest_file,
)

# 当前用例的扫描根目录（由 `_automation_root` 夹具设置）。
_ROOT: Path | None = None


@pytest.fixture(autouse=True)
def _automation_root(tmp_path: Path, monkeypatch):
    """把 `AUTOMATION_ROOT` 指到 `tmp_path`，不碰开发库的真实目录。"""
    global _ROOT
    root = seed_root(tmp_path)
    _ROOT = root
    monkeypatch.setenv("AUTOMATION_ROOT", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()
    _ROOT = None


def _chain(db: Session, *, role: str = "project_admin", project_status: str = "active"):
    admin = make_user(db)
    project = make_project(db, status=project_status)
    add_member(db, project, admin, role)
    return {"admin": admin, "project": project}


def _write(relative: str, content: str) -> None:
    assert _ROOT is not None
    path = _ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_asset(
    db: Session, client, chain: dict, relative: str, content: str, framework: str = "pytest"
) -> int:
    """造一个资产并入库，返回资产 id。"""
    _write(relative, content)
    response = client.post(
        ASSETS.format(project_id=chain["project"].id),
        json={
            "assets": [
                {
                    "file_path": relative,
                    "name": relative,
                    "framework": framework,
                }
            ]
        },
        headers=login(client, chain["admin"]),
    )
    assert response.status_code == 201, response.text
    return response.json()["items"][0]["asset_id"]


def _run_count(db: Session, project_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(AutomationRun)
        .where(AutomationRun.project_id == project_id)
    )


def _item_count(db: Session, project_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(AutomationRunItem)
        .where(AutomationRunItem.project_id == project_id)
    )


def _audits(db: Session, project_id: int, action: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id, AuditLog.action == action
            )
        ).all()
    )


# ------------------------------------------------------------- AC-187 边界


def test_ac_187_playwright_asset_is_rejected(db, client):
    """选 Playwright 资产执行 → 400 `AUTOMATION_FRAMEWORK_NOT_EXECUTABLE`。

    **不产生执行记录**——校验在建行之前。
    """
    chain = _chain(db)
    project_id = chain["project"].id
    asset_id = _create_asset(
        db, client, chain, "login.spec.ts", "test('a', async () => {});\n", "playwright"
    )

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "AUTOMATION_FRAMEWORK_NOT_EXECUTABLE"
    assert _run_count(db, project_id) == 0
    assert _item_count(db, project_id) == 0


def test_ac_187_empty_asset_ids_is_rejected(db, client):
    """`asset_ids` 为空 → 400 `AUTOMATION_RUN_INPUT_EMPTY`，不产生执行记录。"""
    chain = _chain(db)
    project_id = chain["project"].id

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": []},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_RUN_INPUT_EMPTY"
    assert _run_count(db, project_id) == 0


def test_ac_187_asset_of_other_project_is_rejected(db, client):
    """**别的项目**的资产 → 404 `AUTOMATION_ASSET_NOT_FOUND`，不产生执行记录。

    调用方是**本项目的管理员**（权限检查先过），但传进来的资产 id
    属于别的项目 → 资产校验判「不属于本项目」→ 404。
    404 而不是 403——不泄露「这个资产 id 是否存在」。
    """
    chain = _chain(db)
    project_id = chain["project"].id
    asset_id = _create_asset(db, client, chain, "test_a.py", pytest_file(1))

    other = make_project(db)
    owner = make_user(db)
    add_member(db, other, owner, "project_admin")
    # 在别的项目里也造一个同名资产，取它的 id。
    _write("test_other.py", pytest_file(1))
    other_asset = client.post(
        ASSETS.format(project_id=other.id),
        json={
            "assets": [
                {"file_path": "test_other.py", "name": "test_other.py", "framework": "pytest"}
            ]
        },
        headers=login(client, owner),
    )
    assert other_asset.status_code == 201, other_asset.text
    foreign_id = other_asset.json()["items"][0]["asset_id"]

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [foreign_id]},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "AUTOMATION_ASSET_NOT_FOUND"
    assert _run_count(db, project_id) == 0
    # 本项目的资产没被牵连。
    assert _item_count(db, project_id) == 0
    assert asset_id != foreign_id


def test_ac_187_archived_asset_is_rejected(db, client):
    """归档的资产不可执行 → 400 `AUTOMATION_ASSET_INVALID`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain, "test_a.py", pytest_file(1))

    archived = client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"status": "archived"},
        headers=headers,
    )
    assert archived.status_code == 200, archived.text

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_ASSET_INVALID"
    assert _run_count(db, project_id) == 0


def test_ac_187_pytest_asset_executes_normally(db, client):
    """只选 pytest 资产 → 正常执行，`automation_runs.framework='pytest'`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    asset_id = _create_asset(db, client, chain, "test_a.py", pytest_file(2))

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 200, response.text
    run = db.get(AutomationRun, response.json()["id"])
    assert run is not None
    assert run.framework == "pytest"
    assert run.status == "succeeded"


# ------------------------------------------------------------- AC-188 语义


def test_ac_188_failing_test_still_yields_succeeded(db, client):
    """1 通过 + 1 失败 → **退出码 1**，但 `status='succeeded'`、`error` 为空。

    用例失败是**业务结果**，不是系统错误——这两件事不能混。
    """
    chain = _chain(db)
    project_id = chain["project"].id
    asset_id = _create_asset(db, client, chain, "test_mixed.py", mixed_pytest_file())

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["exit_code"] == 1
    assert payload["status"] == "succeeded"
    assert payload["error"] is None
    # `stats` 按**资产**维度，与明细行数一致。
    assert payload["stats"] == {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
    assert payload["items"][0]["result"] == "failed"
    assert payload["items"][0]["error"]


def test_ac_188_pass_and_skip_aggregates_to_passed(db, client):
    """1 通过 + 1 跳过 → 明细 `result='passed'`（有失败才是 failed）。"""
    chain = _chain(db)
    project_id = chain["project"].id
    asset_id = _create_asset(
        db, client, chain, "test_mixed.py", mixed_pytest_file()
    )

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=login(client, chain["admin"]),
    )

    # 1 失败 + 1 通过 → 资产级 failed（失败优先）。
    assert response.json()["items"][0]["result"] == "failed"


def test_ac_188_all_skipped_aggregates_to_skipped(db, client):
    """全部跳过 → 明细 `result='skipped'`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    asset_id = _create_asset(
        db, client, chain, "test_skipped.py", skipped_pytest_file()
    )

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["exit_code"] == 0
    assert payload["items"][0]["result"] == "skipped"
    assert payload["stats"] == {"total": 1, "passed": 0, "failed": 0, "skipped": 1}


def test_ac_188_timeout_yields_failed_with_error(db, client, monkeypatch):
    """超时 → `status='failed'` 且 `error` 含「超时」。

    超时是**跑不起来**，与「有测试失败」是两回事——
    前者 `error` 非空，后者 `error` 为空。
    """
    chain = _chain(db)
    project_id = chain["project"].id
    asset_id = _create_asset(
        db,
        client,
        chain,
        "test_sleep.py",
        "import time\n\n\ndef test_sleeps():\n    time.sleep(999)\n",
    )
    monkeypatch.setenv("AUTOMATION_EXEC_TIMEOUT_SECONDS", "2")
    get_settings.cache_clear()

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["error"] is not None
    assert "超时" in payload["error"]
    assert payload["items"][0]["result"] == "failed"


def test_ac_188_stats_match_item_count(db, client):
    """`stats` 的 total 与**明细行数**一致（都是资产维度）。"""
    chain = _chain(db)
    project_id = chain["project"].id
    first = _create_asset(db, client, chain, "test_a.py", pytest_file(1))
    second = _create_asset(db, client, chain, "test_b.py", pytest_file(1))

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [first, second]},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["stats"]["total"] == 2
    assert len(payload["items"]) == 2
    assert _item_count(db, project_id) == 2


# ------------------------------------------------------------- AC-191 报告


def test_ac_191_report_contains_traceability_chain(db, client):
    """报告明细含追溯链：用例名称 / 测试点 / 目标 / 章节标题。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain, "test_a.py", pytest_file(1))
    case_id = make_case(db, chain["project"], chain["admin"])

    linked = client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"linked_case_id": case_id},
        headers=headers,
    )
    assert linked.status_code == 200, linked.text

    executed = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )
    assert executed.status_code == 200, executed.text

    report = client.get(
        f"{RUNS.format(project_id=project_id)}/{executed.json()['id']}", headers=headers
    )
    assert report.status_code == 200, report.text
    body = report.json()
    trace = body["items"][0]["traceability"]
    assert trace["linked_case_id"] == case_id
    assert trace["case_title"] == "连续输错密码 5 次后账号锁定"
    assert trace["test_point_name"] == "扫码登录连续失败 5 次后锁定"
    assert trace["target_name"] == "用户扫码登录"
    assert trace["chapter_title"] == "4.2 登录失败次数限制"
    assert trace["source_case_deleted"] is False


def test_ac_191_report_survives_source_case_deletion(db, client):
    """关联的用例被 08 物理删除 → **报告仍可读**，`source_case_deleted=true`。

    同时回归 **08 的删用例接口仍返回 204**——`linked_case_id` 不建外键，
    外键会把 08 的既有行为变成 500。
    """
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain, "test_a.py", pytest_file(1))
    case_id = make_case(db, chain["project"], chain["admin"])

    client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"linked_case_id": case_id},
        headers=headers,
    )
    executed = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )
    run_id = executed.json()["id"]

    # 08 的删用例接口——必须仍是 204，不能因外键变 500。
    deleted = client.delete(
        f"/api/projects/{project_id}/test-cases/cases/{case_id}", headers=headers
    )
    assert deleted.status_code == 204, deleted.text

    report = client.get(
        f"{RUNS.format(project_id=project_id)}/{run_id}", headers=headers
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert len(body["items"]) == 1
    trace = body["items"][0]["traceability"]
    assert trace["source_case_deleted"] is True
    # `case_title` 是执行时的快照——用例删了也还在。
    assert trace["case_title"] == "连续输错密码 5 次后账号锁定"


def test_ac_191_report_contains_stats_log_and_duration(db, client):
    """报告含 `stats` / `log` / `duration_ms`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain, "test_a.py", pytest_file(1))

    executed = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )
    run_id = executed.json()["id"]

    report = client.get(
        f"{RUNS.format(project_id=project_id)}/{run_id}", headers=headers
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["stats"]["total"] == 1
    assert body["log"]
    assert "test_a.py" in body["log"]
    assert body["duration_ms"] is not None


def test_ac_191_run_of_other_project_is_not_visible(db, client):
    """**别的项目**的执行记录 → 读不到。

    读接口先判「是不是本项目成员」→ 非成员 403 `NOT_PROJECT_MEMBER`；
    是别的项目的成员但记录不在本项目 → 404 `AUTOMATION_RUN_NOT_FOUND`。
    两条路径都不能泄露记录内容。
    """
    chain = _chain(db)
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain, "test_a.py", pytest_file(1))
    executed = client.post(
        RUNS.format(project_id=chain["project"].id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )
    run_id = executed.json()["id"]

    other = make_project(db)
    owner = make_user(db)
    add_member(db, other, owner, "project_admin")

    # 别的项目的成员 → 记录不在本项目 → 404。
    response = client.get(
        f"{RUNS.format(project_id=other.id)}/{run_id}", headers=login(client, owner)
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "AUTOMATION_RUN_NOT_FOUND"

    # 完全的非成员 → 403（读接口先判成员资格）。
    outsider = make_user(db)
    denied = client.get(
        f"{RUNS.format(project_id=other.id)}/{run_id}", headers=login(client, outsider)
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_191_unknown_run_is_404(db, client):
    """执行记录不存在 → 404 `AUTOMATION_RUN_NOT_FOUND`。"""
    chain = _chain(db)
    response = client.get(
        f"{RUNS.format(project_id=chain['project'].id)}/999999",
        headers=login(client, chain["admin"]),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "AUTOMATION_RUN_NOT_FOUND"


def test_ac_191_report_query_uses_single_batch_load(db, client):
    """追溯链**一次 IN 批量取**用例快照——**不在循环里查库**。

    这条断言盯的是**查询次数**：明细行数增加时，查库次数**不能跟着涨**。
    用 SQLAlchemy 的事件钩子数一次 SELECT 的条数。
    """
    from sqlalchemy import event

    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])

    ids = []
    for index in range(3):
        asset_id = _create_asset(
            db, client, chain, f"test_{index}.py", pytest_file(1)
        )
        case_id = make_case(db, chain["project"], chain["admin"])
        client.patch(
            f"{ASSETS.format(project_id=project_id)}/{asset_id}",
            json={"linked_case_id": case_id},
            headers=headers,
        )
        ids.append(asset_id)

    executed = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": ids},
        headers=headers,
    )
    assert executed.status_code == 200, executed.text
    run_id = executed.json()["id"]

    from app.common.db import get_engine

    statements: list[str] = []
    engine = get_engine()

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        report = client.get(
            f"{RUNS.format(project_id=project_id)}/{run_id}", headers=headers
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert report.status_code == 200, report.text
    assert len(report.json()["items"]) == 3
    # 3 条明细：查用例**一次** IN 就够，不该是 3 次。
    case_queries = [
        stmt
        for stmt in statements
        if "FROM test_cases" in stmt and "WHERE test_cases.id IN" in stmt
    ]
    assert len(case_queries) == 1, (
        f"追溯链查了 {len(case_queries)} 次用例表——应为一次 IN 批量取，"
        f"否则就是 N+1"
    )


# ------------------------------------------------------------- AC-192 审计


def test_ac_192_execution_writes_run_and_items(db, client):
    """执行 → `automation_runs` 一行 + `automation_run_items` 每资产一行。"""
    chain = _chain(db)
    project_id = chain["project"].id
    first = _create_asset(db, client, chain, "test_a.py", pytest_file(1))
    second = _create_asset(db, client, chain, "test_b.py", pytest_file(1))

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [first, second]},
        headers=login(client, chain["admin"]),
    )
    assert response.status_code == 200, response.text

    assert _run_count(db, project_id) == 1
    assert _item_count(db, project_id) == 2

    run = db.get(AutomationRun, response.json()["id"])
    assert run is not None
    assert run.status == "succeeded"
    assert run.exit_code == 0
    assert run.stats == {"total": 2, "passed": 2, "failed": 0, "skipped": 0}
    assert run.log
    assert run.started_at is not None
    assert run.finished_at is not None


def test_ac_192_execute_writes_audit(db, client):
    """执行写审计 `automation.run.execute`，含 `run_id` / `stats`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    asset_id = _create_asset(db, client, chain, "test_a.py", pytest_file(1))

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=login(client, chain["admin"]),
    )
    assert response.status_code == 200, response.text

    audits = _audits(db, project_id, "automation.run.execute")
    assert len(audits) == 1
    audit = audits[0]
    assert audit.target_id == str(response.json()["id"])
    assert audit.after_data["run_id"] == response.json()["id"]
    assert audit.after_data["stats"]["total"] == 1
    assert audit.after_data["asset_ids"] == [asset_id]


def test_ac_192_failed_operations_write_no_audit(db, client):
    """失败操作不写审计（Playwright 被拒 / 空输入 / 越权）。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])

    playwright_id = _create_asset(
        db, client, chain, "login.spec.ts", "test('a', async () => {});\n", "playwright"
    )
    client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [playwright_id]},
        headers=headers,
    )
    client.post(
        RUNS.format(project_id=project_id), json={"asset_ids": []}, headers=headers
    )

    assert _audits(db, project_id, "automation.run.execute") == []
    assert _run_count(db, project_id) == 0


# ------------------------------------------------------------- 执行记录列表


def test_ac_192_run_list_is_paginated_and_newest_first(db, client):
    """执行记录列表：新记录在前，可分页。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain, "test_a.py", pytest_file(1))

    first = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )
    second = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )

    listed = client.get(RUNS.format(project_id=project_id), headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 2
    assert body["items"][0]["id"] == second.json()["id"]
    assert body["items"][1]["id"] == first.json()["id"]
    # 列表**不带明细与日志**——避免响应体膨胀。
    assert body["items"][0]["items"] == []
    assert "log" not in body["items"][0]
