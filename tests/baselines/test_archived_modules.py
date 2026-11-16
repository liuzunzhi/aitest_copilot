"""spec §2.3 第 5 条：归档模块保留历史，但不参与新快照与检索默认展示。

默认（`status=active`）列表隐藏归档模块及其功能；`status=archived` / `all`
分别给出归档与全量视图；审核通过冻结快照时排除归档模块。
"""

from fastapi.testclient import TestClient

from tests.baselines.helpers import (
    BASE,
    build_structure,
    create_function,
    create_module,
    make_snapshot,
)

MODULES = BASE + "/modules"
FUNCTIONS = BASE + "/functions"


def _set_module_status(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    module_id: int,
    status: str,
) -> dict:
    response = client.patch(
        MODULES.format(project_id=project_id) + f"/{module_id}",
        json={"status": status},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _set_function_status(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    function_id: int,
    status: str,
) -> dict:
    response = client.patch(
        FUNCTIONS.format(project_id=project_id) + f"/{function_id}",
        json={"status": status},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_spec_23_archived_module_hidden_by_default(
    client: TestClient, project, headers
):
    """spec §2.3 第 5 条：模块默认不返回归档的，归档视图与全量视图各取所需。"""
    create_module(client, headers, project.id, "在用模块")
    archived = create_module(client, headers, project.id, "归档模块")
    _set_module_status(client, headers, project.id, archived["id"], "archived")

    default = client.get(MODULES.format(project_id=project.id), headers=headers)
    assert default.status_code == 200
    assert default.json()["total"] == 1
    assert [item["name"] for item in default.json()["items"]] == ["在用模块"]

    archived_view = client.get(
        MODULES.format(project_id=project.id), params={"status": "archived"}, headers=headers
    ).json()
    assert archived_view["total"] == 1
    assert [item["name"] for item in archived_view["items"]] == ["归档模块"]

    all_view = client.get(
        MODULES.format(project_id=project.id), params={"status": "all"}, headers=headers
    ).json()
    assert all_view["total"] == 2
    assert {item["name"] for item in all_view["items"]} == {"在用模块", "归档模块"}


def test_spec_23_functions_under_archived_module_hidden_by_default(
    client: TestClient, project, headers
):
    """spec §2.3 第 5 条：归档模块下的功能默认不返回，`all` 时才出现。"""
    active = create_module(client, headers, project.id, "在用模块")
    archived = create_module(client, headers, project.id, "归档模块")
    active_function = create_function(client, headers, project.id, active["id"], "在用功能")
    archived_function = create_function(
        client, headers, project.id, archived["id"], "归档模块下的功能"
    )
    # 在用模块下的归档功能：`status=archived` 应能查到
    hidden_function = create_function(
        client, headers, project.id, active["id"], "已归档功能"
    )
    _set_function_status(client, headers, project.id, hidden_function["id"], "archived")
    _set_module_status(client, headers, project.id, archived["id"], "archived")

    default = client.get(FUNCTIONS.format(project_id=project.id), headers=headers).json()
    assert default["total"] == 1
    assert [item["id"] for item in default["items"]] == [active_function["id"]]

    archived_view = client.get(
        FUNCTIONS.format(project_id=project.id),
        params={"status": "archived"},
        headers=headers,
    ).json()
    assert archived_view["total"] == 1
    assert [item["id"] for item in archived_view["items"]] == [hidden_function["id"]]

    all_view = client.get(
        FUNCTIONS.format(project_id=project.id),
        params={"status": "all"},
        headers=headers,
    ).json()
    assert all_view["total"] == 3
    assert {item["id"] for item in all_view["items"]} == {
        active_function["id"],
        archived_function["id"],
        hidden_function["id"],
    }


def test_spec_23_snapshot_excludes_archived_modules(
    client: TestClient, project, headers, reviewer_headers
):
    """spec §2.3 第 5 条：归档模块及其功能不参与新快照。"""
    build_structure(client, headers, project.id)
    to_archive = build_structure(
        client,
        headers,
        project.id,
        module_name="归档模块",
        function_name="归档功能",
        point_name="归档功能点",
    )
    _set_module_status(
        client, headers, project.id, to_archive["module"]["id"], "archived"
    )

    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)
    assert snapshot["module_count"] == 1
    assert snapshot["function_count"] == 1
    assert snapshot["feature_point_count"] == 1

    detail = client.get(
        BASE.format(project_id=project.id) + f"/revisions/{snapshot['id']}",
        headers=headers,
    ).json()
    assert [module["name"] for module in detail["structure"]] == ["支付模块"]


def test_spec_23_invalid_status_rejected(client: TestClient, project, headers):
    """spec §2.3 第 5 条：status 只认 active / archived / all，非法值 422。"""
    for path in (MODULES, FUNCTIONS):
        response = client.get(
            path.format(project_id=project.id),
            params={"status": "deleted"},
            headers=headers,
        )
        assert response.status_code == 422


def test_spec_23_archive_requires_project_admin(
    client: TestClient, project, headers, member_headers
):
    """spec §2.3 第 5 条：归档走模块 PATCH，仍限项目管理员。"""
    module = create_module(client, headers, project.id, "待归档模块")

    forbidden = client.patch(
        MODULES.format(project_id=project.id) + f"/{module['id']}",
        json={"status": "archived"},
        headers=member_headers,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "NOT_PROJECT_ADMIN"

    # 普通成员没有改成归档：默认视图里模块仍在
    default = client.get(MODULES.format(project_id=project.id), headers=headers).json()
    assert default["total"] == 1
    assert default["items"][0]["status"] == "active"
