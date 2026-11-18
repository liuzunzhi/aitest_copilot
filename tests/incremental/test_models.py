"""增量分析三张表（T68）。

验证数据库层保障：种子模板存在且前缀可识别、三表可写入、
结论唯一键生效、`label_type` / `status` CHECK 生效、结论随分析级联删除。
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.baseline import BaselineRevision
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import (
    IncrementalAnalysis,
    IncrementalConclusion,
    PromptTemplate,
)
from app.models.project import Project
from app.models.user import User


def _user(db: Session) -> User:
    user = User(username=f"inc-{uuid.uuid4().hex[:10]}", password_hash="x" * 60)
    db.add(user)
    db.flush()
    return user


def _template(db: Session) -> PromptTemplate:
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "incremental",
            PromptTemplate.name == "增量分析·第一遍·章节局部",
        )
    )
    assert template is not None, "迁移 0013 应播种一条 incremental 模板"
    return template


def _chain(db: Session) -> dict:
    """造出分析记录所需的完整外键链：用户 / 项目 / 模板 / 快照 / 文档版本 / 章节。"""
    user = _user(db)
    project = Project(name=f"增量项目-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()

    template = _template(db)

    revision = BaselineRevision(project_id=project.id, status="approved")
    db.add(revision)
    db.flush()

    document = Document(project_id=project.id, name="支付需求", created_by=user.id)
    db.add(document)
    db.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        status="active",
        file_name="支付需求.md",
        file_path="var/uploads/1/1.md",
        file_size=128,
        sha256="a" * 64,
        chapter_count=1,
        uploaded_by=user.id,
    )
    db.add(version)
    db.flush()

    chapter = DocumentChapter(
        version_id=version.id,
        parent_id=None,
        seq=1,
        level=1,
        title="登录",
        content="账号密码登录",
        char_count=6,
    )
    db.add(chapter)
    db.flush()

    return {
        "user": user,
        "project": project,
        "template": template,
        "revision": revision,
        "document": document,
        "version": version,
        "chapter": chapter,
    }


def _analysis(db: Session, chain: dict, *, status: str = "running") -> IncrementalAnalysis:
    analysis = IncrementalAnalysis(
        project_id=chain["project"].id,
        template_id=chain["template"].id,
        template_version=chain["template"].version_no,
        baseline_revision_id=chain["revision"].id,
        document_id=chain["document"].id,
        document_version_id=chain["version"].id,
        status=status,
        created_by=chain["user"].id,
    )
    db.add(analysis)
    db.flush()
    return analysis


def _conclusion(
    db: Session,
    chain: dict,
    analysis: IncrementalAnalysis,
    *,
    target_type: str = "function",
    target_id: int = 1,
    label_type: str = "changed",
) -> IncrementalConclusion:
    conclusion = IncrementalConclusion(
        analysis_id=analysis.id,
        chapter_id=chain["chapter"].id,
        chapter_title=chain["chapter"].title,
        target_type=target_type,
        target_id=target_id,
        label_type=label_type,
        confidence=Decimal("0.80"),
        rationale="登录流程有改动",
    )
    db.add(conclusion)
    db.flush()
    return conclusion


def test_ac_78_seed_template_exists(db: Session):
    """迁移播种的 incremental 模板存在，两个 Prompt 的前缀可识别。

    版本号是 2：迁移 0019 修正了第一遍模板的 system prompt
    （原示例写死 `"target_id": 1`，真实模型照抄，结论全被当越界丢弃），
    正文变了 → 版本 +1。
    """
    template = _template(db)

    assert template.task_type == "incremental"
    assert template.status == "active"
    assert template.version_no == 2
    assert template.system_prompt.startswith("[INCREMENTAL_SYSTEM]")
    assert template.user_prompt.startswith("[INCREMENTAL_USER]")
    # 0019 起模板必须说清 target_id 从哪来
    assert "可对照的基线目标" in template.system_prompt
    assert '"target_id": 1,' not in template.system_prompt


def test_analysis_tables_roundtrip(db: Session):
    """三表可写入，默认值与 JSON 统计列符合预期。"""
    chain = _chain(db)
    analysis = _analysis(db, chain)
    conclusion = _conclusion(db, chain, analysis)

    db.refresh(analysis)
    db.refresh(conclusion)
    analysis.stats = {
        "chapter_count": 1,
        "conclusion_count": 1,
        "discarded_count": 0,
        "dropped_new_count": 0,
        "discarded": [],
    }
    db.flush()
    db.refresh(analysis)

    assert analysis.provider == "mock"
    assert analysis.split_granularity == "chapter"
    assert analysis.template_version == chain["template"].version_no
    assert analysis.stats["conclusion_count"] == 1
    assert conclusion.chapter_title == "登录"
    assert conclusion.confidence == Decimal("0.80")
    assert conclusion.created_at is not None


def test_conclusion_unique_per_target(db: Session):
    """同一分析、同一章节、同一目标只允许一条结论。"""
    chain = _chain(db)
    analysis = _analysis(db, chain)
    conclusion = _conclusion(db, chain, analysis)
    db.commit()

    with pytest.raises(IntegrityError) as exc:
        _conclusion(db, chain, analysis, target_type=conclusion.target_type)
    assert exc.value.orig.args[0] == 1062
    assert "uk_iconclusions_unique" in str(exc.value.orig.args[1])


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("label_type", "new", "ck_iconclusions_label_type"),
        ("target_type", "module", "ck_iconclusions_target_type"),
    ],
)
def test_conclusion_check_constraints(db: Session, field: str, value: str, constraint: str):
    """结论的 label_type 只允许三值（不含 new），target_type 只允许两级。"""
    chain = _chain(db)
    analysis = _analysis(db, chain)

    with pytest.raises(OperationalError) as exc:
        _conclusion(db, chain, analysis, **{field: value})
    assert exc.value.orig.args[0] == 3819
    assert constraint in str(exc.value.orig.args[1])


def test_analysis_status_check(db: Session):
    """分析状态只接受四个枚举值。"""
    chain = _chain(db)

    with pytest.raises(OperationalError) as exc:
        _analysis(db, chain, status="done")
    assert exc.value.orig.args[0] == 3819
    assert "ck_ianalyses_status" in str(exc.value.orig.args[1])


def test_conclusions_cascade_with_analysis(db: Session):
    """分析记录删除后，结论随之级联删除。"""
    chain = _chain(db)
    analysis = _analysis(db, chain)
    _conclusion(db, chain, analysis)
    db.commit()

    db.execute(delete(IncrementalAnalysis).where(IncrementalAnalysis.id == analysis.id))
    db.flush()

    remaining = db.scalar(
        select(func.count())
        .select_from(IncrementalConclusion)
        .where(IncrementalConclusion.analysis_id == analysis.id)
    )
    assert remaining == 0
