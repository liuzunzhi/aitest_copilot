"""功能基线模块测试夹具。

写接口限项目管理员，审核要求提交者与审核者分离，
所以这里固定准备三个身份：管理员、审核员、普通成员。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.baselines.helpers import (
    add_member,
    login,
    make_project,
    make_user,
)


@pytest.fixture
def project(db: Session):
    return make_project(db)


@pytest.fixture
def admin(db: Session, project):
    """项目管理员：所有写操作都用它。"""
    user = make_user(db)
    add_member(db, project, user, "project_admin")
    return user


@pytest.fixture
def reviewer(db: Session, project):
    """第二个项目管理员：专职审核，避免自审被拦。"""
    user = make_user(db)
    add_member(db, project, user, "project_admin")
    return user


@pytest.fixture
def member(db: Session, project):
    """普通成员：可读不可写。"""
    user = make_user(db)
    add_member(db, project, user, "member")
    return user


@pytest.fixture
def outsider(db: Session):
    """非项目成员：读接口也进不来。"""
    return make_user(db)


@pytest.fixture
def headers(client: TestClient, admin) -> dict[str, str]:
    return login(client, admin)


@pytest.fixture
def reviewer_headers(client: TestClient, reviewer) -> dict[str, str]:
    return login(client, reviewer)


@pytest.fixture
def member_headers(client: TestClient, member) -> dict[str, str]:
    return login(client, member)


@pytest.fixture
def outsider_headers(client: TestClient, outsider) -> dict[str, str]:
    return login(client, outsider)
