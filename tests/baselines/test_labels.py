"""标签用例：AC-66 两级打标、AC-67 清除留痕、AC-68 标签随快照。"""

from fastapi.testclient import TestClient

from tests.baselines.helpers import (
    BASE,
    build_structure,
    create_function,
    create_module,
    make_snapshot,
)

LABELS = BASE + "/labels"


def _label(client, headers, project_id, revision_id, target_type, target_id, label_type):
    response = client.post(
        LABELS.format(project_id=project_id),
        json={
            "revision_id": revision_id,
            "target_type": target_type,
            "target_id": target_id,
            "label_type": label_type,
        },
        headers=headers,
    )
    return response


def test_ac_66_two_level_labels(client: TestClient, project, headers, reviewer_headers):
    """功能级与功能点级标签各自独立，互不汇总。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    func_label = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    )
    assert func_label.status_code == 201, func_label.text

    point_label = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "feature_point",
        built["point"]["id"],
        "new",
    )
    assert point_label.status_code == 201, point_label.text

    # 功能行只显示自己的标签，不含功能点标签
    functions = client.get(
        BASE.format(project_id=project.id) + "/functions", headers=headers
    ).json()
    row = functions["items"][0]
    assert row["label_types"] == ["changed"]
    assert row["feature_point_label_count"] == 1

    # 功能点行显示自己的标签
    points = client.get(
        BASE.format(project_id=project.id)
        + f"/functions/{built['function']['id']}/feature-points",
        headers=headers,
    ).json()
    assert points[0]["label_types"] == ["new"]


def test_ac_66_duplicate_label(client: TestClient, project, headers, reviewer_headers):
    """同一实体同一快照同一类型重复打标 → 409 DUPLICATE_LABEL。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    first = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    )
    assert first.status_code == 201, first.text

    second = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    )
    assert second.status_code == 409
    assert second.json()["code"] == "DUPLICATE_LABEL"


def test_ac_66_invalid_label_type(client: TestClient, project, headers, reviewer_headers):
    """非法标签类型 → 400 INVALID_LABEL_TYPE。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    response = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "deleted",
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_LABEL_TYPE"


def test_ac_66_weak_hint(client: TestClient, project, headers, reviewer_headers):
    """功能无标签但功能点有标签 → 功能行给弱化提示计数。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    response = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "feature_point",
        built["point"]["id"],
        "affected",
    )
    assert response.status_code == 201, response.text

    functions = client.get(
        BASE.format(project_id=project.id) + "/functions", headers=headers
    ).json()
    row = functions["items"][0]
    assert row["label_types"] == []
    assert row["feature_point_label_count"] == 1


def test_ac_67_clear_reason_required(client: TestClient, project, headers, reviewer_headers):
    """清除原因必填。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)
    label = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    ).json()

    response = client.post(
        LABELS.format(project_id=project.id) + f"/{label['id']}/clear",
        json={},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "CLEAR_REASON_REQUIRED"


def test_ac_67_invalid_clear_reason(client: TestClient, project, headers, reviewer_headers):
    """清除原因必须落在 6 类枚举内。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)
    label = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    ).json()

    response = client.post(
        LABELS.format(project_id=project.id) + f"/{label['id']}/clear",
        json={"clear_reason": "just_because"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CLEAR_REASON"


def test_ac_67_other_requires_note(client: TestClient, project, headers, reviewer_headers):
    """原因为「其他」时必须填备注。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)
    label = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    ).json()

    response = client.post(
        LABELS.format(project_id=project.id) + f"/{label['id']}/clear",
        json={"clear_reason": "other"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "CLEAR_NOTE_REQUIRED"


def test_ac_67_clear_keeps_row(client: TestClient, project, headers, reviewer_headers):
    """清除后行仍在库，状态与清除痕迹齐全，还能重新打标。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)
    label = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    ).json()

    response = client.post(
        LABELS.format(project_id=project.id) + f"/{label['id']}/clear",
        json={"clear_reason": "requirement_done"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "cleared"
    assert body["cleared_by"] is not None
    assert body["cleared_at"] is not None
    assert body["clear_reason"] == "requirement_done"

    # 行还在
    cleared = client.get(
        LABELS.format(project_id=project.id),
        params={"status": "cleared", "revision_id": snapshot["id"]},
        headers=headers,
    ).json()
    assert cleared["total"] == 1
    assert cleared["items"][0]["id"] == label["id"]

    # 默认列表里看不到已清除的
    active = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": snapshot["id"]},
        headers=headers,
    ).json()
    assert active["total"] == 0

    # 再打同类型 → 新增一条生效标签，已清除行保留
    again = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] != label["id"]

    active = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": snapshot["id"]},
        headers=headers,
    ).json()
    assert active["total"] == 1


def test_ac_67_labels_status_filter(client: TestClient, project, headers, reviewer_headers):
    """`GET /labels` 默认只列生效标签；前台要看留痕时取 all。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)
    created = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    ).json()

    def statuses(status: str) -> list[str]:
        body = client.get(
            LABELS.format(project_id=project.id),
            params={"status": status},
            headers=headers,
        ).json()
        return [item["status"] for item in body["items"]]

    assert statuses("active") == ["active"]

    client.post(
        LABELS.format(project_id=project.id) + f"/{created['id']}/clear",
        json={"clear_reason": "misjudged"},
        headers=headers,
    )

    # 默认口径：清除后不再出现
    assert statuses("active") == []
    # 留痕口径：已清除的行还在
    assert statuses("cleared") == ["cleared"]
    assert statuses("all") == ["cleared"]

    invalid = client.get(
        LABELS.format(project_id=project.id),
        params={"status": "deleted"},
        headers=headers,
    )
    assert invalid.status_code == 422


def test_ac_68_label_filtered_by_revision(
    client: TestClient, project, headers, reviewer_headers
):
    """标签只对指定快照生效，列表按快照过滤。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)
    _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
        "changed",
    )

    other = make_snapshot(client, headers, project.id, reviewer_headers)

    scoped = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": snapshot["id"]},
        headers=headers,
    ).json()
    assert scoped["total"] == 1

    other_scoped = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": other["id"]},
        headers=headers,
    ).json()
    # 新快照复制了生效标签，所以这里也有 1 条
    assert other_scoped["total"] == 1
    assert other_scoped["items"][0]["revision_id"] == other["id"]


def test_ac_68_copied_on_new_snapshot(client: TestClient, project, headers, reviewer_headers):
    """生成新快照时，上一快照的生效标签被复制成新行。"""
    built = build_structure(client, headers, project.id)
    first = make_snapshot(client, headers, project.id, reviewer_headers)
    _label(
        client,
        headers,
        project.id,
        first["id"],
        "function",
        built["function"]["id"],
        "changed",
    )

    second = make_snapshot(client, headers, project.id, reviewer_headers)
    assert second["id"] != first["id"]
    assert second["label_count"] == 1

    copied = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": second["id"]},
        headers=headers,
    ).json()
    assert copied["total"] == 1
    row = copied["items"][0]
    assert row["revision_id"] == second["id"]
    assert row["target_id"] == built["function"]["id"]
    assert row["label_type"] == "changed"
    assert row["status"] == "active"


def test_ac_68_clear_old_not_affect_new(client: TestClient, project, headers, reviewer_headers):
    """旧快照上清除标签，不影响新快照里已复制的行（级联清除默认关闭）。"""
    built = build_structure(client, headers, project.id)
    first = make_snapshot(client, headers, project.id, reviewer_headers)
    label = _label(
        client,
        headers,
        project.id,
        first["id"],
        "function",
        built["function"]["id"],
        "changed",
    ).json()

    second = make_snapshot(client, headers, project.id, reviewer_headers)

    cleared = client.post(
        LABELS.format(project_id=project.id) + f"/{label['id']}/clear",
        json={"clear_reason": "misjudged"},
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text

    # 旧快照上的标签已清除
    old = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": first["id"], "status": "cleared"},
        headers=headers,
    ).json()
    assert old["total"] == 1

    # 新快照上的复制行仍然是生效的
    new = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": second["id"]},
        headers=headers,
    ).json()
    assert new["total"] == 1
    assert new["items"][0]["status"] == "active"


def test_ac_68_cleared_label_not_copied(
    client: TestClient, project, headers, reviewer_headers
):
    """已清除的标签不随快照复制。"""
    built = build_structure(client, headers, project.id)
    first = make_snapshot(client, headers, project.id, reviewer_headers)
    label = _label(
        client,
        headers,
        project.id,
        first["id"],
        "function",
        built["function"]["id"],
        "changed",
    ).json()

    client.post(
        LABELS.format(project_id=project.id) + f"/{label['id']}/clear",
        json={"clear_reason": "misjudged"},
        headers=headers,
    )

    second = make_snapshot(client, headers, project.id, reviewer_headers)
    assert second["label_count"] == 0
    copied = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": second["id"]},
        headers=headers,
    ).json()
    assert copied["total"] == 0


def test_ac_66_label_needs_snapshot(client: TestClient, project, headers):
    """还没有任何基线版本时打标 → 400 REVIEW_NOT_FOUND。"""
    module = create_module(client, headers, project.id, "支付模块")
    function = create_function(client, headers, project.id, module["id"], "下单")

    response = _label(
        client, headers, project.id, None, "function", function["id"], "changed"
    )
    assert response.status_code == 404
    assert response.json()["code"] == "REVIEW_NOT_FOUND"
