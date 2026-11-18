"""AC-113 · 大模型配置接口；AC-114 · 连通性测试；AC-105 · 明文边界。

三条贯穿全文件的硬约束：

1. **响应里只有掩码**——没有 `api_key`、没有 `api_key_ciphertext`，
   更没有明文；
2. **审计里也没有明文 / 密文**；
3. **连通性测试失败返回 200 + `ok=false`**，不抛 502。

连通性测试的 HTTP 行为一律走 `httpx.MockTransport`（通过
`dependency_overrides[provider_transport]` 注入），**零真实 socket**。
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.llm_admin.router import provider_transport
from app.models.llm import LLMProviderConfig, LLMRunLog
from app.models.system import AuditLog
from app.models.user import User

PASSWORD = "LlmAdminPass1"
PASSWORD_HASH = hash_password(PASSWORD)

PROVIDERS = "/api/admin/llm-providers"
FAKE_KEY = "sk-supersecret-1234"


def _admin(db: Session) -> User:
    user = User(
        username=f"llm-admin-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        global_role="system_admin",
    )
    db.add(user)
    db.flush()
    return user


def _member(db: Session) -> User:
    user = User(
        username=f"llm-member-{uuid.uuid4().hex[:8]}",
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


def _payload(**overrides) -> dict:
    body = {
        "name": "DeepSeek 生产",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": FAKE_KEY,
        "model": "deepseek-chat",
        "timeout_seconds": 60,
    }
    body.update(overrides)
    return body


def _create(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(PROVIDERS, json=_payload(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _mock_transport(handler) -> None:
    """把连通性测试的 transport 换成 MockTransport（零真实 socket）。"""

    def override():
        return httpx.MockTransport(handler)

    return override


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})


def _timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timeout", request=request)


# ------------------------------------------------------------ CRUD


def test_ac_113_create_returns_masked_only(client: TestClient, db: Session):
    """新建 → 201，响应只有掩码。"""
    headers = _login(client, _admin(db))

    body = _create(client, headers)

    assert body["api_key_masked"] == "sk-****1234"
    assert "api_key" not in body
    assert "api_key_ciphertext" not in body
    assert FAKE_KEY not in str(body)


def test_ac_113_create_persists_ciphertext_only(client: TestClient, db: Session):
    """库层：只存密文，不存明文。"""
    headers = _login(client, _admin(db))

    body = _create(client, headers)

    row = db.get(LLMProviderConfig, body["id"])
    assert row is not None
    assert row.api_key_ciphertext != FAKE_KEY
    assert FAKE_KEY not in row.api_key_ciphertext
    assert row.api_key_last4 == "1234"
    assert row.provider_type == "openai_compat"
    assert row.status == "active"
    assert row.is_default == 0


def test_ac_113_list_returns_masked_only(client: TestClient, db: Session):
    """列表 → 只有掩码。"""
    headers = _login(client, _admin(db))
    _create(client, headers)

    response = client.get(PROVIDERS, headers=headers)

    assert response.status_code == 200, response.text
    items = response.json()
    assert len(items) == 1
    assert items[0]["api_key_masked"] == "sk-****1234"
    assert FAKE_KEY not in response.text
    assert "ciphertext" not in response.text


def test_ac_113_update_without_api_key_keeps_ciphertext(client: TestClient, db: Session):
    """更新时不传 api_key → 原密文与 last4 **不变**。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers)
    before = db.get(LLMProviderConfig, created["id"])
    cipher_before = before.api_key_ciphertext

    response = client.put(
        f"{PROVIDERS}/{created['id']}",
        json={"model": "deepseek-reasoner"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    db.refresh(before)
    assert before.api_key_ciphertext == cipher_before
    assert before.api_key_last4 == "1234"
    assert before.model == "deepseek-reasoner"


def test_ac_113_update_with_null_api_key_keeps_ciphertext(client: TestClient, db: Session):
    """更新时 api_key 传 null → 原密文不变。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers)
    before = db.get(LLMProviderConfig, created["id"])
    cipher_before = before.api_key_ciphertext

    response = client.put(
        f"{PROVIDERS}/{created['id']}",
        json={"api_key": None, "model": "deepseek-reasoner"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    db.refresh(before)
    assert before.api_key_ciphertext == cipher_before
    assert before.api_key_last4 == "1234"


def test_ac_113_update_with_new_api_key_changes_ciphertext(client: TestClient, db: Session):
    """更新时传新 Key → 密文变、last4 变。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers)
    before = db.get(LLMProviderConfig, created["id"])
    cipher_before = before.api_key_ciphertext

    response = client.put(
        f"{PROVIDERS}/{created['id']}",
        json={"api_key": "sk-brandnew-5678"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    db.refresh(before)
    assert before.api_key_ciphertext != cipher_before
    assert before.api_key_last4 == "5678"
    assert response.json()["api_key_masked"] == "sk-****5678"


def test_ac_113_duplicate_name_returns_409(client: TestClient, db: Session):
    """重名 → 409 LLM_PROVIDER_NAME_TAKEN。"""
    headers = _login(client, _admin(db))
    _create(client, headers)

    response = client.post(PROVIDERS, json=_payload(), headers=headers)

    assert response.status_code == 409
    assert response.json()["code"] == "LLM_PROVIDER_NAME_TAKEN"


def test_ac_113_missing_provider_returns_404(client: TestClient, db: Session):
    """配置不存在 → 404。"""
    headers = _login(client, _admin(db))

    response = client.put(
        f"{PROVIDERS}/999999", json={"model": "x"}, headers=headers
    )

    assert response.status_code == 404
    assert response.json()["code"] == "LLM_PROVIDER_NOT_FOUND"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_url", "ftp://x"),
        ("base_url", ""),
        ("api_key", ""),
        ("model", ""),
        ("timeout_seconds", 0),
        ("timeout_seconds", 301),
    ],
)
def test_ac_113_invalid_input_returns_400(
    client: TestClient, db: Session, field: str, value
):
    """非法输入 → 400 LLM_PROVIDER_INVALID（不是 422）。"""
    headers = _login(client, _admin(db))

    response = client.post(
        PROVIDERS, json=_payload(**{field: value}), headers=headers
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "LLM_PROVIDER_INVALID"


def test_ac_113_base_url_trailing_slash_is_stripped(client: TestClient, db: Session):
    """入库前去掉尾部 `/`。"""
    headers = _login(client, _admin(db))

    body = _create(client, headers, base_url="https://api.deepseek.com/v1/")

    assert body["base_url"] == "https://api.deepseek.com/v1"


def test_ac_113_non_admin_forbidden(client: TestClient, db: Session):
    """非系统管理员 → 403。"""
    headers = _login(client, _member(db))

    assert client.get(PROVIDERS, headers=headers).status_code == 403
    assert (
        client.post(PROVIDERS, json=_payload(), headers=headers).status_code == 403
    )


def test_ac_113_anonymous_rejected(client: TestClient, db: Session):
    """未登录 → 401。"""
    assert client.get(PROVIDERS).status_code == 401


# ------------------------------------------------------------ 默认互斥


def test_ac_109_create_with_default_clears_others(client: TestClient, db: Session):
    """新建时 is_default=true → 其余行清 0。"""
    headers = _login(client, _admin(db))
    first = _create(client, headers, name="配置一", is_default=True)
    second = _create(client, headers, name="配置二", is_default=True)

    db.refresh(db.get(LLMProviderConfig, first["id"]))
    db.refresh(db.get(LLMProviderConfig, second["id"]))
    assert db.get(LLMProviderConfig, first["id"]).is_default == 0
    assert db.get(LLMProviderConfig, second["id"]).is_default == 1


def test_ac_109_update_to_default_clears_others(client: TestClient, db: Session):
    """把另一行设为默认 → 原默认行清 0（**先清后置**）。"""
    headers = _login(client, _admin(db))
    first = _create(client, headers, name="配置一", is_default=True)
    second = _create(client, headers, name="配置二")

    response = client.put(
        f"{PROVIDERS}/{second['id']}", json={"is_default": True}, headers=headers
    )

    assert response.status_code == 200, response.text
    db.refresh(db.get(LLMProviderConfig, first["id"]))
    db.refresh(db.get(LLMProviderConfig, second["id"]))
    assert db.get(LLMProviderConfig, first["id"]).is_default == 0
    assert db.get(LLMProviderConfig, second["id"]).is_default == 1


def test_ac_109_only_one_default_after_switch(client: TestClient, db: Session):
    """来回切换后，全局仍只有一个默认。"""
    headers = _login(client, _admin(db))
    first = _create(client, headers, name="配置一", is_default=True)
    second = _create(client, headers, name="配置二")

    client.put(f"{PROVIDERS}/{second['id']}", json={"is_default": True}, headers=headers)
    client.put(f"{PROVIDERS}/{first['id']}", json={"is_default": True}, headers=headers)

    defaults = db.scalars(
        select(LLMProviderConfig).where(LLMProviderConfig.is_default == 1)
    ).all()
    assert len(defaults) == 1
    assert defaults[0].id == first["id"]


def test_ac_109_disabling_default_clears_default_flag(client: TestClient, db: Session):
    """停用默认行 → is_default 一并置 0（可能没有默认配置 → 降级 Mock）。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers, is_default=True)

    response = client.put(
        f"{PROVIDERS}/{created['id']}", json={"status": "disabled"}, headers=headers
    )

    assert response.status_code == 200, response.text
    db.refresh(db.get(LLMProviderConfig, created["id"]))
    row = db.get(LLMProviderConfig, created["id"])
    assert row.status == "disabled"
    assert row.is_default == 0


def test_ac_109_invalid_status_returns_400(client: TestClient, db: Session):
    """非法 status → 400。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers)

    response = client.put(
        f"{PROVIDERS}/{created['id']}", json={"status": "paused"}, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["code"] == "LLM_PROVIDER_INVALID"


# ------------------------------------------------------------ 审计


def test_ac_113_create_writes_audit_without_secrets(client: TestClient, db: Session):
    """新建 → 写 `llm.provider.create`，审计里没有明文 / 密文。"""
    admin = _admin(db)
    headers = _login(client, admin)

    _create(client, headers)

    # 按操作者过滤——开发库里可能有别的管理员留下的同名审计
    log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "llm.provider.create",
            AuditLog.actor_id == admin.id,
        )
    )
    assert log is not None
    assert log.target_type == "llm_provider"
    assert log.target_id is not None
    assert log.after_data["api_key_last4"] == "1234"
    blob = str(log.after_data)
    assert FAKE_KEY not in blob
    assert "ciphertext" not in blob


def test_ac_113_update_writes_audit_with_before_and_after(client: TestClient, db: Session):
    """更新 → 写 `llm.provider.update`，带 before + after。"""
    admin = _admin(db)
    headers = _login(client, admin)
    created = _create(client, headers)

    client.put(
        f"{PROVIDERS}/{created['id']}",
        json={"model": "deepseek-reasoner"},
        headers=headers,
    )

    log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "llm.provider.update",
            AuditLog.actor_id == admin.id,
        )
    )
    assert log is not None
    assert log.before_data["model"] == "deepseek-chat"
    assert log.after_data["model"] == "deepseek-reasoner"
    blob = str(log.before_data) + str(log.after_data)
    assert FAKE_KEY not in blob
    assert "ciphertext" not in blob


def test_ac_113_failed_create_writes_no_audit(client: TestClient, db: Session):
    """校验失败 → 不写审计。"""
    admin = _admin(db)
    headers = _login(client, admin)

    response = client.post(
        PROVIDERS, json=_payload(base_url="ftp://x"), headers=headers
    )

    assert response.status_code == 400
    assert (
        db.scalar(
            select(AuditLog).where(
                AuditLog.action == "llm.provider.create",
                AuditLog.actor_id == admin.id,
            )
        )
        is None
    )


# ------------------------------------------------------------ AC-114 连通性测试


def test_ac_114_success_returns_200_ok_true(client: TestClient, db: Session):
    """连通 → 200 ok=true，回填 last_test_*，写一条运行日志。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers)
    client.app.dependency_overrides[provider_transport] = _mock_transport(_ok_handler)

    response = client.post(f"{PROVIDERS}/{created['id']}/test", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["message"] == "连通正常"
    assert body["model"] == "deepseek-chat"

    row = db.get(LLMProviderConfig, created["id"])
    db.refresh(row)
    assert row.last_test_status == "succeeded"
    assert row.last_test_at is not None

    logs = db.scalars(
        select(LLMRunLog).where(
            LLMRunLog.task_type == "provider_test",
            LLMRunLog.provider_name == "DeepSeek 生产",
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].status == "succeeded"
    assert logs[0].call_count == 1
    assert logs[0].provider_name == "DeepSeek 生产"
    assert logs[0].model == "deepseek-chat"


def test_ac_114_failure_returns_200_ok_false(client: TestClient, db: Session):
    """**连通失败也返回 200** + ok=false，不抛 502。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers)
    client.app.dependency_overrides[provider_transport] = _mock_transport(
        _timeout_handler
    )

    response = client.post(f"{PROVIDERS}/{created['id']}/test", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["message"]
    assert "超时" in body["message"]
    assert body["model"] is None

    row = db.get(LLMProviderConfig, created["id"])
    db.refresh(row)
    assert row.last_test_status == "failed"
    assert row.last_test_error

    logs = db.scalars(
        select(LLMRunLog).where(
            LLMRunLog.task_type == "provider_test",
            LLMRunLog.provider_name == "DeepSeek 生产",
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].status == "failed"
    assert logs[0].error_code == "LLM_CALL_FAILED"


def test_ac_114_failure_message_has_no_api_key(client: TestClient, db: Session):
    """失败消息里没有 API Key。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers)
    client.app.dependency_overrides[provider_transport] = _mock_transport(
        _timeout_handler
    )

    response = client.post(f"{PROVIDERS}/{created['id']}/test", headers=headers)

    assert FAKE_KEY not in response.text


def test_ac_114_run_log_has_no_prompt_or_token(client: TestClient, db: Session):
    """运行日志里不出现 Prompt 正文与 token 金额。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers)
    client.app.dependency_overrides[provider_transport] = _mock_transport(_ok_handler)

    client.post(f"{PROVIDERS}/{created['id']}/test", headers=headers)

    log = db.scalar(
        select(LLMRunLog).where(LLMRunLog.task_type == "provider_test")
    )
    assert log is not None
    blob = f"{log.error_message} {log.error_code} {log.provider_name}"
    assert FAKE_KEY not in blob
    assert "ping" not in blob
    assert "token" not in blob.lower()


def test_ac_114_missing_provider_returns_404(client: TestClient, db: Session):
    """配置不存在 → 404。"""
    headers = _login(client, _admin(db))

    response = client.post(f"{PROVIDERS}/999999/test", headers=headers)

    assert response.status_code == 404
    assert response.json()["code"] == "LLM_PROVIDER_NOT_FOUND"


def test_ac_114_test_writes_no_audit(client: TestClient, db: Session):
    """连通性测试**不写审计**（只写运行日志）。"""
    headers = _login(client, _admin(db))
    created = _create(client, headers)
    client.app.dependency_overrides[provider_transport] = _mock_transport(_ok_handler)

    client.post(f"{PROVIDERS}/{created['id']}/test", headers=headers)

    assert (
        db.scalar(select(AuditLog).where(AuditLog.action == "llm.provider.test"))
        is None
    )
