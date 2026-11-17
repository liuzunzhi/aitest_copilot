"""AC-82：增量分析读 / 写权限矩阵。"""

import json

from tests.incremental import helpers as H


def _create_analysis(client, chain: dict, headers: dict, provider) -> dict:
    provider.queue = [json.dumps({"conclusions": []})]
    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ac_82_read_permissions(client, db, provider):
    chain = H.build_chain(db)
    admin_headers = H.login(client, chain["admin"])
    created = _create_analysis(client, chain, admin_headers, provider)

    member = H.make_user(db)
    guest = H.make_user(db)
    outsider = H.make_user(db)
    system_admin = H.make_user(db, global_role="system_admin")
    H.add_member(db, chain["project"], member, "member")
    H.add_member(db, chain["project"], guest, "guest")

    base = H.BASE.format(project_id=chain["project"].id)
    paths = [
        f"{base}/analyses",
        f"{base}/analyses/{created['id']}",
        f"{base}/analyses/{created['id']}/conclusions",
    ]

    for user in (member, guest, system_admin):
        headers = H.login(client, user)
        for path in paths:
            response = client.get(path, headers=headers)
            assert response.status_code == 200, (user.username, path, response.text)

    outsider_headers = H.login(client, outsider)
    for path in paths:
        response = client.get(path, headers=outsider_headers)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["code"] == "NOT_PROJECT_MEMBER"

    missing = client.get(
        H.BASE.format(project_id=99_999_999) + "/analyses",
        headers=outsider_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "PROJECT_NOT_FOUND"


def test_ac_82_create_requires_project_admin(client, db, provider):
    chain = H.build_chain(db)
    admin_headers = H.login(client, chain["admin"])

    member = H.make_user(db)
    guest = H.make_user(db)
    outsider = H.make_user(db)
    H.add_member(db, chain["project"], member, "member")
    H.add_member(db, chain["project"], guest, "guest")

    payload = H.analysis_payload(
        template_id=chain["template"].id,
        baseline_revision_id=chain["revision"].id,
        document_version_id=chain["version"].id,
    )
    url = H.ANALYSES.format(project_id=chain["project"].id)

    for user in (member, guest, outsider):
        response = client.post(url, json=payload, headers=H.login(client, user))
        assert response.status_code == 403, (user.username, response.text)
        assert response.json()["code"] == "NOT_PROJECT_ADMIN"

    created = _create_analysis(client, chain, admin_headers, provider)
    assert created["status"] == "succeeded"


def test_ac_82_archived_project_rejected_before_role(client, db, provider):
    chain = H.build_chain(db)
    chain["project"].status = "archived"
    db.flush()
    headers = H.login(client, chain["admin"])

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=chain["version"].id,
        ),
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_82_system_admin_can_create(client, db, provider):
    chain = H.build_chain(db)
    system_admin = H.make_user(db, global_role="system_admin")

    created = _create_analysis(client, chain, H.login(client, system_admin), provider)
    assert created["status"] == "succeeded"
