"""分析记录生命周期。

固定校验顺序（spec §5）：项目 → 归档 → 角色 → 模板 → 快照 → 文档版本。
第 4–6 步失败不建行，因此不会留下「脏记录」。

第一遍同步执行：

    insert(status='running') → 跑第一遍 → 回填 stats/status/finished_at

失败处理：引擎抛出的异常在这里统一落成 `status='failed'` + `error_code` +
`error_message` + `finished_at`，**立刻返回/抛出**，不进入下一章、不做重试。
此前章节的结论通过 `on_chapter` 回调已逐章落库，保留在事务里便于排查。

第二遍（第二期）同样同步执行，状态写在 `second_pass_*` 列上，不覆盖第一遍：

    第二遍校验 → second_pass_status='running' → 2b-1/2b-2/2b-3 → 回填统计

失败时置 `second_pass_status='failed'` 并留 `second_pass_error_*`，
已产出的裁决 / 冲突保留在库里便于排查。

审计：`incremental.analysis.create` / `incremental.second_pass.run`，
遵循「改数据 → flush → write_audit → commit」，`write_audit` 内部不 commit。
"""

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.deps import SYSTEM_ADMIN
from app.common.errors import (
    AppError,
    BaselineRevisionRequired,
    ConflictAlreadyResolved,
    ConflictNotFound,
    DocumentVersionNotAnalyzable,
    IncrementalAnalysisNotFound,
    InvalidConflictResolution,
    InvalidSplitGranularity,
    LLMCallFailed,
    NoActiveDocumentVersion,
    NotProjectAdmin,
    NotProjectMember,
    ProjectArchived,
    ProjectNotFound,
    SecondPassConflictsPending,
    SecondPassNotReady,
    SecondPassTemplateMissing,
    TemplateDisabled,
    TemplateNotFound,
)
from app.incremental import engine, links, second_pass
from app.incremental.engine import ChapterResult, PassResult
from app.incremental.schemas import AnalysisCreate, ConflictResolve
from app.llm.provider import LLMProvider
from app.models.baseline import BaselineRevision
from app.models.chapter_link import DocumentChapterLink
from app.models.document import Document, DocumentVersion
from app.models.incremental import (
    SPLIT_GRANULARITIES,
    IncrementalAnalysis,
    IncrementalConclusion,
    IncrementalConflict,
    IncrementalDecision,
    PromptTemplate,
)
from app.models.project import Project, ProjectMember
from app.models.user import User

DEFAULT_GRANULARITY = "chapter"
# 第二遍模板按名字前缀取：与第一遍同属 task_type='incremental'，不能用 task_type 区分
SECOND_PASS_TEMPLATE_PREFIX = "增量分析·第二遍"


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


def _ensure_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFound("项目不存在")
    return project


def _ensure_writable_project(session: Session, project_id: int) -> Project:
    """写接口：不存在 404，已归档 409（先判归档再判角色）。"""
    project = _ensure_project(session, project_id)
    if project.status != "active":
        raise ProjectArchived("项目已归档，不可发起增量分析")
    return project


def _ensure_admin(session: Session, *, project_id: int, actor: User) -> None:
    if actor.global_role == SYSTEM_ADMIN:
        return
    member = session.get(ProjectMember, (project_id, actor.id))
    if member is None or member.role != "project_admin":
        raise NotProjectAdmin("只有项目管理员可以发起增量分析")


def _ensure_member(session: Session, *, project_id: int, actor: User) -> None:
    if actor.global_role == SYSTEM_ADMIN:
        return
    if session.get(ProjectMember, (project_id, actor.id)) is None:
        raise NotProjectMember("不是该项目成员")


def ensure_readable(session: Session, *, project_id: int, actor: User) -> None:
    """读接口权限入口：项目存在 + 成员（含访客）。"""
    _ensure_project(session, project_id)
    _ensure_member(session, project_id=project_id, actor=actor)


# ------------------------------------------------------------ 资源校验


def _load_template(session: Session, template_id: int) -> PromptTemplate:
    template = session.get(PromptTemplate, template_id)
    if template is None:
        raise TemplateNotFound("提示词模板不存在")
    if template.status != "active":
        raise TemplateDisabled("提示词模板已停用")
    return template


def _load_revision(
    session: Session, *, project_id: int, revision_id: int | None
) -> BaselineRevision:
    """快照必须存在、属本项目、且已审核通过。"""
    if revision_id is None:
        raise BaselineRevisionRequired("请选择一份审核通过的基线快照")
    revision = session.scalar(
        select(BaselineRevision).where(
            BaselineRevision.id == revision_id,
            BaselineRevision.project_id == project_id,
            BaselineRevision.status == "approved",
        )
    )
    if revision is None:
        raise BaselineRevisionRequired("基线快照不存在、不属于该项目或尚未通过审核")
    return revision


def _load_version(
    session: Session, *, project_id: int, version_id: int
) -> tuple[DocumentVersion, Document]:
    """文档版本必须属本项目；存在但非生效版本单独报错。"""
    row = session.execute(
        select(DocumentVersion, Document)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.id == version_id, Document.project_id == project_id)
    ).first()
    if row is None:
        raise NoActiveDocumentVersion("文档版本不存在或不属于该项目")
    version, document = row
    if version.status != "active":
        raise DocumentVersionNotAnalyzable("只有生效版本的文档可以参与增量分析")
    return version, document


# ------------------------------------------------------------ 统计


def _stats(
    *,
    chapter_count: int,
    conclusions: list[IncrementalConclusion],
    discarded: list[dict],
) -> dict:
    return {
        "chapter_count": chapter_count,
        "conclusion_count": len(conclusions),
        "discarded_count": len(discarded),
        "dropped_new_count": sum(
            1 for item in discarded if item.get("code") == engine.NEW_DROPPED
        ),
        "discarded": discarded,
    }


def _mark_failed(
    session: Session,
    analysis: IncrementalAnalysis,
    *,
    code: str,
    message: str,
    conclusions: list[IncrementalConclusion],
    discarded: list[dict],
    extra: dict,
) -> None:
    analysis.status = "failed"
    analysis.error_code = code[:64]
    analysis.error_message = (message or code)[:500]
    analysis.finished_at = _now()
    stats = _stats(
        chapter_count=int(extra.get("chapter_count") or 0),
        conclusions=conclusions,
        discarded=discarded,
    )
    if extra.get("chapter_id") is not None:
        stats["failed_chapter_id"] = extra["chapter_id"]
        stats["failed_chapter_title"] = extra.get("chapter_title")
    analysis.stats = stats
    session.flush()


# ------------------------------------------------------------ 发起分析


def create_analysis(
    session: Session,
    *,
    project_id: int,
    actor: User,
    payload: AnalysisCreate,
    provider: LLMProvider,
) -> IncrementalAnalysis:
    """校验 → 建行 → 同步跑第一遍 → 回填状态。"""
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    granularity = payload.split_granularity or DEFAULT_GRANULARITY
    if granularity not in SPLIT_GRANULARITIES:
        raise InvalidSplitGranularity("本期只支持按章节切分（chapter）")

    template = _load_template(session, payload.template_id)
    revision = _load_revision(
        session, project_id=project_id, revision_id=payload.baseline_revision_id
    )
    version, document = _load_version(
        session, project_id=project_id, version_id=payload.document_version_id
    )

    analysis = IncrementalAnalysis(
        project_id=project_id,
        template_id=template.id,
        template_version=template.version_no,
        provider=provider.name,
        baseline_revision_id=revision.id,
        document_id=document.id,
        document_version_id=version.id,
        split_granularity=granularity,
        status="running",
        started_at=_now(),
        created_by=actor.id,
    )
    session.add(analysis)
    session.flush()

    write_audit(
        session,
        "incremental.analysis.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="incremental_analysis",
        target_id=analysis.id,
        after_data={
            "template_id": template.id,
            "template_version": template.version_no,
            "baseline_revision_id": revision.id,
            "document_id": document.id,
            "document_version_id": version.id,
            "split_granularity": granularity,
            "provider": provider.name,
        },
    )
    session.commit()

    conclusions: list[IncrementalConclusion] = []
    discarded: list[dict] = []

    def _persist(result: ChapterResult) -> None:
        """每章处理完立刻落库：后续章节失败时这一章的结果不会丢。"""
        rows = [
            IncrementalConclusion(
                analysis_id=analysis.id,
                chapter_id=item.chapter_id,
                chapter_title=item.chapter_title,
                target_type=item.target_type,
                target_id=item.target_id,
                label_type=item.label_type,
                confidence=item.confidence,
                rationale=item.rationale,
            )
            for item in result.conclusions
        ]
        if rows:
            session.add_all(rows)
            session.flush()
        conclusions.extend(rows)
        discarded.extend(result.discarded)

    try:
        result: PassResult = engine.run_first_pass(
            session,
            analysis=analysis,
            provider=provider,
            template=template,
            on_chapter=_persist,
        )
    except AppError as exc:
        _mark_failed(
            session,
            analysis,
            code=exc.code,
            message=exc.message,
            conclusions=conclusions,
            discarded=discarded,
            extra=exc.extra,
        )
        session.commit()
        raise
    except Exception as exc:  # 内部异常同样立刻失败，不让前端干等
        _mark_failed(
            session,
            analysis,
            code=LLMCallFailed.code,
            message=f"分析执行失败：{exc}",
            conclusions=conclusions,
            discarded=discarded,
            extra={},
        )
        session.commit()
        raise LLMCallFailed("分析执行失败") from exc

    analysis.status = "succeeded"
    analysis.finished_at = _now()
    analysis.stats = _stats(
        chapter_count=result.chapter_count,
        conclusions=conclusions,
        discarded=discarded,
    )
    session.flush()
    session.commit()
    return analysis


# ------------------------------------------------------------ 查询


def _format_revision(version_no: int | None) -> str | None:
    return None if version_no is None else f"v1.{version_no}"


def _analysis_item(session: Session, analysis: IncrementalAnalysis) -> dict:
    template = session.get(PromptTemplate, analysis.template_id)
    revision = session.get(BaselineRevision, analysis.baseline_revision_id)
    document = session.get(Document, analysis.document_id)
    version = session.get(DocumentVersion, analysis.document_version_id)
    return {
        "id": analysis.id,
        "project_id": analysis.project_id,
        "template_id": analysis.template_id,
        "template_name": template.name if template else None,
        "template_version": analysis.template_version,
        "provider": analysis.provider,
        "baseline_revision_id": analysis.baseline_revision_id,
        "baseline_revision_version": (
            _format_revision(revision.version_no) if revision else None
        ),
        "document_id": analysis.document_id,
        "document_name": document.name if document else None,
        "document_version_id": analysis.document_version_id,
        "document_version_no": version.version_no if version else None,
        "split_granularity": analysis.split_granularity,
        "status": analysis.status,
        "error_code": analysis.error_code,
        "error_message": analysis.error_message,
        "stats": analysis.stats,
        "started_at": analysis.started_at,
        "finished_at": analysis.finished_at,
        "second_pass_template_id": analysis.second_pass_template_id,
        "second_pass_status": analysis.second_pass_status,
        "second_pass_stats": analysis.second_pass_stats,
        "second_pass_error_code": analysis.second_pass_error_code,
        "second_pass_error_message": analysis.second_pass_error_message,
        "second_pass_started_at": analysis.second_pass_started_at,
        "second_pass_finished_at": analysis.second_pass_finished_at,
        "created_by": analysis.created_by,
        "created_at": analysis.created_at,
    }


def list_analyses(
    session: Session,
    project_id: int,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    query = select(IncrementalAnalysis).where(
        IncrementalAnalysis.project_id == project_id
    )
    if status is not None:
        query = query.where(IncrementalAnalysis.status == status)
    rows = session.scalars(
        query.order_by(IncrementalAnalysis.id.desc())
    ).all()
    items = [_analysis_item(session, row) for row in rows]
    return _page(items, page, page_size)


def _load_analysis(
    session: Session, *, project_id: int, analysis_id: int
) -> IncrementalAnalysis:
    analysis = session.scalar(
        select(IncrementalAnalysis).where(
            IncrementalAnalysis.id == analysis_id,
            IncrementalAnalysis.project_id == project_id,
        )
    )
    if analysis is None:
        raise IncrementalAnalysisNotFound("分析记录不存在")
    return analysis


def get_analysis(session: Session, *, project_id: int, analysis_id: int) -> dict:
    return _analysis_item(
        session, _load_analysis(session, project_id=project_id, analysis_id=analysis_id)
    )


def list_conclusions(
    session: Session,
    *,
    project_id: int,
    analysis_id: int,
    chapter_id: int | None = None,
    target_type: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    _load_analysis(session, project_id=project_id, analysis_id=analysis_id)

    query = select(IncrementalConclusion).where(
        IncrementalConclusion.analysis_id == analysis_id
    )
    if chapter_id is not None:
        query = query.where(IncrementalConclusion.chapter_id == chapter_id)
    if target_type is not None:
        query = query.where(IncrementalConclusion.target_type == target_type)
    rows = session.scalars(
        query.order_by(IncrementalConclusion.id)
    ).all()
    items = [
        {
            "id": row.id,
            "analysis_id": row.analysis_id,
            "chapter_id": row.chapter_id,
            "chapter_title": row.chapter_title,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "label_type": row.label_type,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "rationale": row.rationale,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    return _page(items, page, page_size)


# ------------------------------------------------------------ 第二遍


def _load_second_pass_template(session: Session) -> PromptTemplate:
    """第二遍模板：按名字前缀取 active 的最新一条。"""
    template = session.scalar(
        select(PromptTemplate)
        .where(
            PromptTemplate.name.like(f"{SECOND_PASS_TEMPLATE_PREFIX}%"),
            PromptTemplate.status == "active",
        )
        .order_by(PromptTemplate.version_no.desc(), PromptTemplate.id.desc())
    )
    if template is None:
        raise SecondPassTemplateMissing("第二遍提示词模板缺失或已停用")
    return template


def _pending_conflict_count(session: Session, analysis_id: int) -> int:
    return (
        session.execute(
            select(func.count())
            .select_from(IncrementalConflict)
            .where(
                IncrementalConflict.analysis_id == analysis_id,
                IncrementalConflict.status == "pending",
            )
        ).scalar_one()
        or 0
    )


def _second_pass_stats(
    *,
    template: PromptTemplate,
    link_count: int,
    result: second_pass.SecondPassResult,
    provider_name: str,
) -> dict:
    return {
        "template_id": template.id,
        "template_version": template.version_no,
        "provider": provider_name,
        "chapter_link_count": link_count,
        "point_count": result.point_count,
        "decision_count": len(result.decisions),
        "new_count": sum(
            1 for item in result.conflicts if item.conflict_type == "new"
        ),
        "conflict_count": sum(
            1 for item in result.conflicts if item.conflict_type == "conflict"
        ),
        "propagated_count": result.propagated_count,
        "failed_target_type": None,
        "failed_target_id": None,
    }


def _clear_second_pass_rows(session: Session, analysis_id: int) -> None:
    """重跑前先删本分析的旧裁决与冲突，结果不累加。"""
    session.execute(
        delete(IncrementalDecision).where(
            IncrementalDecision.analysis_id == analysis_id
        )
    )
    session.execute(
        delete(IncrementalConflict).where(
            IncrementalConflict.analysis_id == analysis_id
        )
    )
    session.flush()


def _ensure_rule_links(
    session: Session, *, analysis: IncrementalAnalysis, actor: User
) -> int:
    """该版本还没有规则边时自动抽一次；已有则不重抽（不覆盖人工调整过的图）。"""
    existing = session.execute(
        select(func.count())
        .select_from(DocumentChapterLink)
        .where(
            DocumentChapterLink.version_id == analysis.document_version_id,
            DocumentChapterLink.source == "rule",
        )
    ).scalar_one()
    if existing:
        return int(existing)

    links.extract_links(
        session,
        project_id=analysis.project_id,
        document_id=analysis.document_id,
        version_id=analysis.document_version_id,
        actor=actor,
    )
    return int(
        session.execute(
            select(func.count())
            .select_from(DocumentChapterLink)
            .where(
                DocumentChapterLink.version_id == analysis.document_version_id,
                DocumentChapterLink.source == "rule",
            )
        ).scalar_one()
    )


def _persist_second_pass(
    session: Session, analysis: IncrementalAnalysis, result: second_pass.SecondPassResult
) -> None:
    decisions = [
        IncrementalDecision(
            analysis_id=analysis.id,
            target_type=item.target_type,
            target_id=item.target_id,
            target_name=item.target_name,
            decision=item.decision,
            confidence=item.confidence,
            rationale=item.rationale,
            evidence=item.evidence,
        )
        for item in result.decisions
    ]
    conflicts = [
        IncrementalConflict(
            analysis_id=analysis.id,
            target_type=item.target_type,
            target_id=item.target_id,
            target_name=item.target_name,
            conflict_type=item.conflict_type,
            candidates=item.candidates,
        )
        for item in result.conflicts
    ]
    if decisions:
        session.add_all(decisions)
    if conflicts:
        session.add_all(conflicts)
    session.flush()


def run_second_pass(
    session: Session,
    *,
    project_id: int,
    analysis_id: int,
    actor: User,
    provider: LLMProvider,
) -> IncrementalAnalysis:
    """触发第二遍。固定校验顺序见 spec-phase2 §5.2。

    1. 项目 404 / 归档 409 / 角色 403；
    2. 分析记录存在且属本项目 404；
    3. 第一遍 `succeeded`，否则 409 `SECOND_PASS_NOT_READY`；
    4. 第二遍模板存在且 active，否则 409 `SECOND_PASS_TEMPLATE_MISSING`；
    5. 无待裁决冲突，否则 409 `SECOND_PASS_CONFLICTS_PENDING`；
    6. 跑 2b-1/2b-2/2b-3，回填统计与状态。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    analysis = _load_analysis(session, project_id=project_id, analysis_id=analysis_id)
    if analysis.status != "succeeded":
        raise SecondPassNotReady("第一遍分析尚未成功，不能执行第二遍")

    template = _load_second_pass_template(session)
    if _pending_conflict_count(session, analysis.id):
        raise SecondPassConflictsPending("仍有待人工裁决的冲突，请先完成裁决再重跑")

    analysis.second_pass_template_id = template.id
    analysis.second_pass_status = "running"
    analysis.second_pass_error_code = None
    analysis.second_pass_error_message = None
    analysis.second_pass_started_at = _now()
    analysis.second_pass_finished_at = None
    session.flush()

    link_count = 0
    try:
        link_count = _ensure_rule_links(session, analysis=analysis, actor=actor)
        _clear_second_pass_rows(session, analysis.id)

        index = second_pass.build_point_index(session, analysis)
        result = second_pass.run_point_pass(
            session,
            analysis=analysis,
            provider=provider,
            template=template,
            index=index,
        )
        second_pass.propagate_impacts(index, result)
        _persist_second_pass(session, analysis, result)
    except AppError as exc:
        analysis.second_pass_status = "failed"
        analysis.second_pass_error_code = exc.code[:64]
        analysis.second_pass_error_message = (exc.message or exc.code)[:500]
        analysis.second_pass_finished_at = _now()
        analysis.second_pass_stats = _second_pass_stats(
            template=template,
            link_count=link_count,
            result=second_pass.SecondPassResult(point_count=0, prompted_count=0),
            provider_name=provider.name,
        )
        target_type = exc.extra.get("target_type")
        target_id = exc.extra.get("target_id")
        if target_type is not None:
            analysis.second_pass_stats["failed_target_type"] = target_type
        if target_id is not None:
            analysis.second_pass_stats["failed_target_id"] = target_id
        session.commit()
        raise
    except Exception as exc:  # 内部异常同样立刻失败，不让前端干等
        analysis.second_pass_status = "failed"
        analysis.second_pass_error_code = LLMCallFailed.code
        analysis.second_pass_error_message = f"第二遍执行失败：{exc}"[:500]
        analysis.second_pass_finished_at = _now()
        session.commit()
        raise LLMCallFailed("第二遍执行失败") from exc

    analysis.second_pass_status = "succeeded"
    analysis.second_pass_finished_at = _now()
    analysis.second_pass_stats = _second_pass_stats(
        template=template,
        link_count=link_count,
        result=result,
        provider_name=provider.name,
    )
    session.flush()

    write_audit(
        session,
        "incremental.second_pass.run",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="incremental_analysis",
        target_id=analysis.id,
        after_data={
            "template_id": template.id,
            "template_version": template.version_no,
            "provider": provider.name,
            "point_count": result.point_count,
            "decision_count": len(result.decisions),
            "conflict_count": len(result.conflicts),
        },
    )
    session.commit()
    return analysis


def list_decisions(
    session: Session,
    *,
    project_id: int,
    analysis_id: int,
    target_type: str | None = None,
    decision: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """第二遍裁决列表（分页）。"""
    _load_analysis(session, project_id=project_id, analysis_id=analysis_id)

    query = select(IncrementalDecision).where(
        IncrementalDecision.analysis_id == analysis_id
    )
    if target_type is not None:
        query = query.where(IncrementalDecision.target_type == target_type)
    if decision is not None:
        query = query.where(IncrementalDecision.decision == decision)
    rows = session.scalars(query.order_by(IncrementalDecision.id)).all()
    items = [
        {
            "id": row.id,
            "analysis_id": row.analysis_id,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "target_name": row.target_name,
            "decision": row.decision,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "rationale": row.rationale,
            "evidence": row.evidence,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    return _page(items, page, page_size)


def list_conflicts(
    session: Session,
    *,
    project_id: int,
    analysis_id: int,
    status: str | None = None,
    conflict_type: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """第二遍待人工裁决队列（分页）。"""
    _load_analysis(session, project_id=project_id, analysis_id=analysis_id)

    query = select(IncrementalConflict).where(
        IncrementalConflict.analysis_id == analysis_id
    )
    if status is not None:
        query = query.where(IncrementalConflict.status == status)
    if conflict_type is not None:
        query = query.where(IncrementalConflict.conflict_type == conflict_type)
    rows = session.scalars(query.order_by(IncrementalConflict.id)).all()
    items = [
        {
            "id": row.id,
            "analysis_id": row.analysis_id,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "target_name": row.target_name,
            "conflict_type": row.conflict_type,
            "candidates": row.candidates,
            "status": row.status,
            "resolved_label_type": row.resolved_label_type,
            "resolved_by": row.resolved_by,
            "resolved_at": row.resolved_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    return _page(items, page, page_size)


# ------------------------------------------------------------ 人工裁决


def _validate_resolution(payload: ConflictResolve) -> tuple[str, str | None]:
    """`confirmed` 必带 `label_type`，`rejected` 不允许带；其余非法。"""
    decision = payload.decision
    if decision not in ("confirmed", "rejected"):
        raise InvalidConflictResolution("decision 只允许 confirmed 或 rejected")
    if decision == "confirmed":
        if payload.label_type is None:
            raise InvalidConflictResolution("确认裁决必须指定 label_type")
        if payload.label_type not in ("changed", "affected", "unchanged"):
            raise InvalidConflictResolution(
                "label_type 只允许 changed / affected / unchanged"
            )
        return decision, payload.label_type
    if payload.label_type is not None:
        raise InvalidConflictResolution("驳回时不允许带 label_type")
    return decision, None


def resolve_conflict(
    session: Session,
    *,
    project_id: int,
    analysis_id: int,
    conflict_id: int,
    actor: User,
    payload: ConflictResolve,
) -> IncrementalConflict:
    """人工裁决一条冲突。

    只改冲突行本身（`status` / `resolved_label_type` / `resolved_by` / `resolved_at`），
    **不写 `baseline_labels`**——产出段是下一期的事。
    """
    _ensure_writable_project(session, project_id)
    _ensure_admin(session, project_id=project_id, actor=actor)

    analysis = _load_analysis(session, project_id=project_id, analysis_id=analysis_id)
    conflict = session.scalar(
        select(IncrementalConflict).where(
            IncrementalConflict.id == conflict_id,
            IncrementalConflict.analysis_id == analysis.id,
        )
    )
    if conflict is None:
        raise ConflictNotFound("冲突记录不存在或不属于该分析")
    if conflict.status != "pending":
        raise ConflictAlreadyResolved("该冲突已完成裁决，不能重复处理")

    decision, label_type = _validate_resolution(payload)

    conflict.status = decision
    conflict.resolved_label_type = label_type
    conflict.resolved_by = actor.id
    conflict.resolved_at = _now()
    session.flush()

    write_audit(
        session,
        "incremental.conflict.resolve",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="incremental_conflict",
        target_id=conflict.id,
        after_data={
            "analysis_id": analysis.id,
            "conflict_type": conflict.conflict_type,
            "target_type": conflict.target_type,
            "target_id": conflict.target_id,
            "decision": decision,
            "label_type": label_type,
        },
    )
    session.commit()
    return conflict


__all__ = [
    "create_analysis",
    "ensure_readable",
    "get_analysis",
    "list_analyses",
    "list_conflicts",
    "list_conclusions",
    "list_decisions",
    "resolve_conflict",
    "run_second_pass",
]
