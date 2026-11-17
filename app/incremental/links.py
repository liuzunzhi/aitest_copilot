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
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common.audit import write_audit
from app.common.deps import SYSTEM_ADMIN
from app.common.errors import (
    DocumentNotFound,
    DocumentVersionNotFound,
    DuplicateChapterLink,
    InvalidChapterLink,
    NotProjectAdmin,
    NotProjectMember,
    ProjectArchived,
    ProjectNotFound,
)
from app.models.baseline import BaselineFeaturePoint, BaselineFunction, BaselineModule
from app.models.chapter_link import CHAPTER_LINK_TYPES, DocumentChapterLink
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.project import Project, ProjectMember
from app.models.user import User

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
    ]
    if rows:
        session.add_all(rows)
        session.flush()
    session.commit()
    return rows


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
            "created_by": row.created_by,
            "created_at": row.created_at,
        }
        for row in rows
    ]


__all__ = [
    "RULE_CONFIDENCE",
    "create_link",
    "ensure_member",
    "ensure_writable_admin",
    "extract_links",
    "list_links",
]
