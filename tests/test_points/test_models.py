"""测试点分析两张表与留痕枚举扩充（07-test-points T99）。

验证数据库层保障：种子模板存在且前缀可识别、两表可写入、
四个 CHECK 约束生效、`needs_review` 默认 0、留痕表接受 `task_type='test_point'`
但拒绝非法值。
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.baseline import BaselineRevision
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import PromptTemplate
from app.models.llm import LLMRunLog
from app.models.project import Project
from app.models.test_point import TestPoint, TestPointAnalysis
from app.models.user import User


def _user(db: Session) -> User:
    user = User(username=f"tp-{uuid.uuid4().hex[:10]}", password_hash="x" * 60)
    db.add(user)
    db.flush()
    return user


def _chain(db: Session) -> dict:
    """造出测试点所需的完整外键链：用户 / 项目 / 模板 / 快照 / 文档版本 / 章节。"""
    user = _user(db)
    project = Project(name=f"测试点项目-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()

    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "test_point")
    )
    assert template is not None, "迁移 0022 应播种一条 test_point 模板"

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
        sha256="b" * 64,
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


def _analysis(db: Session, chain: dict, *, status: str = "running") -> TestPointAnalysis:
    analysis = TestPointAnalysis(
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


def _point(
    db: Session,
    chain: dict,
    analysis: TestPointAnalysis | None = None,
    **overrides,
) -> TestPoint:
    payload = {
        "project_id": chain["project"].id,
        "analysis_id": analysis.id if analysis is not None else None,
        "name": "扫码登录连续失败 5 次后锁定",
        "target_type": "function",
        "target_id": 10096,
        "target_name": "用户扫码登录",
        "priority": "high",
        "precondition": "账号已存在且未锁定",
        "verification": "连续输错密码 5 次，提示锁定",
        "chapter_id": chain["chapter"].id,
        "chapter_title": chain["chapter"].title,
        "source_type": "llm",
        "created_by": chain["user"].id,
    }
    payload.update(overrides)
    point = TestPoint(**payload)
    db.add(point)
    db.flush()
    return point


def test_ac_156_seed_template_exists(db: Session):
    """迁移播种的 test_point 模板存在，两个 Prompt 的前缀可识别。

    **示例里的 target_id 必须是「看起来像占位符」的值**：
    真实模型会照抄示例（06 期 L2 实测——模板写死 `"target_id": 1`，
    模型就抄 1，真实的 10096 / 10097 全被当越界丢弃）。
    """
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "test_point")
    )
    assert template is not None, "迁移 0022 应播种一条 test_point 模板"
    assert template.status == "active"
    assert template.system_prompt.startswith("[TEST_POINT_SYSTEM]")
    assert template.user_prompt.startswith("[TEST_POINT_USER]")
    assert '"target_id": 1,' not in template.system_prompt
    assert '"target_id": 123,' in template.system_prompt
    # 模板必须说清 target_id 从哪来
    assert "可对照的基线目标" in template.system_prompt


def test_ac_156_seed_template_is_unique(db: Session):
    """`task_type='test_point'` 的模板有且只有一条 active。"""
    total = db.scalar(
        select(func.count())
        .select_from(PromptTemplate)
        .where(PromptTemplate.task_type == "test_point")
    )
    assert total == 1


def test_analysis_and_point_roundtrip(db: Session):
    """两表可写入，默认值与 JSON 统计列符合预期。"""
    chain = _chain(db)
    analysis = _analysis(db, chain)
    point = _point(db, chain, analysis)

    db.refresh(analysis)
    db.refresh(point)
    analysis.stats = {"chapter_count": 1, "test_point_count": 1, "discarded_count": 0}
    db.flush()
    db.refresh(analysis)

    assert analysis.provider == "mock"
    assert analysis.template_version == chain["template"].version_no
    assert analysis.stats["test_point_count"] == 1
    assert point.priority == "high"
    assert point.status == "pending"
    assert point.source_type == "llm"
    assert point.needs_review == 0
    assert point.created_at is not None


def test_manual_point_defaults(db: Session):
    """手工新增的测试点：`analysis_id` 为 NULL、`source_type='manual'`。"""
    chain = _chain(db)
    point = _point(db, chain, None, source_type="manual", source_label_id=None)

    assert point.analysis_id is None
    assert point.source_type == "manual"
    assert point.status == "pending"


def test_points_allow_duplicate_names(db: Session):
    """测试点**不建唯一键**：同名是合法的（不同功能的同名测试点）。"""
    chain = _chain(db)
    analysis = _analysis(db, chain)
    first = _point(db, chain, analysis)
    second = _point(db, chain, analysis, target_id=10097, target_name="账号密码登录")
    db.commit()

    assert first.name == second.name
    assert first.id != second.id


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("target_type", "module", "ck_tpoints_target_type"),
        ("priority", "urgent", "ck_tpoints_priority"),
        ("status", "done", "ck_tpoints_status"),
        ("source_type", "manual_v2", "ck_tpoints_source_type"),
    ],
)
def test_point_check_constraints(db: Session, field: str, value: str, constraint: str):
    """测试点的四个 CHECK 约束都生效。"""
    chain = _chain(db)

    with pytest.raises(OperationalError) as exc:
        _point(db, chain, None, **{field: value})
    assert exc.value.orig.args[0] == 3819
    assert constraint in str(exc.value.orig.args[1])


def test_analysis_status_check(db: Session):
    """生成记录状态只接受四个枚举值。"""
    chain = _chain(db)

    with pytest.raises(OperationalError) as exc:
        _analysis(db, chain, status="done")
    assert exc.value.orig.args[0] == 3819
    assert "ck_tpanalyses_status" in str(exc.value.orig.args[1])


def test_ac_154_run_log_accepts_test_point_task_type(db: Session):
    """留痕表接受 `task_type='test_point'`（0022 扩了 CHECK 枚举）。"""
    chain = _chain(db)
    log = LLMRunLog(
        task_type="test_point",
        project_id=chain["project"].id,
        provider_name="mock",
        model="mock",
        call_count=1,
        latency_ms=10,
        status="succeeded",
    )
    db.add(log)
    db.flush()
    db.commit()

    assert log.id is not None
    assert log.task_type == "test_point"


def test_ac_154_run_log_rejects_unknown_task_type(db: Session):
    """留痕表仍然拒绝非法 `task_type`（CHECK 扩了枚举，不是放开了口子）。

    MySQL 的 CHECK 违约抛的是 3819（`OperationalError`），不是 1062。
    """
    chain = _chain(db)
    log = LLMRunLog(
        task_type="bogus_task",
        project_id=chain["project"].id,
        provider_name="mock",
        model="mock",
        call_count=1,
        latency_ms=10,
        status="succeeded",
    )
    db.add(log)
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_llmlogs_task_type" in str(exc.value.orig.args[1])
    db.rollback()
