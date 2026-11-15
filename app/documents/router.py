"""项目内的文档上传（T47 / AC-49 ~ AC-51）。"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.db import get_db
from app.common.deps import SYSTEM_ADMIN, current_user
from app.common.errors import Forbidden, NotProjectMember
from app.documents import service
from app.documents.schemas import DocumentBrief, UploadResponse, VersionOut
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
        version=VersionOut(
            id=version.id,
            version_no=version.version_no,
            status=version.status,
            chapter_count=version.chapter_count,
            file_name=version.file_name,
            file_size=version.file_size,
            created_at=version.created_at,
        ),
    )
