"""审计写入。

审计与业务必须同一事务：业务回滚时审计一起丢弃，不允许出现
「业务没成但审计记了成功」。因此这里只 add + flush，绝不 commit。

字段命名跟表一致（before_data / after_data）——`before` / `after`
是 MySQL 保留字。
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.system import AuditLog


def write_audit(
    session: Session,
    action: str,
    *,
    actor_id: int | None = None,
    actor_role: str | None = None,
    project_id: int | None = None,
    target_type: str | None = None,
    target_id: int | str | None = None,
    before_data: Any = None,
    after_data: Any = None,
    reason: str | None = None,
) -> AuditLog:
    """在当前事务内写入一条审计记录。

    `session` 由调用方提供，事务边界由调用方控制；
    这里 `flush` 是为了让超长字段等错误尽早暴露在业务事务里。
    """
    log = AuditLog(
        action=action,
        actor_id=actor_id,
        actor_role=actor_role,
        project_id=project_id,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        before_data=before_data,
        after_data=after_data,
        reason=reason,
    )
    session.add(log)
    session.flush()
    return log


__all__ = ["write_audit"]
