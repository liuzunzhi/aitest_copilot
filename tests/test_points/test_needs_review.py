"""标签清除 → 测试点待复核标记 + 快照引用保护（07-test-points T102）。

覆盖点：

- **标签清除后测试点内容一个字都不动**，只置 `needs_review`（AC-149）；
- **已评审通过的测试点仍保持 approved**——清除标签不自动降级下游结论（AC-149）；
- 清除 → 引用该标签的测试点全部被标记（AC-150）；
- **手工新增的测试点（不引用标签）不受影响**（AC-150）；
- 快照被测试点生成记录引用 → 引用列表里出现该来源，且禁止删除（AC-151）；
- **表探测保护**：07 的表不存在时，04 的引用检查与清除标签照常工作。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.baselines import references as ref_mod
from app.models.test_point import TestPoint, TestPointAnalysis
from tests.test_points import helpers as H


def _chain(db: Session) -> dict:
    """项目 + 快照 + 结构 + 生效标签。"""
    chain = H.build_chain(db)
    function = chain["structure"]["function"]
    label = H.make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
    )
    chain["label"] = label
    chain["function"] = function
    return chain


def _generate(client, db, provider, chain: dict) -> dict:
    """跑一次生成，产出一条引用了该标签的测试点。"""
    headers = H.login(client, chain["admin"])
    provider.queue = [H.point_response(target_id=chain["function"].id)]
    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json={
            "template_id": chain["template"].id,
            "baseline_revision_id": chain["revision"].id,
            "document_version_id": chain["version"].id,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _clear_label(client, chain: dict, reason: str = "misjudged") -> dict:
    """走真实接口清除标签（04 的接口，前缀是 `baselines` 不是 `test-points`）。"""
    headers = H.login(client, chain["admin"])
    response = client.post(
        f"/api/projects/{chain['project'].id}/baselines/labels/"
        f"{chain['label'].id}/clear",
        json={"clear_reason": reason},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------- 待复核


def test_ac_149_clear_label_marks_needs_review_without_changing_content(
    client, db, provider
):
    """**清除标签后测试点内容一个字都不动**，只多一个待复核标记。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]

    before = db.get(TestPoint, point_id)
    snapshot = {
        "name": before.name,
        "target_type": before.target_type,
        "target_id": before.target_id,
        "target_name": before.target_name,
        "priority": before.priority,
        "precondition": before.precondition,
        "verification": before.verification,
        "chapter_id": before.chapter_id,
        "chapter_title": before.chapter_title,
        "source_label_id": before.source_label_id,
        "source_conclusion_id": before.source_conclusion_id,
        "status": before.status,
        "source_type": before.source_type,
    }
    assert before.needs_review == 0

    _clear_label(client, chain)

    after = db.get(TestPoint, point_id)
    # 内容逐字段不变
    assert after.name == snapshot["name"]
    assert after.target_type == snapshot["target_type"]
    assert after.target_id == snapshot["target_id"]
    assert after.target_name == snapshot["target_name"]
    assert after.priority == snapshot["priority"]
    assert after.precondition == snapshot["precondition"]
    assert after.verification == snapshot["verification"]
    assert after.chapter_id == snapshot["chapter_id"]
    assert after.chapter_title == snapshot["chapter_title"]
    assert after.source_label_id == snapshot["source_label_id"]
    assert after.source_conclusion_id == snapshot["source_conclusion_id"]
    assert after.source_type == snapshot["source_type"]
    # 只有这三个字段变了
    assert after.needs_review == 1
    assert after.needs_review_at is not None
    assert "misjudged" in after.needs_review_reason


def test_ac_149_approved_point_is_not_downgraded(client, db, provider):
    """**已评审通过的测试点仍保持 approved**——清除标签不自动降级。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]
    headers = H.login(client, chain["admin"])

    approve = client.post(
        f"{H.POINTS.format(project_id=chain['project'].id)}/{point_id}/review",
        json={"action": "approve"},
        headers=headers,
    )
    assert approve.status_code == 200, approve.text

    _clear_label(client, chain)

    after = db.get(TestPoint, point_id)
    assert after.status == "approved", "清除标签不该自动降级评审结论"
    assert after.needs_review == 1, "但仍要标记待复核"


def test_ac_150_all_points_referencing_the_label_are_marked(client, db, provider):
    """清除一个标签 → **引用它的所有测试点**都被标记。

    造两条**都引用同一标签**的测试点：
    引擎在同一章节内会对同一目标去重（只留第一条），
    所以要用**两个章节**——每章各产出一条，都挂在同一个目标上。
    """
    chain = H.build_chain(db, chapters=[("第一章", "内容一"), ("第二章", "内容二")])
    function = chain["structure"]["function"]
    label = H.make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
    )
    chain["label"] = label
    chain["function"] = function
    headers = H.login(client, chain["admin"])

    # 两章 → 两次调用 → 两条测试点，都指向同一个目标（因而同一个标签）
    provider.queue = [
        H.point_response(target_id=function.id, name="第一条"),
        H.point_response(target_id=function.id, name="第二条"),
    ]
    created = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json={
            "template_id": chain["template"].id,
            "baseline_revision_id": chain["revision"].id,
            "document_version_id": chain["version"].id,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["stats"]["test_point_count"] == 2

    _clear_label(client, chain)

    rows = list(db.scalars(select(TestPoint)).all())
    assert len(rows) == 2
    assert all(row.needs_review == 1 for row in rows)
    assert all(row.source_label_id == label.id for row in rows)


def test_ac_150_manual_point_without_label_is_unaffected(client, db, provider):
    """**手工新增的测试点（不引用标签）不受影响**。"""
    chain = _chain(db)
    _generate(client, db, provider, chain)

    # 手工加一条**不引用标签**的（source_label_id 为 NULL）
    headers = H.login(client, chain["admin"])
    manual = client.post(
        H.POINTS.format(project_id=chain["project"].id),
        json={
            "name": "不依赖标签的测试点",
            "target_type": "function",
            "target_id": chain["function"].id,
        },
        headers=headers,
    )
    assert manual.status_code == 201, manual.text
    manual_id = manual.json()["id"]

    _clear_label(client, chain)

    after = db.get(TestPoint, manual_id)
    assert after.source_label_id is None
    assert after.needs_review == 0, "不引用标签的测试点不该被标记"


def test_ac_150_clear_is_idempotent_for_the_marker(client, db, provider):
    """重复清除不存在的标签 → 409（标签已清除），已有标记不被改动。"""
    chain = _chain(db)
    created = _generate(client, db, provider, chain)
    point_id = created["points"][0]["id"]

    _clear_label(client, chain)
    first = db.get(TestPoint, point_id)
    first_at = first.needs_review_at

    headers = H.login(client, chain["admin"])
    again = client.post(
        f"/api/projects/{chain['project'].id}/baselines/labels/"
        f"{chain['label'].id}/clear",
        json={"clear_reason": "misjudged"},
        headers=headers,
    )
    assert again.status_code == 409
    assert again.json()["code"] == "LABEL_ALREADY_CLEARED"

    after = db.get(TestPoint, point_id)
    assert after.needs_review == 1
    assert after.needs_review_at == first_at


# --------------------------------------------------------------- 引用保护


def test_ac_151_snapshot_references_include_test_point_analysis(db: Session):
    """快照被测试点生成记录引用 → 引用列表里出现该来源。"""
    chain = _chain(db)
    analysis = TestPointAnalysis(
        project_id=chain["project"].id,
        template_id=chain["template"].id,
        template_version=chain["template"].version_no,
        baseline_revision_id=chain["revision"].id,
        status="succeeded",
        created_by=chain["admin"].id,
    )
    db.add(analysis)
    db.flush()

    refs = ref_mod.snapshot_references(db, chain["revision"].id)

    tp_refs = [r for r in refs if r["source_type"] == "test_point_analysis"]
    assert len(tp_refs) == 1
    assert tp_refs[0]["target_id"] == analysis.id
    assert "测试点生成" in tp_refs[0]["target_name"]


def test_ac_151_test_point_resolver_returns_empty_without_table(db: Session):
    """**表探测保护**：07 的表不存在 → 返回空列表，不报错。

    04 期的老库 / 老测试跑到这里必须安然无恙。
    """
    # 用一个只建了 dummy 表的独立 SQLite 会话——没有 test_point_analyses 表。
    # SQLite 不认 `SET time_zone`，所以把全局的 UTC 监听器摘掉，用完装回去
    # （照 04 的 `test_snapshot_references.py` 的做法）。
    from sqlalchemy import Engine, create_engine, event, text
    from sqlalchemy.pool import StaticPool

    from app.common.db import _force_utc

    event.remove(Engine, "connect", _force_utc)
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE dummy (id INTEGER PRIMARY KEY)"))
            conn.commit()
        with Session(engine) as session:
            assert ref_mod._test_point_references(session, 1) == []
    finally:
        engine.dispose()
        event.listen(Engine, "connect", _force_utc)


def test_ac_151_referenced_snapshot_cannot_be_deleted(client, db, provider):
    """被测试点引用的快照 → 禁止删除（409 `SNAPSHOT_REFERENCED`）。"""
    chain = _chain(db)
    _generate(client, db, provider, chain)
    headers = H.login(client, chain["admin"])

    response = client.delete(
        f"/api/projects/{chain['project'].id}/baselines/revisions/"
        f"{chain['revision'].id}",
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SNAPSHOT_REFERENCED"
