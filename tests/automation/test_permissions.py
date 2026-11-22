"""执行接口的权限矩阵与归档语义（09-automation T114 / AC-189 / AC-190）。

四条红线：

1. **执行限项目管理员**——执行 pytest = 任意代码执行，
   风险等级与「发起生成」同级，成员只能**看报告**。
2. **读接口成员可读**——执行记录列表 / 单次报告对 member / guest 开放。
3. **非项目成员 → 403 `NOT_PROJECT_MEMBER`**；项目不存在 → 404。
4. **归档项目**：写接口 409 `PROJECT_ARCHIVED`，读接口 200；
   **归档先判、角色后判**（顺序与 04 / 05 / 07 / 08 一致）。
"""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.models.automation import AutomationRun

from tests.automation.helpers import (
    ASSETS,
    RUNS,
    add_member,
    login,
    make_project,
    make_user,
    pytest_file,
    seed_root,
)

_ROOT: Path | None = None


@pytest.fixture(autouse=True)
def _automation_root(tmp_path: Path, monkeypatch):
    """把 `AUTOMATION_ROOT` 指到 `tmp_path`，不碰开发库的真实目录。"""
    global _ROOT
    root = seed_root(tmp_path)
    _ROOT = root
    monkeypatch.setenv("AUTOMATION_ROOT", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()
    _ROOT = None


def _chain(db: Session, *, role: str = "project_admin", project_status: str = "active"):
    admin = make_user(db)
    project = make_project(db, status=project_status)
    add_member(db, project, admin, role)
    return {"admin": admin, "project": project}


def _create_asset(
    db: Session, client, project, *, relative: str = "test_a.py"
) -> int:
    """造一个资产并入库，返回资产 id。

    **入库是项目管理员权限**——所以这里用一个**管理员**账号操作。
    被测的「成员不能执行」是在「资产已存在」的前提下断言的，
    资产的建法不能污染被测角色。

    项目必须是 active（归档项目连入库都 400）。
    """
    owner = make_user(db)
    add_member(db, project, owner, "project_admin")

    assert _ROOT is not None
    path = _ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pytest_file(1), encoding="utf-8")
    response = client.post(
        ASSETS.format(project_id=project.id),
        json={"assets": [{"file_path": relative, "name": relative, "framework": "pytest"}]},
        headers=login(client, owner),
    )
    assert response.status_code == 201, response.text
    return response.json()["items"][0]["asset_id"]


def _run_count(db: Session, project_id: int) -> int:
    from sqlalchemy import func, select

    from app.models.automation import AutomationRun as Run

    return db.scalar(
        select(func.count()).select_from(Run).where(Run.project_id == project_id)
    )


# ------------------------------------------------------------- AC-189 权限


def test_ac_189_member_cannot_execute(db, client):
    """成员触发执行 → 403 `NOT_PROJECT_ADMIN`，**不产生执行记录**。"""
    chain = _chain(db, role="member")
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain["project"])

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"
    assert _run_count(db, project_id) == 0


def test_ac_189_guest_cannot_execute(db, client):
    """访客触发执行 → 403 `NOT_PROJECT_ADMIN`。"""
    chain = _chain(db, role="guest")
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain["project"])

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"
    assert _run_count(db, project_id) == 0


def test_ac_189_member_can_read_runs_and_report(db, client):
    """成员读执行记录列表 / 单次报告 → 200。

    成员**不能执行**，但**能看报告**——报告是团队共享的。
    """
    admin_chain = _chain(db)
    project_id = admin_chain["project"].id
    admin_headers = login(client, admin_chain["admin"])
    asset_id = _create_asset(db, client, admin_chain["project"])

    executed = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=admin_headers,
    )
    assert executed.status_code == 200, executed.text
    run_id = executed.json()["id"]

    member = make_user(db)
    add_member(db, admin_chain["project"], member, "member")
    member_headers = login(client, member)

    listed = client.get(RUNS.format(project_id=project_id), headers=member_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1

    report = client.get(
        f"{RUNS.format(project_id=project_id)}/{run_id}", headers=member_headers
    )
    assert report.status_code == 200, report.text
    assert len(report.json()["items"]) == 1


def test_ac_189_guest_can_read_runs(db, client):
    """访客读执行记录 → 200。"""
    admin_chain = _chain(db)
    project_id = admin_chain["project"].id
    asset_id = _create_asset(db, client, admin_chain["project"])

    guest = make_user(db)
    add_member(db, admin_chain["project"], guest, "guest")
    guest_headers = login(client, guest)

    listed = client.get(RUNS.format(project_id=project_id), headers=guest_headers)
    assert listed.status_code == 200, listed.text


def test_ac_189_non_member_cannot_read_runs(db, client):
    """非项目成员读执行记录 → 403 `NOT_PROJECT_MEMBER`。"""
    chain = _chain(db)
    outsider = make_user(db)

    response = client.get(
        RUNS.format(project_id=chain["project"].id),
        headers=login(client, outsider),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_189_non_member_cannot_read_report(db, client):
    """非项目成员读单次报告 → 403 `NOT_PROJECT_MEMBER`。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain["project"])
    executed = client.post(
        RUNS.format(project_id=chain["project"].id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )
    run_id = executed.json()["id"]

    outsider = make_user(db)
    response = client.get(
        f"{RUNS.format(project_id=chain['project'].id)}/{run_id}",
        headers=login(client, outsider),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_189_missing_project_is_404(db, client):
    """项目不存在 → 404 `PROJECT_NOT_FOUND`（**不是** 403）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])

    response = client.get(RUNS.format(project_id=999999), headers=headers)

    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


# ------------------------------------------------------------- AC-190 归档


def test_ac_190_archived_project_rejects_execute(db, client):
    """归档项目触发执行 → 409 `PROJECT_ARCHIVED`，不产生执行记录。

    资产在**归档之前**建好——归档项目连入库都 400。
    """
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain["project"])

    chain["project"].status = "archived"
    db.flush()

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"
    assert _run_count(db, project_id) == 0


def test_ac_190_archived_project_allows_read(db, client):
    """归档项目读执行记录 → 200（读接口不受归档影响）。"""
    admin_chain = _chain(db)
    project_id = admin_chain["project"].id
    headers = login(client, admin_chain["admin"])
    asset_id = _create_asset(db, client, admin_chain["project"])

    executed = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )
    assert executed.status_code == 200, executed.text

    # 归档项目
    admin_chain["project"].status = "archived"
    db.flush()

    listed = client.get(RUNS.format(project_id=project_id), headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1


def test_ac_190_archive_check_precedes_role_check(db, client):
    """校验顺序「归档 409 先于角色 403」：普通成员在归档项目里也看到 409。

    先判归档再判角色，避免用权限错误掩盖归档状态——
    与 04 / 05 / 07 / 08 同一口径。
    """
    chain = _chain(db, role="member")
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain["project"])

    chain["project"].status = "archived"
    db.flush()

    response = client.post(
        RUNS.format(project_id=project_id),
        json={"asset_ids": [asset_id]},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_190_archived_project_missing_run_is_404(db, client):
    """归档项目读**不存在**的执行记录 → 404（不是 409）。

    归档只挡写接口；读接口照常走 404 语义。
    """
    chain = _chain(db, project_status="archived")
    response = client.get(
        f"{RUNS.format(project_id=chain['project'].id)}/999999",
        headers=login(client, chain["admin"]),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "AUTOMATION_RUN_NOT_FOUND"
