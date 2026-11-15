"""项目与项目成员模型。"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class Project(Base):
    """项目。平台数据的隔离边界。"""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('active','archived')", name="ck_projects_status"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="项目简介"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class ProjectMember(Base):
    """项目成员关系。

    复合主键 (project_id, user_id)，不设代理主键——
    同一用户在同一项目内只能有一条成员记录。
    「未归属用户」由「没有任何成员记录」推导，不单独存储。
    """

    __tablename__ = "project_members"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_members_project"),
        ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_members_user"),
        CheckConstraint(
            "role IN ('project_admin','member','guest')", name="ck_members_role"
        ),
        Index("idx_members_user", "user_id"),
        _TABLE_OPTS,
    )

    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = ["Project", "ProjectMember"]
