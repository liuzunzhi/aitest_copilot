"""快照的引用来源解析器。

PRD 2.4.2「被引用即保护」原文列举了四类引用来源：
标签记录、增量分析记录、测试点/用例、测试报告追溯链。

04 落地时只有标签引用一类；增量分析（05）、测试点、用例、报告尚未上线。
本模块把「查引用」拆成若干**来源解析器**，每个解析器只负责一种来源，
新增来源只需再写一个解析器，不必动主流程。

解析器接口：

    def resolver(session, revision_id) -> list[dict]

返回的引用条目统一带这三个字段：

    source_type  来源类型标识（如 `baseline_function`）
    target_id    被引用对象的 id
    target_name  被引用对象的业务名称（前端不暴露内部 id）

可选字段：

    label_type          只对标签引用有意义
    source_analysis_id  该标签/行是由哪次增量分析产出（04 已预留该列）

**一条引用 = 一件可处理的事**。管理员看到「引用来源」列表，每一项都要能
对应一个动作：标签引用 → 去清掉这条标签；分析引用 → 这份快照是某次分析的
比对基准，删了分析的追溯链就断了。同一件事不重复计数——标签若是某次分析的
产物，来源信息挂在标签条目上（`source_analysis_id`），不额外算一条引用。

关于增量分析引用——04 的 schema 里已经预留了 `source_analysis_id` 列
（`baseline_labels` / `baseline_functions` / `baseline_feature_points`），
05 落地后写入方会填上它，因此「标签来自哪次分析」在 05 落地当天就能查到。

「分析记录把该快照当比对基准」这一路引用由 `_analysis_record_references`
负责：它探测 `incremental_analyses` 表是否存在，存在才查，不存在跳过——
这样 04 不必写指向尚不存在的表的死代码，05 落地后无需改动 04 即自动生效。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.models.baseline import (
    BaselineFeaturePoint,
    BaselineFunction,
    BaselineLabel,
)

# 引用来源解析器：session 与被引用的快照 id → 引用条目列表
ReferenceResolver = Callable[[Session, int], list[dict]]

# 增量分析记录表名。05 落地前不存在，探测到就用，探测不到就跳过。
INCREMENTAL_ANALYSIS_TABLE = "incremental_analyses"

# 测试点生成记录表名。07 落地前不存在，探测到就用，探测不到就跳过。
TEST_POINT_ANALYSIS_TABLE = "test_point_analyses"

# 标签类引用的来源类型
LABEL_SOURCE_TYPES = ("baseline_function", "baseline_feature_point")

# 解析器注册表。可变列表——后续模块落地时挂自己的来源进来。
_resolvers: list[ReferenceResolver] = []


def register_resolver(resolver: ReferenceResolver) -> None:
    """注册额外的引用来源解析器。

    供后续模块（测试点、用例、报告）在落地时挂自己的来源。
    """
    if resolver not in _resolvers:
        _resolvers.append(resolver)


def _table_exists(session: Session, table_name: str) -> bool:
    """表是否存在于当前连接的库。

    用 SQLAlchemy 的 inspector 探测，不直接查 information_schema——
    inspector 走的是方言适配的路径，对 MySQL 与 SQLite 都成立。
    """
    try:
        return table_name in inspect(session.get_bind()).get_table_names()
    except Exception:
        # 探测失败（权限不足、连接异常）按「不存在」处理：
        # 宁可少一层保护，也不要让保留策略整个不可用。
        return False


# ------------------------------------------------------- 标签来源（内置）


def _label_references(session: Session, revision_id: int) -> list[dict]:
    """标签引用：被**生效**标签挂在该快照上。

    已清除的标签不再算引用——标签的使命已经结束，快照可以正常清理。

    标签若带 `source_analysis_id`，说明它是某次增量分析的产物；
    这个来源信息随标签一起给出（不算额外的一处引用）。
    """
    rows = session.execute(
        select(
            BaselineLabel.target_type,
            BaselineLabel.target_id,
            BaselineLabel.label_type,
            BaselineLabel.source_analysis_id,
        )
        .where(BaselineLabel.revision_id == revision_id, BaselineLabel.status == "active")
    ).all()
    if not rows:
        return []

    names = _target_names(session, rows)
    refs: list[dict] = []
    for target_type, target_id, label_type, analysis_id in rows:
        ref = {
            "source_type": f"baseline_{target_type}",
            "target_id": target_id,
            "target_name": names.get((target_type, target_id), "已删除的对象"),
            "label_type": label_type,
        }
        if analysis_id is not None:
            ref["source_analysis_id"] = analysis_id
        refs.append(ref)
    return refs


def _target_names(
    session: Session, rows: list[tuple[str, int, str, int | None]]
) -> dict[tuple[str, int], str]:
    """功能与功能点的 id → 业务名称。

    用户认对象靠名称，不靠内部 id；名称查不到时统一显示「已删除的对象」。
    """
    function_ids = [target_id for target_type, target_id, _, _ in rows if target_type == "function"]
    point_ids = [
        target_id for target_type, target_id, _, _ in rows if target_type == "feature_point"
    ]

    names: dict[tuple[str, int], str] = {}
    if function_ids:
        for function_id, function_name in session.execute(
            select(BaselineFunction.id, BaselineFunction.name).where(
                BaselineFunction.id.in_(function_ids)
            )
        ).all():
            names[("function", function_id)] = function_name
    if point_ids:
        for point_id, point_name in session.execute(
            select(BaselineFeaturePoint.id, BaselineFeaturePoint.name).where(
                BaselineFeaturePoint.id.in_(point_ids)
            )
        ).all():
            names[("feature_point", point_id)] = point_name
    return names


# --------------------------------------------- 增量分析来源（04 的预留位）


def _analysis_record_references(session: Session, revision_id: int) -> list[dict]:
    """增量分析记录把该快照当作比对基准 → 该快照被增量分析引用。

    05 落地前 `incremental_analyses` 表不存在，本解析器直接返回空列表；
    05 落地后自动生效，04 不需要改动。
    """
    if not _table_exists(session, INCREMENTAL_ANALYSIS_TABLE):
        return []

    rows = session.execute(
        text(
            "SELECT id, COALESCE(status, '') FROM incremental_analyses "
            "WHERE baseline_revision_id = :revision_id"
        ),
        {"revision_id": revision_id},
    ).all()
    return [
        {
            "source_type": "incremental_analysis",
            "target_id": row_id,
            "target_name": f"增量分析 #{row_id}" + (f"（{status}）" if status else ""),
        }
        for row_id, status in rows
    ]


# --------------------------------------------- 测试点来源（07 的预留位）


def _test_point_references(session: Session, revision_id: int) -> list[dict]:
    """测试点生成记录把该快照当作比对基准 → 该快照被测试点引用。

    07 落地前 `test_point_analyses` 表不存在，本解析器直接返回空列表；
    07 落地后自动生效，04 不需要改动。

    **表探测保护**：用 `_table_exists`（inspector 探测），
    不直接 `select`——表不存在时直接跳过，04 的老库/老测试都不受影响。
    """
    if not _table_exists(session, TEST_POINT_ANALYSIS_TABLE):
        return []

    rows = session.execute(
        text(
            "SELECT id, COALESCE(status, '') FROM test_point_analyses "
            "WHERE baseline_revision_id = :revision_id"
        ),
        {"revision_id": revision_id},
    ).all()
    return [
        {
            "source_type": "test_point_analysis",
            "target_id": row_id,
            "target_name": f"测试点生成 #{row_id}" + (f"（{status}）" if status else ""),
        }
        for row_id, status in rows
    ]


# 内置解析器：标签来源在前（最常见），增量分析来源在后，测试点来源最后。
# 用列表而非元组——测试可以整体替换它来验证各来源分支。
#
# 后两个来源都是「表不存在就跳过」——它们分别由 05 / 07 落地，
# 04 本身不需要知道那些表长什么样。
_BUILTIN_RESOLVERS: list[ReferenceResolver] = [
    _label_references,
    _analysis_record_references,
    _test_point_references,
]


def snapshot_references(session: Session, revision_id: int) -> list[dict]:
    """快照的全部引用来源。

    各来源的引用条目平铺在一个列表里，前端按 `source_type` 区分展示。
    同一条引用被两个解析器查到时按 `(source_type, target_id)` 去重。
    """
    refs: list[dict] = []
    for resolver in (*_BUILTIN_RESOLVERS, *_resolvers):
        refs.extend(resolver(session, revision_id))

    seen: set[tuple[str, int]] = set()
    unique: list[dict] = []
    for ref in refs:
        key = (str(ref.get("source_type", "")), ref.get("target_id"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


__all__ = [
    "INCREMENTAL_ANALYSIS_TABLE",
    "LABEL_SOURCE_TYPES",
    "ReferenceResolver",
    "TEST_POINT_ANALYSIS_TABLE",
    "register_resolver",
    "snapshot_references",
]
