"""快照引用保护扩展用例（04 收尾 · `ac_04_cleanup`）。

04 spec §2.3 第 6 条的遗留：被引用即保护本期只检查标签引用，
增量分析记录、测试点、用例、报告落地时补查引用来源。

本文件验证：
- 引用检查已按「来源解析器」拆开，新增来源只需注册，不必改主流程；
- 增量分析引用能被识别（分析记录把该快照当比对基准这一路）；
- 标签若由某次增量分析产出，其来源信息随标签一起给出（不算额外一处引用）；
- 被增量分析引用的快照禁止删除，保留策略告警与引用明细正确；
- 05 尚未落地时（表不存在）不报错、不误判。

用例名前缀统一为 `test_ac_04_cleanup_`，可用 `pytest -k ac_04_cleanup` 单独跑。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.baselines import references as ref_mod
from app.baselines.references import (
    _analysis_record_references,
    register_resolver,
    snapshot_references,
)
from app.common.db import _force_utc
from app.models.baseline import BaselineLabel
from tests.baselines.helpers import BASE, build_structure, make_snapshot

REVISIONS = "/api/projects/{project_id}/baselines/revisions"


# --------------------------------------------------------------- 造数辅助


def _label(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    revision_id: int,
    target_type: str,
    target_id: int,
    label_type: str = "changed",
) -> dict:
    response = client.post(
        BASE.format(project_id=project_id) + "/labels",
        json={
            "revision_id": revision_id,
            "target_type": target_type,
            "target_id": target_id,
            "label_type": label_type,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_max(client: TestClient, headers: dict[str, str], project_id: int, value: int) -> dict:
    response = client.patch(
        BASE.format(project_id=project_id) + "/retention",
        json={"max_count": value},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------- 增量分析表（SQLite）


def _analysis_engine() -> Engine:
    """一个带 `incremental_analyses` 表的内存 SQLite 库。

    05 落地前这张表在 MySQL 里不存在，用 SQLite 单独造一张来验证
    「表存在时」的分支。

    两个必须注意的点：
    - **StaticPool**：内存库默认每个线程一条连接，测试线程写入、
      请求线程读会落到两个不同的库上，读到的自然是空。StaticPool 让
      所有线程共用同一条连接与同一个库。
    - **check_same_thread=False**：请求跑在 TestClient 的线程里，
      而连接是在测试线程建的，不放开这个限制会直接抛线程错误。

    另外 SQLite 不认 `SET time_zone`，所以把全局的 UTC 监听器摘掉，
    用完再装回去。
    """
    event.remove(Engine, "connect", _force_utc)
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE incremental_analyses ("
                "id INTEGER PRIMARY KEY, "
                "project_id INTEGER, "
                "baseline_revision_id INTEGER, "
                "status TEXT)"
            )
        )
        conn.commit()
    return engine


@pytest.fixture
def analysis_db():
    """带增量分析表的独立 SQLite 会话。"""
    engine = _analysis_engine()
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()
        event.listen(Engine, "connect", _force_utc)


def _insert_analysis(
    session: Session, analysis_id: int, revision_id: int, status: str = "succeeded"
) -> None:
    session.execute(
        text(
            "INSERT INTO incremental_analyses "
            "(id, project_id, baseline_revision_id, status) "
            "VALUES (:id, 1, :rev, :status)"
        ),
        {"id": analysis_id, "rev": revision_id, "status": status},
    )
    session.commit()


# ------------------------------------------------------- 引用来源解析器


def test_ac_04_cleanup_reference_resolvers_are_separated():
    """引用检查按来源拆成解析器：新增来源只需注册，不必改主流程。"""
    assert callable(register_resolver)
    assert callable(snapshot_references)
    names = {fn.__name__ for fn in ref_mod._BUILTIN_RESOLVERS}
    assert "_label_references" in names
    assert "_analysis_record_references" in names


def test_ac_04_cleanup_custom_resolver_is_applied(db: Session):
    """注册一个自定义来源解析器 → 它的引用出现在结果里。"""

    def fake_resolver(session: Session, revision_id: int) -> list[dict]:
        return [{"source_type": "test_point", "target_id": 1, "target_name": "测试点 #1"}]

    register_resolver(fake_resolver)
    try:
        refs = snapshot_references(db, 1)
        assert any(ref["source_type"] == "test_point" for ref in refs)
    finally:
        ref_mod._resolvers.remove(fake_resolver)


def test_ac_04_cleanup_analysis_table_absent_is_not_an_error(db: Session):
    """05 尚未落地（表不存在）→ 增量分析来源返回空，不报错、不误判。"""
    assert _analysis_record_references(db, 1) == []


def test_ac_04_cleanup_analysis_record_reference_detected(analysis_db: Session):
    """分析记录把该快照当比对基准 → 检出引用。"""
    _insert_analysis(analysis_db, 7, 42, "succeeded")
    refs = _analysis_record_references(analysis_db, 42)
    assert len(refs) == 1
    assert refs[0]["source_type"] == "incremental_analysis"
    assert refs[0]["target_id"] == 7
    assert "增量分析 #7" in refs[0]["target_name"]
    # 别的快照不被牵连
    assert _analysis_record_references(analysis_db, 999) == []


def test_ac_04_cleanup_duplicate_references_are_deduplicated(analysis_db: Session):
    """同一条引用被两个解析器查到 → 只算一处，引用数不虚高。"""
    _insert_analysis(analysis_db, 7, 42)

    def duplicate_resolver(session: Session, revision_id: int) -> list[dict]:
        return [
            {
                "source_type": "incremental_analysis",
                "target_id": 7,
                "target_name": "增量分析 #7",
            }
        ]

    register_resolver(duplicate_resolver)
    try:
        # 只跑标签解析器之外的来源：SQLite 库里没有基线表
        original = ref_mod._BUILTIN_RESOLVERS
        ref_mod._BUILTIN_RESOLVERS = [
            ref_mod._analysis_record_references,
            duplicate_resolver,
        ]
        try:
            refs = snapshot_references(analysis_db, 42)
        finally:
            ref_mod._BUILTIN_RESOLVERS = original

        analysis_refs = [r for r in refs if r["source_type"] == "incremental_analysis"]
        assert len(analysis_refs) == 1
    finally:
        ref_mod._resolvers.remove(duplicate_resolver)


# --------------------------------------------- 增量分析引用 → 禁止删除


def test_ac_04_cleanup_snapshot_referenced_by_analysis_cannot_be_deleted(
    client: TestClient, db: Session, project, headers, reviewer_headers
):
    """标签由某次增量分析产出 → 该标签携带来源信息，引用数不被虚增。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    label = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
    )

    # 模拟 05 的写入方：给标签补上增量分析来源
    row = db.get(BaselineLabel, label["id"])
    assert row is not None
    row.source_analysis_id = 88
    db.flush()

    response = client.delete(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}",
        headers=headers,
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "SNAPSHOT_REFERENCED"
    # 一条标签 = 一处引用；来源信息挂在标签条目上，不额外算一条
    assert body["referenced_count"] == 1
    assert len(body["refs"]) == 1
    assert body["refs"][0]["source_type"] == "baseline_function"
    assert body["refs"][0]["source_analysis_id"] == 88
    # 提示语仍是标签引用——用户要处理的动作是「清掉这条标签」
    assert "仍被标签引用" in body["message"]


def test_ac_04_cleanup_analysis_record_blocks_snapshot_deletion(
    client: TestClient, db: Session, project, headers, reviewer_headers
):
    """分析记录把该快照当比对基准 → 快照被引用 → 禁止删除，提示来源为增量分析。

    MySQL 里没有 `incremental_analyses` 表（05 未落地），用替换解析器的方式
    把「增量分析来源」指向测试内的 SQLite 库，
    从而在不动生产 schema 的前提下验证这一路引用。
    """
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    engine = _analysis_engine()
    try:
        with Session(engine) as analysis_session:
            analysis_session.execute(
                text(
                    "INSERT INTO incremental_analyses "
                    "(id, baseline_revision_id, status) VALUES (7, :rev, 'succeeded')"
                ),
                {"rev": snapshot["id"]},
            )
            analysis_session.commit()

            original = ref_mod._BUILTIN_RESOLVERS

            def analysis_resolver(session: Session, revision_id: int) -> list[dict]:
                # 用测试内的 SQLite 库代替 MySQL 里的那张表
                return ref_mod._analysis_record_references(analysis_session, revision_id)

            ref_mod._BUILTIN_RESOLVERS = [
                ref_mod._label_references,
                analysis_resolver,
            ]
            try:
                response = client.delete(
                    REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}",
                    headers=headers,
                )
            finally:
                ref_mod._BUILTIN_RESOLVERS = original
    finally:
        engine.dispose()
        event.listen(Engine, "connect", _force_utc)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "SNAPSHOT_REFERENCED"
    analysis_ref = next(
        r for r in body["refs"] if r["source_type"] == "incremental_analysis"
    )
    assert analysis_ref["target_id"] == 7
    assert "增量分析 #7" in analysis_ref["target_name"]
    # 提示语说明是被增量分析引用
    assert "增量分析" in body["message"]


def test_ac_04_cleanup_cleared_label_releases_reference(
    client: TestClient, db: Session, project, headers, reviewer_headers
):
    """标签被清除后不再算引用 → 快照可以删除。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    label = _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
    )
    row = db.get(BaselineLabel, label["id"])
    assert row is not None
    row.source_analysis_id = 88
    db.flush()

    # 被引用 → 删不掉
    blocked = client.delete(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}",
        headers=headers,
    )
    assert blocked.status_code == 409

    # 清除标签 → 引用解除
    cleared = client.post(
        BASE.format(project_id=project.id) + f"/labels/{label['id']}/clear",
        json={"clear_reason": "misjudged"},
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text

    deleted = client.delete(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}",
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True


def test_ac_04_cleanup_retention_candidate_lists_reference_details(
    client: TestClient, db: Session, project, headers, reviewer_headers
):
    """待清理候选里也要带出引用来源明细，告警照常触发。"""
    built = build_structure(client, headers, project.id)
    first = make_snapshot(client, headers, project.id, reviewer_headers)
    make_snapshot(client, headers, project.id, reviewer_headers)
    make_snapshot(client, headers, project.id, reviewer_headers)

    label = _label(
        client,
        headers,
        project.id,
        first["id"],
        "function",
        built["function"]["id"],
    )
    row = db.get(BaselineLabel, label["id"])
    assert row is not None
    row.source_analysis_id = 88
    db.flush()

    body = _set_max(client, headers, project.id, 2)
    assert len(body["candidates"]) == 1
    candidate = body["candidates"][0]
    assert candidate["referenced_count"] == 1
    assert candidate["refs"][0]["source_analysis_id"] == 88
    # 告警照常触发
    assert body["warnings"]
    assert "保留上限" in body["warnings"][0]
    assert "被引用" in body["warnings"][0]


def test_ac_04_cleanup_unreferenced_snapshot_still_deletable(
    client: TestClient, project, headers, reviewer_headers
):
    """没有任何引用的快照仍可正常删除（回归保护）。"""
    build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)

    response = client.delete(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True


def test_ac_04_cleanup_label_reference_message_unchanged(
    client: TestClient, project, headers, reviewer_headers
):
    """只被标签引用时，提示语仍是「标签引用」（e2e 断言了这句）。"""
    built = build_structure(client, headers, project.id)
    snapshot = make_snapshot(client, headers, project.id, reviewer_headers)
    _label(
        client,
        headers,
        project.id,
        snapshot["id"],
        "function",
        built["function"]["id"],
    )

    response = client.delete(
        REVISIONS.format(project_id=project.id) + f"/{snapshot['id']}",
        headers=headers,
    )
    assert response.status_code == 409
    body = response.json()
    assert "仍被标签引用" in body["message"]
    assert body["refs"][0]["source_type"] == "baseline_function"
