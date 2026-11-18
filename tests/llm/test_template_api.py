"""AC-115 · 提示词模板管理接口。

要点：

- 列表**不含 Prompt 正文**，详情含全文；
- **版本自增只看正文**：正文变了才 `version_no += 1`，
  只改 `description` / `status` **不**升版本；
- `task_type` **不可改**；
- **没有新建 / 删除接口**；
- 非系统管理员 → 403。
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.incremental import PromptTemplate
from app.models.system import AuditLog
from app.models.user import User

PASSWORD = "LlmAdminPass1"
PASSWORD_HASH = hash_password(PASSWORD)

TEMPLATES = "/api/admin/prompt-templates"


def _admin(db: Session) -> User:
    user = User(
        username=f"tpl-admin-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role="system_admin",
    )
    db.add(user)
    db.flush()
    return user


def _member(db: Session) -> User:
    user = User(
        username=f"tpl-member-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role="user",
    )
    db.add(user)
    db.flush()
    return user


def _login(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed(db: Session) -> PromptTemplate:
    """迁移 0013 播种的第一遍模板。"""
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.name == "增量分析·第一遍·章节局部",
        )
    )
    assert template is not None, "迁移 0013 应播种一条 incremental 模板"
    return template


# ------------------------------------------------------------ 列表


def test_ac_115_list_excludes_prompt_body(client: TestClient, db: Session):
    """列表项**不含 Prompt 正文**。"""
    headers = _login(client, _admin(db))
    _seed(db)

    response = client.get(TEMPLATES, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 1
    assert body["page"] == 1
    item = body["items"][0]
    assert "system_prompt" not in item
    assert "user_prompt" not in item
    assert {"id", "name", "task_type", "version_no", "status"} <= set(item)


def test_ac_115_list_filters_by_task_type(client: TestClient, db: Session):
    """按 task_type 筛选。"""
    headers = _login(client, _admin(db))
    _seed(db)

    response = client.get(
        TEMPLATES, params={"task_type": "incremental"}, headers=headers
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    assert all(item["task_type"] == "incremental" for item in items)


def test_ac_115_list_filters_by_status(client: TestClient, db: Session):
    """按 status 筛选。"""
    headers = _login(client, _admin(db))
    template = _seed(db)
    template.status = "disabled"
    db.flush()

    response = client.get(TEMPLATES, params={"status": "disabled"}, headers=headers)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert all(item["status"] == "disabled" for item in items)


def test_ac_115_list_paginates(client: TestClient, db: Session):
    """分页信封。"""
    headers = _login(client, _admin(db))
    _seed(db)

    response = client.get(
        TEMPLATES, params={"page": 1, "page_size": 1}, headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert body["page_size"] == 1
    assert body["total"] >= 1


# ------------------------------------------------------------ 详情


def test_ac_115_detail_includes_prompt_body(client: TestClient, db: Session):
    """详情含完整 System / User Prompt。"""
    headers = _login(client, _admin(db))
    template = _seed(db)

    response = client.get(f"{TEMPLATES}/{template.id}", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["system_prompt"] == template.system_prompt
    assert body["user_prompt"] == template.user_prompt
    assert body["version_no"] == template.version_no


def test_ac_115_missing_template_returns_404(client: TestClient, db: Session):
    """模板不存在 → 404 PROMPT_TEMPLATE_NOT_FOUND。"""
    headers = _login(client, _admin(db))

    response = client.get(f"{TEMPLATES}/999999", headers=headers)

    assert response.status_code == 404
    assert response.json()["code"] == "PROMPT_TEMPLATE_NOT_FOUND"


# ------------------------------------------------------------ 编辑


def test_ac_115_edit_prompt_bumps_version(client: TestClient, db: Session):
    """改 System Prompt → `version_no` +1。"""
    headers = _login(client, _admin(db))
    template = _seed(db)
    before = template.version_no

    response = client.put(
        f"{TEMPLATES}/{template.id}",
        json={"system_prompt": "[NEW] 改过的系统提示词"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["version_no"] == before + 1


def test_ac_115_edit_user_prompt_bumps_version(client: TestClient, db: Session):
    """改 User Prompt → `version_no` +1。"""
    headers = _login(client, _admin(db))
    template = _seed(db)
    before = template.version_no

    response = client.put(
        f"{TEMPLATES}/{template.id}",
        json={"user_prompt": "[NEW] 改过的用户提示词"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["version_no"] == before + 1


def test_ac_115_edit_description_only_does_not_bump_version(client: TestClient, db: Session):
    """只改描述 → **不**升版本。"""
    headers = _login(client, _admin(db))
    template = _seed(db)
    before = template.version_no

    response = client.put(
        f"{TEMPLATES}/{template.id}",
        json={"description": "只改描述"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["version_no"] == before
    assert response.json()["description"] == "只改描述"


def test_ac_115_edit_status_only_does_not_bump_version(client: TestClient, db: Session):
    """只改状态 → **不**升版本。"""
    headers = _login(client, _admin(db))
    template = _seed(db)
    before = template.version_no

    response = client.put(
        f"{TEMPLATES}/{template.id}", json={"status": "disabled"}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["version_no"] == before
    assert response.json()["status"] == "disabled"


def test_ac_115_edit_same_prompt_does_not_bump_version(client: TestClient, db: Session):
    """提交**相同**的正文 → 不升版本（内容没变）。"""
    headers = _login(client, _admin(db))
    template = _seed(db)
    before = template.version_no

    response = client.put(
        f"{TEMPLATES}/{template.id}",
        json={"system_prompt": template.system_prompt},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["version_no"] == before


def test_ac_115_task_type_is_not_editable(client: TestClient, db: Session):
    """`task_type` 不可改——传了也不生效。"""
    headers = _login(client, _admin(db))
    template = _seed(db)

    response = client.put(
        f"{TEMPLATES}/{template.id}",
        json={"task_type": "test_case"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_type"] == template.task_type


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"system_prompt": ""}, "System Prompt 为空"),
        ({"user_prompt": ""}, "User Prompt 为空"),
        ({"system_prompt": "   "}, "System Prompt 空白"),
        ({"system_prompt": "x" * 60001}, "System Prompt 超长"),
        ({"user_prompt": "x" * 60001}, "User Prompt 超长"),
        ({"status": "paused"}, "status 非法"),
        ({"name": ""}, "名称为空"),
    ],
)
def test_ac_115_invalid_input_returns_400(
    client: TestClient, db: Session, payload: dict, reason: str
):
    """非法输入 → 400 PROMPT_TEMPLATE_INVALID（不是 422）。"""
    headers = _login(client, _admin(db))
    template = _seed(db)

    response = client.put(
        f"{TEMPLATES}/{template.id}", json=payload, headers=headers
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROMPT_TEMPLATE_INVALID"


def test_ac_115_duplicate_name_returns_409(client: TestClient, db: Session):
    """同 task_type 下重名 → 409 PROMPT_TEMPLATE_NAME_TAKEN。"""
    headers = _login(client, _admin(db))
    template = _seed(db)
    other = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.id != template.id,
        )
    )
    assert other is not None

    response = client.put(
        f"{TEMPLATES}/{template.id}", json={"name": other.name}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROMPT_TEMPLATE_NAME_TAKEN"


def test_ac_115_missing_template_returns_404_on_edit(client: TestClient, db: Session):
    """编辑不存在的模板 → 404。"""
    headers = _login(client, _admin(db))

    response = client.put(
        f"{TEMPLATES}/999999", json={"description": "x"}, headers=headers
    )

    assert response.status_code == 404
    assert response.json()["code"] == "PROMPT_TEMPLATE_NOT_FOUND"


# ------------------------------------------------------------ 路由不存在


def test_ac_115_no_create_route(client: TestClient, db: Session):
    """**没有新建接口**（路由不存在 → 405 / 404）。"""
    headers = _login(client, _admin(db))

    response = client.post(
        TEMPLATES,
        json={
            "name": "新模板",
            "task_type": "incremental",
            "system_prompt": "s",
            "user_prompt": "u",
        },
        headers=headers,
    )

    assert response.status_code in (404, 405)


def test_ac_115_no_delete_route(client: TestClient, db: Session):
    """**没有删除接口**。"""
    headers = _login(client, _admin(db))
    template = _seed(db)

    response = client.delete(f"{TEMPLATES}/{template.id}", headers=headers)

    assert response.status_code in (404, 405)


# ------------------------------------------------------------ 权限与审计


def test_ac_115_non_admin_forbidden(client: TestClient, db: Session):
    """非系统管理员 → 403。"""
    headers = _login(client, _member(db))
    template = _seed(db)

    assert client.get(TEMPLATES, headers=headers).status_code == 403
    assert client.get(f"{TEMPLATES}/{template.id}", headers=headers).status_code == 403
    assert (
        client.put(
            f"{TEMPLATES}/{template.id}", json={"description": "x"}, headers=headers
        ).status_code
        == 403
    )


def test_ac_115_anonymous_rejected(client: TestClient, db: Session):
    """未登录 → 401。"""
    assert client.get(TEMPLATES).status_code == 401


def test_ac_115_update_writes_audit(client: TestClient, db: Session):
    """编辑 → 写 `prompt_template.update`，before + after 含 Prompt 正文。"""
    headers = _login(client, _admin(db))
    template = _seed(db)
    # 同一 session 里的 ORM 对象会被就地改掉，先把原值存下来
    original = template.system_prompt

    client.put(
        f"{TEMPLATES}/{template.id}",
        json={"system_prompt": "[NEW] 审计用提示词"},
        headers=headers,
    )

    log = db.scalar(
        select(AuditLog).where(AuditLog.action == "prompt_template.update")
    )
    assert log is not None
    assert log.target_type == "prompt_template"
    assert log.target_id == str(template.id)
    assert log.before_data["system_prompt"] == original
    assert log.after_data["system_prompt"] == "[NEW] 审计用提示词"


def test_ac_115_failed_update_writes_no_audit(client: TestClient, db: Session):
    """校验失败 → 不写审计。"""
    headers = _login(client, _admin(db))
    template = _seed(db)

    response = client.put(
        f"{TEMPLATES}/{template.id}", json={"status": "paused"}, headers=headers
    )

    assert response.status_code == 400
    assert (
        db.scalar(
            select(AuditLog).where(AuditLog.action == "prompt_template.update")
        )
        is None
    )
