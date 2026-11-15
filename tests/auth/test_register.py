"""注册接口（T14，AC-08 ~ AC-11）。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.captcha import create_captcha
from app.models.system import AuditLog
from app.models.user import User

REGISTER = "/api/auth/register"


def _payload(**overrides) -> dict:
    """每次调用都新拿一个验证码——验证码一次校验即作废。"""
    captcha = create_captcha()
    data = {
        "username": "new-user",
        "password": "Passw0rd",
        "email": "new@example.com",
        "phone": "13800000000",
        "captcha": captcha.code,
        "captcha_id": captcha.id,
    }
    data.update(overrides)
    return data


def _existing_user(db: Session, **fields) -> User:
    defaults = {"username": "taken-user", "password_hash": "x" * 60}
    defaults.update(fields)
    user = User(**defaults)
    db.add(user)
    db.flush()
    return user


def test_ac_08_register_success(client: TestClient, db: Session):
    """201、status=active、无 token、密码只存哈希、写 register.submit 审计。"""
    response = client.post(REGISTER, json=_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert "access_token" not in body

    user = db.query(User).filter_by(username="new-user").one()
    assert body["user_id"] == user.id
    assert user.status == "active"
    assert user.password_hash != "Passw0rd"
    assert user.password_hash.startswith("$2b$")

    audit = db.query(AuditLog).filter_by(action="register.submit").one()
    assert audit.actor_id == user.id
    assert audit.target_id == str(user.id)


def test_ac_09_username_taken(client: TestClient, db: Session):
    _existing_user(db, username="dup-user")

    response = client.post(REGISTER, json=_payload(username="dup-user"))

    assert response.status_code == 409
    assert response.json()["code"] == "USERNAME_TAKEN"


def test_ac_09_username_case_insensitive(client: TestClient, db: Session):
    """排序规则 utf8mb4_0900_ai_ci 下 Admin 与 admin 是同一个名字。"""
    _existing_user(db, username="CaseUser")

    response = client.post(REGISTER, json=_payload(username="caseuser"))

    assert response.status_code == 409
    assert response.json()["code"] == "USERNAME_TAKEN"


@pytest.mark.parametrize(
    "field, value",
    [("email", "dup@example.com"), ("phone", "13900000000")],
)
def test_ac_09_contact_taken(client: TestClient, db: Session, field, value):
    _existing_user(db, **{field: value})

    response = client.post(REGISTER, json=_payload(**{field: value}))

    assert response.status_code == 409
    assert response.json()["code"] == "CONTACT_TAKEN"


@pytest.mark.parametrize(
    "password",
    ["Ab1", "abcdefgh", "12345678", "中文密码1234"],
    ids=["too-short", "no-digit", "no-letter", "no-ascii-letter"],
)
def test_ac_10_weak_password(client: TestClient, password):
    response = client.post(REGISTER, json=_payload(password=password))

    assert response.status_code == 400
    assert response.json()["code"] == "WEAK_PASSWORD"


def test_ac_11_captcha_required(client: TestClient):
    response = client.post(REGISTER, json=_payload(captcha=None, captcha_id=None))

    assert response.status_code == 400
    assert response.json()["code"] == "CAPTCHA_REQUIRED"


def test_ac_11_captcha_invalid(client: TestClient):
    payload = _payload()
    payload["captcha"] = "ZZZZ"

    response = client.post(REGISTER, json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == "CAPTCHA_INVALID"


def test_ac_11_captcha_expired_or_unknown(client: TestClient):
    response = client.post(REGISTER, json=_payload(captcha_id="unknown-captcha"))

    assert response.status_code == 400
    assert response.json()["code"] == "CAPTCHA_INVALID"


def test_ac_11_captcha_single_use(client: TestClient):
    """同一个验证码不能注册两个账号。"""
    payload = _payload()

    assert client.post(REGISTER, json=payload).status_code == 201

    reused = client.post(REGISTER, json={**payload, "username": "second-user"})
    assert reused.status_code == 400
    assert reused.json()["code"] == "CAPTCHA_INVALID"
