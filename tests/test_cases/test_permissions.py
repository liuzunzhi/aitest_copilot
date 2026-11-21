"""权限矩阵与归档项目（T107 / AC-173 / AC-174）。"""

from tests.test_cases.helpers import (
    ANALYSES,
    CASES,
    add_member,
    login,
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
    make_point(db, project, admin, chapter=chapter)
    return {"admin": admin, "project": project, "template": template}


def test_ac_173_non_member_cannot_read(db, client):
    """非项目成员读列表 → 403 `NOT_PROJECT_MEMBER`。"""
    chain = _chain(db)
    outsider = make_user(db)
    headers = login(client, outsider)
    project_id = chain["project"].id

    for url in (CASES.format(project_id=project_id), ANALYSES.format(project_id=project_id)):
        response = client.get(url, headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_173_member_and_guest_can_read(db, client):
    """member / guest 读接口 200。"""
    chain = _chain(db)
    project_id = chain["project"].id
    member = make_user(db)
    guest = make_user(db)
    add_member(db, chain["project"], member, "member")
    add_member(db, chain["project"], guest, "guest")

    for actor in (member, guest):
        headers = login(client, actor)
        response = client.get(CASES.format(project_id=project_id), headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 0


def test_ac_173_member_and_guest_cannot_write(db, client, provider):
    """member / guest 发起生成 → 403 `NOT_PROJECT_ADMIN`，且不调模型。"""
    chain = _chain(db)
    project_id = chain["project"].id
    member = make_user(db)
    guest = make_user(db)
    add_member(db, chain["project"], member, "member")
    add_member(db, chain["project"], guest, "guest")

    for actor in (member, guest):
        response = client.post(
            ANALYSES.format(project_id=project_id),
            json={"template_id": chain["template"].id},
            headers=login(client, actor),
        )
        assert response.status_code == 403
        assert response.json()["code"] == "NOT_PROJECT_ADMIN"

    assert provider.calls == []


def test_ac_174_archived_project_rejects_generation_but_allows_read(db, client):
    """归档项目：发起生成 409 `PROJECT_ARCHIVED`，读接口仍 200。"""
    chain = _chain(db, project_status="archived")
    headers = login(client, chain["admin"])
    project_id = chain["project"].id

    write = client.post(
        ANALYSES.format(project_id=project_id),
        json={"template_id": chain["template"].id},
        headers=headers,
    )
    assert write.status_code == 409
    assert write.json()["code"] == "PROJECT_ARCHIVED"

    read = client.get(CASES.format(project_id=project_id), headers=headers)
    assert read.status_code == 200


def test_ac_174_archive_check_precedes_role_check(db, client):
    """校验顺序「归档 409 先于角色 403」：普通成员在归档项目里也看到 409。"""
    chain = _chain(db, project_status="archived")
    member = make_user(db)
    add_member(db, chain["project"], member, "member")

    response = client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id},
        headers=login(client, member),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_project_not_found_precedes_everything(db, client):
    """项目不存在 → 404 `PROJECT_NOT_FOUND`（模板 id 再离谱也先报这个）。"""
    actor = make_user(db)

    response = client.post(
        ANALYSES.format(project_id=999_999),
        json={"template_id": 1},
        headers=login(client, actor),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


def test_template_check_precedes_batch_check(db, client):
    """模板不合法（400）先于批次不存在（404）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])

    response = client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": 999_999, "test_point_analysis_id": 888_888},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "TEST_CASE_TEMPLATE_INVALID"


def test_missing_batch_returns_404(db, client):
    """批次不存在 → 404 `TEST_CASE_ANALYSIS_NOT_FOUND`（在测试点校验之前）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])

    response = client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id, "test_point_analysis_id": 888_888},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "TEST_CASE_ANALYSIS_NOT_FOUND"


def test_unknown_explicit_point_returns_400(db, client, provider):
    """显式 id 不存在 → 400 `TEST_CASE_POINT_NOT_FOUND`，不跑模型。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])

    response = client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id, "test_point_ids": [999_999]},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "TEST_CASE_POINT_NOT_FOUND"
    assert provider.calls == []


def test_foreign_point_returns_400(db, client, provider):
    """显式 id 属于另一个项目 → 400，不静默过滤。"""
    chain = _chain(db)
    other_project = make_project(db)
    foreign = make_point(db, other_project, chain["admin"])
    headers = login(client, chain["admin"])

    response = client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id, "test_point_ids": [foreign.id]},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "TEST_CASE_POINT_NOT_FOUND"
    assert provider.calls == []
