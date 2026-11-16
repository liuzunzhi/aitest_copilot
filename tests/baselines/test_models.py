"""功能基线五表（T55）。

验证数据库层保障：同项目模块同名唯一、同模块功能同名唯一、
同功能功能点同名唯一、同快照同实体同类型仅一条生效标签、
已清除标签不占位（可重新打标）、状态 CHECK 生效。
"""

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.baseline import (
    BaselineFeaturePoint,
    BaselineFunction,
    BaselineLabel,
    BaselineModule,
    BaselineRevision,
)
from app.models.project import Project
from app.models.user import User


def _user(db: Session, username: str = "bl_u1") -> User:
    user = User(username=username, password_hash="x" * 60)
    db.add(user)
    db.flush()
    return user


def _project(db: Session, name: str = "基线项目") -> Project:
    project = Project(name=name)
    db.add(project)
    db.flush()
    return project


def _module(db: Session, project_id: int, user_id: int, name: str = "支付") -> BaselineModule:
    module = BaselineModule(project_id=project_id, name=name, created_by=user_id)
    db.add(module)
    db.flush()
    return module


def _function(
    db: Session, project_id: int, module_id: int, user_id: int, name: str = "下单"
) -> BaselineFunction:
    function = BaselineFunction(
        project_id=project_id, module_id=module_id, name=name, created_by=user_id
    )
    db.add(function)
    db.flush()
    return function


def _revision(db: Session, project_id: int, status: str = "approved") -> BaselineRevision:
    revision = BaselineRevision(project_id=project_id, status=status)
    db.add(revision)
    db.flush()
    return revision


def _label(
    db: Session,
    project_id: int,
    revision_id: int,
    user_id: int,
    *,
    target_type: str = "function",
    target_id: int = 1,
    label_type: str = "changed",
) -> BaselineLabel:
    label = BaselineLabel(
        project_id=project_id,
        revision_id=revision_id,
        target_type=target_type,
        target_id=target_id,
        label_type=label_type,
        confirmed_by=user_id,
    )
    db.add(label)
    db.flush()
    return label


def test_baseline_tables_roundtrip(db: Session):
    """五张表可写入，默认值与生成列符合预期。"""
    user = _user(db)
    project = _project(db)
    module = _module(db, project.id, user.id)
    function = _function(db, project.id, module.id, user.id)
    point = BaselineFeaturePoint(
        project_id=project.id, function_id=function.id, name="余额校验", created_by=user.id
    )
    db.add(point)
    db.flush()
    revision = _revision(db, project.id)
    label = _label(db, project.id, revision.id, user.id, target_id=function.id)

    db.refresh(module)
    db.refresh(function)
    db.refresh(label)

    assert module.source_type == "manual"
    assert module.status == "active"
    assert module.sort_order == 0
    assert function.version_no == 1
    assert function.moved_from_module_id is None
    assert point.source_type == "manual"
    assert revision.status == "approved"
    assert revision.version_no is None
    assert label.status == "active"
    assert label.active_key == f"{revision.id}:function:{function.id}:changed"


def test_module_name_unique_per_project(db: Session):
    """同项目同名模块被唯一索引拦下，跨项目可同名。"""
    user = _user(db)
    project = _project(db)
    other = _project(db, name="另一个项目")
    _module(db, project.id, user.id)
    db.commit()

    with pytest.raises(IntegrityError) as exc:
        _module(db, project.id, user.id)
    assert exc.value.orig.args[0] == 1062
    assert "uk_bmodules_project_name" in str(exc.value.orig.args[1])

    db.rollback()
    _module(db, other.id, user.id)


def test_function_name_unique_in_module(db: Session):
    """功能名在模块内唯一。"""
    user = _user(db)
    project = _project(db)
    module = _module(db, project.id, user.id)
    _function(db, project.id, module.id, user.id)
    db.commit()

    with pytest.raises(IntegrityError) as exc:
        _function(db, project.id, module.id, user.id)
    assert exc.value.orig.args[0] == 1062
    assert "uk_bfunctions_module_name" in str(exc.value.orig.args[1])


def test_feature_point_name_unique_in_function(db: Session):
    """功能点名在功能内唯一。"""
    user = _user(db)
    project = _project(db)
    module = _module(db, project.id, user.id)
    function = _function(db, project.id, module.id, user.id)
    db.add(
        BaselineFeaturePoint(
            project_id=project.id, function_id=function.id, name="余额校验", created_by=user.id
        )
    )
    db.flush()
    db.commit()

    with pytest.raises(IntegrityError) as exc:
        db.add(
            BaselineFeaturePoint(
                project_id=project.id,
                function_id=function.id,
                name="余额校验",
                created_by=user.id,
            )
        )
        db.flush()
    assert exc.value.orig.args[0] == 1062
    assert "uk_bpoints_function_name" in str(exc.value.orig.args[1])


def test_label_active_key_only_for_active(db: Session):
    """`active_key` 生成列只约束生效标签，已清除的标签不占位。

    同快照同实体同类型第二条生效标签会撞唯一索引——
    这是「同实体同快照同类型仅一条生效标签」的数据库兜底。
    """
    user = _user(db)
    project = _project(db)
    revision = _revision(db, project.id)
    label = _label(db, project.id, revision.id, user.id)
    db.commit()

    with pytest.raises(IntegrityError) as exc:
        _label(db, project.id, revision.id, user.id)
    assert exc.value.orig.args[0] == 1062
    assert "uk_blabels_active" in str(exc.value.orig.args[1])

    db.rollback()
    # 清除后 active_key 释放，可以重新打同类型标签
    label = db.get(BaselineLabel, label.id)
    label.status = "cleared"
    db.flush()
    db.refresh(label)
    assert label.active_key is None

    again = _label(db, project.id, revision.id, user.id)
    db.refresh(again)
    assert again.active_key is not None


def test_label_type_check(db: Session):
    """标签类型只接受四个枚举值，非法值被 CHECK 拦下（MySQL 3819）。"""
    user = _user(db)
    project = _project(db)
    revision = _revision(db, project.id)

    with pytest.raises(OperationalError) as exc:
        _label(db, project.id, revision.id, user.id, label_type="deleted")
    assert exc.value.orig.args[0] == 3819


def test_revision_status_check(db: Session):
    """审核记录状态只接受三个枚举值。"""
    project = _project(db)

    with pytest.raises(OperationalError) as exc:
        _revision(db, project.id, status="draft")
    assert exc.value.orig.args[0] == 3819


def test_revision_version_no_unique_per_project(db: Session):
    """同一项目的快照版本号唯一。"""
    project = _project(db)
    first = _revision(db, project.id)
    first.version_no = 1
    db.flush()
    db.commit()

    second = _revision(db, project.id)
    second.version_no = 1
    with pytest.raises(IntegrityError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 1062
    assert "uk_brevisions_project_no" in str(exc.value.orig.args[1])
