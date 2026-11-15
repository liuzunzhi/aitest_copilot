"""文档接口出入参（03-documents）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentBrief(BaseModel):
    id: int
    name: str
    version_count: int


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_no: int
    status: str
    chapter_count: int
    file_name: str
    file_size: int
    created_at: datetime


class DocumentListItem(BaseModel):
    id: int
    name: str
    created_at: datetime
    version_count: int
    pending_count: int
    active_version: VersionOut | None


class ChapterOut(BaseModel):
    id: int
    seq: int
    level: int
    title: str
    content: str
    char_count: int
    children: list["ChapterOut"] = []


ChapterOut.model_rebuild()


class UploadResponse(BaseModel):
    document: DocumentBrief
    version: VersionOut
