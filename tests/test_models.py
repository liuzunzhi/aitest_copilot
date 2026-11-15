"""项目与成员表（T06）。

验证三类数据库层保障：复合主键唯一、role 枚举 CHECK、外键约束。
这些约束一旦失效，应用层代码看起来仍然正常，只有并发或脏数据才会暴露。
"""

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectMember
from app.models.user import User


def _user(db: Session, username: str = "u1") -> User:
    user = User(username=username, password_hash="x" * 60)
    db.add(user)
    db.flush()
    return user


def _project(db: Session, name: str = "项目A") -> Project:
    project = Project(name=name)
    db.add(project)
    db.flush()
    return project


def test_project_tables(db: Session):
    """两张表可写入，默认值符合预期。"""
    project = _project(db)
    user = _user(db)
    member = ProjectMember(project_id=project.id, user_id=user.id, role="member")
    db.add(member)
    db.flush()

    db.refresh(project)
    db.refresh(member)

    assert project.status == "active"
    assert project.created_at is not None
    assert member.joined_at is not None


def test_member_composite_pk_unique(db: Session):
    """同一用户在同一项目内只能有一条成员记录。"""
    project = _project(db)
    user = _user(db)
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="member"))
    db.flush()

    with pytest.raises(IntegrityError):
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role="guest"))
        db.flush()


def test_member_role_check(db: Session):
    """role 只接受 project_admin / member / guest，其他值被 CHECK 拦下。

    注意：MySQL 的 CHECK 违反抛的是 3819（OperationalError），
    不是 IntegrityError（那是唯一键/外键的 1062 / 1452）。
    应用层若只捕获 IntegrityError 会漏掉这一类。
    """
    project = _project(db)
    user = _user(db)

    with pytest.raises(OperationalError) as exc:
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
        db.flush()

    assert exc.value.orig.args[0] == 3819


def test_member_unknown_project(db: Session):
    """project_id 不存在时由外键拦下。"""
    user = _user(db)

    with pytest.raises(IntegrityError):
        db.add(ProjectMember(project_id=999999, user_id=user.id, role="member"))
        db.flush()


def test_member_unknown_user(db: Session):
    """user_id 不存在时由外键拦下。"""
    project = _project(db)

    with pytest.raises(IntegrityError):
        db.add(ProjectMember(project_id=project.id, user_id=999999, role="member"))
        db.flush()
