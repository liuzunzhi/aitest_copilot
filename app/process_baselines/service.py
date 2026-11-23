"""流程基线的服务层（10-process-baseline T118）。

**固定校验顺序**（spec §7，与 04 / 05 / 07 / 08 / 09 一致）：

    项目 404 → 归档 409 → 角色 403 → 资源 404 → 业务校验 400 → 执行

校验阶段失败**不建行**：不会留下「校验没过却有一条记录」的脏数据。
**失败操作不写审计**（校验在建行之前）。

四条关键语义：

1. **批量新建整批拒**：5 条里第 3 条校验失败 → 全部不落库（spec §5.1）。
2. **步骤整体覆盖**：先校验整组再删旧插新，校验不过旧步骤原样保留（spec §5.2）。
3. **关联整体覆盖**：空数组合法（清空关联），名称快照由**服务端重查**
   （不采信客户端传值，spec §5.3）。
4. **来源追溯只读**：手工来源六列强制置 NULL；文档推导来源三元组必填且自洽；
   `PATCH` 传了追溯字段也不写（spec §5.1 / AC-201）。
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common import permissions
from app.common.audit import write_audit
from app.common.errors import (
    ProcessBaselineDuplicateName,
    ProcessBaselineInvalid,
    ProcessBaselineLinkInvalid,
    ProcessBaselineNotFound,
    ProcessBaselineStepInvalid,
)
from app.models.baseline import BaselineFeaturePoint, BaselineFunction
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.process_baseline import (
    SOURCE_TYPES,
    STATUSES,
    TARGET_TYPES,
    ProcessBaseline,
    ProcessBaselineLink,
    ProcessBaselineStep,
)
from app.models.user import User

from app.process_baselines.schemas import (
    LinksReplace,
    ScenarioBatchCreate,
    ScenarioUpdate,
    StepsReplace,
)

# ---------------------------------------------------------------- 规模上限

MAX_STEPS = 100
MAX_LINKS = 50
MAX_BATCH_SCENARIOS = 20

# 文本上限（spec §10）
MAX_NAME_LEN = 255
MAX_DESCRIPTION_LEN = 500
MAX_PRECONDITION_LEN = 1000
MAX_TEXT_LEN = 1000

# 来源追溯 6 列（与 04 同名同义）。**只读**：PATCH 传了也不写。
TRACE_FIELDS = (
    "source_document_id",
    "source_version_id",
    "source_chapter_id",
    "source_chapter_title",
    "source_method",
    "source_analysis_id",
)

# 写接口的动作名——只影响错误文案。
_ACTION_CREATE = "新建流程基线场景"
_ACTION_UPDATE = "修改流程基线场景"
_ACTION_DELETE = "删除流程基线场景"
_ACTION_STEPS = "修改流程基线步骤"
_ACTION_LINKS = "修改流程基线关联"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _page(items: list, page: int, page_size: int) -> dict:
    total = len(items)
    start = max(page - 1, 0) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------- 权限


def ensure_readable(session: Session, *, project_id: int, actor: User) -> None:
    """读接口的权限入口（转发 `app/common/permissions.py`）。"""
    permissions.ensure_readable(session, project_id=project_id, actor=actor)


def _ensure_admin(
    session: Session, *, project_id: int, actor: User, action: str
) -> None:
    """写接口的权限入口：**归档先判、角色后判**。

    顺序只有这一处出处（`app/common/permissions.py`）——
    04 / 05 / 07 / 08 / 09 都用同一套。
    """
    permissions.ensure_writable_project(session, project_id, action=action)
    permissions.ensure_admin(session, project_id=project_id, actor=actor, action=action)


# ---------------------------------------------------------------- 入参校验


def _reject_unknown(payload, *, allowed: tuple[str, ...] = ()) -> None:
    """多余字段 → 400。

    写模型一律 `extra="allow"`：多余字段要活到服务层才能被判 400
    （pydantic 默认的 `ignore` 会把它们悄悄丢掉，接口返回 200，
    用户以为改了，其实什么都没改）。

    `allowed` 里的字段**允许出现但被忽略**——来源追溯 6 列属于这一类
    （只读，不是非法字段）。
    """
    extra = getattr(payload, "model_extra", None) or {}
    unknown = [key for key in extra if key not in allowed]
    if unknown:
        raise ProcessBaselineInvalid(
            "存在不支持的字段：" + "、".join(sorted(unknown))
        )


def _clean_name(value: str | None) -> str:
    """场景名称：去空格后不能为空；超长直接 400（spec §7.5）。"""
    name = (value or "").strip()
    if not name:
        raise ProcessBaselineInvalid("场景名称不能为空")
    if len(name) > MAX_NAME_LEN:
        raise ProcessBaselineInvalid(f"场景名称不能超过 {MAX_NAME_LEN} 字")
    return name


def _clean_optional(value: str | None, limit: int) -> str | None:
    """可空文本：去空格；超长截断（spec §10）。"""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def _clean_status(value: str | None, default: str = "active") -> str:
    """场景状态：只能是 active / archived。"""
    if value is None:
        return default
    status = value.strip()
    if status not in STATUSES:
        raise ProcessBaselineInvalid("场景状态只能是 active 或 archived")
    return status


def _validate_steps(steps: list[dict]) -> list[tuple[str, str]]:
    """校验整组步骤。**不合法就整组拒**（照抄 08 的 `_validate_steps`）。

    步骤的空数组非法（场景没有步骤是残缺实体）；关联的空数组合法——
    两者语义不同，校验也不同（spec §5.2 / §5.3）。
    """
    if not steps:
        raise ProcessBaselineStepInvalid("步骤不能为空")
    if len(steps) > MAX_STEPS:
        raise ProcessBaselineStepInvalid(f"步骤不能超过 {MAX_STEPS} 步")

    cleaned: list[tuple[str, str]] = []
    for row in steps:
        action = (row.get("action") or "").strip()
        if not action:
            raise ProcessBaselineStepInvalid("步骤的操作不能为空")
        expected = (row.get("expected") or "").strip()
        cleaned.append((action[:MAX_TEXT_LEN], expected[:MAX_TEXT_LEN]))
    return cleaned


def _resolve_links(
    session: Session, project_id: int, links: list[dict]
) -> list[tuple[str, int, str]]:
    """校验关联并**服务端重查**目标名。

    校验顺序（plan §5.3）：`target_type` 枚举 → 目标存在 / 属本项目 /
    `status='active'` → 同一次提交里不重复 → 关联数 ≤ 50。

    `target_name` **不采信客户端传值**——名称快照必须来自库里的真名
    （与 09 的「入库时服务端重扫重算」同一思路）。
    """
    if len(links) > MAX_LINKS:
        raise ProcessBaselineLinkInvalid(f"关联不能超过 {MAX_LINKS} 条")

    requests: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for row in links:
        target_type = (row.get("target_type") or "").strip()
        if target_type not in TARGET_TYPES:
            raise ProcessBaselineLinkInvalid(
                "关联目标类型只能是 function 或 feature_point"
            )
        target_id = row.get("target_id")
        if (
            not isinstance(target_id, int)
            or isinstance(target_id, bool)
            or target_id <= 0
        ):
            raise ProcessBaselineLinkInvalid("关联目标 id 不合法")
        key = (target_type, target_id)
        if key in seen:
            raise ProcessBaselineLinkInvalid("同一次提交里重复关联了同一个目标")
        seen.add(key)
        requests.append(key)

    function_ids = [tid for ttype, tid in requests if ttype == "function"]
    point_ids = [tid for ttype, tid in requests if ttype == "feature_point"]

    names: dict[tuple[str, int], str] = {}
    if function_ids:
        rows = session.scalars(
            select(BaselineFunction).where(BaselineFunction.id.in_(function_ids))
        ).all()
        for row in rows:
            if row.project_id != project_id:
                raise ProcessBaselineLinkInvalid(f"关联目标「{row.name}」不属于该项目")
            if row.status != "active":
                raise ProcessBaselineLinkInvalid(f"关联目标「{row.name}」已归档，不能关联")
            names[("function", row.id)] = row.name
    if point_ids:
        rows = session.scalars(
            select(BaselineFeaturePoint).where(
                BaselineFeaturePoint.id.in_(point_ids)
            )
        ).all()
        for row in rows:
            if row.project_id != project_id:
                raise ProcessBaselineLinkInvalid(f"关联目标「{row.name}」不属于该项目")
            if row.status != "active":
                raise ProcessBaselineLinkInvalid(f"关联目标「{row.name}」已归档，不能关联")
            names[("feature_point", row.id)] = row.name

    resolved: list[tuple[str, int, str]] = []
    for target_type, target_id in requests:
        name = names.get((target_type, target_id))
        if name is None:
            raise ProcessBaselineLinkInvalid(
                f"关联目标 {target_type}#{target_id} 不存在"
            )
        resolved.append((target_type, target_id, name))
    return resolved


def _check_source_triple(
    session: Session, project_id: int, item
) -> tuple[int, int, int, str | None, str | None]:
    """校验文档推导来源的**三元组自洽**（spec §5.1）。

    1. 文档 / 版本 / 章节三者必填；
    2. 文档存在且属于本项目；
    3. 版本存在且属于该文档；
    4. 章节存在且属于该文档版本。

    任一条不满足 → 400 `PROCESS_BASELINE_INVALID`，**整批拒绝**。

    返回 `(document_id, version_id, chapter_id, chapter_title, source_method)`。
    """
    document_id = item.source_document_id
    version_id = item.source_version_id
    chapter_id = item.source_chapter_id
    if document_id is None or version_id is None or chapter_id is None:
        raise ProcessBaselineInvalid(
            "文档推导来源必须同时提供 source_document_id / "
            "source_version_id / source_chapter_id"
        )

    document = session.get(Document, document_id)
    if document is None or document.project_id != project_id:
        raise ProcessBaselineInvalid("来源文档不存在或不属于该项目")

    version = session.get(DocumentVersion, version_id)
    if version is None or version.document_id != document.id:
        raise ProcessBaselineInvalid("来源文档版本与来源文档对不上")

    chapter = session.get(DocumentChapter, chapter_id)
    if chapter is None or chapter.version_id != version.id:
        raise ProcessBaselineInvalid("来源章节不属于该文档版本")

    # `source_chapter_title` 是**快照列**：优先用客户端（反推候选）给的值，
    # 没给就用库里的当前标题——之后章节改名不影响场景上的标题。
    title = (item.source_chapter_title or "").strip() or chapter.title
    method = (item.source_method or "").strip() or "baseline_reverse"
    return (
        document.id,
        version.id,
        chapter.id,
        title[:255],
        method[:32],
    )


# ---------------------------------------------------------------- 读取


def _steps_of(session: Session, baseline_id: int) -> list[dict]:
    rows = session.scalars(
        select(ProcessBaselineStep)
        .where(ProcessBaselineStep.baseline_id == baseline_id)
        .order_by(ProcessBaselineStep.step_no)
    ).all()
    return [
        {"step_no": row.step_no, "action": row.action, "expected": row.expected}
        for row in rows
    ]


def _live_targets(
    session: Session, links: list[ProcessBaselineLink]
) -> set[tuple[str, int]]:
    """一次 `IN` 批量查目标是否存活（**不做 N+1**）。

    目标被 04 物理删除后，链接行仍在、`target_name` 仍是快照名，
    只是标 `target_deleted=true`（spec §5.6）。
    """
    function_ids = {link.target_id for link in links if link.target_type == "function"}
    point_ids = {
        link.target_id for link in links if link.target_type == "feature_point"
    }
    live: set[tuple[str, int]] = set()
    if function_ids:
        rows = session.scalars(
            select(BaselineFunction.id).where(BaselineFunction.id.in_(function_ids))
        ).all()
        live.update(("function", row) for row in rows)
    if point_ids:
        rows = session.scalars(
            select(BaselineFeaturePoint.id).where(
                BaselineFeaturePoint.id.in_(point_ids)
            )
        ).all()
        live.update(("feature_point", row) for row in rows)
    return live


def _links_of(session: Session, baseline_id: int) -> list[dict]:
    rows = list(
        session.scalars(
            select(ProcessBaselineLink)
            .where(ProcessBaselineLink.baseline_id == baseline_id)
            .order_by(ProcessBaselineLink.id)
        ).all()
    )
    live = _live_targets(session, rows)
    return [
        {
            "target_type": row.target_type,
            "target_id": row.target_id,
            "target_name": row.target_name,
            "target_deleted": (row.target_type, row.target_id) not in live,
        }
        for row in rows
    ]


def _scenario_out(
    session: Session,
    scenario: ProcessBaseline,
    *,
    steps: list[dict] | None = None,
    links: list[dict] | None = None,
    step_count: int | None = None,
    link_count: int | None = None,
) -> dict:
    """场景的展示 dict。

    `steps` / `links` 传空列表 = 列表页只给计数（省掉 N+1 查询）；
    不传 = 详情页给全量。
    """
    if steps is None:
        steps = _steps_of(session, scenario.id)
    if links is None:
        links = _links_of(session, scenario.id)
    return {
        "id": scenario.id,
        "project_id": scenario.project_id,
        "name": scenario.name,
        "description": scenario.description,
        "precondition": scenario.precondition,
        "source_type": scenario.source_type,
        "status": scenario.status,
        "version_no": scenario.version_no,
        "source_document_id": scenario.source_document_id,
        "source_version_id": scenario.source_version_id,
        "source_chapter_id": scenario.source_chapter_id,
        "source_chapter_title": scenario.source_chapter_title,
        "source_method": scenario.source_method,
        "source_analysis_id": scenario.source_analysis_id,
        "created_by": scenario.created_by,
        "created_at": scenario.created_at,
        "updated_at": scenario.updated_at,
        "step_count": len(steps) if step_count is None else step_count,
        "link_count": len(links) if link_count is None else link_count,
        "steps": steps,
        "links": links,
    }


def list_scenarios(
    session: Session,
    project_id: int,
    *,
    keyword: str | None = None,
    source_type: str | None = None,
    status: str = "active",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """场景列表（关键词 / 来源类型 / 状态筛选 + 分页）。

    `status='all'` 不按状态过滤；默认 `'active'`——归档场景默认不展示
    （与 04 的「归档模块默认不展示」同一口径）。

    列表页**只给步骤 / 关联的计数**（两个聚合查询），不给全量——
    全量只在详情里给，避免列表页按场景数放大查询次数。
    """
    query = select(ProcessBaseline).where(ProcessBaseline.project_id == project_id)
    if status != "all":
        query = query.where(ProcessBaseline.status == status)
    if source_type is not None:
        query = query.where(ProcessBaseline.source_type == source_type)
    if keyword:
        query = query.where(ProcessBaseline.name.like(f"%{keyword}%"))

    rows = list(session.scalars(query.order_by(ProcessBaseline.id.desc())).all())
    if not rows:
        return _page([], page, page_size)

    baseline_ids = [row.id for row in rows]
    step_counts = dict(
        session.execute(
            select(ProcessBaselineStep.baseline_id, func.count(ProcessBaselineStep.id))
            .where(ProcessBaselineStep.baseline_id.in_(baseline_ids))
            .group_by(ProcessBaselineStep.baseline_id)
        ).all()
    )
    link_counts = dict(
        session.execute(
            select(ProcessBaselineLink.baseline_id, func.count(ProcessBaselineLink.id))
            .where(ProcessBaselineLink.baseline_id.in_(baseline_ids))
            .group_by(ProcessBaselineLink.baseline_id)
        ).all()
    )

    items = [
        _scenario_out(
            session,
            row,
            steps=[],
            links=[],
            step_count=int(step_counts.get(row.id, 0)),
            link_count=int(link_counts.get(row.id, 0)),
        )
        for row in rows
    ]
    return _page(items, page, page_size)


def _load_scenario(
    session: Session, project_id: int, scenario_id: int
) -> ProcessBaseline:
    scenario = session.get(ProcessBaseline, scenario_id)
    if scenario is None or scenario.project_id != project_id:
        raise ProcessBaselineNotFound("场景不存在")
    return scenario


def get_scenario(session: Session, *, project_id: int, scenario_id: int) -> dict:
    """场景详情（步骤 + 关联 + 目标存活标记）。"""
    scenario = _load_scenario(session, project_id, scenario_id)
    return _scenario_out(session, scenario)


# ---------------------------------------------------------------- 批量新建


def create_scenarios(
    session: Session,
    *,
    project_id: int,
    actor: User,
    payload: ScenarioBatchCreate,
) -> dict:
    """**批量**新建场景（手工添加 / 反推候选采纳）。

    **整批拒**：任一条校验失败 → 全部不落库，不半批（spec §5.1）。

    两条来源口径：

    - `source_type='manual'` → **六列追溯字段强制置 NULL**
      （PRD：手工添加不做追溯要求）；
    - `source_type='document_derived'` → 三元组**必填且自洽**，否则 400。
    """
    _ensure_admin(session, project_id=project_id, actor=actor, action=_ACTION_CREATE)
    _reject_unknown(payload)

    items = payload.scenarios
    if not items:
        raise ProcessBaselineInvalid("至少要创建一个场景")
    if len(items) > MAX_BATCH_SCENARIOS:
        raise ProcessBaselineInvalid(f"一次最多创建 {MAX_BATCH_SCENARIOS} 个场景")

    prepared: list[dict] = []
    names: set[str] = set()
    for item in items:
        _reject_unknown(item)
        name = _clean_name(item.name)
        if name in names:
            raise ProcessBaselineDuplicateName("同一次创建里有同名场景")
        names.add(name)

        source_type = (item.source_type or "manual").strip()
        if source_type not in SOURCE_TYPES:
            raise ProcessBaselineInvalid("来源类型只能是 manual 或 document_derived")

        trace: dict = {
            "source_document_id": None,
            "source_version_id": None,
            "source_chapter_id": None,
            "source_chapter_title": None,
            "source_method": None,
            "source_analysis_id": None,
        }
        if source_type == "document_derived":
            (
                trace["source_document_id"],
                trace["source_version_id"],
                trace["source_chapter_id"],
                trace["source_chapter_title"],
                trace["source_method"],
            ) = _check_source_triple(session, project_id, item)

        steps = (
            _validate_steps([row.model_dump() for row in item.steps])
            if item.steps
            else []
        )
        links = (
            _resolve_links(
                session, project_id, [row.model_dump() for row in item.links]
            )
            if item.links
            else []
        )

        prepared.append(
            {
                "name": name,
                "description": _clean_optional(item.description, MAX_DESCRIPTION_LEN),
                "precondition": _clean_optional(
                    item.precondition, MAX_PRECONDITION_LEN
                ),
                "source_type": source_type,
                "status": _clean_status(item.status),
                "trace": trace,
                "steps": steps,
                "links": links,
            }
        )

    existing = set(
        session.scalars(
            select(ProcessBaseline.name).where(
                ProcessBaseline.project_id == project_id,
                ProcessBaseline.name.in_(names),
            )
        ).all()
    )
    if existing:
        raise ProcessBaselineDuplicateName(
            "同项目已存在同名场景：" + "、".join(sorted(existing))
        )

    created: list[dict] = []
    try:
        with session.begin_nested():
            for index, row in enumerate(prepared):
                scenario = ProcessBaseline(
                    project_id=project_id,
                    name=row["name"],
                    description=row["description"],
                    precondition=row["precondition"],
                    source_type=row["source_type"],
                    status=row["status"],
                    created_by=actor.id,
                    **row["trace"],
                )
                session.add(scenario)
                session.flush()
                session.add_all(
                    [
                        ProcessBaselineStep(
                            baseline_id=scenario.id,
                            step_no=step_no,
                            action=action,
                            expected=expected,
                        )
                        for step_no, (action, expected) in enumerate(
                            row["steps"], start=1
                        )
                    ]
                )
                session.add_all(
                    [
                        ProcessBaselineLink(
                            baseline_id=scenario.id,
                            target_type=target_type,
                            target_id=target_id,
                            target_name=target_name,
                        )
                        for target_type, target_id, target_name in row["links"]
                    ]
                )
                created.append(
                    {
                        "index": index,
                        "id": scenario.id,
                        "name": scenario.name,
                        "source_type": scenario.source_type,
                        "version_no": scenario.version_no,
                        "step_count": len(row["steps"]),
                        "link_count": len(row["links"]),
                    }
                )
            session.flush()
    except IntegrityError as exc:
        if exc.orig.args[0] == 1062:
            raise ProcessBaselineDuplicateName("同项目已存在同名场景") from exc
        raise

    write_audit(
        session,
        "process_baseline.scenario.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="process_baseline_scenario",
        target_id=created[0]["id"] if created else None,
        after_data={
            "created": len(created),
            "names": [row["name"] for row in created][:20],
        },
    )
    session.commit()
    return {"created": len(created), "items": created}


# ---------------------------------------------------------------- 改 / 删


def update_scenario(
    session: Session,
    *,
    project_id: int,
    actor: User,
    scenario_id: int,
    payload: ScenarioUpdate,
) -> dict:
    """改场景元数据。**内容变更 → `version_no` +1**。

    - 只接受名称 / 描述 / 前置条件 / 状态；
    - **来源追溯 6 列只读**：传了也不写（AC-201）；
    - 其余多余字段 → 400（不是静默丢弃）。
    """
    _ensure_admin(session, project_id=project_id, actor=actor, action=_ACTION_UPDATE)

    scenario = _load_scenario(session, project_id, scenario_id)
    _reject_unknown(payload, allowed=TRACE_FIELDS)

    before = {
        "name": scenario.name,
        "description": scenario.description,
        "precondition": scenario.precondition,
        "status": scenario.status,
        "version_no": scenario.version_no,
    }

    content_changed = False

    def _apply() -> None:
        nonlocal content_changed
        if payload.name is not None:
            name = _clean_name(payload.name)
            if name != scenario.name:
                scenario.name = name
                content_changed = True
        if payload.description is not None:
            description = _clean_optional(payload.description, MAX_DESCRIPTION_LEN)
            if description != scenario.description:
                scenario.description = description
                content_changed = True
        if payload.precondition is not None:
            precondition = _clean_optional(payload.precondition, MAX_PRECONDITION_LEN)
            if precondition != scenario.precondition:
                scenario.precondition = precondition
                content_changed = True
        if payload.status is not None:
            status = _clean_status(payload.status, default=scenario.status)
            if status != scenario.status:
                scenario.status = status
        if content_changed:
            scenario.version_no += 1
        scenario.updated_at = _now()

    # 属性修改必须在 SAVEPOINT **内部**——回滚 SAVEPOINT 时 ORM 才会把
    # 已改的属性还原成旧值（照抄 04 的 `_guarded_update`）。
    # 改成别的场景的名字 → 唯一索引冲突 → 409 而不是 500。
    try:
        with session.begin_nested():
            _apply()
            session.flush()
    except IntegrityError as exc:
        if exc.orig.args[0] == 1062:
            raise ProcessBaselineDuplicateName("同项目已存在同名场景") from exc
        raise

    write_audit(
        session,
        "process_baseline.scenario.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="process_baseline_scenario",
        target_id=scenario.id,
        before_data=before,
        after_data={
            "name": scenario.name,
            "description": scenario.description,
            "precondition": scenario.precondition,
            "status": scenario.status,
            "version_no": scenario.version_no,
        },
    )
    session.commit()
    return _scenario_out(session, scenario)


def delete_scenario(
    session: Session, *, project_id: int, actor: User, scenario_id: int
) -> None:
    """删场景（**物理删除**）。

    步骤与关联由**数据库级 `ON DELETE CASCADE`** 清理，不留孤儿行
    （spec §3.9，与 08 的删用例同一口径）。
    """
    _ensure_admin(session, project_id=project_id, actor=actor, action=_ACTION_DELETE)

    scenario = _load_scenario(session, project_id, scenario_id)

    step_count = session.scalar(
        select(func.count())
        .select_from(ProcessBaselineStep)
        .where(ProcessBaselineStep.baseline_id == scenario.id)
    )
    link_count = session.scalar(
        select(func.count())
        .select_from(ProcessBaselineLink)
        .where(ProcessBaselineLink.baseline_id == scenario.id)
    )

    session.delete(scenario)
    session.flush()

    write_audit(
        session,
        "process_baseline.scenario.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="process_baseline_scenario",
        target_id=scenario.id,
        before_data={
            "name": scenario.name,
            "step_count": int(step_count or 0),
            "link_count": int(link_count or 0),
        },
    )
    session.commit()


# ---------------------------------------------------------------- 步骤覆盖


def replace_steps(
    session: Session,
    *,
    project_id: int,
    actor: User,
    scenario_id: int,
    payload: StepsReplace,
) -> dict:
    """整体覆盖步骤：旧的全删，新的按数组顺序重排为 1..n。

    **先校验整组再动手**——校验不过时旧步骤原样保留（spec §5.2）。
    """
    _ensure_admin(session, project_id=project_id, actor=actor, action=_ACTION_STEPS)

    scenario = _load_scenario(session, project_id, scenario_id)
    _reject_unknown(payload)

    steps = _validate_steps([row.model_dump() for row in payload.steps])

    old_rows = list(
        session.scalars(
            select(ProcessBaselineStep)
            .where(ProcessBaselineStep.baseline_id == scenario.id)
            .order_by(ProcessBaselineStep.step_no)
        ).all()
    )
    before_steps = [(row.action, row.expected) for row in old_rows]

    for row in old_rows:
        session.delete(row)
    session.flush()

    session.add_all(
        [
            ProcessBaselineStep(
                baseline_id=scenario.id,
                step_no=index,
                action=action,
                expected=expected,
            )
            for index, (action, expected) in enumerate(steps, start=1)
        ]
    )
    if before_steps != list(steps):
        scenario.version_no += 1
    scenario.updated_at = _now()
    session.flush()

    write_audit(
        session,
        "process_baseline.steps.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="process_baseline_scenario",
        target_id=scenario.id,
        before_data={
            "before_count": len(old_rows),
            "actions": [action for action, _ in before_steps],
        },
        after_data={"after_count": len(steps)},
    )
    session.commit()
    return _scenario_out(session, scenario)


# ---------------------------------------------------------------- 关联覆盖


def replace_links(
    session: Session,
    *,
    project_id: int,
    actor: User,
    scenario_id: int,
    payload: LinksReplace,
) -> dict:
    """整体覆盖关联：旧的全删，新的按服务端重查的名字写入。

    **空数组合法**（清空关联）——场景没有关联仍然可用（spec §5.3）。
    """
    _ensure_admin(session, project_id=project_id, actor=actor, action=_ACTION_LINKS)

    scenario = _load_scenario(session, project_id, scenario_id)
    _reject_unknown(payload)

    resolved = _resolve_links(
        session, project_id, [row.model_dump() for row in payload.links]
    )

    old_rows = list(
        session.scalars(
            select(ProcessBaselineLink).where(
                ProcessBaselineLink.baseline_id == scenario.id
            )
        ).all()
    )
    before_targets = sorted(f"{row.target_type}#{row.target_id}" for row in old_rows)

    for row in old_rows:
        session.delete(row)
    session.flush()

    session.add_all(
        [
            ProcessBaselineLink(
                baseline_id=scenario.id,
                target_type=target_type,
                target_id=target_id,
                target_name=target_name,
            )
            for target_type, target_id, target_name in resolved
        ]
    )
    if before_targets != sorted(
        f"{target_type}#{target_id}" for target_type, target_id, _ in resolved
    ):
        scenario.version_no += 1
    scenario.updated_at = _now()
    session.flush()

    write_audit(
        session,
        "process_baseline.links.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="process_baseline_scenario",
        target_id=scenario.id,
        before_data={"before_count": len(old_rows), "targets": before_targets},
        after_data={"after_count": len(resolved)},
    )
    session.commit()
    return _scenario_out(session, scenario)
