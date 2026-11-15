"""项目与成员表（T06）。

验证三类数据库层保障：复合主键唯一、role 枚举 CHECK、外键约束。
这些约束一旦失效，应用层代码看起来仍然正常，只有并发或脏数据才会暴露。
"""

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.application import ProjectApplication
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


def _application(
    db: Session, project_id: int, applicant_id: int, *,
    reason: str = "希望加入", desired_role: str = "member",
) -> ProjectApplication:
    application = ProjectApplication(
        project_id=project_id,
        applicant_id=applicant_id,
        reason=reason,
        desired_role=desired_role,
    )
    db.add(application)
    db.flush()
    return application


def test_pending_unique(db: Session):
    """同一用户在同一项目仅允许一条 pending 申请（AC-17 的数据库层保障）。

    MySQL 无条件唯一索引，靠 STORED 生成列 pending_key：
    pending 时生成 "project:applicant"，其余状态为 NULL（多个 NULL 不冲突）。
    因此驳回后再次申请可以新建记录，而上一条被驳回的记录不再占位。
    """
    project = _project(db)
    user = _user(db)
    db.commit()

    first = _application(db, project.id, user.id)
    db.refresh(first)
    assert first.pending_key == f"{project.id}:{user.id}"
    db.commit()

    with pytest.raises(IntegrityError) as exc:
        _application(db, project.id, user.id)

    assert exc.value.orig.args[0] == 1062
    assert "uk_app_pending" in str(exc.value.orig.args[1])

    # 回滚这条失败的插入，保留已提交的第一条，再把终态置为 rejected
    db.rollback()
    first.status = "rejected"
    db.flush()
    db.refresh(first)
    assert first.pending_key is None

    # 终态记录不占位，同一 (project, applicant) 可以再次提交 pending
    second = _application(db, project.id, user.id)
    db.refresh(second)
    assert second.pending_key == f"{project.id}:{user.id}"
