"""ORM 模型集中注册。

Alembic 通过这里的 `target_metadata` 自动发现表结构。
**新增模型后必须在本文件 import**，否则 autogenerate 检测不到。
"""

from app.common.db import Base
from app.models.application import ProjectApplication
from app.models.baseline import (
    BaselineFeaturePoint,
    BaselineFunction,
    BaselineLabel,
    BaselineModule,
    BaselineRevision,
)
from app.models.baseline_derive import BaselineDerive, BaselineDeriveCandidate
from app.models.baseline_review import BaselineReviewItem, BaselineReviewRound
from app.models.chapter_link import DocumentChapterLink
from app.models.document import BaselineSnapshot, Document, DocumentChapter, DocumentVersion
from app.models.incremental import (
    IncrementalAnalysis,
    IncrementalConclusion,
    IncrementalConflict,
    IncrementalDecision,
    IncrementalLabel,
    PromptTemplate,
)
from app.models.llm import LLMProviderConfig, LLMRunLog
from app.models.project import Project, ProjectMember
from app.models.system import AuditLog, SystemSetting
from app.models.test_case import TestCase, TestCaseAnalysis, TestCaseStep
from app.models.test_point import TestPoint, TestPointAnalysis
from app.models.token import AccessToken
from app.models.user import User

target_metadata = Base.metadata

__all__ = [
    "AccessToken",
    "AuditLog",
    "Base",
    "BaselineDerive",
    "BaselineDeriveCandidate",
    "BaselineFeaturePoint",
    "BaselineFunction",
    "BaselineLabel",
    "BaselineModule",
    "BaselineReviewItem",
    "BaselineReviewRound",
    "BaselineRevision",
    "BaselineSnapshot",
    "Document",
    "DocumentChapter",
    "DocumentChapterLink",
    "DocumentVersion",
    "IncrementalAnalysis",
    "IncrementalConclusion",
    "IncrementalConflict",
    "IncrementalDecision",
    "IncrementalLabel",
    "LLMProviderConfig",
    "LLMRunLog",
    "Project",
    "ProjectApplication",
    "ProjectMember",
    "PromptTemplate",
    "SystemSetting",
    "TestCase",
    "TestCaseAnalysis",
    "TestCaseStep",
    "TestPoint",
    "TestPointAnalysis",
    "User",
    "target_metadata",
]
