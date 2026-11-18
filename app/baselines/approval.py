"""「生效集合」：最近一轮已批准审核里通过的实体（T94 / AC-135）。

**这是 05 与分点审核之间唯一的耦合点**，因此单独成模块、只依赖模型，
不 import 服务层（避免 `service → derive → incremental.context → 本模块`
的循环）。

规则：

1. 项目内**最近一轮** `status='approved'` 的审核轮次；
2. 该轮 `decision='approved'` 的条目进集合；
3. 父被驳回 → 子自动出局（模块不在集合 → 其下功能出局，依此类推）；
4. **没有已批准轮次 → 返回 `None`**，表示"不过滤"。

第 4 条是兼容性关键：手工建基线、从不提交审核的项目不能被清空。
只有真正用过分点审核的项目才进入"只看 approved"的模式。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.baseline import BaselineFeaturePoint, BaselineFunction
from app.models.baseline_review import BaselineReviewItem, BaselineReviewRound

EntityKey = tuple[str, int]


def latest_approved_round(
    session: Session, project_id: int
) -> BaselineReviewRound | None:
    return session.scalar(
        select(BaselineReviewRound)
        .where(
            BaselineReviewRound.project_id == project_id,
            BaselineReviewRound.status == "approved",
        )
        .order_by(BaselineReviewRound.id.desc())
    )


def approved_entities(
    session: Session, project_id: int
) -> set[EntityKey] | None:
    """返回生效集合；`None` 表示"项目还没用过分点审核，不要过滤"。"""
    review_round = latest_approved_round(session, project_id)
    if review_round is None:
        return None

    approved: set[EntityKey] = {
        (entity_type, entity_id)
        for entity_type, entity_id in session.execute(
            select(BaselineReviewItem.entity_type, BaselineReviewItem.entity_id).where(
                BaselineReviewItem.round_id == review_round.id,
                BaselineReviewItem.decision == "approved",
            )
        ).all()
    }
    if not approved:
        return set()

    modules = {entity_id for kind, entity_id in approved if kind == "module"}
    functions = {entity_id for kind, entity_id in approved if kind == "function"}
    points = {entity_id for kind, entity_id in approved if kind == "feature_point"}

    # 父被驳回 → 子自动出局
    if functions:
        functions = {
            function_id
            for function_id, module_id in session.execute(
                select(BaselineFunction.id, BaselineFunction.module_id).where(
                    BaselineFunction.project_id == project_id,
                    BaselineFunction.id.in_(functions),
                    BaselineFunction.module_id.in_(modules),
                )
            ).all()
        }
    if points:
        points = {
            point_id
            for point_id, function_id in session.execute(
                select(
                    BaselineFeaturePoint.id, BaselineFeaturePoint.function_id
                ).where(
                    BaselineFeaturePoint.project_id == project_id,
                    BaselineFeaturePoint.id.in_(points),
                    BaselineFeaturePoint.function_id.in_(functions),
                )
            ).all()
        }

    result: set[EntityKey] = set()
    result.update(("module", entity_id) for entity_id in modules)
    result.update(("function", entity_id) for entity_id in functions)
    result.update(("feature_point", entity_id) for entity_id in points)
    return result


__all__ = ["EntityKey", "approved_entities", "latest_approved_round"]
