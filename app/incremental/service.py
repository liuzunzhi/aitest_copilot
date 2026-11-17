"""分析记录生命周期。

固定校验顺序（spec §5）：项目 → 归档 → 角色 → 模板 → 快照 → 文档版本。
第 4–6 步失败不建行，因此不会留下「脏记录」。

第一遍同步执行：

    insert(status='running') → 跑第一遍 → 回填 stats/status/finished_at

失败处理：引擎抛出的异常在这里统一落成 `status='failed'` + `error_code` +
`error_message` + `finished_at`，**立刻返回/抛出**，不进入下一章、不做重试。
此前章节的结论通过 `on_chapter` 回调已逐章落库，保留在事务里便于排查。

审计：`incremental.analysis.create`，遵循「改数据 → flush → write_audit → commit」，
`write_audit` 内部不 commit。
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.deps import SYSTEM_ADMIN
from app.common.errors import (
    AppError,
    BaselineRevisionRequired,
    DocumentVersionNotAnalyzable,
    IncrementalAnalysisNotFound,
    InvalidSplitGranularity,
    LLMCallFailed,
    NoActiveDocumentVersion,
    NotProjectAdmin,
    NotProjectMember,
    ProjectArchived,
    ProjectNotFound,
    TemplateDisabled,
    TemplateNotFound,
)
from app.incremental import engine
from app.incremental.engine import ChapterResult, PassResult
from app.incremental.schemas import AnalysisCreate
from app.llm.provider import LLMProvider
from app.models.baseline import BaselineRevision
from app.models.document import Document, DocumentVersion
from app.models.incremental import (
    SPLIT_GRANULARITIES,
    IncrementalAnalysis,
    IncrementalConclusion,
    PromptTemplate,
)
from app.models.project import Project, ProjectMember
from app.models.user import User

DEFAULT_GRANULARITY = "chapter"


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


__all__ = [
    "create_analysis",
    "ensure_readable",
    "get_analysis",
    "list_analyses",
    "list_conclusions",
]
