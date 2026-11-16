"""功能批量迁移用例：AC-65。"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.baseline import BaselineFunction
from app.models.system import AuditLog
from tests.baselines.helpers import (
    BASE,
    create_function,
    create_module,
)

MIGRATE = BASE + "/modules/{module_id}/migrate"


def test_ac_65_migrate_functions(client: TestClient, project, headers, db):
    """功能批量迁到同项目其他模块，保留来源模块记录。"""
    source = create_module(client, headers, project.id, "支付模块")
    target = create_module(client, headers, project.id, "交易模块")
    func_a = create_function(client, headers, project.id, source["id"], "下单")
    func_b = create_function(client, headers, project.id, source["id"], "支付")

    response = client.post(
        MIGRATE.format(project_id=project.id, module_id=source["id"]),
        json={
            "target_module_id": target["id"],
            "function_ids": [func_a["id"], func_b["id"]],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 2
    for item in body:
        assert item["module_id"] == target["id"]
        assert item["moved_from_module_id"] == source["id"]
        assert item["module_name"] == "交易模块"

    rows = db.scalars(
        select(BaselineFunction).where(
            BaselineFunction.id.in_([func_a["id"], func_b["id"]])
        )
    ).all()
    assert {row.module_id for row in rows} == {target["id"]}
    assert {row.moved_from_module_id for row in rows} == {source["id"]}


def test_ac_65_invalid_target(client: TestClient, project, headers):
    """目标等于当前模块 / 目标不存在 → 400 INVALID_MIGRATE_TARGET。"""
    source = create_module(client, headers, project.id, "支付模块")
    func = create_function(client, headers, project.id, source["id"], "下单")

    same = client.post(
        MIGRATE.format(project_id=project.id, module_id=source["id"]),
        json={"target_module_id": source["id"], "function_ids": [func["id"]]},
        headers=headers,
    )
    assert same.status_code == 400
    assert same.json()["code"] == "INVALID_MIGRATE_TARGET"

    missing = client.post(
        MIGRATE.format(project_id=project.id, module_id=source["id"]),
        json={"target_module_id": 99999999, "function_ids": [func["id"]]},
        headers=headers,
    )
    assert missing.status_code == 400
    assert missing.json()["code"] == "INVALID_MIGRATE_TARGET"


def test_ac_65_cross_project_target(client: TestClient, project, headers, db):
    """目标模块属于别的项目 → 400 INVALID_MIGRATE_TARGET。"""
    from tests.baselines.helpers import add_member, login, make_project, make_user

    source = create_module(client, headers, project.id, "支付模块")
    func = create_function(client, headers, project.id, source["id"], "下单")

    other = make_project(db, name="别的项目")
    other_admin = make_user(db)
    add_member(db, other, other_admin, "project_admin")
    other_headers = login(client, other_admin)
    other_module = create_module(client, other_headers, other.id, "外部模块")

    response = client.post(
        MIGRATE.format(project_id=project.id, module_id=source["id"]),
        json={
            "target_module_id": other_module["id"],
            "function_ids": [func["id"]],
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_MIGRATE_TARGET"


def test_ac_65_writes_audit(client: TestClient, project, headers, db):
    """迁移写审计 baseline.module.migrate。"""
    source = create_module(client, headers, project.id, "支付模块")
    target = create_module(client, headers, project.id, "交易模块")
    func = create_function(client, headers, project.id, source["id"], "下单")

    response = client.post(
        MIGRATE.format(project_id=project.id, module_id=source["id"]),
        json={"target_module_id": target["id"], "function_ids": [func["id"]]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    logs = db.scalars(
        select(AuditLog).where(AuditLog.action == "baseline.module.migrate")
    ).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.project_id == project.id
    assert log.target_type == "baseline_function"
    assert log.target_id == str(func["id"])
