"""ORM 模型集中注册。

Alembic 通过这里的 `target_metadata` 自动发现表结构。
**新增模型后必须在本文件 import**，否则 autogenerate 检测不到。
"""

from app.common.db import Base
from app.models.application import ProjectApplication
from app.models.project import Project, ProjectMember
from app.models.token import AccessToken
from app.models.user import User

target_metadata = Base.metadata

__all__ = [
    "AccessToken",
    "Base",
    "Project",
    "ProjectApplication",
    "ProjectMember",
    "User",
    "target_metadata",
]
