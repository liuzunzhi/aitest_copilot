"""AC-116 · 只读模板列表与 05 联动。

`GET /api/prompt-templates` 给普通成员用：

- **只返回 `status='active'`** 的模板；
- **不含 Prompt 正文**（普通成员没有管理权限）；
- 登录即可访问，不要求系统管理员；
- 05 项目页的下拉靠它动态渲染。
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.incremental import PromptTemplate
from app.models.user import User

PASSWORD = "LlmAdminPass1"
PASSWORD_HASH = hash_password(PASSWORD)

READONLY = "/api/prompt-templates"


def _member(db: Session) -> User:
    user = User(
        username=f"ro-member-{uuid.uuid4().hex[:8]}",
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
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.name == "增量分析·第一遍·章节局部",
        )
    )
    assert template is not None, "迁移 0013 应播种一条 incremental 模板"
    return template


def test_ac_116_member_can_read(client: TestClient, db: Session):
    """普通成员登录即可访问。"""
    headers = _login(client, _member(db))

    response = client.get(READONLY, headers=headers)

    assert response.status_code == 200, response.text
    assert "items" in response.json()


def test_ac_116_anonymous_rejected(client: TestClient, db: Session):
    """未登录 → 401。"""
    assert client.get(READONLY).status_code == 401


def test_ac_116_only_active_templates(client: TestClient, db: Session):
    """只返回 active 的模板。"""
    headers = _login(client, _member(db))
    template = _seed(db)
    template.status = "disabled"
    db.flush()

    response = client.get(READONLY, headers=headers)

    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert template.id not in ids


def test_ac_116_filters_by_task_type(client: TestClient, db: Session):
    """按 task_type 筛选。"""
    headers = _login(client, _member(db))
    _seed(db)

    response = client.get(
        READONLY, params={"task_type": "incremental"}, headers=headers
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    assert all(item["task_type"] == "incremental" for item in items)


def test_ac_116_excludes_prompt_body(client: TestClient, db: Session):
    """**不含 Prompt 正文**。"""
    headers = _login(client, _member(db))
    _seed(db)

    response = client.get(READONLY, headers=headers)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    for item in items:
        assert "system_prompt" not in item
        assert "user_prompt" not in item
        assert {"id", "name", "task_type", "version_no", "description"} <= set(item)


def test_ac_116_response_text_has_no_prompt_body(client: TestClient, db: Session):
    """整个响应体里都不含 Prompt 正文。"""
    headers = _login(client, _member(db))
    template = _seed(db)

    response = client.get(READONLY, headers=headers)

    assert response.status_code == 200, response.text
    assert template.system_prompt not in response.text
    assert template.user_prompt not in response.text


def test_ac_116_two_templates_render_two_items(client: TestClient, db: Session):
    """接口返回的条数随模板变化——05 项目页下拉按这个渲染。

    迁移已经播种了两条 incremental 模板（第一遍 / 第二遍），
    所以这里断言的是「加一条 → 列表多一项」，而不是绝对条数。
    """
    headers = _login(client, _member(db))
    _seed(db)
    before = len(
        client.get(
            READONLY, params={"task_type": "incremental"}, headers=headers
        ).json()["items"]
    )

    db.add(
        PromptTemplate(
            name="测试用第二模板",
            task_type="incremental",
            description="联调用",
            system_prompt="[S] 系统",
            user_prompt="[U] 用户",
            version_no=1,
            status="active",
        )
    )
    db.flush()

    response = client.get(
        READONLY, params={"task_type": "incremental"}, headers=headers
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == before + 1
    assert all(item["task_type"] == "incremental" for item in items)


def test_ac_116_disabled_template_disappears(client: TestClient, db: Session):
    """停用某模板后 → 列表不再出现该项（05 下拉也不再出现）。"""
    headers = _login(client, _member(db))
    template = _seed(db)

    before = client.get(
        READONLY, params={"task_type": "incremental"}, headers=headers
    ).json()["items"]
    assert template.id in {item["id"] for item in before}

    template.status = "disabled"
    db.flush()

    after = client.get(
        READONLY, params={"task_type": "incremental"}, headers=headers
    ).json()["items"]
    assert template.id not in {item["id"] for item in after}
