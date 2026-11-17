"""功能基线的业务逻辑（T56–T62）。

结构层：模块 → 功能 → 功能点；
标签层：标签挂在功能/功能点上，但归属于某一份快照；
审核层：审核通过冻结结构并分配版本号。

权限判定统一放在服务层（路由只取当前用户），因为「成员 vs 访客 vs 管理员」
的分支在多个接口里重复，走依赖容易和 03 的写法漂移。
"""

import json
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.baselines.references import snapshot_references
from app.baselines.schemas import trace_fields_in
from app.common.audit import write_audit
from app.common.deps import SYSTEM_ADMIN
from app.common.errors import (
    AppError,
    ClearNoteRequired,
    ClearReasonRequired,
    DuplicateFeaturePointName,
    DuplicateFunctionName,
    DuplicateLabel,
    DuplicateModuleName,
    FeaturePointNotFound,
    FunctionNotFound,
    InvalidClearReason,
    InvalidLabelType,
    InvalidMigrateTarget,
    InvalidReviewStatus,
    LabelAlreadyCleared,
    LabelNotFound,
    ModuleNotEmpty,
    ModuleNotFound,
    NotProjectAdmin,
    NotProjectMember,
    ProjectArchived,
    ProjectNotFound,
    ReviewCommentRequired,
    ReviewNotFound,
    SelfApprovalForbidden,
    SnapshotNotFound,
    SnapshotReferenced,
    TraceFieldsReadOnly,
)
from app.models.baseline import (
    BaselineFeaturePoint,
    BaselineFunction,
    BaselineLabel,
    BaselineModule,
    BaselineRevision,
)
from app.models.project import Project, ProjectMember
from app.models.user import User

LABEL_TYPES = ("new", "changed", "affected", "unchanged")

# 清除原因 6 类（PRD 2.4.2「人工清除」）
CLEAR_REASONS = (
    "requirement_done",
    "requirement_cancelled",
    "misjudged",
    "priority_changed",
    "duplicate_label",
    "other",
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _page(items: list, page: int, page_size: int) -> dict:
    """列表分页信封：先过滤后计数，`total` 是过滤后的条数。"""
    total = len(items)
    start = max(page - 1, 0) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _ensure_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFound("项目不存在")
    return project


def _ensure_writable_project(session: Session, project_id: int) -> Project:
    """写接口的项目校验：不存在 404，已归档 409。

    顺序与 03 一致：先判归档再判角色，避免用权限错误掩盖归档状态。
    """
    project = _ensure_project(session, project_id)
    if project.status != "active":
        raise ProjectArchived("项目已归档，不可修改功能基线")
    return project


def _ensure_admin(session: Session, *, project_id: int, actor: User) -> None:
    """结构写操作限项目管理员；系统管理员兜底。

    非成员与角色不符统一 `NOT_PROJECT_ADMIN`——区分会泄露项目是否存在。
    """
    if actor.global_role == SYSTEM_ADMIN:
        return
    member = session.get(ProjectMember, (project_id, actor.id))
    if member is None or member.role != "project_admin":
        raise NotProjectAdmin("只有项目管理员可以修改功能基线")


def _ensure_member(session: Session, *, project_id: int, actor: User) -> None:
    """读接口：成员（含访客）可读；非成员 `NOT_PROJECT_MEMBER`。"""
    if actor.global_role == SYSTEM_ADMIN:
        return
    if session.get(ProjectMember, (project_id, actor.id)) is None:
        raise NotProjectMember("不是该项目成员")


def ensure_readable(session: Session, *, project_id: int, actor: User) -> None:
    """读接口的权限入口（路由调用）。"""
    _ensure_project(session, project_id)
    _ensure_member(session, project_id=project_id, actor=actor)


def _load_module(session: Session, project_id: int, module_id: int) -> BaselineModule:
    module = session.scalar(
        select(BaselineModule).where(
            BaselineModule.id == module_id, BaselineModule.project_id == project_id
        )
    )
    if module is None:
        raise ModuleNotFound("模块不存在")
    return module


def _load_function(session: Session, project_id: int, function_id: int) -> BaselineFunction:
    function = session.scalar(
        select(BaselineFunction).where(
            BaselineFunction.id == function_id, BaselineFunction.project_id == project_id
        )
    )
    if function is None:
        raise FunctionNotFound("功能不存在")
    return function


def _load_feature_point(
    session: Session, project_id: int, point_id: int
) -> BaselineFeaturePoint:
    point = session.scalar(
        select(BaselineFeaturePoint).where(
            BaselineFeaturePoint.id == point_id, BaselineFeaturePoint.project_id == project_id
        )
    )
    if point is None:
        raise FeaturePointNotFound("功能点不存在")
    return point


def _is_duplicate(exc: IntegrityError) -> bool:
    """MySQL 唯一索引冲突（1062）。"""
    return exc.orig.args[0] == 1062


def _guarded_insert(session: Session, entity, error_cls, message: str) -> None:
    """在 SAVEPOINT 内插入。

    唯一索引冲突时只回滚本次插入（同会话此前的写入不受影响），
    冲突则抛业务错误。用 `session.rollback()` 会把整个事务回滚掉，
    连同本次请求里前面已经写好的数据一起抹掉。
    """
    try:
        with session.begin_nested():
            session.add(entity)
            session.flush()
    except IntegrityError as exc:
        if entity in session:
            session.expunge(entity)
        if _is_duplicate(exc):
            raise error_cls(message) from exc
        raise


def _guarded_update(
    session: Session, action: Callable[[], None], error_cls, message: str
) -> None:
    """在 SAVEPOINT 内改属性并 flush。

    属性修改必须在 SAVEPOINT **内部**——回滚 SAVEPOINT 时 ORM 才会把
    已改的属性还原成旧值；改在 SAVEPOINT 外面则状态还原不可靠。
    """
    try:
        with session.begin_nested():
            action()
            session.flush()
    except IntegrityError as exc:
        if _is_duplicate(exc):
            raise error_cls(message) from exc
        raise


def ensure_no_trace_fields(payload) -> None:
    """写接口拒绝来源追溯字段（AC-63）。

    追溯字段只读：能从文档分析带出来，但不能从写接口手动改。
    """
    fields = trace_fields_in(payload)
    if fields:
        raise TraceFieldsReadOnly(
            "来源追溯字段只读，不允许通过写接口修改",
            fields=fields,
        )


def get_module_name(session: Session, module_id: int) -> str:
    """模块名。找不到时返回空串（功能已迁移等边界情况）。"""
    name = session.scalar(
        select(BaselineModule.name).where(BaselineModule.id == module_id)
    )
    return name or ""


# 级联删除时写进标签的清除原因。人工清除只能用 PRD 的 6 类原因，
# 这里的标记由服务层内部写入，不经过人工清除接口。
CASCADE_CLEAR_REASON = "target_deleted"


# ---------------------------------------------------------------- 模块（T56）


def list_modules(
    session: Session,
    project_id: int,
    *,
    status: str = "active",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """模块列表，带功能数。

    默认只返回在用模块；归档模块保留历史但不参与默认展示（spec §2.3 第 5 条）。
    一次取全部模块 + 全部功能的计数后在内存聚合，
    避免按模块逐个查功能的 N+1。
    """
    query = select(BaselineModule).where(BaselineModule.project_id == project_id)
    if status != "all":
        query = query.where(BaselineModule.status == status)
    modules = session.scalars(
        query.order_by(BaselineModule.sort_order, BaselineModule.id)
    ).all()

    counts = dict(
        session.execute(
            select(BaselineFunction.module_id, func.count(BaselineFunction.id))
            .where(BaselineFunction.project_id == project_id)
            .group_by(BaselineFunction.module_id)
        ).all()
    )

    items = [
        {
            "id": module.id,
            "name": module.name,
            "description": module.description,
            "sort_order": module.sort_order,
            "source_type": module.source_type,
            "status": module.status,
            "function_count": int(counts.get(module.id, 0)),
            "created_at": module.created_at,
        }
        for module in modules
    ]
    return _page(items, page, page_size)


def create_module(
    session: Session,
    *,
    project_id: int,
    actor: User,
    name: str,
    description: str | None = None,
    sort_order: int = 0,
) -> BaselineModule:
    """新建模块。同项目模块名重复 → 409。"""
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    module = BaselineModule(
        project_id=project_id,
        name=name,
        description=description,
        sort_order=sort_order,
        created_by=actor.id,
    )
    _guarded_insert(session, module, DuplicateModuleName, "同项目已存在同名模块")

    write_audit(
        session,
        "baseline.module.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_module",
        target_id=module.id,
        after_data={"name": module.name, "sort_order": module.sort_order},
    )
    session.commit()
    return module


def update_module(
    session: Session,
    *,
    project_id: int,
    module_id: int,
    actor: User,
    name: str | None = None,
    description: str | None = None,
    sort_order: int | None = None,
    status: str | None = None,
) -> BaselineModule:
    """改模块的名称/描述/排序/状态。"""
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    module = _load_module(session, project_id, module_id)
    before = {
        "name": module.name,
        "description": module.description,
        "sort_order": module.sort_order,
        "status": module.status,
    }

    def _apply() -> None:
        if name is not None:
            module.name = name
        if description is not None:
            module.description = description
        if sort_order is not None:
            module.sort_order = sort_order
        if status is not None:
            module.status = status

    _guarded_update(
        session, _apply, DuplicateModuleName, "同项目已存在同名模块"
    )

    write_audit(
        session,
        "baseline.module.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_module",
        target_id=module.id,
        before_data=before,
        after_data={
            "name": module.name,
            "description": module.description,
            "sort_order": module.sort_order,
            "status": module.status,
        },
    )
    session.commit()
    return module


def delete_module(
    session: Session, *, project_id: int, module_id: int, actor: User
) -> dict:
    """删除模块。

    模块下还有功能 → 409 `MODULE_NOT_EMPTY`，响应带两个处理入口
    （迁移功能 / 删除功能），对应 PRD 的级联删除策略。
    无功能时直接删；该模块下的功能点（连带标签）一并清除。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    module = _load_module(session, project_id, module_id)
    function_count = int(
        session.scalar(
            select(func.count(BaselineFunction.id)).where(
                BaselineFunction.module_id == module_id
            )
        )
        or 0
    )
    if function_count > 0:
        raise ModuleNotEmpty(
            "模块下还有功能，请先迁移或删除功能",
            available_actions=["migrate_functions", "delete_functions"],
            function_count=function_count,
        )

    cleared = _clear_targets(
        session,
        project_id=project_id,
        target_type="module",
        target_ids=[module_id],
        actor=actor,
    )

    before = {"name": module.name, "status": module.status}
    session.delete(module)
    session.flush()

    write_audit(
        session,
        "baseline.module.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_module",
        target_id=module_id,
        before_data=before,
        reason="cascade_cleared_labels",
    )
    session.commit()
    return {"deleted": True, "cleared_label_count": cleared}


# ---------------------------------------------------------------- 功能（T57）


def list_functions(
    session: Session,
    project_id: int,
    *,
    module_id: int | None = None,
    source_type: str | None = None,
    label_type: str | None = None,
    keyword: str | None = None,
    revision_id: int | None = None,
    status: str = "active",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """功能列表，支持多条件组合筛选。

    默认只返回在用功能，且排除挂在归档模块下的功能（spec §2.3 第 5 条）；
    `status=archived` 只看归档功能，`status=all` 不按状态过滤。
    标签按「实体自身」与「其功能点」分开统计：功能标签不由功能点标签汇总
    （AC-66），但功能无标签而功能点有标签时给出弱化提示用的计数。
    """
    query = select(BaselineFunction, BaselineModule).join(
        BaselineModule, BaselineModule.id == BaselineFunction.module_id
    )
    if status != "all":
        query = query.where(BaselineFunction.status == status)
    if status == "active":
        # 归档模块不参与默认展示：其下功能一并隐藏
        query = query.where(BaselineModule.status == "active")
    if module_id is not None:
        query = query.where(BaselineFunction.module_id == module_id)
    if source_type is not None:
        query = query.where(BaselineFunction.source_type == source_type)
    if keyword:
        query = query.where(BaselineFunction.name.like(f"%{keyword}%"))
    query = query.where(BaselineFunction.project_id == project_id)
    rows = session.execute(query.order_by(BaselineFunction.id)).all()

    functions = [row[0] for row in rows]
    if not functions:
        return _page([], page, page_size)

    function_ids = [f.id for f in functions]
    module_names = {row[1].id: row[1].name for row in rows}

    point_counts = dict(
        session.execute(
            select(BaselineFeaturePoint.function_id, func.count(BaselineFeaturePoint.id))
            .where(BaselineFeaturePoint.function_id.in_(function_ids))
            .group_by(BaselineFeaturePoint.function_id)
        ).all()
    )

    # 功能自身的标签
    function_labels = _label_type_map(
        session, project_id, "function", function_ids, revision_id
    )
    # 功能点的标签：既要按功能汇总计数，也要供 label_type 筛选
    point_ids = list(
        session.scalars(
            select(BaselineFeaturePoint.id).where(
                BaselineFeaturePoint.function_id.in_(function_ids)
            )
        )
    )
    point_labels = _label_type_map(session, project_id, "feature_point", point_ids, revision_id)
    point_label_count_by_function = _label_count_by_function(
        session, project_id, function_ids, revision_id
    )
    # 功能 → 其功能点上的标签类型集合（筛选用）
    point_label_types_by_function: dict[int, set[str]] = {}
    point_owner = dict(
        session.execute(
            select(BaselineFeaturePoint.id, BaselineFeaturePoint.function_id).where(
                BaselineFeaturePoint.id.in_(point_ids)
            )
        ).all()
    ) if point_ids else {}
    for point_id, label_types in point_labels.items():
        owner = point_owner.get(point_id)
        if owner is None:
            continue
        point_label_types_by_function.setdefault(owner, set()).update(label_types)

    result = []
    for function in functions:
        label_types = sorted(function_labels.get(function.id, []))
        point_label_types = sorted(point_label_types_by_function.get(function.id, []))
        point_label_count = point_label_count_by_function.get(function.id, 0)

        if label_type is not None:
            if label_type not in label_types and label_type not in point_label_types:
                continue

        result.append(
            {
                "id": function.id,
                "module_id": function.module_id,
                "module_name": module_names.get(function.module_id, ""),
                "name": function.name,
                "description": function.description,
                "version_no": function.version_no,
                "source_type": function.source_type,
                "status": function.status,
                "moved_from_module_id": function.moved_from_module_id,
                "source_document_id": function.source_document_id,
                "source_version_id": function.source_version_id,
                "source_chapter_id": function.source_chapter_id,
                "source_chapter_title": function.source_chapter_title,
                "source_method": function.source_method,
                "source_analysis_id": function.source_analysis_id,
                "label_types": label_types,
                "feature_point_count": int(point_counts.get(function.id, 0)),
                "feature_point_label_count": point_label_count,
                "created_at": function.created_at,
            }
        )
    return _page(result, page, page_size)


def create_function(
    session: Session,
    *,
    project_id: int,
    actor: User,
    module_id: int,
    name: str,
    description: str | None = None,
) -> BaselineFunction:
    """在模块下新建功能。同模块功能名重复 → 409。"""
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)
    _load_module(session, project_id, module_id)

    function = BaselineFunction(
        project_id=project_id,
        module_id=module_id,
        name=name,
        description=description,
        created_by=actor.id,
    )
    _guarded_insert(session, function, DuplicateFunctionName, "同模块已存在同名功能")

    write_audit(
        session,
        "baseline.function.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_function",
        target_id=function.id,
        after_data={"name": function.name, "module_id": module_id},
    )
    session.commit()
    return function


def update_function(
    session: Session,
    *,
    project_id: int,
    function_id: int,
    actor: User,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> BaselineFunction:
    """改功能内容。

    入参只有名称/描述/状态——来源追溯字段只读（AC-63），
    不提供写入路径。内容变更时 `version_no` +1。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    function = _load_function(session, project_id, function_id)
    before = {"name": function.name, "version_no": function.version_no, "status": function.status}

    content_changed = False

    def _apply() -> None:
        nonlocal content_changed
        if name is not None and name != function.name:
            function.name = name
            content_changed = True
        if description is not None and description != function.description:
            function.description = description
            content_changed = True
        if status is not None and status != function.status:
            function.status = status
        if content_changed:
            function.version_no += 1

    _guarded_update(session, _apply, DuplicateFunctionName, "同模块已存在同名功能")

    write_audit(
        session,
        "baseline.function.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_function",
        target_id=function.id,
        before_data=before,
        after_data={
            "name": function.name,
            "version_no": function.version_no,
            "status": function.status,
        },
    )
    session.commit()
    return function


def delete_function(
    session: Session, *, project_id: int, function_id: int, actor: User
) -> dict:
    """删功能：连带删其功能点与标签。

    功能带生效标签时返回 warning，提示标签失效、下游测试点将不再引用。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    function = _load_function(session, project_id, function_id)
    active_label_count = _active_label_count(session, project_id, "function", [function_id])

    point_ids = list(
        session.scalars(
            select(BaselineFeaturePoint.id).where(
                BaselineFeaturePoint.function_id == function_id
            )
        )
    )
    cleared = _clear_targets(
        session,
        project_id=project_id,
        target_type="feature_point",
        target_ids=point_ids,
        actor=actor,
    )
    cleared += _clear_targets(
        session,
        project_id=project_id,
        target_type="function",
        target_ids=[function_id],
        actor=actor,
    )

    before = {"name": function.name, "module_id": function.module_id}
    # 功能点先删：外键指向功能，不先删会 1452
    if point_ids:
        points = session.scalars(
            select(BaselineFeaturePoint).where(
                BaselineFeaturePoint.id.in_(point_ids)
            )
        ).all()
        for point in points:
            session.delete(point)
    session.delete(function)
    session.flush()

    write_audit(
        session,
        "baseline.function.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_function",
        target_id=function_id,
        before_data=before,
        reason="cascade_cleared_labels",
    )
    session.commit()

    warning = None
    if active_label_count:
        warning = (
            f"该功能原有 {active_label_count} 个生效标签，删除后标签失效，"
            "下游测试点将不再引用"
        )
    return {"deleted": True, "cleared_label_count": cleared, "warning": warning}


# ------------------------------------------------------------ 功能点（T57）


def list_feature_points(
    session: Session, project_id: int, function_id: int
) -> list[dict]:
    """功能列表下的功能点，带各自标签。"""
    _load_function(session, project_id, function_id)
    points = session.scalars(
        select(BaselineFeaturePoint)
        .where(BaselineFeaturePoint.function_id == function_id)
        .order_by(BaselineFeaturePoint.id)
    ).all()
    point_ids = [p.id for p in points]
    labels = _label_type_map(session, project_id, "feature_point", point_ids, None)
    return [
        {
            "id": point.id,
            "function_id": point.function_id,
            "name": point.name,
            "description": point.description,
            "source_type": point.source_type,
            "status": point.status,
            "label_types": sorted(labels.get(point.id, [])),
            "created_at": point.created_at,
        }
        for point in points
    ]


def create_feature_point(
    session: Session,
    *,
    project_id: int,
    actor: User,
    function_id: int,
    name: str,
    description: str | None = None,
) -> BaselineFeaturePoint:
    """在功能下新建功能点。同功能功能点名重复 → 409。"""
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)
    _load_function(session, project_id, function_id)

    point = BaselineFeaturePoint(
        project_id=project_id,
        function_id=function_id,
        name=name,
        description=description,
        created_by=actor.id,
    )
    _guarded_insert(
        session, point, DuplicateFeaturePointName, "同功能已存在同名功能点"
    )

    write_audit(
        session,
        "baseline.feature_point.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_feature_point",
        target_id=point.id,
        after_data={"name": point.name, "function_id": function_id},
    )
    session.commit()
    return point


def update_feature_point(
    session: Session,
    *,
    project_id: int,
    point_id: int,
    actor: User,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> BaselineFeaturePoint:
    """改功能点内容。追溯字段同样只读。"""
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    point = _load_feature_point(session, project_id, point_id)
    before = {"name": point.name, "status": point.status}

    def _apply() -> None:
        if name is not None:
            point.name = name
        if description is not None:
            point.description = description
        if status is not None:
            point.status = status

    _guarded_update(
        session, _apply, DuplicateFeaturePointName, "同功能已存在同名功能点"
    )

    write_audit(
        session,
        "baseline.feature_point.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_feature_point",
        target_id=point.id,
        before_data=before,
        after_data={"name": point.name, "status": point.status},
    )
    session.commit()
    return point


def delete_feature_point(
    session: Session, *, project_id: int, point_id: int, actor: User
) -> dict:
    """删功能点，其标签一并清除。"""
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    point = _load_feature_point(session, project_id, point_id)
    active_label_count = _active_label_count(
        session, project_id, "feature_point", [point_id]
    )
    cleared = _clear_targets(
        session,
        project_id=project_id,
        target_type="feature_point",
        target_ids=[point_id],
        actor=actor,
    )

    before = {"name": point.name, "function_id": point.function_id}
    session.delete(point)
    session.flush()

    write_audit(
        session,
        "baseline.feature_point.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_feature_point",
        target_id=point_id,
        before_data=before,
        reason="cascade_cleared_labels",
    )
    session.commit()

    warning = None
    if active_label_count:
        warning = (
            f"该功能点原有 {active_label_count} 个生效标签，删除后标签失效，"
            "下游测试点将不再引用"
        )
    return {"deleted": True, "cleared_label_count": cleared, "warning": warning}


# ------------------------------------------------------------ 功能迁移（T58）


def migrate_functions(
    session: Session,
    *,
    project_id: int,
    module_id: int,
    actor: User,
    target_module_id: int,
    function_ids: list[int],
) -> list[BaselineFunction]:
    """把功能批量迁到同项目的另一个模块。

    目标模块必须存在、同项目、且不是当前模块；迁移后
    `moved_from_module_id` 记来源模块，追溯信息保留。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    source = _load_module(session, project_id, module_id)
    if target_module_id == module_id:
        raise InvalidMigrateTarget("目标模块不能是当前模块")
    target = session.scalar(
        select(BaselineModule).where(
            BaselineModule.id == target_module_id,
            BaselineModule.project_id == project_id,
        )
    )
    if target is None:
        raise InvalidMigrateTarget("目标模块不存在或不属于该项目")

    moved: list[BaselineFunction] = []
    for function_id in function_ids:
        function = session.scalar(
            select(BaselineFunction).where(
                BaselineFunction.id == function_id,
                BaselineFunction.project_id == project_id,
            )
        )
        if function is None:
            raise FunctionNotFound("功能不存在")
        if function.module_id != module_id:
            raise InvalidMigrateTarget("功能不属于源模块")

        before = {"module_id": function.module_id, "name": function.name}
        function.module_id = target_module_id
        function.moved_from_module_id = module_id
        session.flush()
        moved.append(function)

        write_audit(
            session,
            "baseline.module.migrate",
            actor_id=actor.id,
            actor_role=actor.global_role,
            project_id=project_id,
            target_type="baseline_function",
            target_id=function.id,
            before_data=before,
            after_data={
                "module_id": target_module_id,
                "moved_from_module_id": module_id,
                "name": function.name,
            },
        )

    session.commit()
    return moved


# ------------------------------------------------------- 标签辅助（T59/T60）


def _label_type_map(
    session: Session,
    project_id: int,
    target_type: str,
    target_ids: list[int],
    revision_id: int | None,
) -> dict[int, set[str]]:
    """实体 → 生效标签类型集合。"""
    if not target_ids:
        return {}
    query = select(BaselineLabel.target_id, BaselineLabel.label_type).where(
        BaselineLabel.project_id == project_id,
        BaselineLabel.target_type == target_type,
        BaselineLabel.target_id.in_(target_ids),
        BaselineLabel.status == "active",
    )
    if revision_id is not None:
        query = query.where(BaselineLabel.revision_id == revision_id)
    result: dict[int, set[str]] = {}
    for target_id, label_type in session.execute(query).all():
        result.setdefault(target_id, set()).add(label_type)
    return result


def _label_count_by_function(
    session: Session,
    project_id: int,
    function_ids: list[int],
    revision_id: int | None,
) -> dict[int, int]:
    """功能 → 其功能点的生效标签数量（弱化提示用）。"""
    if not function_ids:
        return {}
    query = (
        select(BaselineFeaturePoint.function_id, func.count(BaselineLabel.id))
        .join(BaselineLabel, BaselineLabel.target_id == BaselineFeaturePoint.id)
        .where(
            BaselineFeaturePoint.function_id.in_(function_ids),
            BaselineLabel.target_type == "feature_point",
            BaselineLabel.status == "active",
        )
    )
    if revision_id is not None:
        query = query.where(BaselineLabel.revision_id == revision_id)
    return {
        function_id: int(count)
        for function_id, count in session.execute(
            query.group_by(BaselineFeaturePoint.function_id)
        ).all()
    }


def _active_label_count(
    session: Session, project_id: int, target_type: str, target_ids: list[int]
) -> int:
    if not target_ids:
        return 0
    return int(
        session.scalar(
            select(func.count(BaselineLabel.id)).where(
                BaselineLabel.project_id == project_id,
                BaselineLabel.target_type == target_type,
                BaselineLabel.target_id.in_(target_ids),
                BaselineLabel.status == "active",
            )
        )
        or 0
    )


def _clear_targets(
    session: Session,
    *,
    project_id: int,
    target_type: str,
    target_ids: list[int],
    actor: User,
) -> int:
    """把指定实体的生效标签置为 `cleared`（级联删除时的软清除）。

    标签行保留，只改状态——「清除」在 PRD 里是可追溯的动作，不是删除。
    """
    if not target_ids:
        return 0
    rows = session.scalars(
        select(BaselineLabel).where(
            BaselineLabel.project_id == project_id,
            BaselineLabel.target_type == target_type,
            BaselineLabel.target_id.in_(target_ids),
            BaselineLabel.status == "active",
        )
    ).all()
    now = _now()
    for label in rows:
        label.status = "cleared"
        label.cleared_by = actor.id
        label.cleared_at = now
        label.clear_reason = CASCADE_CLEAR_REASON
    session.flush()
    return len(rows)


# ------------------------------------------------------------ 标签（T59/T60）


def _load_revision(
    session: Session, project_id: int, revision_id: int, *, as_review: bool = False
) -> BaselineRevision:
    """按 id 取记录。

    同一张表既是审核记录也是快照，错误码按调用方语义区分：
    审核动作抛 `REVIEW_NOT_FOUND`，快照读取/删除/打标抛 `SNAPSHOT_NOT_FOUND`。
    """
    revision = session.scalar(
        select(BaselineRevision).where(
            BaselineRevision.id == revision_id, BaselineRevision.project_id == project_id
        )
    )
    if revision is None:
        if as_review:
            raise ReviewNotFound("基线版本不存在")
        raise SnapshotNotFound("基线快照不存在")
    return revision


def _latest_revision(session: Session, project_id: int) -> BaselineRevision | None:
    return session.scalar(
        select(BaselineRevision)
        .where(BaselineRevision.project_id == project_id)
        .order_by(BaselineRevision.id.desc())
    )


def list_labels(
    session: Session,
    project_id: int,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    revision_id: int | None = None,
    status: str = "active",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """标签列表。默认只返回生效标签；传 `status='cleared'` 看已清除的。"""
    query = select(BaselineLabel).where(BaselineLabel.project_id == project_id)
    if target_type is not None:
        query = query.where(BaselineLabel.target_type == target_type)
    if target_id is not None:
        query = query.where(BaselineLabel.target_id == target_id)
    if revision_id is not None:
        query = query.where(BaselineLabel.revision_id == revision_id)
    if status != "all":
        query = query.where(BaselineLabel.status == status)

    rows = session.scalars(query.order_by(BaselineLabel.id)).all()
    items = [
        {
            "id": label.id,
            "revision_id": label.revision_id,
            "target_type": label.target_type,
            "target_id": label.target_id,
            "label_type": label.label_type,
            "status": label.status,
            "confirmed_by": label.confirmed_by,
            "confirmed_at": label.confirmed_at,
            "cleared_by": label.cleared_by,
            "cleared_at": label.cleared_at,
            "clear_reason": label.clear_reason,
            "clear_note": label.clear_note,
        }
        for label in rows
    ]
    return _page(items, page, page_size)


def create_label(
    session: Session,
    *,
    project_id: int,
    actor: User,
    revision_id: int | None,
    target_type: str,
    target_id: int,
    label_type: str,
) -> BaselineLabel:
    """打标。

    标签归属于某一份基线版本；不传 `revision_id` 时用项目内最新的一份。
    同实体同版本同类型只允许一条生效标签——由 `active_key` 唯一索引兜底。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    if label_type not in LABEL_TYPES:
        raise InvalidLabelType("标签类型只能是 new/changed/affected/unchanged")

    if revision_id is None:
        revision = _latest_revision(session, project_id)
        if revision is None:
            raise ReviewNotFound("请先提交审核生成基线版本，再打标")
    else:
        revision = _load_revision(session, project_id, revision_id)

    if target_type == "function":
        target = _load_function(session, project_id, target_id)
    elif target_type == "feature_point":
        target = _load_feature_point(session, project_id, target_id)
    else:
        raise InvalidLabelType("标签对象只能是 function 或 feature_point")

    label = BaselineLabel(
        project_id=project_id,
        revision_id=revision.id,
        target_type=target_type,
        target_id=target.id,
        label_type=label_type,
        confirmed_by=actor.id,
    )
    _guarded_insert(
        session, label, DuplicateLabel, "该对象在同一基线版本下已有同类型生效标签"
    )

    write_audit(
        session,
        "baseline.label.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type=f"baseline_{target_type}",
        target_id=target.id,
        after_data={
            "label_type": label_type,
            "revision_id": revision.id,
            "target_type": target_type,
            "target_id": target.id,
        },
    )
    session.commit()
    return label


def clear_label(
    session: Session,
    *,
    project_id: int,
    label_id: int,
    actor: User,
    clear_reason: str | None,
    clear_note: str | None,
) -> BaselineLabel:
    """清除标签。

    行不删除：状态置 `cleared` 并记清除人/时间/原因，
    这样「谁在什么时候因为什么清掉了这个标签」可追溯。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    if not clear_reason:
        raise ClearReasonRequired("请选择清除原因")
    if clear_reason not in CLEAR_REASONS:
        raise InvalidClearReason("清除原因不在允许的 6 类之内")
    if clear_reason == "other" and not (clear_note or "").strip():
        raise ClearNoteRequired("清除原因为「其他」时必须填写备注")

    label = session.scalar(
        select(BaselineLabel).where(
            BaselineLabel.id == label_id, BaselineLabel.project_id == project_id
        )
    )
    if label is None:
        raise LabelNotFound("标签不存在")
    if label.status != "active":
        raise LabelAlreadyCleared("该标签已清除")

    before = {"status": label.status, "label_type": label.label_type}
    label.status = "cleared"
    label.cleared_by = actor.id
    label.cleared_at = _now()
    label.clear_reason = clear_reason
    label.clear_note = clear_note
    session.flush()

    write_audit(
        session,
        "baseline.label.clear",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type=f"baseline_{label.target_type}",
        target_id=label.target_id,
        before_data=before,
        after_data={
            "status": "cleared",
            "label_type": label.label_type,
            "clear_reason": clear_reason,
            "clear_note": clear_note,
        },
        reason=clear_reason,
    )
    session.commit()
    return label


# ------------------------------------------------- 审核与快照（T61）


def submit_review(
    session: Session, *, project_id: int, actor: User, comment: str | None = None
) -> BaselineRevision:
    """提交审核。

    同一项目同时只允许一份「审核中」的记录——避免两份草稿互相覆盖。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    pending = session.scalar(
        select(BaselineRevision).where(
            BaselineRevision.project_id == project_id,
            BaselineRevision.status == "submitted",
        )
    )
    if pending is not None:
        raise InvalidReviewStatus("已有一份审核中的基线版本，请先处理它")

    revision = BaselineRevision(
        project_id=project_id,
        status="submitted",
        submitted_by=actor.id,
        submitted_at=_now(),
        review_comment=comment,
    )
    session.add(revision)
    session.flush()

    write_audit(
        session,
        "baseline.revision.submit",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_revision",
        target_id=revision.id,
        after_data={"status": "submitted", "comment": comment},
    )
    session.commit()
    return revision


def approve_review(
    session: Session,
    *,
    project_id: int,
    revision_id: int,
    actor: User,
    comment: str | None = None,
) -> BaselineRevision:
    """审核通过：冻结结构、分配版本号、把上一份快照的生效标签复制过来。

    标签复制成**独立行**（`revision_id` 指向新版本），
    因此旧版本上的清除动作不会波及新版本——级联清除默认关闭。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    revision = _load_revision(session, project_id, revision_id, as_review=True)
    if revision.status != "submitted":
        raise InvalidReviewStatus("只有审核中的记录可以通过")
    if revision.submitted_by == actor.id:
        raise SelfApprovalForbidden("不能审核自己提交的基线版本")

    structure, counts = _freeze_structure(session, project_id)
    revision.structure_json = structure
    revision.module_count = counts["modules"]
    revision.function_count = counts["functions"]
    revision.feature_point_count = counts["feature_points"]
    revision.version_no = _next_version_no(session, project_id)
    revision.status = "approved"
    revision.reviewed_by = actor.id
    revision.reviewed_at = _now()
    if comment:
        revision.review_comment = comment
    session.flush()

    copied = _copy_labels_forward(session, project_id, revision.id)
    revision.label_count = copied
    session.flush()

    write_audit(
        session,
        "baseline.revision.approve",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_revision",
        target_id=revision.id,
        before_data={"status": "submitted"},
        after_data={
            "status": "approved",
            "version_no": revision.version_no,
            "module_count": revision.module_count,
            "function_count": revision.function_count,
            "feature_point_count": revision.feature_point_count,
            "label_count": revision.label_count,
            "comment": comment,
        },
    )
    session.commit()
    return revision


def reject_review(
    session: Session,
    *,
    project_id: int,
    revision_id: int,
    actor: User,
    comment: str | None = None,
) -> BaselineRevision:
    """驳回。意见必填；不生成快照、不占版本号。"""
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    revision = _load_revision(session, project_id, revision_id, as_review=True)
    if revision.status != "submitted":
        raise InvalidReviewStatus("只有审核中的记录可以驳回")
    if revision.submitted_by == actor.id:
        raise SelfApprovalForbidden("不能审核自己提交的基线版本")
    if not (comment or "").strip():
        raise ReviewCommentRequired("驳回必须填写意见")

    revision.status = "rejected"
    revision.reviewed_by = actor.id
    revision.reviewed_at = _now()
    revision.review_comment = comment
    session.flush()

    write_audit(
        session,
        "baseline.revision.reject",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_revision",
        target_id=revision.id,
        before_data={"status": "submitted"},
        after_data={"status": "rejected", "comment": comment},
        reason=comment,
    )
    session.commit()
    return revision


def list_revisions(
    session: Session,
    project_id: int,
    *,
    status: str = "approved",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """快照列表，新版本在前。

    默认只列审核通过的（`status='approved'`）；`status='submitted'` 用来
    看待审核的记录，`status='all'` 列全部。
    """
    query = select(BaselineRevision).where(
        BaselineRevision.project_id == project_id
    )
    if status != "all":
        query = query.where(BaselineRevision.status == status)
    rows = session.scalars(
        query.order_by(BaselineRevision.id.desc())
    ).all()
    items = [
        {
            "id": revision.id,
            "version_no": revision.version_no,
            "status": revision.status,
            "module_count": revision.module_count,
            "function_count": revision.function_count,
            "feature_point_count": revision.feature_point_count,
            "label_count": revision.label_count,
            "submitted_by": revision.submitted_by,
            "submitted_at": revision.submitted_at,
            "reviewed_by": revision.reviewed_by,
            "reviewed_at": revision.reviewed_at,
            "review_comment": revision.review_comment,
            "created_at": revision.created_at,
        }
        for revision in rows
    ]
    return _page(items, page, page_size)


def get_revision(session: Session, project_id: int, revision_id: int) -> dict:
    """快照详情，含冻结的结构。"""
    revision = _load_revision(session, project_id, revision_id)
    item = {
        "id": revision.id,
        "version_no": revision.version_no,
        "status": revision.status,
        "module_count": revision.module_count,
        "function_count": revision.function_count,
        "feature_point_count": revision.feature_point_count,
        "label_count": revision.label_count,
        "submitted_by": revision.submitted_by,
        "submitted_at": revision.submitted_at,
        "reviewed_by": revision.reviewed_by,
        "reviewed_at": revision.reviewed_at,
        "review_comment": revision.review_comment,
        "created_at": revision.created_at,
    }
    structure = None
    if revision.structure_json:
        try:
            structure = json.loads(revision.structure_json)
        except json.JSONDecodeError:
            structure = None
    item["structure"] = structure
    return item


def _freeze_structure(session: Session, project_id: int) -> tuple[str, dict[str, int]]:
    """把当前的三级结构冻结成 JSON 文本，并给出各级计数。

    归档模块及其功能不参与新快照（spec §2.3 第 5 条），计数也不含它们。
    """
    modules = session.scalars(
        select(BaselineModule)
        .where(BaselineModule.project_id == project_id, BaselineModule.status == "active")
        .order_by(BaselineModule.sort_order, BaselineModule.id)
    ).all()
    module_ids = [module.id for module in modules]
    functions = (
        session.scalars(
            select(BaselineFunction)
            .where(
                BaselineFunction.project_id == project_id,
                BaselineFunction.status == "active",
                BaselineFunction.module_id.in_(module_ids),
            )
            .order_by(BaselineFunction.id)
        ).all()
        if module_ids
        else []
    )
    function_ids = [function.id for function in functions]
    points = (
        session.scalars(
            select(BaselineFeaturePoint)
            .where(
                BaselineFeaturePoint.project_id == project_id,
                BaselineFeaturePoint.status == "active",
                BaselineFeaturePoint.function_id.in_(function_ids),
            )
            .order_by(BaselineFeaturePoint.id)
        ).all()
        if function_ids
        else []
    )

    points_by_function: dict[int, list[BaselineFeaturePoint]] = {}
    for point in points:
        points_by_function.setdefault(point.function_id, []).append(point)
    functions_by_module: dict[int, list[BaselineFunction]] = {}
    for function in functions:
        functions_by_module.setdefault(function.module_id, []).append(function)

    structure = []
    for module in modules:
        module_functions = []
        for function in functions_by_module.get(module.id, []):
            module_functions.append(
                {
                    "id": function.id,
                    "name": function.name,
                    "description": function.description,
                    "version_no": function.version_no,
                    "source_type": function.source_type,
                    "feature_points": [
                        {
                            "id": point.id,
                            "name": point.name,
                            "description": point.description,
                            "source_type": point.source_type,
                        }
                        for point in points_by_function.get(function.id, [])
                    ],
                }
            )
        structure.append(
            {
                "id": module.id,
                "name": module.name,
                "description": module.description,
                "sort_order": module.sort_order,
                "source_type": module.source_type,
                "functions": module_functions,
            }
        )

    counts = {
        "modules": len(modules),
        "functions": len(functions),
        "feature_points": len(points),
    }
    return json.dumps(structure, ensure_ascii=False), counts


def _next_version_no(session: Session, project_id: int) -> int:
    """下一个快照版本号。项目内从 0 开始递增（v1.0、v1.1…）。"""
    current = session.scalar(
        select(func.max(BaselineRevision.version_no)).where(
            BaselineRevision.project_id == project_id,
            BaselineRevision.status == "approved",
        )
    )
    return int(current) + 1 if current is not None else 0


def _copy_labels_forward(session: Session, project_id: int, revision_id: int) -> int:
    """把上一份快照的**生效**标签复制成新行，挂在当前版本下。

    已清除的标签不复制；当前版本已有的同类型标签不重复复制。
    """
    previous = session.scalar(
        select(BaselineRevision)
        .where(
            BaselineRevision.project_id == project_id,
            BaselineRevision.status == "approved",
            BaselineRevision.id != revision_id,
        )
        .order_by(BaselineRevision.version_no.desc(), BaselineRevision.id.desc())
    )
    if previous is None:
        return 0

    source_labels = session.scalars(
        select(BaselineLabel).where(
            BaselineLabel.project_id == project_id,
            BaselineLabel.revision_id == previous.id,
            BaselineLabel.status == "active",
        )
    ).all()

    existing = {
        (label.target_type, label.target_id, label.label_type)
        for label in session.scalars(
            select(BaselineLabel).where(
                BaselineLabel.project_id == project_id,
                BaselineLabel.revision_id == revision_id,
                BaselineLabel.status == "active",
            )
        ).all()
    }

    copied = 0
    for label in source_labels:
        key = (label.target_type, label.target_id, label.label_type)
        if key in existing:
            continue
        existing.add(key)
        session.add(
            BaselineLabel(
                project_id=project_id,
                revision_id=revision_id,
                target_type=label.target_type,
                target_id=label.target_id,
                label_type=label.label_type,
                source_analysis_id=label.source_analysis_id,
                confirmed_by=label.confirmed_by,
                confirmed_at=label.confirmed_at,
            )
        )
        copied += 1
    session.flush()
    return copied


# ------------------------------------------------- 保留策略（T62）


def get_retention(session: Session, project_id: int) -> dict:
    """保留策略状态：上限、快照数、待清理候选、告警。"""
    project = _ensure_project(session, project_id)
    max_count = project.baseline_snapshot_max_count

    snapshots = session.scalars(
        select(BaselineRevision)
        .where(BaselineRevision.project_id == project_id, BaselineRevision.status == "approved")
        .order_by(BaselineRevision.version_no, BaselineRevision.id)
    ).all()

    candidates: list[dict] = []
    warnings: list[str] = []
    if max_count is not None and len(snapshots) > max_count:
        for revision in snapshots[: len(snapshots) - max_count]:
            referenced = _snapshot_references(session, revision.id)
            candidates.append(
                {
                    "id": revision.id,
                    "version_no": revision.version_no,
                    "referenced_count": len(referenced),
                    "refs": referenced,
                    "created_at": revision.created_at.isoformat(),
                }
            )
        blocked = [c for c in candidates if c["referenced_count"] > 0]
        if blocked:
            warnings.append(
                f"{len(blocked)} 份快照达到保留上限但因被引用不可清理，"
                "请先解除引用或调高保留上限"
            )

    return {
        "max_count": max_count,
        "enabled": max_count is not None,
        "snapshot_count": len(snapshots),
        "keep_count": max_count if max_count is not None else len(snapshots),
        "candidates": candidates,
        "warnings": warnings,
    }


def update_retention(
    session: Session, *, project_id: int, actor: User, max_count: int | None
) -> Project:
    """设置保留上限。`None` 表示关闭策略（永久保留）。"""
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    project = _ensure_project(session, project_id)
    before = project.baseline_snapshot_max_count
    project.baseline_snapshot_max_count = max_count
    session.flush()

    write_audit(
        session,
        "baseline.retention.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="project",
        target_id=project_id,
        before_data={"baseline_snapshot_max_count": before},
        after_data={"baseline_snapshot_max_count": max_count},
    )
    session.commit()
    return project


def _snapshot_references(session: Session, revision_id: int) -> list[dict]:
    """快照的引用来源。

    标签、增量分析（以及后续的测试点、用例、报告）各类来源统一在
    `app/baselines/references.py` 里按「来源解析器」拆开，
    新增来源只写解析器、不动这里。

    返回带 `target_name`：用户认对象靠业务名称，不靠内部 ID。
    """
    return snapshot_references(session, revision_id)


def _referenced_message(refs: list[dict]) -> str:
    """按引用来源给一句人话。

    只被标签引用时说「标签引用」；被增量分析引用时说「增量分析引用」；
    混在一起时取标签那句——用户先要处理的是标签。
    """
    source_types = {ref.get("source_type", "") for ref in refs}
    if source_types & {"baseline_function", "baseline_feature_point"}:
        return "该快照仍被标签引用，清理前请先解除引用"
    if "incremental_analysis" in source_types:
        return "该快照仍被增量分析引用，清理前请先解除引用"
    return "该快照仍被引用，清理前请先解除引用"


def delete_revision(
    session: Session, *, project_id: int, revision_id: int, actor: User
) -> dict:
    """删快照。

    被**生效**标签引用的快照禁止删除（只告警）；
    仅剩已清除标签的快照可以删，其已清除标签行随之删除。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    revision = _load_revision(session, project_id, revision_id)
    if revision.status != "approved":
        raise InvalidReviewStatus("只有审核通过的快照可以删除")

    refs = _snapshot_references(session, revision_id)
    if refs:
        raise SnapshotReferenced(
            _referenced_message(refs),
            refs=refs,
            referenced_count=len(refs),
        )

    cleared_rows = session.scalars(
        select(BaselineLabel).where(BaselineLabel.revision_id == revision_id)
    ).all()
    for label in cleared_rows:
        session.delete(label)
    session.flush()

    before = {"version_no": revision.version_no, "status": revision.status}
    session.delete(revision)
    session.flush()

    write_audit(
        session,
        "baseline.snapshot.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="baseline_revision",
        target_id=revision_id,
        before_data=before,
        reason="retention_cleanup",
    )
    session.commit()
    return {"deleted": True, "cleared_label_count": len(cleared_rows)}
