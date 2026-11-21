"""生成链路：只吃 approved、逐点落库、失败留痕（T107）。

覆盖 AC-160 / 161 / 162 / 163 / 165 / 166 / 176。
"""

from sqlalchemy import func, select

from app.models.test_case import TestCase, TestCaseAnalysis, TestCaseStep
from app.models.test_point import TestPoint

from tests.test_cases.helpers import (
    ANALYSES,
    add_member,
    case_response,
    fenced_response,
    login,
    make_case,
    make_chapter,
    make_point,
    make_project,
    make_user,
    seed_template,
)


def _chain(db, *, project_status: str = "active") -> dict:
    admin = make_user(db)
    project = make_project(db, status=project_status)
    add_member(db, project, admin, "project_admin")
    template = seed_template(db)
    chapter = make_chapter(db, project, admin)
    return {
        "admin": admin,
        "project": project,
        "template": template,
        "chapter": chapter,
    }


def _post(client, chain: dict, headers: dict, **payload):
    body = {"template_id": chain["template"].id}
    body.update(payload)
    return client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json=body,
        headers=headers,
    )


def test_ac_160_only_approved_points_are_consumed(db, client, provider):
    """3 条测试点只有 1 条 approved → 只调 1 次模型，Prompt 里不出现另两条。"""
    chain = _chain(db)
    make_point(db, chain["project"], chain["admin"], name="可用：扫码登录锁定")
    make_point(
        db, chain["project"], chain["admin"], status="pending", name="待评审：密码登录"
    )
    make_point(
        db, chain["project"], chain["admin"], status="rejected", name="已驳回：短信登录"
    )
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers)

    assert response.status_code == 201, response.text
    assert len(provider.calls) == 1
    prompt = provider.calls[0].user
    assert "可用：扫码登录锁定" in prompt
    assert "待评审：密码登录" not in prompt
    assert "已驳回：短信登录" not in prompt
    assert response.json()["stats"]["test_point_count"] == 1


def test_ac_176_system_prompt_comes_from_database_template(db, client, provider):
    """Mock 收到的 `system` 等于模板的 `system_prompt`（模板来自数据库）。"""
    chain = _chain(db)
    make_point(db, chain["project"], chain["admin"])
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers)

    assert response.status_code == 201, response.text
    assert provider.calls[0].system == chain["template"].system_prompt
    assert provider.calls[0].user.startswith(chain["template"].user_prompt)


def test_ac_161_no_approved_points_rejects_without_record(db, client, provider):
    """只有 pending / rejected → 400 且**不产生**生成记录。"""
    chain = _chain(db)
    make_point(db, chain["project"], chain["admin"], status="pending")
    make_point(db, chain["project"], chain["admin"], status="rejected")
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers)

    assert response.status_code == 400
    assert response.json()["code"] == "TEST_CASE_INPUT_EMPTY"
    assert provider.calls == []
    total = db.scalar(
        select(func.count())
        .select_from(TestCaseAnalysis)
        .where(TestCaseAnalysis.project_id == chain["project"].id)
    )
    assert total == 0


def test_ac_162_one_point_can_produce_multiple_cases(db, client, provider):
    """一条测试点返回 3 条用例 → 3 行用例、步骤行数与各自 steps 长度一致。"""
    chain = _chain(db)
    point = make_point(db, chain["project"], chain["admin"])
    provider.queue = [
        case_response(
            make_case("正向：正确密码登录成功", steps=[{"action": "输密码", "expected": "进入首页"}]),
            make_case(
                "反向：错误密码被拒绝",
                steps=[
                    {"action": "输错密码", "expected": "提示错误"},
                    {"action": "再输错", "expected": "仍提示错误"},
                ],
            ),
            make_case(
                "边界：第 5 次错误后锁定",
                steps=[{"action": "连续输错 5 次", "expected": "账号锁定"}],
            ),
        )
    ]
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert len(payload["cases"]) == 3
    assert {row["test_point_id"] for row in payload["cases"]} == {point.id}
    assert payload["stats"]["case_count"] == 3
    assert payload["stats"]["step_count"] == 4

    rows = db.scalars(
        select(TestCase).where(TestCase.analysis_id == payload["id"])
    ).all()
    assert len(rows) == 3
    per_case = {
        row.id: db.scalar(
            select(func.count())
            .select_from(TestCaseStep)
            .where(TestCaseStep.case_id == row.id)
        )
        for row in rows
    }
    assert sorted(per_case.values()) == [1, 1, 2]


def test_ac_163_step_numbers_are_renumbered_from_one(db, client, provider):
    """模型给的 `step_no` 一律不信：服务端按数组顺序重排为 1..n。"""
    chain = _chain(db)
    make_point(db, chain["project"], chain["admin"])
    provider.queue = [
        case_response(
            make_case(
                steps=[
                    {"step_no": 99, "action": "第一步", "expected": "甲"},
                    {"step_no": 7, "action": "第二步", "expected": "乙"},
                    {"step_no": 1, "action": "第三步", "expected": "丙"},
                ]
            )
        )
    ]
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers)

    assert response.status_code == 201, response.text
    steps = response.json()["cases"][0]["steps"]
    assert [row["step_no"] for row in steps] == [1, 2, 3]
    assert [row["action"] for row in steps] == ["第一步", "第二步", "第三步"]


def test_ac_165_bad_json_fails_run_and_keeps_no_cases(db, client, provider):
    """坏 JSON → 记录 `failed` + `TEST_CASE_INVALID`，**不产生任何用例行**。"""
    chain = _chain(db)
    make_point(db, chain["project"], chain["admin"])
    provider.queue = ["这不是 JSON"]
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers)

    assert response.status_code == 400
    assert response.json()["code"] == "TEST_CASE_INVALID"

    analysis = db.scalar(
        select(TestCaseAnalysis)
        .where(TestCaseAnalysis.project_id == chain["project"].id)
        .order_by(TestCaseAnalysis.id.desc())
    )
    assert analysis is not None
    assert analysis.status == "failed"
    assert analysis.error_code == "TEST_CASE_INVALID"
    assert analysis.finished_at is not None

    cases = db.scalar(
        select(func.count())
        .select_from(TestCase)
        .where(TestCase.analysis_id == analysis.id)
    )
    assert cases == 0


def test_ac_166_fenced_json_is_accepted(db, client, provider):
    """带 Markdown 围栏的 JSON 照常落库（走 `parse_llm_json`）。"""
    chain = _chain(db)
    make_point(db, chain["project"], chain["admin"])
    provider.queue = [fenced_response(case_response(make_case("围栏里的用例")))]
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers)

    assert response.status_code == 201, response.text
    assert response.json()["cases"][0]["title"] == "围栏里的用例"


def test_ac_160_explicit_ids_are_strict(db, client, provider):
    """显式给的 id 里夹一条 pending → 400 `TEST_CASE_POINT_NOT_FOUND`，不跑模型。"""
    chain = _chain(db)
    make_point(db, chain["project"], chain["admin"])
    pending = make_point(db, chain["project"], chain["admin"], status="pending")
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers, test_point_ids=[pending.id])

    assert response.status_code == 400
    assert response.json()["code"] == "TEST_CASE_POINT_NOT_FOUND"
    assert provider.calls == []


def test_mid_run_failure_stops_remaining_points(db, client, provider):
    """第 1 个点就失败 → 不再调后续点（调用次数 = 1），记录 `failed`。"""
    chain = _chain(db)
    make_point(db, chain["project"], chain["admin"], name="第一个点")
    make_point(db, chain["project"], chain["admin"], name="第二个点", target_id=10097)
    provider.queue = ["这不是 JSON"]
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers)

    assert response.status_code == 400
    assert len(provider.calls) == 1
    analysis = db.scalar(
        select(TestCaseAnalysis)
        .where(TestCaseAnalysis.project_id == chain["project"].id)
        .order_by(TestCaseAnalysis.id.desc())
    )
    assert analysis.status == "failed"
    assert analysis.stats["test_point_count"] == 2


def test_audit_is_written_on_create_but_not_on_validation_failure(db, client, provider):
    """成功发起 → 审计 `test_case.analysis.create`；校验失败 → 不写审计。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    from app.models.system import AuditLog

    def _audits() -> list[AuditLog]:
        return list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.project_id == chain["project"].id,
                    AuditLog.action == "test_case.analysis.create",
                )
            ).all()
        )

    failed = _post(client, chain, headers)
    assert failed.status_code == 400
    assert _audits() == []

    make_point(db, chain["project"], chain["admin"])
    succeeded = _post(client, chain, headers)
    assert succeeded.status_code == 201, succeeded.text
    audits = _audits()
    assert len(audits) == 1
    assert audits[0].target_type == "test_case_analysis"
    assert audits[0].target_id == str(succeeded.json()["id"])
    assert audits[0].after_data["point_count"] == 1


def test_point_analysis_batch_filters_approved_points(db, client, provider):
    """给了 `test_point_analysis_id` → 只处理该批次下的 approved。"""
    chain = _chain(db)
    from app.models.test_point import TestPointAnalysis

    batch = TestPointAnalysis(
        project_id=chain["project"].id,
        template_id=chain["template"].id,
        template_version=1,
        status="succeeded",
        created_by=chain["admin"].id,
    )
    db.add(batch)
    db.flush()

    make_point(
        db,
        chain["project"],
        chain["admin"],
        name="批次内",
        point_analysis_id=batch.id,
    )
    make_point(
        db,
        chain["project"],
        chain["admin"],
        name="批次外",
        point_analysis_id=None,
    )
    headers = login(client, chain["admin"])

    response = _post(client, chain, headers, test_point_analysis_id=batch.id)

    assert response.status_code == 201, response.text
    prompt = provider.calls[0].user
    assert "批次内" in prompt
    assert "批次外" not in prompt
