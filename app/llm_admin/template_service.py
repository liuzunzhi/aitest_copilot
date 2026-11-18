"""提示词模板的服务层（T85 · AC-115 / AC-116）。

三条规矩：

1. **只做列表 + 编辑**，**不提供新建 / 删除**——模板由迁移播种，
   改文案不用改代码、不用发版，但也别让人随手删掉种子模板；
2. **版本自增只看正文**：`system_prompt` / `user_prompt` 变了才
   `version_no += 1`；只改 `description` / `status` **不**升版本
   （升了会让「模板版本」这个概念失去意义——它标记的是「内容变了」）；
3. **`task_type` 不可改**：改了等于换了个模板的身份，历史分析对不上。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.errors import (
    PromptTemplateInvalid,
    PromptTemplateNameTaken,
    PromptTemplateNotFound,
)
from app.models.incremental import PromptTemplate
from app.models.user import User

__all__ = [
    "list_templates",
    "get_template",
    "readonly_templates",
    "to_brief",
    "to_detail",
    "update_template",
]

NAME_MAX = 128
PROMPT_MAX = 60000
DESCRIPTION_MAX = 500
VALID_STATUSES = ("active", "disabled")


# ------------------------------------------------------------ 校验


def _validate_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise PromptTemplateInvalid("模板名不能为空")
    if len(value) > NAME_MAX:
        raise PromptTemplateInvalid(f"模板名不能超过 {NAME_MAX} 个字符")
    return value


def _validate_prompt(prompt: str, label: str) -> str:
    value = prompt or ""
    if not value.strip():
        raise PromptTemplateInvalid(f"{label}不能为空")
    if len(value) > PROMPT_MAX:
        raise PromptTemplateInvalid(f"{label}不能超过 {PROMPT_MAX} 个字符")
    return value


def _validate_status(status: str) -> str:
    if status not in VALID_STATUSES:
        raise PromptTemplateInvalid("状态只能是 active 或 disabled")
    return status


def _validate_description(description: str | None) -> str | None:
    if description is None:
        return None
    if len(description) > DESCRIPTION_MAX:
        raise PromptTemplateInvalid(f"描述不能超过 {DESCRIPTION_MAX} 个字符")
    return description


# ------------------------------------------------------------ 读取


def get_template(session: Session, template_id: int) -> PromptTemplate:
    """取一行，不存在抛 404。"""
    row = session.get(PromptTemplate, template_id)
    if row is None:
        raise PromptTemplateNotFound("提示词模板不存在")
    return row


def list_templates(
    session: Session,
    *,
    task_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """模板分页列表。列表项**不含 Prompt 正文**。"""
    filters = []
    if task_type:
        filters.append(PromptTemplate.task_type == task_type)
    if status:
        filters.append(PromptTemplate.status == status)

    total = session.scalar(
        select(func.count()).select_from(PromptTemplate).where(*filters)
    )

    rows = session.scalars(
        select(PromptTemplate)
        .where(*filters)
        .order_by(PromptTemplate.task_type, PromptTemplate.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "items": [to_brief(row) for row in rows],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    }


def readonly_templates(
    session: Session, *, task_type: str | None = None
) -> list[dict[str, Any]]:
    """只读模板列表：**只给 `status='active'`**，只给元信息。

    普通成员没有管理权限，不该看到 Prompt 正文。
    """
    filters = [PromptTemplate.status == "active"]
    if task_type:
        filters.append(PromptTemplate.task_type == task_type)

    rows = session.scalars(
        select(PromptTemplate).where(*filters).order_by(PromptTemplate.task_type, PromptTemplate.id)
    ).all()

    return [
        {
            "id": row.id,
            "name": row.name,
            "task_type": row.task_type,
            "version_no": row.version_no,
            "description": row.description,
        }
        for row in rows
    ]


def to_brief(row: PromptTemplate) -> dict[str, Any]:
    """列表项。**不含 Prompt 正文。**"""
    return {
        "id": row.id,
        "name": row.name,
        "task_type": row.task_type,
        "description": row.description,
        "version_no": row.version_no,
        "status": row.status,
        "updated_at": row.updated_at,
    }


def to_detail(row: PromptTemplate) -> dict[str, Any]:
    """详情：列表项 + 完整 System / User Prompt。"""
    return {
        **to_brief(row),
        "system_prompt": row.system_prompt,
        "user_prompt": row.user_prompt,
        "created_at": row.created_at,
    }


def _audit_snapshot(row: PromptTemplate) -> dict[str, Any]:
    """审计里记的字段集。含 Prompt 正文（spec §7.5 明确要求）。"""
    return {
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "version_no": row.version_no,
        "system_prompt": row.system_prompt,
        "user_prompt": row.user_prompt,
    }


# ------------------------------------------------------------ 编辑


def update_template(
    session: Session,
    *,
    actor: User,
    template_id: int,
    payload: dict[str, Any],
) -> PromptTemplate:
    """编辑模板。

    **版本自增只看正文**：`system_prompt` / `user_prompt` 与原值不同
    才 `version_no += 1`；只改 `description` / `status` 不升版本。
    """
    row = get_template(session, template_id)
    before = _audit_snapshot(row)

    if payload.get("name") is not None:
        clean_name = _validate_name(payload["name"])
        if clean_name != row.name:
            duplicate = session.scalar(
                select(PromptTemplate).where(
                    PromptTemplate.task_type == row.task_type,
                    PromptTemplate.name == clean_name,
                    PromptTemplate.id != row.id,
                )
            )
            if duplicate is not None:
                raise PromptTemplateNameTaken("同一任务类型下模板名已存在")
            row.name = clean_name

    if payload.get("description") is not None:
        row.description = _validate_description(payload["description"])

    if payload.get("status") is not None:
        row.status = _validate_status(payload["status"])

    # ---- 版本自增：只有正文变了才升版本 ----
    content_changed = False
    if payload.get("system_prompt") is not None:
        clean = _validate_prompt(payload["system_prompt"], "System Prompt")
        if clean != row.system_prompt:
            row.system_prompt = clean
            content_changed = True

    if payload.get("user_prompt") is not None:
        clean = _validate_prompt(payload["user_prompt"], "User Prompt")
        if clean != row.user_prompt:
            row.user_prompt = clean
            content_changed = True

    if content_changed:
        row.version_no += 1

    session.flush()

    write_audit(
        session,
        "prompt_template.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        target_type="prompt_template",
        target_id=row.id,
        before_data=before,
        after_data=_audit_snapshot(row),
    )
    session.commit()
    return row
