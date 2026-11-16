"""项目内的文档上传（T47 / AC-49 ~ AC-51）。"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.db import get_db
from app.common.deps import (
    SYSTEM_ADMIN,
    current_user,
    require_project_member_or_system_admin,
)
from app.common.errors import Forbidden, NotProjectMember
from app.documents import service
from app.documents.schemas import (
    ActivateResponse,
    BaselineOut,
    ChapterOut,
    DocumentBrief,
    DocumentListItem,
    UploadResponse,
    VersionOut,
)
from app.models.document import DocumentVersion
from app.models.project import ProjectMember
from app.models.user import User

router = APIRouter(prefix="/api/projects", tags=["documents"])


def require_uploader(
    project_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> User:
    """上传要求「是项目成员且不是访客」，系统管理员兜底。

    不复用 `require_project_role`：那条依赖把「非成员」和「角色不符」都报成
    `FORBIDDEN`，而 spec 要求非成员返回 `NOT_PROJECT_MEMBER`。
    """
    if user.global_role == SYSTEM_ADMIN:
        return user

    member = session.get(ProjectMember, (project_id, user.id))
    if member is None:
        raise NotProjectMember("不是该项目成员")
    if member.role == "guest":
        raise Forbidden("访客不能上传文档")
    return user


@router.post("/{project_id}/documents", response_model=UploadResponse, status_code=201)
def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    document_id: int | None = Form(default=None),
    session: Session = Depends(get_db),
    user: User = Depends(require_uploader),
) -> UploadResponse:
    """上传新文档或追加版本。

    多读 1 字节用于判断超限：超过上限时不必把大文件完整读进内存，
    服务层看到 `len(data) > max` 直接报 `DOC_TOO_LARGE`。
    """
    data = file.file.read(get_settings().doc_max_bytes + 1)
    file_name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]

    document, version, version_count = service.upload_document(
        session,
        project_id=project_id,
        actor=user,
        file_name=file_name,
        data=data,
        document_id=document_id,
    )
    return UploadResponse(
        document=DocumentBrief(
            id=document.id, name=document.name, version_count=version_count
        ),
        version=_version_out(version),
    )


@router.get("/{project_id}/documents", response_model=list[DocumentListItem])
def list_documents(
    project_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(require_project_member_or_system_admin),
) -> list[DocumentListItem]:
    """项目成员（含访客）可读；非成员 403。响应刻意不含 `file_path`。"""
    return [
        DocumentListItem(
            id=item["id"],
            name=item["name"],
            created_at=item["created_at"],
            version_count=item["version_count"],
            pending_count=item["pending_count"],
            active_version=(
                _version_out(item["active_version"]) if item["active_version"] else None
            ),
        )
        for item in service.list_documents(session, project_id)
    ]


@router.get(
    "/{project_id}/documents/{document_id}/versions",
    response_model=list[VersionOut],
)
def list_versions(
    project_id: int,
    document_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(require_project_member_or_system_admin),
) -> list[VersionOut]:
    versions = service.list_versions(
        session, project_id=project_id, document_id=document_id
    )
    return [_version_out(version) for version in versions]


@router.get(
    "/{project_id}/documents/{document_id}/versions/{version_id}/chapters",
    response_model=list[ChapterOut],
)
def list_chapters(
    project_id: int,
    document_id: int,
    version_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(require_project_member_or_system_admin),
) -> list[ChapterOut]:
    """章节树。扁平列表在服务层按 `parent_id` 组好，这里只做响应校验。"""
    return service.list_chapters(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
    )


@router.post(
    "/{project_id}/documents/{document_id}/versions/{version_id}/activate",
    response_model=ActivateResponse,
)
def activate_version(
    project_id: int,
    document_id: int,
    version_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ActivateResponse:
    """确认生效并生成基线快照。

    权限在服务层判定（要读 `uploaded_by` 才知道普通成员能否操作），
    所以这里只取当前用户，不复用项目角色依赖。
    """
    document, version, snapshot = service.activate_version(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
        actor=user,
    )
    return ActivateResponse(
        version=_version_out(version),
        baseline=BaselineOut(
            id=snapshot.id,
            version_no=snapshot.version_no,
            chapter_count=snapshot.chapter_count,
            created_at=snapshot.created_at,
            document_id=document.id,
            document_name=document.name,
            document_version_no=version.version_no,
        ),
    )


@router.post(
    "/{project_id}/documents/{document_id}/versions/{version_id}/void",
    response_model=VersionOut,
)
def void_version(
    project_id: int,
    document_id: int,
    version_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> VersionOut:
    """作废待确认版本；权限与确认生效一致，在服务层判定。"""
    version = service.void_version(
        session,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
        actor=user,
    )
    return _version_out(version)


@router.get(
    "/{project_id}/documents/{document_id}/versions/{version_id}/download",
    response_class=FileResponse,
)
def download_source(
    project_id: int,
    document_id: int,
    version_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(require_project_member_or_system_admin),
) -> FileResponse:
    """下载原文。文件名用中文也能正确落盘：Starlette 会写成 RFC 5987 的 `filename*`。"""
    path, file_name = service.get_source_file(
        session, project_id=project_id, document_id=document_id, version_id=version_id
    )
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=file_name,
        content_disposition_type="attachment",
    )


@router.get("/{project_id}/baselines", response_model=list[BaselineOut])
def list_baselines(
    project_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(require_project_member_or_system_admin),
) -> list[BaselineOut]:
    return service.list_baselines(session, project_id)


def _version_out(version: DocumentVersion) -> VersionOut:
    return VersionOut(
        id=version.id,
        version_no=version.version_no,
        status=version.status,
        chapter_count=version.chapter_count,
        file_name=version.file_name,
        file_size=version.file_size,
        created_at=version.created_at,
    )
