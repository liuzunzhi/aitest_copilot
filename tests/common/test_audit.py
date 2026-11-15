"""审计写入（T12）。

核心断言：审计与业务同事务，业务异常时审计一起回滚（AC-25 的前提）。
"""

import pytest
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.models.system import AuditLog


def test_write_fields(db: Session):
    """字段原样落库，target_id 统一转字符串。"""
    log = write_audit(
        db,
        "project.apply.approve",
        actor_id=10,
        actor_role="project_admin",
        project_id=3,
        target_type="project_application",
        target_id=42,
        before_data={"status": "pending"},
        after_data={"status": "approved"},
        reason="符合准入条件",
    )

    assert log.id is not None
    assert log.target_id == "42"
    assert log.before_data == {"status": "pending"}
    assert log.after_data == {"status": "approved"}
    assert log.created_at is not None

    row = db.get(AuditLog, log.id)
    assert row.action == "project.apply.approve"
    assert row.actor_role == "project_admin"


def test_same_transaction_visible(db: Session):
    """写完的审计在调用方事务内立即可见，说明没有另起连接。"""
    write_audit(db, "auth.login.fail", actor_id=7)

    count = db.query(AuditLog).filter_by(action="auth.login.fail").count()
    assert count == 1


def test_rollback(db: Session):
    """业务异常时审计一起回滚，不留下「业务失败但审计成功」。"""
    with pytest.raises(RuntimeError):
        with db.begin_nested():
            write_audit(db, "project.apply.approve", project_id=1, target_id=1)
            raise RuntimeError("业务失败")

    assert db.query(AuditLog).filter_by(action="project.apply.approve").count() == 0
