"""章节引用图路由（05-incremental 第二期 T71 / 12-chapter-link-ai / 12.5 期评审）。

前缀 `/api/projects/{project_id}/documents/{document_id}/versions/{version_id}/links`：

- `GET  ""`             引用图列表（不分页，可按 link_type / source 筛选）
- `POST ""`             手动补一条（项目管理员，落库即 `approved`）
- `POST /extract`       按规则重抽取（幂等，项目管理员）
- `POST /analyze`       AI 分析引用关系（项目管理员，产出的边落 `pending` 待评审）
- `POST /approve-batch` 批量采纳待评审的边（项目管理员，整批原子）
- `POST /{id}/approve`  采纳一条（项目管理员，幂等）
- `DELETE /{id}`        删一条引用边（项目管理员）

读权限随文档章节（成员含访客）；写权限单独校验，固定顺序是
项目不存在 404 → 已归档 409 → 不是管理员 403。
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import current_user
from app.incremental import links
from app.incremental.schemas import (
    ChapterLinkAnalyzeOut,
    ChapterLinkApproveBatchIn,
    ChapterLinkApproveBatchOut,
    ChapterLinkCreate,
    ChapterLinkOut,
)
from app.llm.provider import LLMProvider, get_provider
from app.models.user import User

router = APIRouter(
    prefix=(
        "/api/projects/{project_id}/documents/{document_id}"
        "/versions/{version_id}/links"
    ),
    tags=["incremental"],
)


@router.get("", response_model=list[ChapterLinkOut])
def list_links(
    project_id: int,
    document_id: int,
    version_id: int,
    link_type: str | None = Query(
        default=None, pattern="^(references|depends_on|mentions_entity)$"
    ),
    source: str | None = Query(default=None, pattern="^(rule|manual|ai)$"),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ChapterLinkOut]:
    """引用图列表。单版本量级小，不分页。"""
    links.ensure_member(session, project_id=project_id, actor=user)
    return [
        ChapterLinkOut(**item)
        for item in links.list_links(
            session,
            project_id=project_id,
            document_id=document_id,
            version_id=version_id,
            link_type=link_type,
            source=source,
        )
    ]


@router.post("", response_model=ChapterLinkOut, status_code=201)
def create_link(
    project_id: int,
    document_id: int,
    version_id: int,
    payload: ChapterLinkCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ChapterLinkOut:
    """人工补链。`to_chapter_id` 与 `entity` 二选一。"""
    link = links.create_link(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
        actor=user,
        from_chapter_id=payload.from_chapter_id,
        link_type=payload.link_type,
        to_chapter_id=payload.to_chapter_id,
        entity=payload.entity,
    )
    item = next(
        row
        for row in links.list_links(
            session,
            project_id=project_id,
            document_id=document_id,
            version_id=version_id,
        )
        if row["id"] == link.id
    )
    return ChapterLinkOut(**item)


@router.post("/extract", response_model=list[ChapterLinkOut])
def extract_links(
    project_id: int,
    document_id: int,
    version_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ChapterLinkOut]:
    """按规则重抽取。重复调用结果不累加，人工边不受影响。"""
    links.extract_links(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
        actor=user,
    )
    return [
        ChapterLinkOut(**item)
        for item in links.list_links(
            session,
            project_id=project_id,
            document_id=document_id,
            version_id=version_id,
        )
    ]


@router.post("/analyze", response_model=ChapterLinkAnalyzeOut)
def analyze_links(
    project_id: int,
    document_id: int,
    version_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
    provider: LLMProvider = Depends(get_provider),
) -> ChapterLinkAnalyzeOut:
    """AI 分析引用关系（项目管理员）。**同步**执行，响应带统计。

    调用真实大模型，产出的边落库为 `source='ai'`。
    **人工边与规则边不受影响**——这里只重算 `source='ai'` 的那批。
    """
    result = links.analyze_links(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
        actor=user,
        provider=provider,
    )
    return ChapterLinkAnalyzeOut(
        links=[ChapterLinkOut(**item) for item in result["links"]],
        analyzed_count=result["analyzed_count"],
        discarded_count=result["discarded_count"],
        chapter_count=result["chapter_count"],
        provider=result["provider"],
        mode=result["mode"],
    )


@router.post("/approve-batch", response_model=ChapterLinkApproveBatchOut)
def approve_links_batch(
    project_id: int,
    document_id: int,
    version_id: int,
    payload: ChapterLinkApproveBatchIn,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ChapterLinkApproveBatchOut:
    """批量采纳待评审的引用边（项目管理员）。

    **整批原子**：只要有一个 id 不存在或不属于该版本，整批失败（404），
    不部分成功。空数组 → 400 `INVALID_CHAPTER_LINK`。

    **路径顺序**：本路由的字面量段数（1 段）与 `/{link_id}/approve`（2 段）
    不同、与 `POST /extract`、`POST /analyze` 同段但字面量不同，实际不冲突。
    仍然把它放在 `/{link_id}/approve` **之前**——具体路径优先，避免以后
    有人加 `POST /{link_id}/xxx` 时踩坑。
    """
    approved_count = links.approve_links_batch(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
        actor=user,
        link_ids=payload.link_ids,
    )
    return ChapterLinkApproveBatchOut(approved_count=approved_count)


@router.post("/{link_id}/approve", response_model=ChapterLinkOut)
def approve_link(
    project_id: int,
    document_id: int,
    version_id: int,
    link_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ChapterLinkOut:
    """采纳一条待评审的引用边（项目管理员）。**幂等**：已生效的再采纳返回 200。"""
    link = links.approve_link(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
        actor=user,
        link_id=link_id,
    )
    item = next(
        row
        for row in links.list_links(
            session,
            project_id=project_id,
            document_id=document_id,
            version_id=version_id,
        )
        if row["id"] == link.id
    )
    return ChapterLinkOut(**item)


@router.delete("/{link_id}", status_code=204)
def delete_link(
    project_id: int,
    document_id: int,
    version_id: int,
    link_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """删一条引用边（项目管理员）。三种来源的边都可删。

    删 `source='rule'` 的边后，再次「按规则重抽」会重新生成它——
    前端在确认框里要提示这一点。
    """
    links.delete_link(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
        actor=user,
        link_id=link_id,
    )
    return Response(status_code=204)


__all__ = ["router"]