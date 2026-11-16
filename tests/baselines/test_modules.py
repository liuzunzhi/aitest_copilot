"""模块级用例：AC-62 三级结构、AC-64 删除策略、AC-74 权限矩阵。"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.baselines.helpers import (
    BASE,
    build_structure,
    create_function,
    create_module,
    make_snapshot,
)

MODULES = BASE + "/modules"


def test_ac_62_module_tree(client: TestClient, project, headers):
    """建模块 → 建功能 → 建功能点，三级列表各自可见。"""
    module = create_module(client, headers, project.id, "支付模块")
    assert module["source_type"] == "manual"
    assert module["status"] == "active"

    function = create_function(client, headers, project.id, module["id"], "下单")
    assert function["module_id"] == module["id"]
    assert function["module_name"] == "支付模块"
    assert function["source_type"] == "manual"
    # 手工添加的行，来源追溯字段全空
    assert function["source_document_id"] is None
    assert function["source_version_id"] is None
    assert function["source_chapter_id"] is None
    assert function["source_analysis_id"] is None

    response = client.post(
        BASE.format(project_id=project.id)
        + f"/functions/{function['id']}/feature-points",
        json={"name": "填写收货地址"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    point = response.json()
    assert point["function_id"] == function["id"]
    assert point["source_type"] == "manual"

    modules = client.get(MODULES.format(project_id=project.id), headers=headers)
    assert modules.status_code == 200
    body = modules.json()
    assert body["total"] == 1
    assert body["items"][0]["function_count"] == 1

    functions = client.get(
        BASE.format(project_id=project.id) + "/functions", headers=headers
    )
    assert functions.status_code == 200
    assert functions.json()["total"] == 1

    points = client.get(
        BASE.format(project_id=project.id)
        + f"/functions/{function['id']}/feature-points",
        headers=headers,
    )
    assert points.status_code == 200
    assert len(points.json()) == 1


def test_ac_62_duplicate_module_name(client: TestClient, project, headers):
    """同项目模块名重复 → 409 DUPLICATE_MODULE_NAME。"""
    create_module(client, headers, project.id, "支付模块")

    response = client.post(
        MODULES.format(project_id=project.id),
        json={"name": "支付模块"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_MODULE_NAME"


def test_ac_62_duplicate_conflict_keeps_previous_rows(
    client: TestClient, project, headers
):
    """唯一索引冲突后，同一会话里先前写下的数据不能被回滚掉。"""
    create_module(client, headers, project.id, "支付模块")

    conflict = client.post(
        MODULES.format(project_id=project.id),
        json={"name": "支付模块"},
        headers=headers,
    )
    assert conflict.status_code == 409

    # 先前的模块还在
    listing = client.get(MODULES.format(project_id=project.id), headers=headers)
    assert listing.json()["total"] == 1

    # 会话仍然可用：后续写入正常
    created = create_module(client, headers, project.id, "退款模块")
    assert created["id"] > 0
    listing = client.get(MODULES.format(project_id=project.id), headers=headers)
    assert listing.json()["total"] == 2


def test_ac_64_delete_module_not_empty(client: TestClient, project, headers):
    """模块下有功能 → 409，响应带两个处理入口。"""
    module = create_module(client, headers, project.id, "支付模块")
    create_function(client, headers, project.id, module["id"], "下单")

    response = client.delete(
        MODULES.format(project_id=project.id) + f"/{module['id']}", headers=headers
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "MODULE_NOT_EMPTY"
    assert body["available_actions"] == ["migrate_functions", "delete_functions"]
    assert body["function_count"] == 1


def test_ac_64_delete_module_cascades(client: TestClient, project, headers):
    """模块下无功能 → 可删，删后模块不在列表里。"""
    module = create_module(client, headers, project.id, "支付模块")

    response = client.delete(
        MODULES.format(project_id=project.id) + f"/{module['id']}", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True

    listing = client.get(MODULES.format(project_id=project.id), headers=headers)
    assert listing.json()["total"] == 0


def test_ac_64_delete_function_warning(client: TestClient, project, headers, reviewer_headers):
    """有生效标签的功能被删 → 响应带 warning。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    labeled = client.post(
        BASE.format(project_id=project.id) + "/labels",
        json={
            "revision_id": snapshot["id"],
            "target_type": "function",
            "target_id": built["function"]["id"],
            "label_type": "changed",
        },
        headers=headers,
    )
    assert labeled.status_code == 201, labeled.text

    response = client.delete(
        BASE.format(project_id=project.id)
        + f"/functions/{built['function']['id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["warning"] is not None
    assert "标签" in body["warning"]


def test_ac_74_permission_matrix(
    client: TestClient, project, headers, member_headers, outsider_headers
):
    """读开放给全体成员，写限项目管理员。"""
    # 普通成员可读
    assert (
        client.get(
            MODULES.format(project_id=project.id), headers=member_headers
        ).status_code
        == 200
    )

    # 非成员读 → 403
    response = client.get(
        MODULES.format(project_id=project.id), headers=outsider_headers
    )
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"

    # 普通成员写 → 403
    response = client.post(
        MODULES.format(project_id=project.id),
        json={"name": "支付模块"},
        headers=member_headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_74_archived_project_is_readonly(
    client: TestClient, project, headers, db: Session
):
    """归档项目：读正常，写 409 PROJECT_ARCHIVED（先判归档再判角色）。"""
    project.status = "archived"
    db.flush()

    assert (
        client.get(
            MODULES.format(project_id=project.id), headers=headers
        ).status_code
        == 200
    )

    response = client.post(
        MODULES.format(project_id=project.id),
        json={"name": "支付模块"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"
