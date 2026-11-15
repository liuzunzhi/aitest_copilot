"""文档接口出入参（03-documents）。"""

from datetime import datetime

from pydantic import BaseModel


class DocumentBrief(BaseModel):
    id: int
    name: str
    version_count: int


class VersionOut(BaseModel):
    id: int
    version_no: int
    status: str
    chapter_count: int
    file_name: str
    file_size: int
    created_at: datetime


class UploadResponse(BaseModel):
    document: DocumentBrief
    version: VersionOut
