"""AC-152 / AC-153：测试点接口的权限矩阵与校验顺序。

**校验顺序是硬要求**（spec §6.2）：
项目 404 → 归档 409 → 角色 403 → 模板 400 → …

也就是说：**归档项目 + member 身份**必须先报 409（归档），
不能报 403（角色）——否则用权限错误掩盖了归档状态。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.test_point import TestPointAnalysis
from tests.test_points import helpers as H


def _payload(chain: dict) -> dict:
    return {
        "template_id": chain["template"].id,
        "baseline_revision_id": chain["revision"].id,
        "document_version_id": chain["version"].id,
    }


def _label_chain(db: Session, chain: dict) -> int:
    function = chain["structure"]["function"]
    H.make_label(
        db,
        chain["project"],
        chain["revision"],
        chain["admin"],
        target_id=function.id,
        label_type="changed",
    )
    return function.id


def test_ac_152_read_permissions(client, db, provider):
    """member / guest / system_admin 都能读；非成员 403。"""
    chain = H.build_chain(db)
    _label_chain(db, chain)
    member = H.make_user(db)
    guest = H.make_user(db)
    outsider = H.make_user(db)
    system_admin = H.make_user(db, global_role="system_admin")
    H.add_member(db, chain["project"], member, "member")
    H.add_member(db, chain["project"], guest, "guest")

    base = H.BASE.format(project_id=chain["project"].id)
    paths = [
        f"{base}/analyses",
        f"{base}/points",
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


def test_ac_152_guest_cannot_generate(client, db, provider):
    """访客发起生成 → 403 `NOT_PROJECT_ADMIN`。"""
    chain = H.build_chain(db)
    _label_chain(db, chain)
    guest = H.make_user(db)
    H.add_member(db, chain["project"], guest, "guest")
    headers = H.login(client, guest)

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_152_outsider_cannot_write(client, db, provider):
    """非成员写接口 → 403 `NOT_PROJECT_ADMIN`。

    **与读接口不同**：读接口非成员报 `NOT_PROJECT_MEMBER`，
    写接口统一报 `NOT_PROJECT_ADMIN`——区分「非成员」与「角色不符」
    会泄露项目是否存在（05 的 `ensure_admin` 注释里明写了这条）。
    """
    chain = H.build_chain(db)
    _label_chain(db, chain)
    outsider = H.make_user(db)
    headers = H.login(client, outsider)

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_152_system_admin_can_generate(client, db, provider):
    """系统管理员兜底可以发起。"""
    chain = H.build_chain(db)
    function_id = _label_chain(db, chain)
    system_admin = H.make_user(db, global_role="system_admin")
    headers = H.login(client, system_admin)
    provider.queue = [H.point_response(target_id=function_id)]

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 201, response.text


def test_ac_153_archived_beats_role_check(client, db, provider):
    """**归档优先于角色**：归档项目 + member → 409，不是 403。

    「先判归档再判角色」是 04 定下的约定：
    顺序只有一个出处（`app/common/permissions.py`）。
    """
    chain = H.build_chain(db, project_status="archived")
    _label_chain(db, chain)
    member = H.make_user(db)
    H.add_member(db, chain["project"], member, "member")
    headers = H.login(client, member)

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_153_missing_project_beats_role_check(client, db, provider):
    """**项目不存在优先于角色**：非成员访问不存在的项目 → 404，不是 403。

    先判 404 是为了不泄露「项目是否存在」——
    但项目根本不存在时，报 404 是唯一诚实的答案。
    """
    chain = H.build_chain(db)
    outsider = H.make_user(db)
    headers = H.login(client, outsider)

    response = client.post(
        H.ANALYSES.format(project_id=99_999_999),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


def test_ac_152_role_check_beats_template_check(client, db, provider):
    """**角色优先于模板**：member + 停用模板 → 403，不是 400。

    顺序是 404 → 409 → 403 → 400：角色在模板前面。
    """
    chain = H.build_chain(db)
    _label_chain(db, chain)
    member = H.make_user(db)
    H.add_member(db, chain["project"], member, "member")
    headers = H.login(client, member)
    chain["template"].status = "disabled"
    db.flush()

    response = client.post(
        H.ANALYSES.format(project_id=chain["project"].id),
        json=_payload(chain),
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"
