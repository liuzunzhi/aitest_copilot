"""章节引用图路由（05-incremental 第二期 T71）。

前缀 `/api/projects/{project_id}/documents/{document_id}/versions/{version_id}/links`：

- `GET  ""`        引用图列表（不分页，可按 link_type / source 筛选）
- `POST ""`        手动补一条（项目管理员）
- `POST /extract`  按规则重抽取（幂等，项目管理员）
- `POST /analyze`  AI 分析引用关系（项目管理员，调用真实大模型）

读权限随文档章节（成员含访客）；写权限单独校验，固定顺序是
项目不存在 404 → 已归档 409 → 不是管理员 403。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import current_user
from app.incremental import links
from app.incremental.schemas import (
    ChapterLinkAnalyzeOut,
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
    source: str | None = Query(default=None, pattern="^(rule|manual)$"),
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


__all__ = ["router"]