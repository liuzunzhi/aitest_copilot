"""两笔显式欠账的断言（10-process-baseline T121 / AC-210、AC-211）。

本期**不做**两件事，它们是**显式欠账**而不是遗漏：

- **AC-210 不做标签**：PRD 2.4.2 明写流程基线有「标签」，但标签语义依赖
  「增量分析 → 打标」，而增量分析目前只认功能基线
  （`baseline_labels.target_type` 的 CHECK 写死 `('function','feature_point')`）。
- **AC-211 不做保留策略 / 被引用即保护**：04 的保留策略是**项目级单列**
  `baseline_snapshot_max_count`，两套基线共用一列会**混算**；
  要独立就得新增项目列（那是整套功能，超出本期）。

**「确实不存在」怎么断言**：不是「我没写」这种主观判断，而是三样都查：

1. **库里查不到表**（`information_schema.tables` / inspector）；
2. **OpenAPI 的 paths / methods 里查不到路由**；
3. **响应体里没有那个字段**。

三样都要有断言——少一样，下一个人就可能以为「漏做了」。

**零真实 socket**：本文件不引入任何网络客户端，
请求全部走 `fastapi.testclient.TestClient`（进程内 ASGI）。
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app.main import app as fastapi_app
from app.models.project import Project

from tests.process_baselines.helpers import (
    BASE,
    SCENARIOS,
    create_scenario,
    login,
    make_chain,
)

REVIEWS = BASE + "/reviews"
REVISIONS = BASE + "/revisions"

# spec §13 的「后续期（明确不在本期）」登记表——欠账必须在这里有登记。
SPEC_FILE = Path(__file__).resolve().parents[2] / "specs" / "10-process-baseline" / "spec.md"

# 04 的标签表（本期零改动）
LABEL_TABLE = "baseline_labels"


# ---------------------------------------------------------------- 辅助


def _openapi_paths() -> dict:
    """OpenAPI 的 paths（路由表的唯一事实来源）。"""
    return fastapi_app.openapi()["paths"]


def _process_baseline_routes() -> list[tuple[str, str]]:
    """流程基线前缀下的 `(方法, 路径)` 列表。"""
    routes: list[tuple[str, str]] = []
    for path, methods in _openapi_paths().items():
        if "process-baselines" not in path:
            continue
        for method in methods:
            routes.append((method.upper(), path))
    return sorted(routes)


def _spec_section_13() -> str:
    """spec §13（后续期 / 欠账登记表）的原文。"""
    text_content = SPEC_FILE.read_text(encoding="utf-8")
    start = text_content.index("## 13. 后续期")
    end = text_content.index("## 附录", start)
    return text_content[start:end]


# ============================================================= AC-210


def test_ac_210_no_process_baseline_label_table(engine):
    """**库里不存在任何流程基线的标签表**（AC-210 的第一样）。

    用 `information_schema.tables` 查——不是查 ORM 元数据，
    是查**真的库**（元数据里没有不代表迁移没建表）。
    """
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() "
                "AND table_name LIKE '%process%'"
            )
        ).all()
    names = {row[0] for row in rows}
    # 流程基线的四张表在，但**没有**标签表
    assert {
        "process_baselines",
        "process_baseline_steps",
        "process_baseline_links",
        "process_baseline_revisions",
    } <= names
    assert not any("label" in name for name in names), names


def test_ac_210_baseline_labels_check_is_unchanged(engine):
    """**`baseline_labels` 表结构零改动**：`target_type` 的 CHECK 仍是
    `('function','feature_point')`（04 的，不是流程基线的）。"""
    checks = {
        item["name"]: str(item["sqltext"]).lower()
        for item in inspect(engine).get_check_constraints(LABEL_TABLE)
    }
    assert "ck_blabels_target_type" in checks
    sqltext = checks["ck_blabels_target_type"]
    assert "function" in sqltext
    assert "feature_point" in sqltext
    # 不该出现流程基线相关的层级名
    assert "scenario" not in sqltext
    assert "process_baseline" not in sqltext

    # 列集合也没多出流程基线专属的列
    columns = {item["name"] for item in inspect(engine).get_columns(LABEL_TABLE)}
    assert not any("process" in name or "scenario" in name for name in columns)


def test_ac_210_baseline_labels_rejects_scenario_target_type(engine):
    """**真写一次**：往 `baseline_labels` 塞 `target_type='scenario'` → 被 CHECK 拒。

    只查 CHECK 字符串是「看声明」；真写一次才是「看行为」。
    """
    from sqlalchemy.exc import OperationalError

    with engine.begin() as connection:
        with pytest.raises(OperationalError) as exc:
            connection.execute(
                text(
                    "INSERT INTO baseline_labels "
                    "(project_id, revision_id, target_type, target_id, label_type, "
                    "confirmed_by, status) "
                    "VALUES (0, 0, 'scenario', 1, 'changed', 0, 'active')"
                )
            )
    assert exc.value.orig.args[0] == 3819


def test_ac_210_no_label_route_in_openapi():
    """**路由表里不存在流程基线的标签接口**（AC-210 的第二样）。

    04 的标签接口在 `/baselines/labels` 下——**那不是流程基线的**。
    流程基线前缀下只有场景 / 反推 / 审核 / 快照四类路由。
    """
    routes = _process_baseline_routes()
    assert routes

    for method, path in routes:
        assert "label" not in path.lower(), (method, path)
        assert "label" not in method.lower(), (method, path)

    # 精确列出流程基线的全部路由（13 个 method / 10 条 path）
    paths = {path for _, path in routes}
    assert paths == {
        "/api/projects/{project_id}/process-baselines/scenarios",
        "/api/projects/{project_id}/process-baselines/scenarios/{scenario_id}",
        "/api/projects/{project_id}/process-baselines/scenarios/{scenario_id}/steps",
        "/api/projects/{project_id}/process-baselines/scenarios/{scenario_id}/links",
        "/api/projects/{project_id}/process-baselines/derive",
        "/api/projects/{project_id}/process-baselines/reviews/submit",
        "/api/projects/{project_id}/process-baselines/reviews/{revision_id}/approve",
        "/api/projects/{project_id}/process-baselines/reviews/{revision_id}/reject",
        "/api/projects/{project_id}/process-baselines/revisions",
        "/api/projects/{project_id}/process-baselines/revisions/{revision_id}",
    }
    assert len(routes) == 13


def test_ac_210_scenario_response_has_no_label_fields(db, client):
    """**场景的响应体里没有 `label_types` / `labels` 字段**（AC-210 的第三样）。

    列表与详情都查——列表页给的是同一套 `ScenarioOut`。
    """
    chain = make_chain(db)
    headers = login(client, chain["user"])
    scenario_id = create_scenario(client, chain, headers)["items"][0]["id"]

    detail = client.get(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert "label_types" not in body
    assert "labels" not in body
    # 场景原有的字段还在（不是把响应清空了）
    assert body["name"] == "扫码登录连续失败 5 次后锁定"
    assert body["step_count"] == 2

    listing = client.get(
        SCENARIOS.format(project_id=chain["project"].id),
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
    item = listing.json()["items"][0]
    assert "label_types" not in item
    assert "labels" not in item


def test_ac_210_spec_registers_the_debt():
    """**spec §13 已登记**「增量分析支持流程基线打标」这条欠账。

    欠账必须**有去向**——否则下一个人会以为漏做了。
    """
    section = _spec_section_13()
    assert "增量分析支持流程基线打标" in section
    assert "baseline_labels" in section


# ============================================================= AC-211


def test_ac_211_projects_table_has_no_new_column(engine):
    """**`projects` 表没有新增列**（AC-211 的第一样）。

    `baseline_snapshot_max_count` 仍是**唯一的**快照上限列——
    两套基线共用一列会混算，要独立就得新增项目列（超出本期）。
    """
    columns = {item["name"] for item in inspect(engine).get_columns("projects")}
    assert "baseline_snapshot_max_count" in columns
    assert not any("process" in name for name in columns), columns
    # 快照上限列只有这一个
    assert [name for name in columns if "max_count" in name] == [
        "baseline_snapshot_max_count"
    ]


def test_ac_211_no_retention_or_delete_route_in_openapi():
    """**路由表里不存在流程基线的快照删除 / 保留策略 / 清理候选 / 告警接口**
    （AC-211 的第二样）。

    04 有 `DELETE /baselines/revisions/{id}` 与 `PATCH /baselines/retention`——
    流程基线**一个都没有**。

    注意区分：流程基线的 `DELETE /scenarios/{id}` 是**删场景**（正常的 CRUD），
    不是删快照——这里只禁**快照**相关的删除。
    """
    routes = _process_baseline_routes()

    for method, path in routes:
        # 快照（revisions）没有删除接口
        if "revisions" in path:
            assert method != "DELETE", (method, path)
        assert "retention" not in path.lower(), (method, path)
        assert "cleanup" not in path.lower(), (method, path)
        assert "candidate" not in path.lower(), (method, path)
        assert "alert" not in path.lower(), (method, path)
        assert "warning" not in path.lower(), (method, path)
        assert "protect" not in path.lower(), (method, path)

    # 04 的保留策略与快照删除接口**只在 04 的前缀下**
    paths = _openapi_paths()
    assert "delete" in paths["/api/projects/{project_id}/baselines/revisions/{revision_id}"]
    assert "patch" in paths["/api/projects/{project_id}/baselines/retention"]


def test_ac_211_process_baseline_snapshots_are_never_deleted(db, client):
    """**流程基线的快照永久保留**——没有任何接口能删它。

    断言方式：① OpenAPI 里查不到快照的删除接口；
    ② 走一遍「驳回 → 场景解锁 → 再提交」，快照行**始终还在**。
    """
    chain = make_chain(db)
    headers = login(client, chain["user"])
    create_scenario(client, chain, headers)

    submitted = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={},
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    revision_id = submitted.json()["id"]

    # ① 没有删除快照的接口（OpenAPI 里查不到）
    for method, path in _process_baseline_routes():
        if "revisions" in path:
            assert method != "DELETE", (method, path)

    # ② 走一遍「驳回 → 场景解锁 → 再提交」，快照行**始终还在**
    rejected = client.post(
        REVIEWS.format(project_id=chain["project"].id) + f"/{revision_id}/reject",
        json={"comment": "步骤写漏了"},
        headers=headers,
    )
    assert rejected.status_code == 200, rejected.text

    detail = client.get(
        REVISIONS.format(project_id=chain["project"].id) + f"/{revision_id}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "rejected"
    # 驳回了也**保留** `draft_snapshot`——快照不被清理
    assert detail.json()["draft_snapshot"]

    # ③ 再提交一份：旧的那份**还在**（没有被覆盖，也没有被清掉）
    again = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={},
        headers=headers,
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] != revision_id

    old = client.get(
        REVISIONS.format(project_id=chain["project"].id) + f"/{revision_id}",
        headers=headers,
    )
    assert old.status_code == 200, old.text
    assert old.json()["status"] == "rejected"


def test_ac_211_projects_model_has_no_process_column():
    """**`app/models/project.py` 零改动**——模型层也没有流程基线的列。

    「表里没有」还不够，模型层也不该有——否则下一个人
    看到模型上有列就会以为「表结构漏迁移了」。
    """
    columns = {column.name for column in Project.__table__.columns}
    assert not any("process" in name for name in columns), columns
    assert "baseline_snapshot_max_count" in columns


def test_ac_211_spec_registers_the_debt():
    """**spec §13 已登记**「流程基线快照保留策略」这条欠账。"""
    section = _spec_section_13()
    assert "流程基线快照保留策略" in section
    assert "process_snapshot_max_count" in section
    # 被引用即保护 / 清理候选 / 告警同属这一笔欠账
    assert "被引用即保护" in section
