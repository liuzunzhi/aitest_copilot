"""评审 / 手工增删改 / 步骤覆盖 / 删生成记录（T108 / AC-167~170）。

覆盖点：

- 评审：通过 → `approved` + `reviewed_by/at`；重复评审 → 409；审计含 `self_approved`；
- 手工新增：`source_type='manual'`、`analysis_id=NULL`、快照齐全、**允许挂 pending 点**；
- `PATCH` 只允许 4 个字段，传 `status` / `test_point_id` → 400；
- 删除用例 → 步骤级联消失；
- `PUT /steps`：整体覆盖成功；空数组 / action 空 / >100 步 → 400 且**原步骤不变**；
- 删生成记录：有 approved → 409；否则连带删用例与步骤。
"""

from sqlalchemy import func, select

from app.models.system import AuditLog
from app.models.test_case import TestCase, TestCaseAnalysis, TestCaseStep

from tests.test_cases.helpers import (
    ANALYSES,
    CASES,
    add_member,
    case_response,
    login,
    make_case,
    make_chapter,
    make_point,
    make_project,
    make_user,
    seed_template,
)


def _chain(db, *, role: str = "project_admin") -> dict:
    admin = make_user(db)
    project = make_project(db)
    add_member(db, project, admin, role)
    template = seed_template(db)
    chapter = make_chapter(db, project, admin)
    point = make_point(db, project, admin, chapter=chapter)
    return {
        "admin": admin,
        "project": project,
        "template": template,
        "chapter": chapter,
        "point": point,
    }


def _create_case(client, chain: dict, headers: dict, **overrides) -> dict:
    body = {
        "test_point_id": chain["point"].id,
        "title": "手工补录的用例",
        "case_type": "functional",
        "priority": "high",
        "precondition": "账号已存在",
        "steps": [
            {"action": "输入用户名与密码", "expected": "进入首页"},
            {"action": "点击退出", "expected": "回到登录页"},
        ],
    }
    body.update(overrides)
    return client.post(
        CASES.format(project_id=chain["project"].id), json=body, headers=headers
    )


def _audits(db, project_id: int, action: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id, AuditLog.action == action
            )
        ).all()
    )


# ------------------------------------------------------------- 评审


def test_ac_167_approve_marks_case_approved(db, client):
    """评审通过 → `status='approved'`，记 `reviewed_by` / `reviewed_at`。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    created = _create_case(client, chain, headers).json()
    case_id = created["id"]

    response = client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/review",
        json={"action": "approve", "comment": "覆盖到位"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "approved"
    assert payload["reviewed_by"] == chain["admin"].id
    assert payload["reviewed_at"] is not None
    assert payload["review_comment"] == "覆盖到位"


def test_ac_167_reject_marks_case_rejected(db, client):
    """评审驳回 → `status='rejected'`。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]

    response = client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/review",
        json={"action": "reject", "comment": "预期结果写得太笼统"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"


def test_ac_167_second_review_returns_409(db, client):
    """已评审过的用例再评审 → 409 `TEST_CASE_REVIEW_STATE_INVALID`。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]
    url = f"{CASES.format(project_id=chain['project'].id)}/{case_id}/review"
    client.post(url, json={"action": "approve"}, headers=headers)

    response = client.post(url, json={"action": "reject"}, headers=headers)

    assert response.status_code == 409
    assert response.json()["code"] == "TEST_CASE_REVIEW_STATE_INVALID"


def test_ac_167_audit_contains_self_approved(db, client):
    """评审审计写 `test_case.review`，并带 `self_approved` 标记。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]

    client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/review",
        json={"action": "approve"},
        headers=headers,
    )

    audits = _audits(db, chain["project"].id, "test_case.review")
    assert len(audits) == 1
    assert audits[0].after_data["status"] == "approved"
    assert audits[0].after_data["self_approved"] is True
    assert audits[0].target_id == str(case_id)


def test_ac_167_invalid_action_returns_400(db, client):
    """非法评审动作 → 400 `TEST_CASE_INVALID`。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]

    response = client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/review",
        json={"action": "maybe"},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "TEST_CASE_INVALID"


# --------------------------------------------------------- 手工增删改


def test_ac_168_manual_case_snapshot_and_source(db, client):
    """手工新增：`source_type='manual'`、`analysis_id=NULL`、快照取自测试点。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])

    response = _create_case(client, chain, headers)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["source_type"] == "manual"
    assert payload["analysis_id"] is None
    assert payload["test_point_id"] == chain["point"].id
    assert payload["test_point_name"] == chain["point"].name
    assert payload["target_name"] == chain["point"].target_name
    assert payload["chapter_title"] == chain["chapter"].title
    assert payload["status"] == "pending"
    assert [row["step_no"] for row in payload["steps"]] == [1, 2]


def test_ac_168_manual_case_can_attach_pending_point(db, client):
    """手工用例允许挂 **pending** 测试点（人工补录不被评审状态卡死）。"""
    chain = _chain(db)
    pending = make_point(
        db, chain["project"], chain["admin"], status="pending", name="还没评审的点"
    )
    headers = login(client, chain["admin"])

    response = _create_case(client, chain, headers, test_point_id=pending.id)

    assert response.status_code == 201, response.text
    assert response.json()["test_point_id"] == pending.id
    assert response.json()["test_point_name"] == "还没评审的点"


def test_ac_168_manual_case_unknown_point_returns_400(db, client):
    """挂不存在的测试点 → 400 `TEST_CASE_POINT_NOT_FOUND`。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])

    response = _create_case(client, chain, headers, test_point_id=999_999)

    assert response.status_code == 400
    assert response.json()["code"] == "TEST_CASE_POINT_NOT_FOUND"


def test_ac_168_update_allows_only_four_fields(db, client):
    """4 个可改字段都改得动。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]

    response = client.patch(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}",
        json={
            "title": "改过的用例名",
            "case_type": "api",
            "priority": "low",
            "precondition": "改过的前置条件",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["title"] == "改过的用例名"
    assert payload["case_type"] == "api"
    assert payload["priority"] == "low"
    assert payload["precondition"] == "改过的前置条件"


def test_ac_168_update_rejects_status_and_test_point_id(db, client):
    """传 `status` / `test_point_id` → 400 `TEST_CASE_INVALID`（且不改动数据）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]
    url = f"{CASES.format(project_id=chain['project'].id)}/{case_id}"

    for payload in (
        {"status": "approved"},
        {"test_point_id": 999},
        {"title": "新名字", "status": "approved"},
    ):
        response = client.patch(url, json=payload, headers=headers)
        assert response.status_code == 400, payload
        assert response.json()["code"] == "TEST_CASE_INVALID"

    current = client.get(url, headers=headers).json()
    assert current["status"] == "pending"
    assert current["title"] == "手工补录的用例"


def test_ac_168_delete_case_removes_steps(db, client):
    """删用例 → 行被物理删除，步骤由级联清理，不留孤儿。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]

    response = client.delete(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}", headers=headers
    )

    assert response.status_code == 204, response.text
    assert (
        db.scalar(
            select(func.count()).select_from(TestCase).where(TestCase.id == case_id)
        )
        == 0
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(TestCaseStep)
            .where(TestCaseStep.case_id == case_id)
        )
        == 0
    )
    assert _audits(db, chain["project"].id, "test_case.case.delete")


# --------------------------------------------------------- 步骤覆盖


def test_ac_169_steps_are_replaced_and_renumbered(db, client):
    """3 步覆盖成 2 步 → 旧行删净，新行 `step_no` 为 1 / 2。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]

    response = client.put(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/steps",
        json={
            "steps": [
                {"action": "新第一步", "expected": "预期一"},
                {"action": "新第二步", "expected": "预期二"},
            ]
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    steps = response.json()["steps"]
    assert [row["step_no"] for row in steps] == [1, 2]
    assert [row["action"] for row in steps] == ["新第一步", "新第二步"]

    rows = db.scalars(
        select(TestCaseStep)
        .where(TestCaseStep.case_id == case_id)
        .order_by(TestCaseStep.step_no)
    ).all()
    assert len(rows) == 2


def test_ac_169_invalid_steps_keep_original(db, client):
    """空数组 / action 空 / 超过 100 步 → 400，**原步骤不变**。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]
    url = f"{CASES.format(project_id=chain['project'].id)}/{case_id}/steps"

    payloads = [
        {"steps": []},
        {"steps": [{"action": "  ", "expected": "x"}]},
        {"steps": [{"action": f"第{i}步", "expected": "x"} for i in range(101)]},
    ]
    for payload in payloads:
        response = client.put(url, json=payload, headers=headers)
        assert response.status_code == 400, payload
        assert response.json()["code"] == "TEST_CASE_STEP_INVALID"

    current = client.get(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}", headers=headers
    ).json()
    assert [row["action"] for row in current["steps"]] == [
        "输入用户名与密码",
        "点击退出",
    ]


def test_ac_169_steps_audit_records_counts(db, client):
    """步骤覆盖审计记 `before_count` / `after_count`。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers).json()["id"]

    client.put(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/steps",
        json={"steps": [{"action": "只剩一步", "expected": "x"}]},
        headers=headers,
    )

    audits = _audits(db, chain["project"].id, "test_case.steps.update")
    assert len(audits) == 1
    assert audits[0].before_data["before_count"] == 2
    assert audits[0].after_data["after_count"] == 1


# ------------------------------------------------------- 删生成记录


def _run_generation(db, client, chain: dict, headers: dict) -> int:
    """跑一次生成，返回 analysis id。"""
    response = client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_ac_170_delete_analysis_removes_cases_and_steps(db, client, provider):
    """删生成记录 → 记录、用例、步骤一起消失。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    analysis_id = _run_generation(db, client, chain, headers)
    case_id = db.scalar(
        select(TestCase.id)
        .where(TestCase.analysis_id == analysis_id)
        .limit(1)
    )
    assert case_id is not None

    response = client.delete(
        f"{ANALYSES.format(project_id=chain['project'].id)}/{analysis_id}",
        headers=headers,
    )

    assert response.status_code == 204, response.text
    assert (
        db.scalar(
            select(func.count())
            .select_from(TestCaseAnalysis)
            .where(TestCaseAnalysis.id == analysis_id)
        )
        == 0
    )
    assert (
        db.scalar(
            select(func.count()).select_from(TestCase).where(TestCase.id == case_id)
        )
        == 0
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(TestCaseStep)
            .where(TestCaseStep.case_id == case_id)
        )
        == 0
    )


def test_ac_170_delete_analysis_with_approved_case_returns_409(db, client, provider):
    """已有评审通过的用例 → 409 `TEST_CASE_ANALYSIS_HAS_APPROVED`。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    analysis_id = _run_generation(db, client, chain, headers)
    case_id = db.scalar(
        select(TestCase.id).where(TestCase.analysis_id == analysis_id).limit(1)
    )
    client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/review",
        json={"action": "approve"},
        headers=headers,
    )

    response = client.delete(
        f"{ANALYSES.format(project_id=chain['project'].id)}/{analysis_id}",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "TEST_CASE_ANALYSIS_HAS_APPROVED"
    # 记录与用例都还在
    assert (
        db.scalar(
            select(func.count())
            .select_from(TestCaseAnalysis)
            .where(TestCaseAnalysis.id == analysis_id)
        )
        == 1
    )


def test_manual_case_is_not_blocked_by_analysis_deletion(db, client):
    """手工新增的用例 `analysis_id=NULL`，不随生成记录删除而消失。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    analysis_id = _run_generation(db, client, chain, headers)
    manual_id = _create_case(client, chain, headers).json()["id"]

    client.delete(
        f"{ANALYSES.format(project_id=chain['project'].id)}/{analysis_id}",
        headers=headers,
    )

    assert (
        db.scalar(
            select(func.count()).select_from(TestCase).where(TestCase.id == manual_id)
        )
        == 1
    )


def test_member_cannot_write(db, client, provider):
    """member / guest 不能发起生成（AC-173 写侧）。"""
    chain = _chain(db)
    member = make_user(db)
    add_member(db, chain["project"], member, "member")
    headers = login(client, member)

    response = client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_generated_case_can_be_reviewed(db, client, provider):
    """生成出来的用例同样能评审通过（端到端串一次）。"""
    chain = _chain(db)
    provider.queue = [case_response(make_case())]
    headers = login(client, chain["admin"])
    analysis_id = _run_generation(db, client, chain, headers)
    case_id = db.scalar(
        select(TestCase.id).where(TestCase.analysis_id == analysis_id).limit(1)
    )

    response = client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/review",
        json={"action": "approve"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
