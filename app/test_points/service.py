"""测试点生成的服务层（07-test-points T101）。

**固定校验顺序**（spec §6.2）：

    项目 404 → 归档 409 → 角色 403 → 模板 400 → 增量记录 404/409 →
    快照 404/400 → 章节 400 → 输入为空 400 → 跑模型

**校验阶段失败不建行**，因此不会留下「脏记录」——
这与 05 的「失败留痕」不同：05 是在创建行**之后**失败才留痕，
07 在校验阶段就失败的话，连行都不该有。

生成过程与 05 同构：

    insert(status='running') → 跑引擎 → 回填 stats/status/finished_at

失败时置 `status='failed'` + `error_code` + `error_message`，
**已落库的章节保留**（`on_chapter` 回调逐章落库）。

审计遵循「改数据 → flush → write_audit → commit」，`write_audit` 内部不 commit。
运行留痕的 `calls` **跑前记基线、跑完相减**——`provider.calls` 是累计的，
直接取 `len(calls)` 会把历史调用也算进来。
"""

import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import permissions
from app.common.audit import write_audit
from app.common.errors import (
    AppError,
    LLMCallFailed,
    TestPointAnalysisHasApproved,
    TestPointAnalysisNotFound,
    TestPointInputEmpty,
    TestPointInvalid,
    TestPointNotFound,
    TestPointReviewStateInvalid,
    TestPointTargetNotFound,
    TestPointTemplateInvalid,
)
from app.llm import run_log
from app.llm.provider import LLMProvider
from app.models.baseline import BaselineRevision
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import IncrementalAnalysis, PromptTemplate
from app.models.test_point import (
    POINT_PRIORITIES,
    POINT_TARGET_TYPES,
    TestPoint,
    TestPointAnalysis,
)
from app.models.user import User

from app.test_points import engine
from app.test_points.context import (
    active_label_context,
    analysis_fully_revoked,
    conclusion_context,
)
from app.test_points.schemas import AnalysisCreate, PointCreate, PointUpdate

# 写接口的动作名——只影响错误文案。
_ACTION = "发起测试点生成"

# 模板的 task_type。`prompt_templates.task_type` 的枚举 0013 就已预留。
TEMPLATE_TASK_TYPE = "test_point"


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
    """读接口的权限入口（路由调用）。"""
    permissions.ensure_readable(session, project_id=project_id, actor=actor)


# ------------------------------------------------------------ 资源校验


def _load_template(session: Session, template_id: int) -> PromptTemplate:
    """取模板。必须 `task_type='test_point'` 且已启用。"""
    template = session.get(PromptTemplate, template_id)
    if template is None:
        raise TestPointTemplateInvalid("提示词模板不存在")
    if template.task_type != TEMPLATE_TASK_TYPE:
        raise TestPointTemplateInvalid("提示词模板类型不是「测试点生成」")
    if template.status != "active":
        raise TestPointTemplateInvalid("提示词模板已停用")
    return template


def _load_analysis(
    session: Session, *, project_id: int, analysis_id: int
) -> IncrementalAnalysis:
    """取增量分析记录。**结论已全部撤销的记录不可选**（spec AC-143）。"""
    analysis = session.get(IncrementalAnalysis, analysis_id)
    if analysis is None or analysis.project_id != project_id:
        raise TestPointAnalysisNotFound("增量分析记录不存在")
    if analysis.status != "succeeded":
        raise TestPointAnalysisNotFound("增量分析记录未成功，不能作为依据")
    if analysis_fully_revoked(session, analysis_id=analysis.id):
        raise TestPointInputEmpty(
            "该增量分析结论已全部撤销，不能作为测试点依据"
        )
    return analysis


def _load_revision(
    session: Session, *, project_id: int, revision_id: int
) -> BaselineRevision:
    """取基线快照。必须是 `approved` 的。"""
    revision = session.get(BaselineRevision, revision_id)
    if revision is None or revision.project_id != project_id:
        raise TestPointTargetNotFound("基线快照不存在")
    if revision.status != "approved":
        raise TestPointTargetNotFound("基线快照未审核通过，不能作为依据")
    return revision


def _load_version(
    session: Session, *, project_id: int, version_id: int
) -> tuple[DocumentVersion, Document]:
    """取文档版本。必须属于本项目且已生效。"""
    version = session.get(DocumentVersion, version_id)
    if version is None:
        raise TestPointTargetNotFound("文档版本不存在")
    document = session.get(Document, version.document_id)
    if document is None or document.project_id != project_id:
        raise TestPointTargetNotFound("文档版本不属于该项目")
    if version.status != "active":
        raise TestPointTargetNotFound("只有生效版本的文档可以生成测试点")
    return version, document


def _load_chapters(
    session: Session, *, version_id: int, chapter_ids: list[int] | None
) -> list[DocumentChapter]:
    """取章节。不给 `chapter_ids` → 全文档；给了 → 只取这些（按 `seq` 升序）。"""
    query = select(DocumentChapter).where(DocumentChapter.version_id == version_id)
    if chapter_ids:
        query = query.where(DocumentChapter.id.in_(chapter_ids))
    rows = list(session.scalars(query.order_by(DocumentChapter.seq)).all())
    if chapter_ids:
        found = {row.id for row in rows}
        missing = [cid for cid in chapter_ids if cid not in found]
        if missing:
            raise TestPointTargetNotFound(
                f"章节不存在或不属于该文档版本：{missing}"
            )
    return rows


def _stats(
    *,
    chapter_count: int,
    processed_count: int,
    points: list,
    discarded: list[dict],
    skipped_empty: int,
) -> dict:
    """生成统计。`test_point_count` 只算落库的条数。"""
    return {
        "chapter_count": chapter_count,
        "processed_count": processed_count,
        "test_point_count": len(points),
        "discarded_count": len(discarded),
        "skipped_empty_count": skipped_empty,
        "discarded": discarded,
    }


# ------------------------------------------------------------ 发起生成


def create_analysis(
    session: Session,
    *,
    project_id: int,
    actor: User,
    payload: AnalysisCreate,
    provider: LLMProvider,
) -> TestPointAnalysis:
    """发起一次测试点生成（**同步执行**）。

    校验顺序固定（spec §6.2）：项目 404 → 归档 409 → 角色 403 → 模板 400 →
    增量记录 404/409 → 快照 404/400 → 章节 400 → 输入为空 400 → 跑模型。

    **任何一步失败都不产生生成记录**（校验在建行之前）。
    """
    permissions.ensure_writable_project(session, project_id, action=_ACTION)
    permissions.ensure_admin(session, project_id=project_id, actor=actor, action=_ACTION)

    template = _load_template(session, payload.template_id)

    source_analysis = None
    if payload.analysis_id is not None:
        source_analysis = _load_analysis(
            session, project_id=project_id, analysis_id=payload.analysis_id
        )

    revision = None
    if payload.baseline_revision_id is not None:
        revision = _load_revision(
            session, project_id=project_id, revision_id=payload.baseline_revision_id
        )

    # 增量结论与基线快照**至少给一个**——没有输入就没有依据。
    if source_analysis is None and revision is None:
        raise TestPointInputEmpty(
            "至少要选择增量分析记录或基线快照之一作为测试点依据"
        )

    version = None
    document = None
    if payload.document_version_id is not None:
        version, document = _load_version(
            session, project_id=project_id, version_id=payload.document_version_id
        )
    elif source_analysis is not None:
        version = session.get(DocumentVersion, source_analysis.document_version_id)
        if version is not None:
            document = session.get(Document, version.document_id)

    chapters: list[DocumentChapter] = []
    if version is not None:
        chapters = _load_chapters(
            session, version_id=version.id, chapter_ids=payload.chapter_ids
        )

    # 取输入上下文：生效标签 + 增量结论。
    labels = active_label_context(
        session,
        project_id=project_id,
        revision_id=revision.id if revision is not None else None,
    )
    conclusions = (
        conclusion_context(session, analysis_id=source_analysis.id)
        if source_analysis is not None
        else None
    )

    # 输入为空 → 400。**没有依据就不许生成**——测试点挂不到任何功能上。
    if not labels.index and not (conclusions and conclusions.items):
        raise TestPointInputEmpty("没有生效标签也没有可用的增量结论，无法生成测试点")

    analysis = TestPointAnalysis(
        project_id=project_id,
        template_id=template.id,
        template_version=template.version_no,
        provider=provider.name,
        document_id=document.id if document is not None else None,
        document_version_id=version.id if version is not None else None,
        analysis_id=source_analysis.id if source_analysis is not None else None,
        baseline_revision_id=revision.id if revision is not None else None,
        status="running",
        started_at=_now(),
        created_by=actor.id,
    )
    session.add(analysis)
    session.flush()

    write_audit(
        session,
        "test_point.analysis.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_point_analysis",
        target_id=analysis.id,
        after_data={
            "template_id": template.id,
            "template_version": template.version_no,
            "analysis_id": analysis.analysis_id,
            "baseline_revision_id": analysis.baseline_revision_id,
            "document_version_id": analysis.document_version_id,
            "provider": provider.name,
        },
    )
    session.commit()

    points: list[engine.PendingPoint] = []
    discarded: list[dict] = []

    def _persist(result: engine.ChapterResult) -> None:
        """每章处理完立刻落库：后续章节失败时这一章的结果不会丢。"""
        rows = [
            TestPoint(
                project_id=project_id,
                analysis_id=analysis.id,
                name=item.name,
                target_type=item.target_type,
                target_id=item.target_id,
                target_name=item.target_name,
                priority=item.priority,
                precondition=item.precondition,
                verification=item.verification,
                chapter_id=item.chapter_id,
                chapter_title=item.chapter_title,
                source_label_id=item.source_label_id,
                source_conclusion_id=item.source_conclusion_id,
                status="pending",
                source_type="llm",
                created_by=actor.id,
            )
            for item in result.points
        ]
        if rows:
            session.add_all(rows)
            session.flush()
        points.extend(rows)
        discarded.extend(result.discarded)

    # 运行留痕：跑前记调用基线，跑完相减算本次调用了几次。
    calls_before = run_log.call_count(provider)
    started_at = time.monotonic()

    try:
        result: engine.GenerateResult = engine.run_generate(
            session,
            provider=provider,
            template=template,
            chapters=chapters,
            labels=labels,
            conclusions=conclusions,
            on_chapter=_persist,
        )
    except AppError as exc:
        _mark_failed(
            session,
            analysis,
            code=exc.code,
            message=exc.message,
            points=points,
            discarded=discarded,
        )
        run_log.record_run(
            session,
            task_type="test_point",
            provider=provider,
            calls=run_log.call_count(provider) - calls_before,
            started_at=started_at,
            status="failed",
            error_code=exc.code,
            error_message=exc.message,
            project_id=project_id,
            analysis_id=analysis.id,
            template_id=template.id,
            template_version=template.version_no,
        )
        session.commit()
        raise
    except Exception as exc:  # 内部异常同样立刻失败，不让前端干等
        message = f"测试点生成失败：{exc}"
        _mark_failed(
            session,
            analysis,
            code=LLMCallFailed.code,
            message=message,
            points=points,
            discarded=discarded,
        )
        run_log.record_run(
            session,
            task_type="test_point",
            provider=provider,
            calls=run_log.call_count(provider) - calls_before,
            started_at=started_at,
            status="failed",
            error_code=LLMCallFailed.code,
            error_message=message,
            project_id=project_id,
            analysis_id=analysis.id,
            template_id=template.id,
            template_version=template.version_no,
        )
        session.commit()
        raise LLMCallFailed("测试点生成失败") from exc

    analysis.status = "succeeded"
    analysis.finished_at = _now()
    analysis.stats = _stats(
        chapter_count=result.chapter_count,
        processed_count=len(result.chapters),
        points=points,
        discarded=discarded,
        skipped_empty=result.skipped_empty,
    )
    run_log.record_run(
        session,
        task_type="test_point",
        provider=provider,
        calls=run_log.call_count(provider) - calls_before,
        started_at=started_at,
        status="succeeded",
        project_id=project_id,
        analysis_id=analysis.id,
        template_id=template.id,
        template_version=template.version_no,
    )
    session.flush()
    session.commit()
    return analysis


def _mark_failed(
    session: Session,
    analysis: TestPointAnalysis,
    *,
    code: str,
    message: str,
    points: list,
    discarded: list[dict],
) -> None:
    """把生成记录标成失败。**已落库的测试点保留**（便于排查）。"""
    analysis.status = "failed"
    analysis.error_code = code
    analysis.error_message = message[:500]
    analysis.finished_at = _now()
    analysis.stats = _stats(
        chapter_count=analysis.stats.get("chapter_count", 0)
        if analysis.stats
        else 0,
        processed_count=analysis.stats.get("processed_count", 0)
        if analysis.stats
        else 0,
        points=points,
        discarded=discarded,
        skipped_empty=analysis.stats.get("skipped_empty_count", 0)
        if analysis.stats
        else 0,
    )
    session.flush()


# ------------------------------------------------------------ 查询


def _analysis_item(session: Session, analysis: TestPointAnalysis) -> dict:
    template = session.get(PromptTemplate, analysis.template_id)
    document = (
        session.get(Document, analysis.document_id)
        if analysis.document_id is not None
        else None
    )
    return {
        "id": analysis.id,
        "project_id": analysis.project_id,
        "template_id": analysis.template_id,
        "template_name": template.name if template else None,
        "template_version": analysis.template_version,
        "provider": analysis.provider,
        "analysis_id": analysis.analysis_id,
        "baseline_revision_id": analysis.baseline_revision_id,
        "document_id": analysis.document_id,
        "document_name": document.name if document else None,
        "document_version_id": analysis.document_version_id,
        "status": analysis.status,
        "error_code": analysis.error_code,
        "error_message": analysis.error_message,
        "stats": analysis.stats,
        "started_at": analysis.started_at,
        "finished_at": analysis.finished_at,
        "created_by": analysis.created_by,
        "created_at": analysis.created_at,
    }


def list_analyses(
    session: Session, *, project_id: int, page: int = 1, page_size: int = 50
) -> dict:
    """生成记录列表（按 id 倒序——新的在前）。"""
    rows = list(
        session.scalars(
            select(TestPointAnalysis)
            .where(TestPointAnalysis.project_id == project_id)
            .order_by(TestPointAnalysis.id.desc())
        ).all()
    )
    items = [_analysis_item(session, row) for row in rows]
    return _page(items, page, page_size)


def get_analysis(
    session: Session, *, project_id: int, analysis_id: int
) -> dict:
    """生成记录详情 + 它产出的测试点。"""
    analysis = session.get(TestPointAnalysis, analysis_id)
    if analysis is None or analysis.project_id != project_id:
        raise TestPointAnalysisNotFound("生成记录不存在")
    item = _analysis_item(session, analysis)
    item["points"] = [
        _point_item(row)
        for row in session.scalars(
            select(TestPoint)
            .where(TestPoint.analysis_id == analysis.id)
            .order_by(TestPoint.id)
        ).all()
    ]
    return item


def _point_item(point: TestPoint) -> dict:
    return {
        "id": point.id,
        "project_id": point.project_id,
        "analysis_id": point.analysis_id,
        "name": point.name,
        "target_type": point.target_type,
        "target_id": point.target_id,
        "target_name": point.target_name,
        "priority": point.priority,
        "precondition": point.precondition,
        "verification": point.verification,
        "chapter_id": point.chapter_id,
        "chapter_title": point.chapter_title,
        "source_label_id": point.source_label_id,
        "source_conclusion_id": point.source_conclusion_id,
        "status": point.status,
        "reviewed_by": point.reviewed_by,
        "reviewed_at": point.reviewed_at,
        "review_comment": point.review_comment,
        "needs_review": bool(point.needs_review),
        "needs_review_reason": point.needs_review_reason,
        "needs_review_at": point.needs_review_at,
        "source_type": point.source_type,
        "created_by": point.created_by,
        "created_at": point.created_at,
        "updated_at": point.updated_at,
    }


def list_analysis_points(
    session: Session, *, project_id: int, analysis_id: int
) -> list[dict]:
    """某次生成产出的测试点。"""
    analysis = session.get(TestPointAnalysis, analysis_id)
    if analysis is None or analysis.project_id != project_id:
        raise TestPointAnalysisNotFound("生成记录不存在")
    return [
        _point_item(row)
        for row in session.scalars(
            select(TestPoint)
            .where(TestPoint.analysis_id == analysis.id)
            .order_by(TestPoint.id)
        ).all()
    ]


def list_points(
    session: Session,
    *,
    project_id: int,
    status: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    analysis_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """测试点列表（按项目 / 状态 / 目标 / 生成记录筛选）。"""
    query = select(TestPoint).where(TestPoint.project_id == project_id)
    if status is not None:
        query = query.where(TestPoint.status == status)
    if target_type is not None:
        query = query.where(TestPoint.target_type == target_type)
    if target_id is not None:
        query = query.where(TestPoint.target_id == target_id)
    if analysis_id is not None:
        query = query.where(TestPoint.analysis_id == analysis_id)

    rows = list(session.scalars(query.order_by(TestPoint.id.desc())).all())
    items = [_point_item(row) for row in rows]
    return _page(items, page, page_size)


def get_point(session: Session, *, project_id: int, point_id: int) -> dict:
    """测试点详情。"""
    point = session.get(TestPoint, point_id)
    if point is None or point.project_id != project_id:
        raise TestPointNotFound("测试点不存在")
    return _point_item(point)


# ------------------------------------------------------------ 评审


def review_point(
    session: Session,
    *,
    project_id: int,
    point_id: int,
    actor: User,
    action: str,
    comment: str | None = None,
) -> dict:
    """评审一条测试点：通过 / 驳回。

    **已评审过的不能重复评审**（409）——评审意见一次定稿，
    反复改会让人搞不清哪条意见是最终结论。
    """
    permissions.ensure_writable_project(
        session, project_id, action="评审测试点"
    )
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="评审测试点"
    )

    if action not in ("approve", "reject"):
        raise TestPointInvalid("评审动作只能是 approve 或 reject")

    point = session.get(TestPoint, point_id)
    if point is None or point.project_id != project_id:
        raise TestPointNotFound("测试点不存在")
    if point.status != "pending":
        raise TestPointReviewStateInvalid("该测试点已评审过，不能重复评审")

    point.status = "approved" if action == "approve" else "rejected"
    point.reviewed_by = actor.id
    point.reviewed_at = _now()
    point.review_comment = comment
    session.flush()

    write_audit(
        session,
        "test_point.review",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_point",
        target_id=point.id,
        before_data={"status": "pending"},
        after_data={
            "status": point.status,
            "action": action,
            # 自审留痕：单人管理员是常态，但要知道这条是不是自己批的。
            "self_approved": point.created_by == actor.id,
        },
        reason=comment,
    )
    session.commit()
    return _point_item(point)


# ------------------------------------------------------------ 手工增删改


def create_manual_point(
    session: Session,
    *,
    project_id: int,
    actor: User,
    payload: PointCreate,
) -> dict:
    """手工新增一条测试点。

    `source_type='manual'`、`analysis_id=NULL`——手工新增没有来源。
    """
    permissions.ensure_writable_project(
        session, project_id, action="手工新增测试点"
    )
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="手工新增测试点"
    )

    name = (payload.name or "").strip()
    if not name:
        raise TestPointInvalid("测试点名称不能为空")
    if payload.target_type not in POINT_TARGET_TYPES:
        raise TestPointInvalid("测试点归属类型只能是 function 或 feature_point")
    priority = payload.priority or "medium"
    if priority not in POINT_PRIORITIES:
        raise TestPointInvalid("优先级只能是 high / medium / low")

    target_name = _target_name(
        session, target_type=payload.target_type, target_id=payload.target_id
    )
    if target_name is None:
        raise TestPointTargetNotFound("测试点归属的功能或功能点不存在")

    chapter_title = None
    if payload.chapter_id is not None:
        chapter = session.get(DocumentChapter, payload.chapter_id)
        if chapter is None:
            raise TestPointTargetNotFound("章节不存在")
        chapter_title = chapter.title

    point = TestPoint(
        project_id=project_id,
        analysis_id=None,
        name=name,
        target_type=payload.target_type,
        target_id=payload.target_id,
        target_name=target_name,
        priority=priority,
        precondition=payload.precondition or "",
        verification=payload.verification or "",
        chapter_id=payload.chapter_id,
        chapter_title=chapter_title,
        status="pending",
        source_type="manual",
        created_by=actor.id,
    )
    session.add(point)
    session.flush()

    write_audit(
        session,
        "test_point.point.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_point",
        target_id=point.id,
        after_data={
            "name": point.name,
            "target_type": point.target_type,
            "target_id": point.target_id,
            "priority": point.priority,
            "source_type": "manual",
        },
    )
    session.commit()
    return _point_item(point)


def update_point(
    session: Session,
    *,
    project_id: int,
    point_id: int,
    actor: User,
    payload: PointUpdate,
) -> dict:
    """手工改测试点。

    **只接受 4 个字段**：名称 / 优先级 / 前置条件 / 验证要点。
    目标 / 状态 / 来源都不该手工改——那会破坏追溯链。
    """
    permissions.ensure_writable_project(
        session, project_id, action="修改测试点"
    )
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="修改测试点"
    )

    point = session.get(TestPoint, point_id)
    if point is None or point.project_id != project_id:
        raise TestPointNotFound("测试点不存在")

    before = {
        "name": point.name,
        "priority": point.priority,
        "precondition": point.precondition,
        "verification": point.verification,
    }

    updates = payload.model_dump(exclude_unset=True)
    # `extra="allow"` 留下的多余字段也在 `model_extra` 里——
    # 它们**必须被判 400**，否则用户以为改了目标，其实被悄悄丢掉。
    extras = payload.model_extra or {}
    forbidden = (set(updates) - {"name", "priority", "precondition", "verification"}) | set(
        extras
    )
    if forbidden:
        raise TestPointInvalid(f"这些字段不允许手工修改：{sorted(forbidden)}")

    if "name" in updates and updates["name"] is not None:
        name = updates["name"].strip()
        if not name:
            raise TestPointInvalid("测试点名称不能为空")
        point.name = name
    if "priority" in updates and updates["priority"] is not None:
        if updates["priority"] not in POINT_PRIORITIES:
            raise TestPointInvalid("优先级只能是 high / medium / low")
        point.priority = updates["priority"]
    if "precondition" in updates and updates["precondition"] is not None:
        point.precondition = updates["precondition"]
    if "verification" in updates and updates["verification"] is not None:
        point.verification = updates["verification"]

    session.flush()
    write_audit(
        session,
        "test_point.point.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_point",
        target_id=point.id,
        before_data=before,
        after_data={
            "name": point.name,
            "priority": point.priority,
            "precondition": point.precondition,
            "verification": point.verification,
        },
    )
    session.commit()
    return _point_item(point)


def delete_point(
    session: Session, *, project_id: int, point_id: int, actor: User
) -> None:
    """删测试点。

    **物理删除**——测试点是活文档，不是留痕记录（留痕在审计日志里）。
    """
    permissions.ensure_writable_project(session, project_id, action="删除测试点")
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="删除测试点"
    )

    point = session.get(TestPoint, point_id)
    if point is None or point.project_id != project_id:
        raise TestPointNotFound("测试点不存在")

    before = {
        "name": point.name,
        "target_type": point.target_type,
        "target_id": point.target_id,
        "status": point.status,
    }
    session.delete(point)
    session.flush()

    write_audit(
        session,
        "test_point.point.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_point",
        target_id=point_id,
        before_data=before,
    )
    session.commit()


def delete_analysis(
    session: Session, *, project_id: int, analysis_id: int, actor: User
) -> None:
    """删除一次生成记录，**连带删除它产出的测试点**。

    已有评审通过的测试点 → 409：评审通过的测试点可能已被下游（08 期用例）
    引用，不能因为删一次生成记录就把它带走。
    """
    permissions.ensure_writable_project(
        session, project_id, action="删除测试点生成记录"
    )
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="删除测试点生成记录"
    )

    analysis = session.get(TestPointAnalysis, analysis_id)
    if analysis is None or analysis.project_id != project_id:
        raise TestPointAnalysisNotFound("生成记录不存在")

    points = list(
        session.scalars(
            select(TestPoint).where(TestPoint.analysis_id == analysis.id)
        ).all()
    )
    approved = [row for row in points if row.status == "approved"]
    if approved:
        raise TestPointAnalysisHasApproved(
            f"这次生成已产出 {len(approved)} 条评审通过的测试点，不允许连带删除"
        )

    for row in points:
        session.delete(row)
    session.delete(analysis)
    session.flush()

    write_audit(
        session,
        "test_point.analysis.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_point_analysis",
        target_id=analysis_id,
        before_data={
            "status": analysis.status,
            "template_id": analysis.template_id,
            "point_count": len(points),
        },
    )
    session.commit()


def _target_name(
    session: Session, *, target_type: str, target_id: int
) -> str | None:
    """目标 id → 名称。查不到返回 None（目标已删）。"""
    from app.models.baseline import BaselineFeaturePoint, BaselineFunction

    if target_type == "function":
        return session.scalar(
            select(BaselineFunction.name).where(BaselineFunction.id == target_id)
        )
    return session.scalar(
        select(BaselineFeaturePoint.name).where(
            BaselineFeaturePoint.id == target_id
        )
    )


__all__ = [
    "TEMPLATE_TASK_TYPE",
    "create_analysis",
    "create_manual_point",
    "delete_analysis",
    "delete_point",
    "ensure_readable",
    "get_analysis",
    "get_point",
    "list_analysis_points",
    "list_analyses",
    "list_points",
    "review_point",
    "update_point",
]
