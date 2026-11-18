"""注册接口（T14，AC-08 ~ AC-10）。

**AC-11 图形验证码已于 2026-11-18 移除**（内部测试环境，注册不对外开放）。
注册不再需要验证码；对外发布前需补回，见 `specs/01-auth/tasks.md` 待办。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.system import AuditLog
from app.models.user import User

REGISTER = "/api/auth/register"


def _payload(**overrides) -> dict:
    data = {
        "username": "new-user",
        "password": "Passw0rd",
        "email": "new@example.com",
        "phone": "13800000000",
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

    # 按自己的用户过滤——开发库里可能有别的注册记录，不能全表查
    audit = (
        db.query(AuditLog)
        .filter_by(action="register.submit", actor_id=user.id)
        .one()
    )
    assert audit.target_id == str(user.id)


def test_ac_08_register_without_captcha(client: TestClient, db: Session):
    """2026-11-18：注册不再要求图形验证码，不传 captcha 也直接成功。"""
    response = client.post(REGISTER, json=_payload(username="no-captcha-user"))

    assert response.status_code == 201, response.text
    assert db.query(User).filter_by(username="no-captcha-user").count() == 1


def test_ac_08_register_ignores_extra_captcha_fields(client: TestClient, db: Session):
    """老客户端若仍带 captcha 字段，不应因此失败。"""
    response = client.post(
        REGISTER,
        json=_payload(username="legacy-captcha-user", captcha="ZZZZ", captcha_id="x"),
    )

    assert response.status_code == 201, response.text


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
