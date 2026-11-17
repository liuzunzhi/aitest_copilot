"""Prompt 组装与基线索引。

组装规则（AC-78）：

    system = template.system_prompt
    user   = f"{template.user_prompt}\n\n## 章节：{chapter.title}\n{chapter.content}"

基线索引：从比对基准快照对应的**当前**结构表取功能 / 功能点 id → name，
排除归档模块及其下属。目标不在索引里即越界（AC-79）。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.baseline import BaselineFeaturePoint, BaselineFunction, BaselineModule
from app.models.document import DocumentChapter
from app.models.incremental import PromptTemplate


def build_system_prompt(template: PromptTemplate) -> str:
    """系统提示词原样取自数据库模板，不做任何加工。"""
    return template.system_prompt


def build_user_prompt(
    template: PromptTemplate, chapter: DocumentChapter, *, max_chars: int | None = None
) -> str:
    """组装用户提示词；超长时只截断正文。

    前缀（模板正文 + 章节标题）保持不变，这样 AC-78 的
    「user 以模板 user_prompt 开头」在截断场景下依然成立。
    """
    prefix = f"{template.user_prompt}\n\n## 章节：{chapter.title}\n"
    if max_chars is None or len(prefix) + len(chapter.content) <= max_chars:
        return f"{prefix}{chapter.content}"
    remaining = max(0, max_chars - len(prefix))
    return f"{prefix}{chapter.content[:remaining]}"


def baseline_index(session: Session, *, project_id: int) -> dict[tuple[str, int], str]:
    """当前结构的 `(target_type, target_id) → name` 索引。

    与快照冻结口径一致：归档模块及其下功能、功能点都不参与。
    这份索引就是 AC-79 的判定依据——目标不在索引里即越界。
    """
    module_ids = list(
        session.scalars(
            select(BaselineModule.id).where(
                BaselineModule.project_id == project_id,
                BaselineModule.status == "active",
            )
        )
    )
    if not module_ids:
        return {}

    functions = session.execute(
        select(BaselineFunction.id, BaselineFunction.name).where(
            BaselineFunction.project_id == project_id,
            BaselineFunction.status == "active",
            BaselineFunction.module_id.in_(module_ids),
        )
    ).all()
    index: dict[tuple[str, int], str] = {
        ("function", function_id): name for function_id, name in functions
    }

    function_ids = [function_id for function_id, _ in functions]
    if function_ids:
        points = session.execute(
            select(BaselineFeaturePoint.id, BaselineFeaturePoint.name).where(
                BaselineFeaturePoint.project_id == project_id,
                BaselineFeaturePoint.status == "active",
                BaselineFeaturePoint.function_id.in_(function_ids),
            )
        ).all()
        index.update({("feature_point", point_id): name for point_id, name in points})
    return index


__all__ = ["baseline_index", "build_system_prompt", "build_user_prompt"]
