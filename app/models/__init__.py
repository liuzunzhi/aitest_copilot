"""ORM 模型集中注册。

Alembic 通过这里的 `target_metadata` 自动发现表结构。
**新增模型后必须在本文件 import**，否则 autogenerate 检测不到。
"""

from app.common.db import Base

target_metadata = Base.metadata

__all__ = ["Base", "target_metadata"]
