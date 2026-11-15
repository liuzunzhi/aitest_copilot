"""文档、版本、章节与基线快照模型（03-documents 解析段）。

一章一节都挂在「文档版本」下：版本一旦上传即不可变，
基线快照只引用版本，不再复制章节——这是本期「不做人工修正章节」的直接结果。

`active_key` 是 STORED 生成列：仅当版本 `active` 时等于 `document_id`，
配合唯一索引保证「同一文档只有一个生效版本」。MySQL 无条件唯一索引，
但允许多个 NULL，所以归档/作废的版本不会互相冲突。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER, MEDIUMTEXT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_default_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

ACTIVE_KEY_EXPR = "IF(status = 'active', document_id, NULL)"


class Document(Base):
    """需求文档。项目内的逻辑文档，版本挂在它下面。"""

    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_documents_project"),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_documents_creator"),
        Index("uk_documents_project_name", "project_id", "name", unique=True),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="默认取文件名去扩展名")
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class DocumentVersion(Base):
    """文档版本。上传即解析，`version_no` 在文档内从 1 递增。"""

    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_versions_document"
        ),
        ForeignKeyConstraint(["uploaded_by"], ["users.id"], name="fk_versions_uploader"),
        Index("uk_versions_doc_no", "document_id", "version_no", unique=True),
        Index("uk_versions_active", "active_key", unique=True),
        CheckConstraint(
            "status IN ('pending','active','archived','void')",
            name="ck_versions_status",
        ),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    version_no: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="相对路径，不对外返回"
    )
    file_size: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chapter_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text("0")
    )
    uploaded_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    active_key: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        Computed(ACTIVE_KEY_EXPR, persisted=True),
        comment="生成列：active 时等于 document_id，其余为 NULL",
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class DocumentChapter(Base):
    """章节树节点。`content` 只含直属正文，不含子章节正文。"""

    __tablename__ = "document_chapters"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_chapters_version"
        ),
        ForeignKeyConstraint(
            ["parent_id"], ["document_chapters.id"], name="fk_chapters_parent"
        ),
        Index("uk_chapters_version_seq", "version_id", "seq", unique=True),
        Index("idx_chapters_parent", "parent_id"),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    seq: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    level: Mapped[int] = mapped_column(TINYINT(unsigned=True), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    char_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)


class BaselineSnapshot(Base):
    """基线快照。确认生效时同事务写入，只读、只增。

    `version_id` 唯一：同一版本不会生成两次快照；
    `(project_id, version_no)` 唯一：项目内序号单调，靠项目行锁取号。
    """

    __tablename__ = "baseline_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_baseline_project"),
        ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_baseline_version"
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_baseline_creator"),
        Index("uk_baseline_version", "version_id", unique=True),
        Index("uk_baseline_project_no", "project_id", "version_no", unique=True),
        _TABLE_OPTS,
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    version_no: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, comment="项目内基线序号"
    )
    chapter_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


__all__ = ["BaselineSnapshot", "Document", "DocumentChapter", "DocumentVersion"]
