"""分点审核用例：AC-132 ~ AC-139。

审核流程：提交（建 revision + round）→ 逐项决策草稿（decide，可多次）
→ 通过（approve 带 items，只冻结 approved）。被驳回的节点留在结构表里，
不进快照、不进 05 的比对清单。
"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incremental.context import baseline_index
from app.models.baseline_review import BaselineReviewItem, BaselineReviewRound
from app.models.system import AuditLog
from tests.baselines.helpers import (
    BASE,
    build_structure,
    create_feature_point,
    create_function,
    create_module,
    submit_review,
)

REVIEWS = BASE + "/reviews"
REVISIONS = BASE + "/revisions"
FUNCTIONS = BASE + "/functions"
LABELS = BASE + "/labels"


def _decide(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    revision_id: int,
    items: list[dict],
    *,
    expect: int = 200,
) -> dict:
    response = client.post(
        REVIEWS.format(project_id=project_id) + f"/{revision_id}/decide",
        json={"items": items},
        headers=headers,
    )
    assert response.status_code == expect, response.text
    return response.json()


def _approve_with_items(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    revision_id: int,
    items: list[dict],
) -> dict:
    response = client.post(
        REVIEWS.format(project_id=project_id) + f"/{revision_id}/approve",
        json={"comment": "分点审核通过", "items": items},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _decision(entity_type: str, entity_id: int, decision: str, comment=None) -> dict:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "decision": decision,
        "comment": comment,
    }


def _round_of(db: Session, revision_id: int) -> BaselineReviewRound:
    review_round = db.scalar(
        select(BaselineReviewRound).where(
            BaselineReviewRound.revision_id == revision_id
        )
    )
    assert review_round is not None
    return review_round


# ---------------------------------------------------------------- AC-132


def test_ac_132_submit_creates_review_round(
    client: TestClient, db: Session, project, headers
):
    """提交审核 → 建 pending 轮次，tree 返回全量候选且都是 pending。"""
    build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)

    review_round = _round_of(db, submitted["id"])
    assert review_round.round_no == 1
    assert review_round.status == "pending"

    tree = client.get(
        REVIEWS.format(project_id=project.id) + f"/{submitted['id']}/tree",
        headers=headers,
    ).json()
    assert tree["round_id"] == review_round.id
    assert tree["round_no"] == 1
    assert tree["status"] == "pending"
    assert tree["stats"] == {
        "total": 3,
        "approved": 0,
        "rejected": 0,
        "pending": 3,
    }
    module = tree["tree"][0]
    assert module["entity_type"] == "module"
    assert module["decision"] == "pending"
    function = module["children"][0]
    assert function["decision"] == "pending"
    assert function["children"][0]["entity_type"] == "feature_point"
    assert function["children"][0]["decision"] == "pending"


def test_ac_132_decide_upserts_same_entity(
    client: TestClient, db: Session, project, headers
):
    """同轮同实体重复决策 → 覆盖旧行，不新增行。"""
    built = build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)
    review_round = _round_of(db, submitted["id"])
    function_id = built["function"]["id"]

    first = _decide(
        client,
        headers,
        project.id,
        submitted["id"],
        [_decision("function", function_id, "approved")],
    )
    assert first["updated"] == 1
    assert first["stats"]["approved"] == 1

    second = _decide(
        client,
        headers,
        project.id,
        submitted["id"],
        [_decision("function", function_id, "rejected", "与需求 3.2 不符")],
    )
    assert second["updated"] == 1
    assert second["stats"] == {
        "total": 1,
        "approved": 0,
        "rejected": 1,
        "pending": 0,
    }

    rows = db.scalars(
        select(BaselineReviewItem).where(
            BaselineReviewItem.round_id == review_round.id
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].decision == "rejected"
    assert rows[0].comment == "与需求 3.2 不符"
    assert rows[0].entity_name == "下单"


def test_ac_132_decide_validation_order(
    client: TestClient, db: Session, project, headers
):
    """非法枚举 → 400；实体不存在 → 404；驳回缺意见 → 400。"""
    built = build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)
    url = REVIEWS.format(project_id=project.id) + f"/{submitted['id']}/decide"

    def post(items: list[dict]) -> dict:
        response = client.post(url, json={"items": items}, headers=headers)
        return response

    invalid_type = post([_decision("label", 1, "approved")])
    assert invalid_type.status_code == 400
    assert invalid_type.json()["code"] == "INVALID_REVIEW_ITEM"

    invalid_decision = post(
        [_decision("function", built["function"]["id"], "pass")]
    )
    assert invalid_decision.status_code == 400
    assert invalid_decision.json()["code"] == "INVALID_REVIEW_DECISION"

    missing = post([_decision("function", 999999, "approved")])
    assert missing.status_code == 404
    assert missing.json()["code"] == "REVIEW_ITEM_NOT_FOUND"

    no_comment = post(
        [_decision("function", built["function"]["id"], "rejected", "   ")]
    )
    assert no_comment.status_code == 400
    assert no_comment.json()["code"] == "REVIEW_ITEM_COMMENT_REQUIRED"

    # 校验失败不落库
    assert _round_items(db, submitted["id"]) == []


def _round_items(db: Session, revision_id: int) -> list[BaselineReviewItem]:
    return list(
        db.scalars(
            select(BaselineReviewItem).where(
                BaselineReviewItem.revision_id == revision_id
            )
        ).all()
    )


# ---------------------------------------------------------------- AC-133


def _three_functions(
    client: TestClient, headers: dict[str, str], project_id: int
) -> dict:
    """一个模块 + 三个功能（各带一个功能点）。"""
    module = create_module(client, headers, project_id, "支付模块")
    functions = []
    for index in (1, 2, 3):
        function = create_function(
            client, headers, project_id, module["id"], f"功能{index}"
        )
        point = create_feature_point(
            client, headers, project_id, function["id"], f"功能点{index}"
        )
        functions.append({"function": function, "point": point})
    return {"module": module, "functions": functions}


def _partial_items(structure: dict) -> list[dict]:
    """通过模块与前两个功能（含功能点），驳回第三个功能。"""
    items = [_decision("module", structure["module"]["id"], "approved")]
    for entry in structure["functions"][:2]:
        items.append(_decision("function", entry["function"]["id"], "approved"))
        items.append(_decision("feature_point", entry["point"]["id"], "approved"))
    items.append(
        _decision(
            "function",
            structure["functions"][2]["function"]["id"],
            "rejected",
            "与需求不符",
        )
    )
    return items


def test_ac_133_approve_freezes_only_approved(
    client: TestClient, project, headers, reviewer_headers
):
    """只冻结 approved：快照 2 个功能，驳回的仍在结构表里。"""
    structure = _three_functions(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)
    items = _partial_items(structure)

    approved = _approve_with_items(
        client, reviewer_headers, project.id, submitted["id"], items
    )
    assert approved["status"] == "approved"
    assert approved["version_no"] == 0
    assert approved["module_count"] == 1
    assert approved["function_count"] == 2
    assert approved["feature_point_count"] == 2

    detail = client.get(
        REVISIONS.format(project_id=project.id) + f"/{submitted['id']}",
        headers=headers,
    ).json()
    module = detail["structure"][0]
    assert module["name"] == "支付模块"
    assert [item["name"] for item in module["functions"]] == ["功能1", "功能2"]
    assert [
        point["name"]
        for item in module["functions"]
        for point in item["feature_points"]
    ] == ["功能点1", "功能点2"]

    # 被驳回的功能仍在结构表里（status=active）
    functions = client.get(
        FUNCTIONS.format(project_id=project.id), headers=headers
    ).json()
    assert functions["total"] == 3
    rejected = structure["functions"][2]["function"]
    assert any(item["id"] == rejected["id"] for item in functions["items"])
    assert all(item["status"] == "active" for item in functions["items"])


def test_ac_133_all_pending_is_rejected(
    client: TestClient, project, headers, reviewer_headers
):
    """一条都没通过 → 409 EMPTY_REVIEW_APPROVAL，且不生成快照。"""
    structure = _three_functions(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)

    response = client.post(
        REVIEWS.format(project_id=project.id) + f"/{submitted['id']}/approve",
        json={
            "items": [
                _decision("module", structure["module"]["id"], "pending"),
                _decision(
                    "function",
                    structure["functions"][0]["function"]["id"],
                    "pending",
                ),
            ]
        },
        headers=reviewer_headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "EMPTY_REVIEW_APPROVAL"

    detail = client.get(
        REVISIONS.format(project_id=project.id) + f"/{submitted['id']}",
        headers=headers,
    ).json()
    assert detail["status"] == "submitted"
    assert detail["version_no"] is None
    assert detail["structure"] is None


# ---------------------------------------------------------------- AC-135


def test_ac_135_rejected_parent_excludes_children(
    client: TestClient, project, headers, reviewer_headers
):
    """驳回功能 → 它下面已通过的功能点也不进快照。"""
    built = build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)
    items = [
        _decision("module", built["module"]["id"], "approved"),
        _decision("feature_point", built["point"]["id"], "approved"),
        _decision("function", built["function"]["id"], "rejected", "功能描述有误"),
    ]
    approved = _approve_with_items(
        client, reviewer_headers, project.id, submitted["id"], items
    )
    assert approved["module_count"] == 1
    assert approved["function_count"] == 0
    assert approved["feature_point_count"] == 0

    detail = client.get(
        REVISIONS.format(project_id=project.id) + f"/{submitted['id']}",
        headers=headers,
    ).json()
    assert detail["structure"][0]["functions"] == []


def test_ac_135_rejected_module_excludes_everything(
    client: TestClient, project, headers, reviewer_headers
):
    """驳回模块 → 模块下所有功能、功能点都不进快照。"""
    built = build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)
    items = [
        _decision("module", built["module"]["id"], "rejected", "整个模块重写"),
        _decision("function", built["function"]["id"], "approved"),
        _decision("feature_point", built["point"]["id"], "approved"),
    ]
    approved = _approve_with_items(
        client, reviewer_headers, project.id, submitted["id"], items
    )
    assert approved["module_count"] == 0
    assert approved["function_count"] == 0
    assert approved["feature_point_count"] == 0

    detail = client.get(
        REVISIONS.format(project_id=project.id) + f"/{submitted['id']}",
        headers=headers,
    ).json()
    assert detail["structure"] == []


# ---------------------------------------------------------------- AC-134


def test_ac_134_rejected_stays_editable_and_history_kept(
    client: TestClient, project, headers, reviewer_headers
):
    """驳回节点仍可改（版本号 +1）；再次提交后旧决策仍可查。"""
    structure = _three_functions(client, headers, project.id)
    rejected = structure["functions"][2]["function"]
    submitted = submit_review(client, headers, project.id)
    _approve_with_items(
        client,
        reviewer_headers,
        project.id,
        submitted["id"],
        _partial_items(structure),
    )

    # 改被驳回的功能：成功且 version_no +1
    updated = client.patch(
        FUNCTIONS.format(project_id=project.id) + f"/{rejected['id']}",
        json={"name": "功能3（已修正）"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version_no"] == rejected["version_no"] + 1

    # 再次提交 → 新的 revision / 新的 pending 轮次
    resubmitted = submit_review(client, headers, project.id)
    assert resubmitted["id"] != submitted["id"]
    assert resubmitted["status"] == "submitted"

    # 旧 revision 的决策仍可查，意见完整
    old_items = client.get(
        REVIEWS.format(project_id=project.id) + f"/{submitted['id']}/items",
        headers=headers,
    ).json()
    assert old_items["status"] == "approved"
    rejected_row = next(
        item
        for item in old_items["items"]
        if item["entity_type"] == "function" and item["decision"] == "rejected"
    )
    assert rejected_row["entity_id"] == rejected["id"]
    assert rejected_row["comment"] == "与需求不符"

    # 新一轮是项目级第 2 轮：从零重新决策，不隐式继承旧轮次
    new_tree = client.get(
        REVIEWS.format(project_id=project.id) + f"/{resubmitted['id']}/tree",
        headers=headers,
    ).json()
    assert new_tree["round_no"] == 2
    assert new_tree["status"] == "pending"
    assert new_tree["stats"]["pending"] == new_tree["stats"]["total"]


# ---------------------------------------------------------------- AC-137


def test_ac_137_no_approved_round_keeps_full_index(
    client: TestClient, db: Session, project, headers
):
    """纯手工基线（从未审核通过）→ 05 清单保持全量 active。"""
    built = build_structure(client, headers, project.id)
    index = baseline_index(db, project_id=project.id)

    assert ("function", built["function"]["id"]) in index
    assert ("feature_point", built["point"]["id"]) in index
    client.get(FUNCTIONS.format(project_id=project.id), headers=headers)


def test_ac_137_baseline_index_excludes_rejected(
    client: TestClient, db: Session, project, headers, reviewer_headers
):
    """有已批准轮次后，被驳回的节点与父被驳的子节点都不进 05 清单。"""
    structure = _three_functions(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)
    _approve_with_items(
        client,
        reviewer_headers,
        project.id,
        submitted["id"],
        _partial_items(structure),
    )

    index = baseline_index(db, project_id=project.id)
    # 清单只含功能/功能点（模块只用于圈定范围）
    for entry in structure["functions"][:2]:
        assert ("function", entry["function"]["id"]) in index
        assert ("feature_point", entry["point"]["id"]) in index
    rejected = structure["functions"][2]
    assert ("function", rejected["function"]["id"]) not in index
    assert ("feature_point", rejected["point"]["id"]) not in index


# ---------------------------------------------------------------- AC-138


def test_ac_138_copy_labels_only_for_approved(
    client: TestClient, project, headers, reviewer_headers
):
    """驳回节点上的标签不复制到新快照；旧快照上的标签保持不动。"""
    module = create_module(client, headers, project.id, "支付模块")
    keep = create_function(client, headers, project.id, module["id"], "保留功能")
    drop = create_function(client, headers, project.id, module["id"], "驳回功能")

    first = submit_review(client, headers, project.id)
    first_snapshot = client.post(
        REVIEWS.format(project_id=project.id) + f"/{first['id']}/approve",
        json={},
        headers=reviewer_headers,
    )
    assert first_snapshot.status_code == 200, first_snapshot.text
    first_id = first_snapshot.json()["id"]

    for target_id, label_type in ((keep["id"], "changed"), (drop["id"], "new")):
        response = client.post(
            LABELS.format(project_id=project.id),
            json={
                "revision_id": first_id,
                "target_type": "function",
                "target_id": target_id,
                "label_type": label_type,
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text

    second = submit_review(client, headers, project.id)
    approved = _approve_with_items(
        client,
        reviewer_headers,
        project.id,
        second["id"],
        [
            _decision("module", module["id"], "approved"),
            _decision("function", keep["id"], "approved"),
            _decision("function", drop["id"], "rejected", "需求已取消"),
        ],
    )
    assert approved["label_count"] == 1

    copied = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": second["id"]},
        headers=headers,
    ).json()
    assert copied["total"] == 1
    assert copied["items"][0]["target_id"] == keep["id"]

    # 旧快照上的两条标签不受影响
    original = client.get(
        LABELS.format(project_id=project.id),
        params={"revision_id": first_id},
        headers=headers,
    ).json()
    assert original["total"] == 2


# ---------------------------------------------------------------- AC-139


def test_ac_139_permissions_and_audit(
    client: TestClient,
    db: Session,
    project,
    headers,
    member_headers,
    outsider_headers,
):
    """decide 限管理员；读 tree/items 限成员；审计落库。"""
    build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)
    url = REVIEWS.format(project_id=project.id) + f"/{submitted['id']}"

    denied = client.post(
        url + "/decide",
        json={"items": [_decision("module", 1, "approved")]},
        headers=member_headers,
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "NOT_PROJECT_ADMIN"

    for path in ("/tree", "/items"):
        forbidden = client.get(url + path, headers=outsider_headers)
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "NOT_PROJECT_MEMBER"

    # 管理员 decide → 审计
    built = client.get(
        FUNCTIONS.format(project_id=project.id), headers=headers
    ).json()["items"][0]
    _decide(
        client,
        headers,
        project.id,
        submitted["id"],
        [_decision("function", built["id"], "approved")],
    )
    audit = (
        db.query(AuditLog)
        .filter_by(action="baseline.review.decide", project_id=project.id)
        .one()
    )
    assert audit.after_data["updated"] == 1
    assert audit.after_data["stats"]["approved"] == 1


def test_ac_139_archived_project_rejects_decide(
    client: TestClient, db: Session, project, headers
):
    """归档项目 → 409 PROJECT_ARCHIVED（写接口统一前置校验）。"""
    build_structure(client, headers, project.id)
    submitted = submit_review(client, headers, project.id)
    project.status = "archived"
    db.flush()

    response = client.post(
        REVIEWS.format(project_id=project.id) + f"/{submitted['id']}/decide",
        json={"items": [_decision("function", 1, "approved")]},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"
