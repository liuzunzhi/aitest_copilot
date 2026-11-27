"""章节引用图：规则抽取与手动补链（05-incremental 第二期 T71）。

抽取规则（spec-phase2 §6.4）：

- 显式引用「见第 2 章」「详见 2.1」「参见 3.2 节」→ `references`；
- 依赖 / 前置「依赖第 2 章」「前置条件见 2.1」→ `depends_on`；
- 正文包含基线功能点名称（去空白后长度 ≥ 2）→ `mentions_entity`。

序号解析顺序：

1. 章节标题自带编号（「第2章 登录」「2.1 登录流程」「3、概述」）时建编号路径索引，
   按完整路径精确匹配，匹配不到再按前缀匹配（「第 2 章」→ `(2,1)`）；
2. 全部标题都没有编号时，退化为「第 N 章 = 第 N 个一级章节」（跳过「前言」「全文」）。

解析不到、指向自身、跨版本的引用一律丢弃，不报错——引用抽取是尽力而为，
脏数据不该阻断整个版本。

幂等：规则边按 `(version_id, source='rule')` 先删后插，人工边不动。
"""

import re
import time
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.config import get_settings
from app.common.deps import SYSTEM_ADMIN
from app.common.errors import (
    ChapterLinkNotFound,
    DocumentNotFound,
    DocumentVersionNotFound,
    DuplicateChapterLink,
    InvalidChapterLink,
    LLMCallFailed,
    LLMOutputInvalid,
    NotProjectAdmin,
    NotProjectMember,
    ProjectArchived,
    ProjectNotFound,
    TemplateDisabled,
    TemplateNotFound,
)
from app.documents import service as documents_service
from app.incremental import link_analyze as link_analyze_engine
from app.llm import run_log
from app.llm.provider import LLMProvider
from app.models.baseline import BaselineFeaturePoint, BaselineFunction, BaselineModule
from app.models.chapter_link import CHAPTER_LINK_TYPES, DocumentChapterLink
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import PromptTemplate
from app.models.project import Project, ProjectMember
from app.models.user import User

# AI 分析用的提示词模板类型（独立成一个类型，理由见 spec §2.3）
LINK_ANALYZE_TASK_TYPE = "chapter_link_analyze"
# AI 分析写运行留痕的 task_type（与 `llm_run_logs.task_type` 的枚举一致）
LINK_ANALYZE_RUN_LOG_TASK_TYPE = "chapter_link_analyze"

# 规则抽取的固定置信度（spec §6.4）
RULE_CONFIDENCE = {
    "references": Decimal("0.80"),
    "depends_on": Decimal("0.80"),
    "mentions_entity": Decimal("0.60"),
}

_UNNUMBERED_TITLES = frozenset({"前言", "全文"})

# 标题开头编号：「2 登录」「2.1 登录流程」「第2章 登录」「3、概述」
_TITLE_NUMBER_RE = re.compile(r"^\s*第?\s*(\d+(?:\.\d+)*)\s*(?:[章节)）、.]|\s|$)")

# 依赖优先于引用：「前置条件见 2.1」「依赖第 2 章」
_DEPEND_RE = re.compile(
    r"(?:依赖|前置条件|前置|基于)\s*(?:参见|详见|见)?\s*第?\s*(\d+(?:\.\d+)*)\s*(?:章节|章|节)?"
)
_REFERENCE_RE = re.compile(
    r"(?:参见|详见|见|参考)\s*第?\s*(\d+(?:\.\d+)*)\s*(?:章节|章|节)?"
)


@dataclass(frozen=True)
class _Candidate:
    """一条待落库的规则边。`key` 用于同源同类型去重。"""

    from_chapter_id: int
    link_type: str
    to_chapter_id: int | None = None
    entity: str | None = None


# ---------------------------------------------------------------- 权限


def _ensure_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFound("项目不存在")
    return project


def ensure_member(session: Session, *, project_id: int, actor: User) -> None:
    """读接口：项目存在 + 是成员（含访客）。"""
    _ensure_project(session, project_id)
    if actor.global_role == SYSTEM_ADMIN:
        return
    if session.get(ProjectMember, (project_id, actor.id)) is None:
        raise NotProjectMember("不是该项目成员")


def ensure_writable_admin(session: Session, *, project_id: int, actor: User) -> Project:
    """写接口：不存在 404 → 已归档 409 → 不是管理员 403。"""
    project = _ensure_project(session, project_id)
    if project.status != "active":
        raise ProjectArchived("项目已归档，不可维护章节引用图")
    if actor.global_role == SYSTEM_ADMIN:
        return project
    member = session.get(ProjectMember, (project_id, actor.id))
    if member is None or member.role != "project_admin":
        raise NotProjectAdmin("只有项目管理员可以维护章节引用图")
    return project


# ------------------------------------------------------------ 资源校验


def _load_version(
    session: Session, *, project_id: int, document_id: int, version_id: int
) -> tuple[Document, DocumentVersion]:
    document = session.scalar(
        select(Document).where(
            Document.id == document_id, Document.project_id == project_id
        )
    )
    if document is None:
        raise DocumentNotFound("文档不存在或不属于该项目")
    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id, DocumentVersion.document_id == document_id
        )
    )
    if version is None:
        raise DocumentVersionNotFound("文档版本不存在或不属于该文档")
    return document, version


def _chapters(session: Session, version_id: int) -> list[DocumentChapter]:
    return list(
        session.scalars(
            select(DocumentChapter)
            .where(DocumentChapter.version_id == version_id)
            .order_by(DocumentChapter.seq)
        ).all()
    )


# ------------------------------------------------------------ 规则抽取


def _title_path(title: str) -> tuple[int, ...] | None:
    match = _TITLE_NUMBER_RE.match(title or "")
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _resolve_number(
    number: tuple[int, ...],
    *,
    by_path: dict[tuple[int, ...], DocumentChapter],
    top_level: list[DocumentChapter],
    numbered: bool,
) -> DocumentChapter | None:
    """把引用里的序号解析成章节；解析不到返回 None（丢弃这条引用）。"""
    if not numbered:
        # 标题没有任何编号：按「第 N 章 = 第 N 个一级章节」退化匹配
        if len(number) == 1 and 1 <= number[0] <= len(top_level):
            return top_level[number[0] - 1]
        return None

    chapter = by_path.get(number)
    if chapter is not None:
        return chapter
    # 前缀匹配：「第 2 章」指向 2.x 里最早出现的一节
    matched = [
        item for path, item in by_path.items() if path[: len(number)] == number
    ]
    if not matched:
        return None
    return min(matched, key=lambda item: item.seq)


def _feature_point_names(session: Session, project_id: int) -> list[str]:
    """当前结构里有效的功能点名称（归档模块及其下不算，与基线索引口径一致）。"""
    rows = session.execute(
        select(BaselineFeaturePoint.name)
        .join(BaselineFunction, BaselineFunction.id == BaselineFeaturePoint.function_id)
        .join(BaselineModule, BaselineModule.id == BaselineFunction.module_id)
        .where(
            BaselineFeaturePoint.project_id == project_id,
            BaselineFeaturePoint.status == "active",
            BaselineFunction.status == "active",
            BaselineModule.status == "active",
            BaselineModule.project_id == project_id,
        )
    ).all()
    names: list[str] = []
    for (name,) in rows:
        cleaned = "".join((name or "").split())
        if len(cleaned) >= 2:
            names.append(cleaned)
    return names


def _collect(
    chapters: list[DocumentChapter], point_names: list[str]
) -> dict[tuple, _Candidate]:
    """扫描章节正文，产出「同源同类型同目标只留一条」的候选集合。"""
    by_path: dict[tuple[int, ...], DocumentChapter] = {}
    for chapter in chapters:
        path = _title_path(chapter.title)
        if path is not None and path not in by_path:
            by_path[path] = chapter
    numbered = bool(by_path)
    min_level = min((chapter.level for chapter in chapters), default=1)
    top_level = [
        chapter
        for chapter in chapters
        if chapter.level == min_level and chapter.title not in _UNNUMBERED_TITLES
    ]

    found: dict[tuple, _Candidate] = {}

    def _add(from_chapter: DocumentChapter, link_type: str, target: DocumentChapter) -> None:
        if target.id == from_chapter.id:
            return
        key = (from_chapter.id, link_type, target.id)
        found.setdefault(
            key, _Candidate(from_chapter.id, link_type, to_chapter_id=target.id)
        )

    for chapter in chapters:
        content = chapter.content or ""

        depend_spans: list[tuple[int, int]] = []
        for match in _DEPEND_RE.finditer(content):
            depend_spans.append(match.span())
            target = _resolve_number(
                tuple(int(part) for part in match.group(1).split(".")),
                by_path=by_path,
                top_level=top_level,
                numbered=numbered,
            )
            if target is not None:
                _add(chapter, "depends_on", target)

        for match in _REFERENCE_RE.finditer(content):
            if any(start <= match.start() < end for start, end in depend_spans):
                continue
            target = _resolve_number(
                tuple(int(part) for part in match.group(1).split(".")),
                by_path=by_path,
                top_level=top_level,
                numbered=numbered,
            )
            if target is not None:
                _add(chapter, "references", target)

        compact = "".join(content.split())
        for name in point_names:
            if name in compact:
                key = (chapter.id, "mentions_entity", name)
                found.setdefault(
                    key,
                    _Candidate(chapter.id, "mentions_entity", entity=name),
                )

    return found


def extract_links(
    session: Session,
    *,
    project_id: int,
    document_id: int,
    version_id: int,
    actor: User,
) -> list[DocumentChapterLink]:
    """按规则重抽该版本的引用图（幂等）。"""
    ensure_writable_admin(session, project_id=project_id, actor=actor)
    _load_version(session, project_id=project_id, document_id=document_id, version_id=version_id)

    chapters = _chapters(session, version_id)
    point_names = _feature_point_names(session, project_id)
    candidates = _collect(chapters, point_names)

    session.execute(
        delete(DocumentChapterLink).where(
            DocumentChapterLink.version_id == version_id,
            DocumentChapterLink.source == "rule",
        )
    )
    # 人工边优先：规则重抽命中同一条（同源同类型同目标）时跳过，避免撞唯一键
    manual_keys = {
        (row.from_chapter_id, row.link_type, row.to_chapter_id, row.entity)
        for row in session.scalars(
            select(DocumentChapterLink).where(
                DocumentChapterLink.version_id == version_id,
                DocumentChapterLink.source == "manual",
            )
        ).all()
    }
    rows = [
        DocumentChapterLink(
            version_id=version_id,
            from_chapter_id=item.from_chapter_id,
            to_chapter_id=item.to_chapter_id,
            link_type=item.link_type,
            entity=item.entity,
            confidence=RULE_CONFIDENCE[item.link_type],
            source="rule",
            created_by=actor.id,
        )
        for item in sorted(candidates.values(), key=lambda c: (c.from_chapter_id, c.link_type))
        if (item.from_chapter_id, item.link_type, item.to_chapter_id, item.entity)
        not in manual_keys
    ]
    if rows:
        session.add_all(rows)
        session.flush()
    session.commit()
    return rows


# ------------------------------------------------------------ AI 分析


def _load_link_analyze_template(session: Session) -> PromptTemplate:
    """取 AI 分析的模板（`task_type='chapter_link_analyze'` + `status='active'`）。

    **按类型取，不按 id 取**——用户点「AI 一键分析」时前端不选模板，
    平台用唯一的那条种子模板。管理员可以在「系统设置 → 提示词模板」里
    改它的正文（改文案不用发版），但**不能改它的 `task_type`**
    （改了就匹配不上）。

    模板缺失 → `TemplateNotFound`（404）；模板存在但被停用 →
    `TemplateDisabled`（409）。**都不静默降级**——降级会让「模板可编辑」
    这个设计失效，也让用户以为 AI 跑了、其实什么都没跑。
    """
    template = session.scalar(
        select(PromptTemplate)
        .where(
            PromptTemplate.task_type == LINK_ANALYZE_TASK_TYPE,
            PromptTemplate.status == "active",
        )
        .order_by(PromptTemplate.version_no.desc(), PromptTemplate.id.desc())
    )
    if template is not None:
        return template

    exists = session.scalar(
        select(func.count())
        .select_from(PromptTemplate)
        .where(PromptTemplate.task_type == LINK_ANALYZE_TASK_TYPE)
    )
    if exists:
        raise TemplateDisabled(
            "AI 分析引用关系的提示词模板已停用，请先在系统设置里启用"
        )
    raise TemplateNotFound(
        "AI 分析引用关系的提示词模板缺失，请先在系统设置里创建并启用"
    )


def analyze_links(
    session: Session,
    *,
    project_id: int,
    document_id: int,
    version_id: int,
    actor: User,
    provider: LLMProvider,
) -> dict:
    """AI 分析该版本的章节引用关系（同步跑完）。

    编排顺序（与 10 期的 `run_derive` 同构）：

    1. 权限：项目 404 → 归档 409 → 角色 403；
    2. 文档 / 版本校验；
    3. 取模板（`task_type='chapter_link_analyze'` + active）；
    4. 取章节（复用 `documents_service.list_chapters`）；
    5. 调引擎（`link_analyze.analyze`，纯函数）；
    6. **落库**：删 `source='ai'` 旧行 → 插新行；
    7. 写审计 + 写运行留痕。

    **三种来源互不覆盖**：这里只重算 `source='ai'` 的边，
    人工边（`manual`）与规则边（`rule`）一个字节都不动。

    **「没有引用关系」不是错误**：模型返回 `{"references": []}`
    → 写 0 行，`analyzed_count=0`，不抛异常。
    """
    ensure_writable_admin(session, project_id=project_id, actor=actor)
    document, version = _load_version(
        session, project_id=project_id, document_id=document_id, version_id=version_id
    )

    template = _load_link_analyze_template(session)
    limit = get_settings().incremental_max_input_chars

    chapters = documents_service.list_chapters(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
    )

    started_at = time.monotonic()
    calls_before = run_log.call_count(provider)
    status = "succeeded"
    error_code: str | None = None
    error_message: str | None = None
    try:
        result = link_analyze_engine.analyze(
            provider=provider,
            template=template,
            document_name=document.name,
            version_no=version.version_no,
            chapters=chapters,
            max_chars=limit,
        )
    except (LLMCallFailed, LLMOutputInvalid) as exc:
        status = "failed"
        error_code = exc.code
        error_message = exc.message
        _record_link_analyze_run(
            session,
            provider=provider,
            template=template,
            project_id=project_id,
            calls_before=calls_before,
            started_at=started_at,
            status=status,
            error_code=error_code,
            error_message=error_message,
        )
        session.commit()
        raise

    rows = _persist_ai_links(
        session,
        version_id=version_id,
        actor=actor,
        references=result.references,
    )

    _record_link_analyze_run(
        session,
        provider=provider,
        template=template,
        project_id=project_id,
        calls_before=calls_before,
        started_at=started_at,
        status=status,
        error_code=error_code,
        error_message=error_message,
    )

    write_audit(
        session,
        "document.chapter_link.analyze",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="document_chapter_link",
        target_id=None,
        after_data={
            "document_id": document_id,
            "version_id": version_id,
            "template_id": template.id,
            "provider": getattr(provider, "name", "mock"),
            "mode": result.mode,
            "chapter_count": result.chapter_count,
            "analyzed_count": result.analyzed_count,
            "discarded_count": result.discarded_count,
        },
    )
    session.commit()

    return {
        "links": list_links(
            session,
            project_id=project_id,
            document_id=document_id,
            version_id=version_id,
        ),
        "analyzed_count": result.analyzed_count,
        "discarded_count": result.discarded_count,
        "chapter_count": result.chapter_count,
        "provider": getattr(provider, "name", "mock"),
        "mode": result.mode,
        "inserted_count": len(rows),
    }


def _persist_ai_links(
    session: Session,
    *,
    version_id: int,
    actor: User,
    references: list[dict],
) -> list[DocumentChapterLink]:
    """把引擎产出的引用边落库为**待评审**（`status='pending'`）。

    12.5 期的口径变化（与 12 期的直接落库相比，有三处）：

    1. **只删「上一轮还没审的」**：删 `(version_id, source='ai', status='pending')`。
       **已 `approved` 的 AI 边原样保留**——用户逐条采纳过的成果，
       不能因为重新分析一次就被冲掉。
    2. **落库即待评审**：新插入的边 `status='pending'`，
       并在 `rationale` 里记下模型给的分析理由（详情弹窗要展示）。
       采纳前不参与 05 期第二遍的图传播（见 `second_pass.build_point_index`）。
    3. **跳过「已存在的同一条边」**：唯一键
       `uk_chlinks_to_chapter` 是 `(version_id, from, link_type, to)`，
       **不含 `source` 也不含 `status`**。所以新分析出的边只要命中任何已存在的边
       （不论来源、不论状态）就必须跳过，否则撞唯一键 500。

    跳过是最保守也最符合直觉的做法：已采纳的边保持 `approved`，
    新一轮的结果由「尚未被采纳的那批」承载（与 12 期「人工边优先」同一哲学）。
    """
    # ① 只清上一轮**没被采纳**的 AI 边；已 approved 的保留
    session.execute(
        delete(DocumentChapterLink).where(
            DocumentChapterLink.version_id == version_id,
            DocumentChapterLink.source == "ai",
            DocumentChapterLink.status == "pending",
        )
    )

    # ② 收集「已存在的章节边」（不论来源 / 状态）——它们占着唯一键
    existing_keys = {
        (row.from_chapter_id, row.link_type, row.to_chapter_id)
        for row in session.scalars(
            select(DocumentChapterLink).where(
                DocumentChapterLink.version_id == version_id,
                DocumentChapterLink.to_chapter_id.is_not(None),
            )
        ).all()
    }

    rows = [
        DocumentChapterLink(
            version_id=version_id,
            from_chapter_id=item["from_chapter_id"],
            to_chapter_id=item["to_chapter_id"],
            link_type=item["link_type"],
            entity=None,
            confidence=item.get("confidence"),
            rationale=item.get("rationale"),
            source="ai",
            status="pending",
            created_by=actor.id,
        )
        for item in references
        if (item["from_chapter_id"], item["link_type"], item["to_chapter_id"])
        not in existing_keys
    ]
    if rows:
        session.add_all(rows)
        session.flush()
    return rows


def _record_link_analyze_run(
    session: Session,
    *,
    provider: LLMProvider,
    template: PromptTemplate,
    project_id: int,
    calls_before: int,
    started_at: float,
    status: str,
    error_code: str | None,
    error_message: str | None,
) -> None:
    """写模型运行留痕（**只 add + flush**，事务边界归调用方）。

    `calls_before` 是跑之前的累计调用数——`provider.calls` 是**累计**的，
    直接取 `len(calls)` 会把历史调用也算进来。
    """
    run_log.record_run(
        session,
        task_type=LINK_ANALYZE_RUN_LOG_TASK_TYPE,
        provider=provider,
        calls=max(0, run_log.call_count(provider) - calls_before),
        started_at=started_at,
        status=status,
        error_code=error_code,
        error_message=error_message,
        project_id=project_id,
        template_id=template.id,
        template_version=template.version_no,
    )


# ------------------------------------------------------------ 删除引用边


def delete_link(
    session: Session,
    *,
    project_id: int,
    document_id: int,
    version_id: int,
    actor: User,
    link_id: int,
) -> None:
    """删一条引用边（项目管理员）。

    **三种来源都可删**：`ai` / `manual` / `rule` 统一口径——
    用户诉求是「可以修改或删除错误结果」，规则边也是「结果」，
    限制它会让抽屉顶部的提示语变成半真。

    `source='rule'` 的边删掉后，**下次「按规则重抽」会重新生成它**
    （重抽是「按 `source='rule'` 先删后插」）。前端在删除确认框里
    要把这一点告诉用户。

    **必须校验归属**：`id == link_id AND version_id == version_id`——
    不校验就能跨版本删边。边不存在 / 不属于该版本 → 404
    `CHAPTER_LINK_NOT_FOUND`。
    """
    ensure_writable_admin(session, project_id=project_id, actor=actor)
    _load_version(
        session, project_id=project_id, document_id=document_id, version_id=version_id
    )

    link = session.scalar(
        select(DocumentChapterLink).where(
            DocumentChapterLink.id == link_id,
            DocumentChapterLink.version_id == version_id,
        )
    )
    if link is None:
        raise ChapterLinkNotFound("引用关系不存在或不属于该文档版本")

    before_data = {
        "document_id": document_id,
        "version_id": version_id,
        "from_chapter_id": link.from_chapter_id,
        "to_chapter_id": link.to_chapter_id,
        "link_type": link.link_type,
        "entity": link.entity,
        "source": link.source,
    }
    session.delete(link)
    session.flush()

    write_audit(
        session,
        "document.chapter_link.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="document_chapter_link",
        target_id=link.id,
        before_data=before_data,
    )
    session.commit()


# ------------------------------------------------------------ 采纳（人工评审）


def _load_version_link(
    session: Session, *, version_id: int, link_id: int
) -> DocumentChapterLink:
    """取一条属于该版本的边；不存在 / 跨版本 → 404。

    **必须校验归属**：`id == link_id AND version_id == version_id`——
    不校验就能跨版本采纳别人的边。
    """
    link = session.scalar(
        select(DocumentChapterLink).where(
            DocumentChapterLink.id == link_id,
            DocumentChapterLink.version_id == version_id,
        )
    )
    if link is None:
        raise ChapterLinkNotFound("引用关系不存在或不属于该文档版本")
    return link


def approve_link(
    session: Session,
    *,
    project_id: int,
    document_id: int,
    version_id: int,
    actor: User,
    link_id: int,
) -> DocumentChapterLink:
    """采纳一条待评审的引用边（项目管理员）。

    **幂等**：已经 `approved` 的边再采纳一次直接返回，**不报错、不写审计**。

    为什么幂等而不是像 07 期测试点那样「已评审过就 409」：
    07 期的评审是**有决策语义**的动作（通过 / 驳回），驳回后状态变了，
    重复「通过」确实自相矛盾。本期**没有驳回态**（用户原话「错的直接删除」），
    唯一的状态迁移是 `pending → approved`，重复采纳就是「再确认一次」，
    语义上完全成立，也让前端「批量采纳」可以放心重复点。

    为什么状态没变就不写审计：审计记录的是**业务变更**。
    没变更却记一条「采纳」，会让审计流里出现无法解释的重复记录。
    """
    ensure_writable_admin(session, project_id=project_id, actor=actor)
    _load_version(
        session, project_id=project_id, document_id=document_id, version_id=version_id
    )

    link = _load_version_link(session, version_id=version_id, link_id=link_id)

    if link.status != "approved":
        before_status = link.status
        link.status = "approved"
        session.flush()
        write_audit(
            session,
            "document.chapter_link.approve",
            actor_id=actor.id,
            actor_role=actor.global_role,
            project_id=project_id,
            target_type="document_chapter_link",
            target_id=link.id,
            before_data={"status": before_status},
            after_data={
                "document_id": document_id,
                "version_id": version_id,
                "status": "approved",
                "link_ids": [link.id],
                "approved_count": 1,
            },
        )
    session.commit()
    return link


def approve_links_batch(
    session: Session,
    *,
    project_id: int,
    document_id: int,
    version_id: int,
    actor: User,
    link_ids: list[int],
) -> int:
    """批量采纳（项目管理员）。返回本次被确认为已生效的条数。

    **整批原子**：只要有一个 id 不存在或不属于该版本，**整批失败**（404），
    不部分成功。部分成功会让用户不知道哪些进了、哪些没进。

    **空列表直接 400**：复用既有 `INVALID_CHAPTER_LINK`（本期零新增错误码）。

    **幂等**：已 `approved` 的边按成功计（计入返回值），但**不写**「变更」审计；
    只有确实发生状态迁移时才写一条审计。
    """
    ensure_writable_admin(session, project_id=project_id, actor=actor)
    _load_version(
        session, project_id=project_id, document_id=document_id, version_id=version_id
    )

    if not link_ids:
        raise InvalidChapterLink("请选择要采纳的引用关系")

    rows = list(
        session.scalars(
            select(DocumentChapterLink).where(
                DocumentChapterLink.id.in_(link_ids),
                DocumentChapterLink.version_id == version_id,
            )
        ).all()
    )
    found = {row.id for row in rows}
    missing = [item for item in link_ids if item not in found]
    if missing:
        raise ChapterLinkNotFound(
            f"引用关系不存在或不属于该文档版本：{sorted(missing)}"
        )

    changed = [row for row in rows if row.status != "approved"]
    for row in changed:
        row.status = "approved"
    if changed:
        session.flush()
        write_audit(
            session,
            "document.chapter_link.approve",
            actor_id=actor.id,
            actor_role=actor.global_role,
            project_id=project_id,
            target_type="document_chapter_link",
            target_id=None,
            after_data={
                "document_id": document_id,
                "version_id": version_id,
                "status": "approved",
                "link_ids": sorted(found),
                "approved_count": len(rows),
            },
        )
    session.commit()
    return len(rows)


# ------------------------------------------------------------ 手动补链


def _normalize_entity(entity: str | None) -> str | None:
    if entity is None:
        return None
    cleaned = entity.strip()
    return cleaned or None


def create_link(
    session: Session,
    *,
    project_id: int,
    document_id: int,
    version_id: int,
    actor: User,
    from_chapter_id: int,
    link_type: str,
    to_chapter_id: int | None,
    entity: str | None,
) -> DocumentChapterLink:
    """人工补一条边。目标二选一，重复 409，非法 400。"""
    ensure_writable_admin(session, project_id=project_id, actor=actor)
    _load_version(session, project_id=project_id, document_id=document_id, version_id=version_id)

    if link_type not in CHAPTER_LINK_TYPES:
        raise InvalidChapterLink("link_type 只支持 references / depends_on / mentions_entity")
    if (to_chapter_id is None) == (entity is None):
        raise InvalidChapterLink("to_chapter_id 与 entity 必须二选一")

    chapter_ids = {chapter.id for chapter in _chapters(session, version_id)}
    if from_chapter_id not in chapter_ids:
        raise InvalidChapterLink("源章节不存在或不属于该文档版本")

    if to_chapter_id is not None:
        if to_chapter_id not in chapter_ids:
            raise InvalidChapterLink("目标章节不存在或不属于该文档版本")
        if to_chapter_id == from_chapter_id:
            raise InvalidChapterLink("章节不能引用自己")
        entity_value = None
    else:
        entity_value = _normalize_entity(entity)
        if entity_value is None:
            raise InvalidChapterLink("entity 不能为空")

    existing = session.scalar(
        select(DocumentChapterLink).where(
            DocumentChapterLink.version_id == version_id,
            DocumentChapterLink.from_chapter_id == from_chapter_id,
            DocumentChapterLink.link_type == link_type,
            (
                DocumentChapterLink.to_chapter_id == to_chapter_id
                if to_chapter_id is not None
                else DocumentChapterLink.entity == entity_value
            ),
        )
    )
    if existing is not None:
        raise DuplicateChapterLink("相同源章节、类型与目标的引用已存在")

    link = DocumentChapterLink(
        version_id=version_id,
        from_chapter_id=from_chapter_id,
        to_chapter_id=to_chapter_id,
        link_type=link_type,
        entity=entity_value,
        confidence=None,
        source="manual",
        # 人工补的边**天然已生效**：人自己写的，不需要再走一遍评审。
        status="approved",
        created_by=actor.id,
    )
    session.add(link)
    session.flush()

    write_audit(
        session,
        "document.chapter_link.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="document_chapter_link",
        target_id=link.id,
        after_data={
            "document_id": document_id,
            "version_id": version_id,
            "from_chapter_id": from_chapter_id,
            "link_type": link_type,
            "to_chapter_id": to_chapter_id,
            "entity": entity_value,
        },
    )
    session.commit()
    return link


# ---------------------------------------------------------------- 查询


def list_links(
    session: Session,
    *,
    project_id: int,
    document_id: int,
    version_id: int,
    link_type: str | None = None,
    source: str | None = None,
) -> list[dict]:
    """引用图列表（不分页）。章节标题在服务层补齐，前端不用二次查询。"""
    _load_version(session, project_id=project_id, document_id=document_id, version_id=version_id)

    query = select(DocumentChapterLink).where(
        DocumentChapterLink.version_id == version_id
    )
    if link_type is not None:
        query = query.where(DocumentChapterLink.link_type == link_type)
    if source is not None:
        query = query.where(DocumentChapterLink.source == source)
    rows = session.scalars(query.order_by(DocumentChapterLink.id)).all()

    titles = {
        chapter.id: chapter.title for chapter in _chapters(session, version_id)
    }
    return [
        {
            "id": row.id,
            "version_id": row.version_id,
            "from_chapter_id": row.from_chapter_id,
            "from_chapter_title": titles.get(row.from_chapter_id),
            "to_chapter_id": row.to_chapter_id,
            "to_chapter_title": (
                titles.get(row.to_chapter_id) if row.to_chapter_id is not None else None
            ),
            "link_type": row.link_type,
            "entity": row.entity,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "source": row.source,
            # 12.5 期：待评审 / 已生效；AI 边的分析理由（详情弹窗展示）
            "status": row.status,
            "rationale": row.rationale,
            "created_by": row.created_by,
            "created_at": row.created_at,
        }
        for row in rows
    ]


__all__ = [
    "RULE_CONFIDENCE",
    "analyze_links",
    "approve_link",
    "approve_links_batch",
    "create_link",
    "delete_link",
    "ensure_member",
    "ensure_writable_admin",
    "extract_links",
    "list_links",
]
