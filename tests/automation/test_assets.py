"""扫描入库与资产维护（09-automation T112 / AC-183 / AC-184 / AC-189 / AC-192）。

四组关注点：

1. **扫描不写表**（AC-183）：扫完 `automation_assets` 行数不变。
2. **人工确认后入库**（AC-184）：服务端重扫重算、同路径不重复入库、
   再次扫描标 `existing`。
3. **资产 CRUD 与关联用例**（AC-184）：关联 / 解绑、越权关联被拒。
4. **权限与审计**（AC-189 / AC-192）：成员只读、审计写入、失败不写审计。
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.models.automation import AutomationAsset
from app.models.system import AuditLog

from tests.automation.helpers import (
    ASSETS,
    SCAN,
    add_member,
    login,
    make_case,
    make_project,
    make_user,
    pytest_file,
    seed_root,
)

# 当前用例的扫描根目录（由 `_automation_root` 夹具设置）。
_ROOT: Path | None = None


@pytest.fixture(autouse=True)
def _automation_root(tmp_path: Path, monkeypatch):
    """把 `AUTOMATION_ROOT` 指到 `tmp_path`，不碰开发库的真实目录。

    根目录路径记在模块级 `_ROOT` 上——用例里的 `_write` 直接用它，
    不用给每个用例都加一个 fixture 参数。
    """
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


def _write(root: Path | None, relative: str, content: str) -> None:
    assert root is not None
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _asset_count(db: Session, project_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(AutomationAsset)
        .where(AutomationAsset.project_id == project_id)
    )


def _audits(db: Session, project_id: int, action: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id, AuditLog.action == action
            )
        ).all()
    )


# ------------------------------------------------------------- 扫描


def test_ac_183_scan_returns_manifest_without_writing(db, client):
    """扫描**只出清单，不写表**——`automation_assets` 行数不变。"""
    chain = _chain(db)
    project_id = chain["project"].id
    _write(_ROOT, "test_a.py", pytest_file(2))
    _write(_ROOT, "readme.md", "# 说明\n")

    before = _asset_count(db, project_id)
    response = client.post(
        SCAN.format(project_id=project_id),
        json={"directory": ""},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scanned_files"] == 2
    assert payload["matched"] == 1
    assert payload["skipped"] == 1
    assert payload["assets"][0]["file_path"] == "test_a.py"
    assert payload["assets"][0]["parse_confidence"] == 0.95
    assert payload["assets"][0]["detected_cases"] == 2
    assert payload["assets"][0]["status"] == "new"
    assert _asset_count(db, project_id) == before


def test_ac_182_scan_rejects_traversal(db, client):
    """目录越界 → 400 `AUTOMATION_SCAN_PATH_INVALID`，**不扫描任何文件**。"""
    chain = _chain(db)
    project_id = chain["project"].id
    root = _ROOT
    _write(root, "test_a.py", pytest_file(1))
    before = _asset_count(db, project_id)

    response = client.post(
        SCAN.format(project_id=project_id),
        json={"directory": "../../etc"},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_SCAN_PATH_INVALID"
    assert _asset_count(db, project_id) == before


def test_ac_182_scan_rejects_absolute_path(db, client, tmp_path):
    """绝对路径 → 400 `AUTOMATION_SCAN_PATH_INVALID`。"""
    chain = _chain(db)
    outside = tmp_path / "outside"
    outside.mkdir()

    response = client.post(
        SCAN.format(project_id=chain["project"].id),
        json={"directory": str(outside)},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_SCAN_PATH_INVALID"


def test_ac_182_response_does_not_leak_absolute_root(db, client):
    """响应**不含** `AUTOMATION_ROOT` 的绝对路径。

    绝对路径会泄露服务器目录结构——响应里只给相对展示名。
    """
    chain = _chain(db)
    root = _ROOT
    _write(root, "test_a.py", pytest_file(1))

    response = client.post(
        SCAN.format(project_id=chain["project"].id),
        json={"directory": ""},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 200
    body = response.text
    assert str(root) not in body
    # 只给相对展示名（测试里 root 在 tmp_path 下 → 只给最后一段）
    assert response.json()["root"] == "automation"


def test_ac_183_scan_marks_existing_assets(db, client):
    """再次扫描 → 已入库项 `status='existing'` 且带 `existing_asset_id`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    root = _ROOT
    _write(root, "test_a.py", pytest_file(2))

    created = client.post(
        ASSETS.format(project_id=project_id),
        json={
            "assets": [
                {"file_path": "test_a.py", "name": "test_a.py", "framework": "pytest"}
            ]
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    asset_id = created.json()["items"][0]["asset_id"]

    response = client.post(
        SCAN.format(project_id=project_id),
        json={"directory": ""},
        headers=headers,
    )

    assert response.status_code == 200
    item = response.json()["assets"][0]
    assert item["status"] == "existing"
    assert item["existing_asset_id"] == asset_id


# ------------------------------------------------------------- 入库


def test_ac_184_confirm_creates_assets(db, client):
    """人工确认后入库 → 新增资产行，`source='scanned'`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    root = _ROOT
    _write(root, "test_a.py", pytest_file(3))
    _write(root, "login.spec.ts", "test('a', async () => {});\n")

    response = client.post(
        ASSETS.format(project_id=project_id),
        json={
            "assets": [
                {"file_path": "test_a.py", "name": "test_a.py", "framework": "pytest"},
                {
                    "file_path": "login.spec.ts",
                    "name": "login.spec.ts",
                    "framework": "playwright",
                },
            ]
        },
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["created"] == 2
    assert payload["skipped"] == 0

    rows = list(
        db.scalars(
            select(AutomationAsset)
            .where(AutomationAsset.project_id == project_id)
            .order_by(AutomationAsset.id)
        ).all()
    )
    assert len(rows) == 2
    assert rows[0].source == "scanned"
    assert float(rows[0].parse_confidence) == 0.95
    assert rows[0].detected_cases == 3
    assert rows[1].framework == "playwright"
    assert float(rows[1].parse_confidence) == 0.95
    assert rows[1].detected_cases == 1


def test_ac_184_server_recomputes_confidence(db, client):
    """入库时服务端**重算**置信度与用例数——不采信前端传的值。

    前端传 0.99 / 99，实际文件只有 1 个测试函数 → 库里存 0.95 / 1。
    """
    chain = _chain(db)
    project_id = chain["project"].id
    root = _ROOT
    _write(root, "test_a.py", pytest_file(1))

    response = client.post(
        ASSETS.format(project_id=project_id),
        json={
            "assets": [
                {
                    "file_path": "test_a.py",
                    "name": "test_a.py",
                    "framework": "pytest",
                    "parse_confidence": 0.99,
                    "detected_cases": 99,
                }
            ]
        },
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 201, response.text
    row = db.scalar(
        select(AutomationAsset).where(AutomationAsset.project_id == project_id)
    )
    assert float(row.parse_confidence) == 0.95
    assert row.detected_cases == 1


def test_ac_184_duplicate_path_is_skipped(db, client):
    """同路径重复入库 → 不新增行，返回 `skipped` 计数。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    root = _ROOT
    _write(root, "test_a.py", pytest_file(1))

    body = {
        "assets": [
            {"file_path": "test_a.py", "name": "test_a.py", "framework": "pytest"}
        ]
    }
    first = client.post(
        ASSETS.format(project_id=project_id), json=body, headers=headers
    )
    assert first.status_code == 201, first.text
    assert first.json()["created"] == 1

    second = client.post(
        ASSETS.format(project_id=project_id), json=body, headers=headers
    )
    assert second.status_code == 201, second.text
    assert second.json()["created"] == 0
    assert second.json()["skipped"] == 1
    assert _asset_count(db, project_id) == 1


def test_ac_184_invalid_framework_is_rejected(db, client):
    """框架非法 → 400 `AUTOMATION_ASSET_INVALID`，不写表。"""
    chain = _chain(db)
    project_id = chain["project"].id

    response = client.post(
        ASSETS.format(project_id=project_id),
        json={"assets": [{"file_path": "x.py", "framework": "selenium"}]},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_ASSET_INVALID"
    assert _asset_count(db, project_id) == 0


def test_ac_184_empty_path_is_rejected(db, client):
    """路径为空 → 400 `AUTOMATION_ASSET_INVALID`。"""
    chain = _chain(db)

    response = client.post(
        ASSETS.format(project_id=chain["project"].id),
        json={"assets": [{"file_path": "  ", "framework": "pytest"}]},
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_ASSET_INVALID"


def test_ac_184_path_outside_root_is_rejected(db, client):
    """入库路径越界 → 400 `AUTOMATION_SCAN_PATH_INVALID`，不写表。

    入库的路径同样不能越界——否则等于往库里塞一个任意路径引用。
    """
    chain = _chain(db)
    project_id = chain["project"].id

    response = client.post(
        ASSETS.format(project_id=project_id),
        json={
            "assets": [
                {"file_path": "../../etc/passwd", "framework": "pytest"},
            ]
        },
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_SCAN_PATH_INVALID"
    assert _asset_count(db, project_id) == 0


def test_ac_184_skipped_by_user_is_not_created(db, client):
    """前端标 `skip` 的项 → 不入库，计入 `skipped`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    root = _ROOT
    _write(root, "test_a.py", pytest_file(1))

    response = client.post(
        ASSETS.format(project_id=project_id),
        json={
            "assets": [
                {
                    "file_path": "test_a.py",
                    "name": "test_a.py",
                    "framework": "pytest",
                    "skip": True,
                }
            ]
        },
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 201, response.text
    assert response.json()["created"] == 0
    assert response.json()["skipped"] == 1
    assert _asset_count(db, project_id) == 0


def test_ac_184_unrecognized_file_is_skipped(db, client):
    """文件识别不出来 → 跳过（`reason='unrecognized'`），不写表。"""
    chain = _chain(db)
    project_id = chain["project"].id
    root = _ROOT
    _write(root, "readme.md", "# 说明\n")

    response = client.post(
        ASSETS.format(project_id=project_id),
        json={
            "assets": [
                {"file_path": "readme.md", "name": "readme.md", "framework": "pytest"}
            ]
        },
        headers=login(client, chain["admin"]),
    )

    assert response.status_code == 201, response.text
    assert response.json()["created"] == 0
    assert response.json()["skipped"] == 1
    assert response.json()["items"][0]["reason"] == "unrecognized"
    assert _asset_count(db, project_id) == 0


# ------------------------------------------------------------- 资产 CRUD


def _create_asset(db: Session, client, chain: dict, relative: str = "test_a.py") -> int:
    root = _ROOT
    _write(root, relative, pytest_file(1))
    response = client.post(
        ASSETS.format(project_id=chain["project"].id),
        json={
            "assets": [
                {"file_path": relative, "name": relative, "framework": "pytest"}
            ]
        },
        headers=login(client, chain["admin"]),
    )
    assert response.status_code == 201, response.text
    return response.json()["items"][0]["asset_id"]


def test_ac_184_link_and_unlink_case(db, client):
    """关联用例 → 可解绑。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain)
    case_id = make_case(db, chain["project"], chain["admin"])

    linked = client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"linked_case_id": case_id},
        headers=headers,
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["linked_case_id"] == case_id
    assert linked.json()["linked_case_title"] == "连续输错密码 5 次后账号锁定"

    unlinked = client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"linked_case_id": None},
        headers=headers,
    )
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["linked_case_id"] is None


def test_ac_184_link_case_from_other_project_is_rejected(db, client):
    """关联**别的项目**的用例 → 400 `AUTOMATION_ASSET_INVALID`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain)

    other = make_project(db)
    other_case_id = make_case(db, other, chain["admin"])

    response = client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"linked_case_id": other_case_id},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_ASSET_INVALID"


def test_ac_184_archive_asset(db, client):
    """归档资产 → `status='archived'`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain)

    response = client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"status": "archived"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "archived"


def test_ac_184_invalid_status_is_rejected(db, client):
    """非法状态 → 400 `AUTOMATION_ASSET_INVALID`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain)

    response = client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"status": "deleted"},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_ASSET_INVALID"


def test_ac_184_unknown_field_is_rejected(db, client):
    """多余字段 → 400 `AUTOMATION_ASSET_INVALID`（不默默丢掉）。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain)

    response = client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"framework": "playwright"},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "AUTOMATION_ASSET_INVALID"


def test_ac_184_asset_not_found(db, client):
    """资产不存在 → 404 `AUTOMATION_ASSET_NOT_FOUND`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])

    response = client.get(
        f"{ASSETS.format(project_id=project_id)}/999999", headers=headers
    )
    assert response.status_code == 404
    assert response.json()["code"] == "AUTOMATION_ASSET_NOT_FOUND"


def test_ac_184_asset_of_other_project_is_not_visible(db, client):
    """**别的项目**的资产 → 读不到。

    读接口先判「是不是本项目成员」（403 `NOT_PROJECT_MEMBER`），
    再判资产在不在本项目（404）——顺序与 04 / 05 / 07 / 08 一致。
    """
    chain = _chain(db)
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain)

    other = make_project(db)
    response = client.get(
        f"{ASSETS.format(project_id=other.id)}/{asset_id}", headers=headers
    )
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_192_asset_list_is_filterable(db, client):
    """资产列表按框架 / 状态筛选。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain)

    listed = client.get(ASSETS.format(project_id=project_id), headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == asset_id

    filtered = client.get(
        f"{ASSETS.format(project_id=project_id)}?framework=playwright", headers=headers
    )
    assert filtered.json()["total"] == 0


# ------------------------------------------------------------- 权限与审计


def test_ac_189_member_cannot_scan_or_confirm(db, client):
    """成员发起扫描 / 入库 → 403 `NOT_PROJECT_ADMIN`。"""
    chain = _chain(db, role="member")
    project_id = chain["project"].id
    headers = login(client, chain["admin"])

    scanned = client.post(
        SCAN.format(project_id=project_id), json={"directory": ""}, headers=headers
    )
    assert scanned.status_code == 403
    assert scanned.json()["code"] == "NOT_PROJECT_ADMIN"

    confirmed = client.post(
        ASSETS.format(project_id=project_id),
        json={"assets": [{"file_path": "x.py", "framework": "pytest"}]},
        headers=headers,
    )
    assert confirmed.status_code == 403
    assert confirmed.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_189_member_can_read_assets(db, client):
    """成员读资产列表 / 详情 → 200。

    资产由**管理员**先入库（入库是管理员权限），成员只读。
    """
    admin_chain = _chain(db)
    project_id = admin_chain["project"].id
    asset_id = _create_asset(db, client, admin_chain)

    member = make_user(db)
    add_member(db, admin_chain["project"], member, "member")
    headers = login(client, member)

    listed = client.get(ASSETS.format(project_id=project_id), headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    detail = client.get(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}", headers=headers
    )
    assert detail.status_code == 200


def test_ac_189_non_member_cannot_read(db, client):
    """非项目成员读资产列表 → 403 `NOT_PROJECT_MEMBER`。"""
    chain = _chain(db)
    outsider = make_user(db)

    response = client.get(
        ASSETS.format(project_id=chain["project"].id),
        headers=login(client, outsider),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_190_archived_project_rejects_scan_but_allows_read(db, client):
    """归档项目：扫描 / 入库 → 409 `PROJECT_ARCHIVED`，读接口仍 200。"""
    chain = _chain(db, project_status="archived")
    project_id = chain["project"].id
    headers = login(client, chain["admin"])

    scanned = client.post(
        SCAN.format(project_id=project_id), json={"directory": ""}, headers=headers
    )
    assert scanned.status_code == 409
    assert scanned.json()["code"] == "PROJECT_ARCHIVED"

    confirmed = client.post(
        ASSETS.format(project_id=project_id),
        json={"assets": [{"file_path": "x.py", "framework": "pytest"}]},
        headers=headers,
    )
    assert confirmed.status_code == 409
    assert confirmed.json()["code"] == "PROJECT_ARCHIVED"

    listed = client.get(ASSETS.format(project_id=project_id), headers=headers)
    assert listed.status_code == 200


def test_ac_190_archive_check_precedes_role_check(db, client):
    """校验顺序「归档 409 先于角色 403」：普通成员在归档项目里也看到 409。"""
    chain = _chain(db, role="member", project_status="archived")
    headers = login(client, chain["admin"])

    response = client.post(
        SCAN.format(project_id=chain["project"].id),
        json={"directory": ""},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_192_scan_writes_audit(db, client):
    """扫描写审计 `automation.scan`，含目录与统计。"""
    chain = _chain(db)
    project_id = chain["project"].id
    root = _ROOT
    _write(root, "test_a.py", pytest_file(1))

    client.post(
        SCAN.format(project_id=project_id),
        json={"directory": ""},
        headers=login(client, chain["admin"]),
    )

    audits = _audits(db, project_id, "automation.scan")
    assert len(audits) == 1
    assert audits[0].after_data["matched"] == 1
    assert audits[0].after_data["scanned_files"] == 1


def test_ac_192_confirm_writes_audit(db, client):
    """入库写审计 `automation.asset.create`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    root = _ROOT
    _write(root, "test_a.py", pytest_file(1))

    client.post(
        ASSETS.format(project_id=project_id),
        json={
            "assets": [
                {"file_path": "test_a.py", "name": "test_a.py", "framework": "pytest"}
            ]
        },
        headers=login(client, chain["admin"]),
    )

    audits = _audits(db, project_id, "automation.asset.create")
    assert len(audits) == 1
    assert audits[0].after_data["created"] == 1
    assert audits[0].after_data["skipped"] == 0


def test_ac_192_update_writes_audit(db, client):
    """改资产写审计 `automation.asset.update`。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])
    asset_id = _create_asset(db, client, chain)

    client.patch(
        f"{ASSETS.format(project_id=project_id)}/{asset_id}",
        json={"status": "archived"},
        headers=headers,
    )

    audits = _audits(db, project_id, "automation.asset.update")
    assert len(audits) == 1
    assert audits[0].target_id == str(asset_id)
    assert audits[0].before_data["status"] == "active"
    assert audits[0].after_data["status"] == "archived"


def test_ac_192_failed_operations_write_no_audit(db, client):
    """失败操作不写审计（目录越界 / 越权）。"""
    chain = _chain(db)
    project_id = chain["project"].id
    headers = login(client, chain["admin"])

    client.post(
        SCAN.format(project_id=project_id),
        json={"directory": "../../etc"},
        headers=headers,
    )
    assert _audits(db, project_id, "automation.scan") == []

    client.post(
        ASSETS.format(project_id=project_id),
        json={"assets": [{"file_path": "x.py", "framework": "selenium"}]},
        headers=headers,
    )
    assert _audits(db, project_id, "automation.asset.create") == []
