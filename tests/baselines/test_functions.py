"""功能与功能点用例：AC-62 结构、AC-63 追溯字段只读、AC-73 检索。"""

from fastapi.testclient import TestClient

from tests.baselines.helpers import (
    BASE,
    create_feature_point,
    create_function,
    create_module,
)

FUNCTIONS = BASE + "/functions"


def test_ac_62_function_crud(client: TestClient, project, headers):
    """功能 / 功能点的增删改查。"""
    module = create_module(client, headers, project.id, "支付模块")
    function = create_function(client, headers, project.id, module["id"], "下单")
    assert function["version_no"] == 1

    # 改内容 → version_no +1
    response = client.patch(
        FUNCTIONS.format(project_id=project.id) + f"/{function['id']}",
        json={"name": "提交订单"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "提交订单"
    assert body["version_no"] == 2

    # 建功能点
    point = create_feature_point(
        client, headers, project.id, function["id"], "填写收货地址"
    )
    assert point["function_id"] == function["id"]

    # 改功能点
    response = client.patch(
        BASE.format(project_id=project.id)
        + f"/feature-points/{point['id']}",
        json={"name": "填写地址"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "填写地址"

    # 删功能点
    response = client.delete(
        BASE.format(project_id=project.id)
        + f"/feature-points/{point['id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True

    # 删功能（连带删功能点）
    response = client.delete(
        FUNCTIONS.format(project_id=project.id) + f"/{function['id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True

    listing = client.get(FUNCTIONS.format(project_id=project.id), headers=headers)
    assert listing.json()["total"] == 0


def test_ac_62_duplicate_function_name(client: TestClient, project, headers):
    """同模块功能名重复 → 409 DUPLICATE_FUNCTION_NAME。"""
    module = create_module(client, headers, project.id, "支付模块")
    create_function(client, headers, project.id, module["id"], "下单")

    response = client.post(
        FUNCTIONS.format(project_id=project.id),
        json={"module_id": module["id"], "name": "下单"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_FUNCTION_NAME"


def test_ac_62_duplicate_feature_point_name(client: TestClient, project, headers):
    """同功能功能点名重复 → 409 DUPLICATE_FEATURE_POINT_NAME。"""
    module = create_module(client, headers, project.id, "支付模块")
    function = create_function(client, headers, project.id, module["id"], "下单")
    create_feature_point(client, headers, project.id, function["id"], "填写收货地址")

    response = client.post(
        FUNCTIONS.format(project_id=project.id)
        + f"/{function['id']}/feature-points",
        json={"name": "填写收货地址"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_FEATURE_POINT_NAME"


def test_ac_63_trace_fields_readonly(client: TestClient, project, headers):
    """写接口传追溯字段 → 400 TRACE_FIELDS_READONLY。"""
    module = create_module(client, headers, project.id, "支付模块")
    function = create_function(client, headers, project.id, module["id"], "下单")

    response = client.patch(
        FUNCTIONS.format(project_id=project.id) + f"/{function['id']}",
        json={"name": "提交订单", "source_document_id": 123},
        headers=headers,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "TRACE_FIELDS_READONLY"
    assert body["fields"] == ["source_document_id"]

    # 新建功能时传追溯字段同样拒绝
    response = client.post(
        FUNCTIONS.format(project_id=project.id),
        json={
            "module_id": module["id"],
            "name": "退款",
            "source_chapter_title": "退款章节",
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TRACE_FIELDS_READONLY"

    # 功能点也一样
    response = client.post(
        FUNCTIONS.format(project_id=project.id)
        + f"/{function['id']}/feature-points",
        json={"name": "填写地址", "source_analysis_id": 7},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TRACE_FIELDS_READONLY"


def test_ac_63_manual_row_has_no_trace_fields(client: TestClient, project, headers):
    """手工建的行，追溯字段全空。"""
    module = create_module(client, headers, project.id, "支付模块")
    function = create_function(client, headers, project.id, module["id"], "下单")

    response = client.get(FUNCTIONS.format(project_id=project.id), headers=headers)
    row = response.json()["items"][0]
    assert row["source_type"] == "manual"
    for field in (
        "source_document_id",
        "source_version_id",
        "source_chapter_id",
        "source_chapter_title",
        "source_method",
        "source_analysis_id",
    ):
        assert row[field] is None, field


def test_ac_73_search_filters(client: TestClient, project, headers, reviewer_headers):
    """组合筛选：模块 / 来源类型 / 标签类型 / 关键词。"""
    from tests.baselines.helpers import make_snapshot

    module_a = create_module(client, headers, project.id, "支付模块")
    module_b = create_module(client, headers, project.id, "退款模块")
    func_a = create_function(client, headers, project.id, module_a["id"], "下单")
    func_b = create_function(client, headers, project.id, module_b["id"], "申请退款")
    create_function(client, headers, project.id, module_a["id"], "查询订单")

    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)
    labeled = client.post(
        BASE.format(project_id=project.id) + "/labels",
        json={
            "revision_id": snapshot["id"],
            "target_type": "function",
            "target_id": func_a["id"],
            "label_type": "changed",
        },
        headers=headers,
    )
    assert labeled.status_code == 201, labeled.text

    def query(**params) -> dict:
        response = client.get(
            FUNCTIONS.format(project_id=project.id), params=params, headers=headers
        )
        assert response.status_code == 200, response.text
        return response.json()

    assert query(module_id=module_a["id"])["total"] == 2
    assert query(source_type="manual")["total"] == 3
    assert query(label_type="changed")["total"] == 1
    assert query(keyword="退款")["total"] == 1
    assert query(module_id=module_a["id"], label_type="changed")["total"] == 1
    assert query(module_id=module_a["id"], keyword="下单")["total"] == 1
    assert query(module_id=module_b["id"], label_type="changed")["total"] == 0

    # 命中数与 total 一致
    body = query(label_type="changed")
    assert len(body["items"]) == body["total"]
    assert body["items"][0]["id"] == func_a["id"]
    assert body["items"][0]["label_types"] == ["changed"]
    assert func_b["id"] != body["items"][0]["id"]
