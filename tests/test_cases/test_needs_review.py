"""待复核派生（读时计算，不落库）（T108 / AC-171 / AC-172）。

覆盖点：

- 源测试点任一 `_FIELDS` 字段变化 → `needs_review=true` + `source_point_changed`；
- **用例内容完全不变**（派生只算，不改用例）；
- 只改 `updated_at` → **不触发**（判定基准是内容指纹，不是时间戳）；
- 源测试点被 07 物理删除 → 用例仍在、快照保留、原因 `source_point_deleted`；
- 07 的删除接口**仍成功、不 500**；
- `ack` → 提示消失；再改 → 重新出现；源已删时 `ack` → 指纹置 NULL、不再提示。
"""

import pytest
from sqlalchemy import select

from app.models.test_case import TestCase
from app.models.test_point import TestPoint
from app.test_cases.fingerprint import FIELDS, fingerprint_point

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

# `needs_review` 是整数列（TINYINT），这里逐字段给出「改动它」的方式。
MUTATIONS = {
    "name": ("改名后的测试点",),
    "target_type": ("feature_point",),
    "target_id": (10097,),
    "target_name": ("改名后的目标",),
    "priority": ("low",),
    "precondition": ("改后的前置条件",),
    "verification": ("改后的验证要点",),
    "chapter_id": (None,),
    "chapter_title": ("改后的章节标题",),
    "needs_review": (1,),
}


def _chain(db) -> dict:
    admin = make_user(db)
    project = make_project(db)
    add_member(db, project, admin, "project_admin")
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


def _generate(db, client, chain: dict, headers: dict) -> int:
    """跑一次生成，返回第一条用例的 id。"""
    response = client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    case_id = response.json()["cases"][0]["id"]
    return case_id


def _case_payload(client, chain: dict, headers: dict, case_id: int) -> dict:
    response = client.get(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("field", sorted(MUTATIONS))
def test_ac_171_any_point_field_change_triggers_review(db, client, provider, field: str):
    """`_FIELDS` 里**每一个**字段被改，都触发待复核（防漏项）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _generate(db, client, chain, headers)
    before = _case_payload(client, chain, headers, case_id)
    assert before["needs_review"] is False

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    setattr(point, field, MUTATIONS[field][0])
    db.flush()

    after = _case_payload(client, chain, headers, case_id)
    assert after["needs_review"] is True
    assert after["needs_review_reason"] == "source_point_changed"


def test_ac_171_case_content_is_unchanged(db, client, provider):
    """源测试点变了，用例**内容完全不变**（派生不写用例）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _generate(db, client, chain, headers)
    before = _case_payload(client, chain, headers, case_id)

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    point.name = "改名后的测试点"
    point.precondition = "改后的前置条件"
    db.flush()

    after = _case_payload(client, chain, headers, case_id)
    assert after["title"] == before["title"]
    assert after["precondition"] == before["precondition"]
    assert after["test_point_name"] == before["test_point_name"]
    assert after["steps"] == before["steps"]
    # 只有待复核标记变了
    assert after["needs_review"] is True


def test_ac_171_updated_at_change_does_not_trigger(db, client, provider):
    """只改 `updated_at` → **不**触发待复核（判定基准是内容指纹）。"""
    from datetime import datetime, timezone

    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _generate(db, client, chain, headers)

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    point.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()

    after = _case_payload(client, chain, headers, case_id)
    assert after["needs_review"] is False
    assert after["needs_review_reason"] is None


def test_ac_171_point_deletion_marks_review_and_keeps_case(db, client, provider):
    """源测试点被删 → 用例仍在、快照保留、原因 `source_point_deleted`。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _generate(db, client, chain, headers)
    before = _case_payload(client, chain, headers, case_id)

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    db.delete(point)
    db.flush()

    after = _case_payload(client, chain, headers, case_id)
    assert after["needs_review"] is True
    assert after["needs_review_reason"] == "source_point_deleted"
    assert after["test_point_name"] == before["test_point_name"]
    assert after["title"] == before["title"]


def test_ac_171_seven_point_delete_api_still_works(db, client, provider):
    """07 的删测试点接口**仍然成功、不 500**（08 不建外键的回报）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    _generate(db, client, chain, headers)

    response = client.delete(
        f"/api/projects/{chain['project'].id}/test-points/points/{chain['point'].id}",
        headers=headers,
    )

    assert response.status_code == 204, response.text


def test_ac_171_deleting_point_analysis_still_works(db, client, provider):
    """07 的删生成记录接口**仍然成功、不 500**（连带删测试点也不报错）。"""
    from app.models.test_point import TestPointAnalysis

    chain = _chain(db)
    headers = login(client, chain["admin"])
    # 一条 07 的生成记录，挂一个 pending 测试点（approved 的 07 会 409）
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
        status="pending",
        name="批次里的点",
        point_analysis_id=batch.id,
    )
    _generate(db, client, chain, headers)

    response = client.delete(
        f"/api/projects/{chain['project'].id}/test-points/analyses/{batch.id}",
        headers=headers,
    )

    assert response.status_code == 204, response.text


def test_ac_172_ack_clears_review_and_refreshes_fingerprint(db, client, provider):
    """`ack` → 提示消失、指纹刷成当前值。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _generate(db, client, chain, headers)

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    point.name = "改名后的测试点"
    db.flush()
    assert _case_payload(client, chain, headers, case_id)["needs_review"] is True

    response = client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/ack", headers=headers
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["needs_review"] is False
    assert payload["needs_review_ack_at"] is not None

    row = db.scalar(select(TestCase).where(TestCase.id == case_id))
    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    assert row.source_point_fingerprint == fingerprint_point(point)


def test_ac_172_review_reappears_after_another_change(db, client, provider):
    """`ack` 之后源再被改 → 待复核重新出现。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _generate(db, client, chain, headers)

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    point.name = "第一次改名"
    db.flush()
    client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/ack", headers=headers
    )
    assert _case_payload(client, chain, headers, case_id)["needs_review"] is False

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    point.name = "第二次改名"
    db.flush()

    after = _case_payload(client, chain, headers, case_id)
    assert after["needs_review"] is True
    assert after["needs_review_reason"] == "source_point_changed"


def test_ac_172_ack_after_source_deleted_nulls_fingerprint(db, client, provider):
    """源已删除时 `ack` → 指纹置 NULL，之后不再提示。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _generate(db, client, chain, headers)

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    db.delete(point)
    db.flush()
    assert _case_payload(client, chain, headers, case_id)["needs_review"] is True

    response = client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/ack", headers=headers
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["needs_review"] is False
    assert payload["needs_review_ack_at"] is not None

    row = db.scalar(select(TestCase).where(TestCase.id == case_id))
    assert row.source_point_fingerprint is None


def test_ac_171_needs_review_filter_works(db, client, provider):
    """列表按 `needs_review=true` 筛选（Python 层过滤）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _generate(db, client, chain, headers)

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    point.priority = "low"
    db.flush()

    url = CASES.format(project_id=chain["project"].id)
    flagged = client.get(f"{url}?needs_review=true", headers=headers)
    clean = client.get(f"{url}?needs_review=false", headers=headers)

    assert flagged.status_code == 200, flagged.text
    assert flagged.json()["total"] == 1
    assert flagged.json()["items"][0]["id"] == case_id
    assert clean.json()["total"] == 0


def test_fingerprint_fields_cover_the_spec():
    """`_FIELDS` 与 spec §6.5 的清单一致（字段清单只有一个出处）。"""
    assert set(FIELDS) == {
        "name",
        "target_type",
        "target_id",
        "target_name",
        "priority",
        "precondition",
        "verification",
        "chapter_id",
        "chapter_title",
        "needs_review",
    }


def test_manual_case_also_tracks_source_change(db, client):
    """手工新增的用例同样参与待复核派生（快照在生成时就写好了）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    created = client.post(
        CASES.format(project_id=chain["project"].id),
        json={
            "test_point_id": chain["point"].id,
            "title": "手工用例",
            "steps": [{"action": "第一步", "expected": "预期"}],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]

    point = db.scalar(select(TestPoint).where(TestPoint.id == chain["point"].id))
    point.verification = "改后的验证要点"
    db.flush()

    after = _case_payload(client, chain, headers, case_id)
    assert after["needs_review"] is True
    assert after["needs_review_reason"] == "source_point_changed"


def test_generated_case_has_fingerprint(db, client, provider):
    """生成出来的用例写入了源测试点指纹（不是 NULL）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    provider.queue = [case_response(make_case())]
    case_id = _generate(db, client, chain, headers)

    row = db.scalar(select(TestCase).where(TestCase.id == case_id))
    assert row.source_point_fingerprint is not None
    assert len(row.source_point_fingerprint) == 64
