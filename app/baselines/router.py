"""功能基线的路由（T56–T62）。

权限判定在服务层（`_ensure_admin` / `_ensure_member`），
路由只取当前用户——这样「归档先判、角色后判」的顺序只有一个出处。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.baselines import service
from app.baselines.schemas import (
    AdoptOut,
    AdoptRequest,
    DeleteResponse,
    DeriveDetailOut,
    DeriveOut,
    DeriveRunRequest,
    FeaturePointCreate,
    FeaturePointOut,
    FeaturePointUpdate,
    FunctionCreate,
    FunctionOut,
    FunctionUpdate,
    LabelClear,
    LabelCreate,
    LabelOut,
    MigrateRequest,
    ModuleCreate,
    ModuleOut,
    ModuleUpdate,
    Page,
    RetentionOut,
    RetentionUpdate,
    RevisionDetail,
    RevisionOut,
    ReviewDecideOut,
    ReviewDecideRequest,
    ReviewDecision,
    ReviewItemsOut,
    ReviewSubmit,
    ReviewTreeOut,
)
from app.common.db import get_db
from app.common.deps import current_user
from app.llm.provider import LLMProvider, get_provider
from app.models.user import User

router = APIRouter(prefix="/api/projects", tags=["baselines"])


@router.get("/{project_id}/baselines/modules", response_model=Page[ModuleOut])
def list_modules(
    project_id: int,
    status: str = Query(default="active", pattern="^(active|archived|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[ModuleOut]:
    """模块列表。默认只列在用模块；`status=archived` 看归档的。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_modules(
        session, project_id, status=status, page=page, page_size=page_size
    )
    return Page[ModuleOut](
        items=[ModuleOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post(
    "/{project_id}/baselines/modules", response_model=ModuleOut, status_code=201
)
def create_module(
    project_id: int,
    payload: ModuleCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ModuleOut:
    """新建模块。限项目管理员。"""
    module = service.create_module(
        session,
        project_id=project_id,
        actor=user,
        name=payload.name,
        description=payload.description,
        sort_order=payload.sort_order,
    )
    return ModuleOut(
        id=module.id,
        name=module.name,
        description=module.description,
        sort_order=module.sort_order,
        source_type=module.source_type,
        status=module.status,
        created_at=module.created_at,
    )


@router.patch("/{project_id}/baselines/modules/{module_id}", response_model=ModuleOut)
def update_module(
    project_id: int,
    module_id: int,
    payload: ModuleUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ModuleOut:
    """改模块。"""
    module = service.update_module(
        session,
        project_id=project_id,
        module_id=module_id,
        actor=user,
        name=payload.name,
        description=payload.description,
        sort_order=payload.sort_order,
        status=payload.status,
    )
    return ModuleOut(
        id=module.id,
        name=module.name,
        description=module.description,
        sort_order=module.sort_order,
        source_type=module.source_type,
        status=module.status,
        created_at=module.created_at,
    )


@router.delete("/{project_id}/baselines/modules/{module_id}", response_model=DeleteResponse)
def delete_module(
    project_id: int,
    module_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeleteResponse:
    """删模块。模块下有功能 → 409 `MODULE_NOT_EMPTY`，响应带两个处理入口。"""
    result = service.delete_module(
        session, project_id=project_id, module_id=module_id, actor=user
    )
    return DeleteResponse(**result)


@router.post(
    "/{project_id}/baselines/modules/{module_id}/migrate", response_model=list[FunctionOut]
)
def migrate_functions(
    project_id: int,
    module_id: int,
    payload: MigrateRequest,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[FunctionOut]:
    """批量迁移功能到同项目其他模块。"""
    moved = service.migrate_functions(
        session,
        project_id=project_id,
        module_id=module_id,
        actor=user,
        target_module_id=payload.target_module_id,
        function_ids=payload.function_ids,
    )
    return [
        FunctionOut(
            id=item.id,
            module_id=item.module_id,
            module_name=service.get_module_name(session, item.module_id),
            name=item.name,
            description=item.description,
            version_no=item.version_no,
            source_type=item.source_type,
            status=item.status,
            moved_from_module_id=item.moved_from_module_id,
            source_document_id=item.source_document_id,
            source_version_id=item.source_version_id,
            source_chapter_id=item.source_chapter_id,
            source_chapter_title=item.source_chapter_title,
            source_method=item.source_method,
            source_analysis_id=item.source_analysis_id,
            created_at=item.created_at,
        )
        for item in moved
    ]


@router.get("/{project_id}/baselines/functions", response_model=Page[FunctionOut])
def list_functions(
    project_id: int,
    module_id: int | None = Query(default=None),
    source_type: str | None = Query(default=None),
    label_type: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    revision_id: int | None = Query(default=None),
    status: str = Query(default="active", pattern="^(active|archived|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[FunctionOut]:
    """功能列表，支持模块/来源类型/标签类型/关键词/状态筛选。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_functions(
        session,
        project_id,
        module_id=module_id,
        source_type=source_type,
        label_type=label_type,
        keyword=keyword,
        revision_id=revision_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return Page[FunctionOut](
        items=[FunctionOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post(
    "/{project_id}/baselines/functions", response_model=FunctionOut, status_code=201
)
def create_function(
    project_id: int,
    payload: FunctionCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FunctionOut:
    """新建功能。"""
    service.ensure_no_trace_fields(payload)
    function = service.create_function(
        session,
        project_id=project_id,
        actor=user,
        module_id=payload.module_id,
        name=payload.name,
        description=payload.description,
    )
    return FunctionOut(
        id=function.id,
        module_id=function.module_id,
        module_name=service.get_module_name(session, function.module_id),
        name=function.name,
        description=function.description,
        version_no=function.version_no,
        source_type=function.source_type,
        status=function.status,
        created_at=function.created_at,
    )


@router.patch(
    "/{project_id}/baselines/functions/{function_id}", response_model=FunctionOut
)
def update_function(
    project_id: int,
    function_id: int,
    payload: FunctionUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FunctionOut:
    """改功能。入参只有名称/描述/状态——来源追溯字段只读。"""
    service.ensure_no_trace_fields(payload)
    function = service.update_function(
        session,
        project_id=project_id,
        function_id=function_id,
        actor=user,
        name=payload.name,
        description=payload.description,
        status=payload.status,
    )
    return FunctionOut(
        id=function.id,
        module_id=function.module_id,
        module_name=service.get_module_name(session, function.module_id),
        name=function.name,
        description=function.description,
        version_no=function.version_no,
        source_type=function.source_type,
        status=function.status,
        moved_from_module_id=function.moved_from_module_id,
        source_document_id=function.source_document_id,
        source_version_id=function.source_version_id,
        source_chapter_id=function.source_chapter_id,
        source_chapter_title=function.source_chapter_title,
        source_method=function.source_method,
        source_analysis_id=function.source_analysis_id,
        created_at=function.created_at,
    )


@router.delete(
    "/{project_id}/baselines/functions/{function_id}", response_model=DeleteResponse
)
def delete_function(
    project_id: int,
    function_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeleteResponse:
    """删功能，连带删其功能点与标签。"""
    return DeleteResponse(
        **service.delete_function(
            session, project_id=project_id, function_id=function_id, actor=user
        )
    )


@router.get(
    "/{project_id}/baselines/functions/{function_id}/feature-points",
    response_model=list[FeaturePointOut],
)
def list_feature_points(
    project_id: int,
    function_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[FeaturePointOut]:
    """功能下的功能点列表。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return [
        FeaturePointOut(**item)
        for item in service.list_feature_points(session, project_id, function_id)
    ]


@router.post(
    "/{project_id}/baselines/functions/{function_id}/feature-points",
    response_model=FeaturePointOut,
    status_code=201,
)
def create_feature_point(
    project_id: int,
    function_id: int,
    payload: FeaturePointCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FeaturePointOut:
    """新建功能点。"""
    service.ensure_no_trace_fields(payload)
    point = service.create_feature_point(
        session,
        project_id=project_id,
        actor=user,
        function_id=function_id,
        name=payload.name,
        description=payload.description,
    )
    return FeaturePointOut(
        id=point.id,
        function_id=point.function_id,
        name=point.name,
        description=point.description,
        source_type=point.source_type,
        status=point.status,
        created_at=point.created_at,
    )


@router.patch(
    "/{project_id}/baselines/feature-points/{point_id}", response_model=FeaturePointOut
)
def update_feature_point(
    project_id: int,
    point_id: int,
    payload: FeaturePointUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FeaturePointOut:
    """改功能点。"""
    service.ensure_no_trace_fields(payload)
    point = service.update_feature_point(
        session,
        project_id=project_id,
        point_id=point_id,
        actor=user,
        name=payload.name,
        description=payload.description,
        status=payload.status,
    )
    return FeaturePointOut(
        id=point.id,
        function_id=point.function_id,
        name=point.name,
        description=point.description,
        source_type=point.source_type,
        status=point.status,
        created_at=point.created_at,
    )


@router.delete(
    "/{project_id}/baselines/feature-points/{point_id}", response_model=DeleteResponse
)
def delete_feature_point(
    project_id: int,
    point_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeleteResponse:
    """删功能点，其标签一并清除。"""
    return DeleteResponse(
        **service.delete_feature_point(
            session, project_id=project_id, point_id=point_id, actor=user
        )
    )


@router.get("/{project_id}/baselines/labels", response_model=Page[LabelOut])
def list_labels(
    project_id: int,
    target_type: str | None = Query(default=None),
    target_id: int | None = Query(default=None),
    revision_id: int | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(active|cleared|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[LabelOut]:
    """标签列表。默认只返回生效标签；传 `status=cleared` 看已清除的。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_labels(
        session,
        project_id,
        target_type=target_type,
        target_id=target_id,
        revision_id=revision_id,
        status=status or "active",
        page=page,
        page_size=page_size,
    )
    return Page[LabelOut](
        items=[LabelOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/{project_id}/baselines/labels", response_model=LabelOut, status_code=201)
def create_label(
    project_id: int,
    payload: LabelCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> LabelOut:
    """打标。功能级与功能点级独立，互不汇总。"""
    label = service.create_label(
        session,
        project_id=project_id,
        actor=user,
        revision_id=payload.revision_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        label_type=payload.label_type,
    )
    return LabelOut(
        id=label.id,
        revision_id=label.revision_id,
        target_type=label.target_type,
        target_id=label.target_id,
        label_type=label.label_type,
        status=label.status,
        confirmed_by=label.confirmed_by,
        confirmed_at=label.confirmed_at,
        cleared_by=label.cleared_by,
        cleared_at=label.cleared_at,
        clear_reason=label.clear_reason,
        clear_note=label.clear_note,
    )


@router.post("/{project_id}/baselines/labels/{label_id}/clear", response_model=LabelOut)
def clear_label(
    project_id: int,
    label_id: int,
    payload: LabelClear,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> LabelOut:
    """清除标签。行保留，状态置 `cleared` 并记清除人/时间/原因。"""
    label = service.clear_label(
        session,
        project_id=project_id,
        label_id=label_id,
        actor=user,
        clear_reason=payload.clear_reason,
        clear_note=payload.clear_note,
    )
    return LabelOut(
        id=label.id,
        revision_id=label.revision_id,
        target_type=label.target_type,
        target_id=label.target_id,
        label_type=label.label_type,
        status=label.status,
        confirmed_by=label.confirmed_by,
        confirmed_at=label.confirmed_at,
        cleared_by=label.cleared_by,
        cleared_at=label.cleared_at,
        clear_reason=label.clear_reason,
        clear_note=label.clear_note,
    )


@router.get("/{project_id}/baselines/revisions", response_model=Page[RevisionOut])
def list_revisions(
    project_id: int,
    status: str = Query(default="approved", pattern="^(approved|submitted|rejected|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[RevisionOut]:
    """快照列表。默认只列审核通过的；`status=submitted` 看待审核的。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_revisions(
        session, project_id, status=status, page=page, page_size=page_size
    )
    return Page[RevisionOut](
        items=[RevisionOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get(
    "/{project_id}/baselines/revisions/{revision_id}", response_model=RevisionDetail
)
def get_revision(
    project_id: int,
    revision_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RevisionDetail:
    """快照详情，含冻结的结构。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    item = service.get_revision(session, project_id, revision_id)
    return RevisionDetail(**item)


@router.post(
    "/{project_id}/baselines/reviews/submit", response_model=RevisionOut, status_code=201
)
def submit_review(
    project_id: int,
    payload: ReviewSubmit,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RevisionOut:
    """提交审核。"""
    revision = service.submit_review(
        session, project_id=project_id, actor=user, comment=payload.comment
    )
    return RevisionOut(
        id=revision.id,
        version_no=revision.version_no,
        status=revision.status,
        module_count=revision.module_count,
        function_count=revision.function_count,
        feature_point_count=revision.feature_point_count,
        label_count=revision.label_count,
        submitted_by=revision.submitted_by,
        submitted_at=revision.submitted_at,
        reviewed_by=revision.reviewed_by,
        reviewed_at=revision.reviewed_at,
        review_comment=revision.review_comment,
        created_at=revision.created_at,
    )


@router.post(
    "/{project_id}/baselines/reviews/{revision_id}/approve", response_model=RevisionOut
)
def approve_review(
    project_id: int,
    revision_id: int,
    payload: ReviewDecision,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RevisionOut:
    """审核通过：冻结结构、分配版本号、把生效标签复制到新快照。"""
    revision = service.approve_review(
        session,
        project_id=project_id,
        revision_id=revision_id,
        actor=user,
        comment=payload.comment,
        items=payload.items,
    )
    return RevisionOut(
        id=revision.id,
        version_no=revision.version_no,
        status=revision.status,
        module_count=revision.module_count,
        function_count=revision.function_count,
        feature_point_count=revision.feature_point_count,
        label_count=revision.label_count,
        submitted_by=revision.submitted_by,
        submitted_at=revision.submitted_at,
        reviewed_by=revision.reviewed_by,
        reviewed_at=revision.reviewed_at,
        review_comment=revision.review_comment,
        created_at=revision.created_at,
    )


@router.post(
    "/{project_id}/baselines/reviews/{revision_id}/reject", response_model=RevisionOut
)
def reject_review(
    project_id: int,
    revision_id: int,
    payload: ReviewDecision,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RevisionOut:
    """驳回。意见必填，不占版本号、不生成快照。"""
    revision = service.reject_review(
        session, project_id=project_id, revision_id=revision_id, actor=user, comment=payload.comment
    )
    return RevisionOut(
        id=revision.id,
        version_no=revision.version_no,
        status=revision.status,
        module_count=revision.module_count,
        function_count=revision.function_count,
        feature_point_count=revision.feature_point_count,
        label_count=revision.label_count,
        submitted_by=revision.submitted_by,
        submitted_at=revision.submitted_at,
        reviewed_by=revision.reviewed_by,
        reviewed_at=revision.reviewed_at,
        review_comment=revision.review_comment,
        created_at=revision.created_at,
    )


@router.get(
    "/{project_id}/baselines/reviews/{revision_id}/items",
    response_model=ReviewItemsOut,
)
def list_review_items(
    project_id: int,
    revision_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ReviewItemsOut:
    """该审核记录最近一轮的逐项决策。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return ReviewItemsOut(**service.list_review_items(session, project_id, revision_id))


@router.get(
    "/{project_id}/baselines/reviews/{revision_id}/tree",
    response_model=ReviewTreeOut,
)
def get_review_tree(
    project_id: int,
    revision_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ReviewTreeOut:
    """该轮待审内容树（模块 / 功能 / 功能点 + 当前决策）。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return ReviewTreeOut(**service.list_review_tree(session, project_id, revision_id))


@router.post(
    "/{project_id}/baselines/reviews/{revision_id}/decide",
    response_model=ReviewDecideOut,
)
def decide_review(
    project_id: int,
    revision_id: int,
    payload: ReviewDecideRequest,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ReviewDecideOut:
    """保存逐项决策草稿（不冻结）。可多次调用。"""
    return ReviewDecideOut(
        **service.decide_review(
            session,
            project_id=project_id,
            revision_id=revision_id,
            actor=user,
            items=payload.items,
        )
    )


@router.get("/{project_id}/baselines/retention", response_model=RetentionOut)
def get_retention(
    project_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RetentionOut:
    """保留策略状态：上限、快照数、待清理候选、告警。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return RetentionOut(**service.get_retention(session, project_id))


@router.patch("/{project_id}/baselines/retention", response_model=RetentionOut)
def update_retention(
    project_id: int,
    payload: RetentionUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RetentionOut:
    """设置保留上限。传 `null` 关闭策略（永久保留）。"""
    service.update_retention(
        session, project_id=project_id, actor=user, max_count=payload.max_count
    )
    return RetentionOut(**service.get_retention(session, project_id))


@router.delete(
    "/{project_id}/baselines/revisions/{revision_id}", response_model=DeleteResponse
)
def delete_revision(
    project_id: int,
    revision_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeleteResponse:
    """删快照。被标签引用 → 409 `SNAPSHOT_REFERENCED`。"""
    return DeleteResponse(
        **service.delete_revision(session, project_id=project_id, revision_id=revision_id, actor=user)
    )


# ------------------------------------------------- 从文档推导基线（T90）


@router.post(
    "/{project_id}/baselines/derive",
    response_model=DeriveDetailOut,
    status_code=201,
)
def run_derive(
    project_id: int,
    payload: DeriveRunRequest,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
    provider: LLMProvider = Depends(get_provider),
) -> DeriveDetailOut:
    """发起推导（同步跑完返回）。限项目管理员。

    响应直接带候选树（AC-123）：前端不用再发一次 GET。
    """
    derive = service.run_document_derive(
        session,
        project_id=project_id,
        actor=user,
        document_id=payload.document_id,
        document_version_id=payload.document_version_id,
        template_id=payload.template_id,
        provider=provider,
    )
    return DeriveDetailOut(
        **service.get_derive_detail(session, project_id, derive.id)
    )


@router.get(
    "/{project_id}/baselines/derive", response_model=Page[DeriveOut]
)
def list_derives(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[DeriveOut]:
    """推导记录列表。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_derives(session, project_id, page=page, page_size=page_size)
    return Page[DeriveOut](
        items=[DeriveOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get(
    "/{project_id}/baselines/derive/{derive_id}", response_model=DeriveDetailOut
)
def get_derive(
    project_id: int,
    derive_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeriveDetailOut:
    """推导详情 + 候选树。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return DeriveDetailOut(**service.get_derive_detail(session, project_id, derive_id))


@router.post(
    "/{project_id}/baselines/derive/{derive_id}/adopt", response_model=AdoptOut
)
def adopt_derive(
    project_id: int,
    derive_id: int,
    payload: AdoptRequest,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AdoptOut:
    """采纳候选：写入结构表（层级递归）。"""
    return AdoptOut(
        **service.adopt_derive_candidates(
            session,
            project_id=project_id,
            derive_id=derive_id,
            actor=user,
            items=payload.candidates,
        )
    )


@router.delete(
    "/{project_id}/baselines/derive/{derive_id}/candidates/{candidate_id}",
    response_model=DeleteResponse,
)
def delete_derive_candidate(
    project_id: int,
    derive_id: int,
    candidate_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeleteResponse:
    """删一个候选（草稿阶段），子候选随之删除。"""
    return DeleteResponse(
        **service.delete_derive_candidate(
            session,
            project_id=project_id,
            derive_id=derive_id,
            candidate_id=candidate_id,
            actor=user,
        )
    )
