"""产出段引擎（第三期 · T80）。

把第二遍的裁决结果落成 04 的基线标签，并准备一份待审核快照。

四个入口按「先算 → 再删旧 → 再写新」串起来：

    targets = collect_labelable(decisions, conflicts)   # 纯函数，不碰库
    revision = resolve_revision(...)                    # 复用或新建 submitted
    clear_previous(...)                                 # 逻辑清除本分析上一轮标签
    result = write_labels(...)                          # 写 baseline_labels + 映射

红线（违反即返工）：

- 不物理删除任何标签行：重跑只把本分析上一轮的生效标签置 ``cleared``；
- 不写 ``unchanged`` 标签，也不处理 ``new`` 冲突（没有基线实体）；
- 不自动创建功能 / 功能点；
- 不自动批准快照，只建 / 复用 ``status='submitted'`` 的记录；
- 只调用 04 的既有方法（``clear_label`` / 模型），不改 ``app/baselines``。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.baselines import service as baseline_service
from app.common.errors import DuplicateLabel
from app.models.baseline import (
    BaselineFeaturePoint,
    BaselineFunction,
    BaselineLabel,
    BaselineModule,
    BaselineRevision,
)
from app.models.incremental import (
    APPLIED_LABEL_TYPES,
    IncrementalAnalysis,
    IncrementalLabel,
)
from app.models.user import User

# 重跑产出时旧标签的清除原因，与 spec-phase3 §5.4 一致
CLEAR_REASON = "misjudged"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class LabelableTarget:
    """一条可落标签的目标。

    `source` 记录它来自裁决还是冲突，方便排查；`source_id` 是对应行 id
    （第二遍引擎的待落库对象没有 id，此时为 None）。
    """

    target_type: str
    target_id: int
    target_name: str
    label_type: str
    source: str
    source_id: int | None = None


@dataclass
class WriteResult:
    """一次写标签的结果。`skipped_missing` 用于回填 ``apply_stats``。"""

    labels: list[BaselineLabel] = field(default_factory=list)
    skipped_missing: list[LabelableTarget] = field(default_factory=list)

    @property
    def label_count(self) -> int:
        return len(self.labels)


# ------------------------------------------------------------ 收集


def collect_labelable(decisions, conflicts) -> list[LabelableTarget]:
    """按 spec §5.1 规则表挑出要落标签的目标（纯函数）。

    - 裁决只收 ``changed`` / ``affected``，``unchanged`` 不落标签；
    - 冲突只收 ``status='confirmed'`` 且 ``resolved_label_type`` 是变更类；
      待裁决 / 已驳回 / 裁决为 ``unchanged`` / ``new``（无 ``target_id``）都不收；
    - 同一目标只留第一条：第二遍保证一个目标只出现在裁决或冲突之一，
      这里再做一次兜底，裁决优先，避免同一目标写两条标签。
    """
    targets: list[LabelableTarget] = []
    seen: set[tuple[str, int]] = set()

    for row in decisions:
        if row.decision not in APPLIED_LABEL_TYPES:
            continue
        key = (row.target_type, row.target_id)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            LabelableTarget(
                target_type=row.target_type,
                target_id=row.target_id,
                target_name=row.target_name,
                label_type=row.decision,
                source="decision",
                source_id=getattr(row, "id", None),
            )
        )

    for row in conflicts:
        if row.status != "confirmed":
            continue
        if row.resolved_label_type not in APPLIED_LABEL_TYPES:
            continue
        # `new` 没有基线实体，target_id 为空
        if row.target_id is None:
            continue
        key = (row.target_type, row.target_id)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            LabelableTarget(
                target_type=row.target_type,
                target_id=row.target_id,
                target_name=row.target_name,
                label_type=row.resolved_label_type,
                source="conflict",
                source_id=getattr(row, "id", None),
            )
        )

    return targets


# ------------------------------------------------------------ 快照


def resolve_revision(
    session: Session,
    *,
    project_id: int,
    actor: User,
    analysis: IncrementalAnalysis,
) -> BaselineRevision:
    """给标签找一份待审核快照：项目内已有 submitted 就复用，否则新建。

    产出段不填 ``version_no`` / ``structure_json`` / 各级计数——这些由 04
    的审核通过流程（``approve_review``）填写，产出段不自动批准。
    """
    revision = session.scalar(
        select(BaselineRevision)
        .where(
            BaselineRevision.project_id == project_id,
            BaselineRevision.status == "submitted",
        )
        .order_by(BaselineRevision.id.desc())
    )
    if revision is not None:
        return revision

    revision = BaselineRevision(
        project_id=project_id,
        status="submitted",
        submitted_by=actor.id,
        submitted_at=_now(),
        review_comment=f"增量分析 #{analysis.id} 产出",
    )
    session.add(revision)
    session.flush()
    return revision


# ------------------------------------------------------------ 逻辑清除


def clear_previous(
    session: Session, *, analysis: IncrementalAnalysis, actor: User
) -> int:
    """逻辑清除本分析上一轮产出的生效标签，返回清除条数。

    走 04 的 ``clear_label``（自带 ``baseline.label.clear`` 审计与
    ``misjudged`` 语义），标签行**不删除**，只置 ``cleared``。
    清除后 ``active_key`` 变 NULL，新一轮同键标签不会撞唯一索引。
    """
    label_ids = list(
        session.scalars(
            select(BaselineLabel.id)
            .join(
                IncrementalLabel,
                IncrementalLabel.baseline_label_id == BaselineLabel.id,
            )
            .where(
                IncrementalLabel.analysis_id == analysis.id,
                BaselineLabel.status == "active",
            )
            .order_by(BaselineLabel.id)
        ).all()
    )
    cleared = 0
    for label_id in label_ids:
        baseline_service.clear_label(
            session,
            project_id=analysis.project_id,
            label_id=label_id,
            actor=actor,
            clear_reason=CLEAR_REASON,
            clear_note=None,
        )
        cleared += 1
    return cleared


# ------------------------------------------------------------ 写标签


def _valid_target_ids(
    session: Session, *, project_id: int, targets: list[LabelableTarget]
) -> set[tuple[str, int]]:
    """当前结构里仍可打标的目标（功能 / 功能点，且所属模块未归档）。"""
    function_ids = {
        item.target_id for item in targets if item.target_type == "function"
    }
    point_ids = {
        item.target_id for item in targets if item.target_type == "feature_point"
    }
    valid: set[tuple[str, int]] = set()

    if function_ids:
        rows = session.scalars(
            select(BaselineFunction.id)
            .join(BaselineModule, BaselineModule.id == BaselineFunction.module_id)
            .where(
                BaselineFunction.id.in_(function_ids),
                BaselineFunction.project_id == project_id,
                BaselineFunction.status == "active",
                BaselineModule.status == "active",
            )
        ).all()
        valid.update(("function", int(row)) for row in rows)

    if point_ids:
        rows = session.scalars(
            select(BaselineFeaturePoint.id)
            .join(BaselineFunction, BaselineFunction.id == BaselineFeaturePoint.function_id)
            .join(BaselineModule, BaselineModule.id == BaselineFunction.module_id)
            .where(
                BaselineFeaturePoint.id.in_(point_ids),
                BaselineFeaturePoint.project_id == project_id,
                BaselineFeaturePoint.status == "active",
                BaselineFunction.status == "active",
                BaselineModule.status == "active",
            )
        ).all()
        valid.update(("feature_point", int(row)) for row in rows)

    return valid


def _insert_label(
    session: Session,
    *,
    project_id: int,
    revision_id: int,
    target: LabelableTarget,
    analysis: IncrementalAnalysis,
    actor: User,
) -> BaselineLabel:
    """插入一条基线标签；同键生效标签已存在时抛 04 的 `DUPLICATE_LABEL`。

    用 SAVEPOINT 包住插入：唯一索引冲突只回滚这一条，
    不影响同一个事务里前面已写的标签。
    """
    label = BaselineLabel(
        project_id=project_id,
        revision_id=revision_id,
        target_type=target.target_type,
        target_id=target.target_id,
        label_type=target.label_type,
        source_analysis_id=analysis.id,
        confirmed_by=actor.id,
    )
    try:
        with session.begin_nested():
            session.add(label)
            session.flush()
    except IntegrityError as exc:
        if label in session:
            session.expunge(label)
        if exc.orig.args[0] == 1062:
            raise DuplicateLabel(
                f"「{target.target_name}」在同一快照下已有同类型生效标签"
            ) from exc
        raise
    return label


def write_labels(
    session: Session,
    *,
    analysis: IncrementalAnalysis,
    revision_id: int,
    targets: list[LabelableTarget],
    actor: User,
) -> WriteResult:
    """逐条写 ``baseline_labels`` + ``incremental_labels`` 映射。

    - 目标已删除或所属模块已归档 → 跳过并记入 ``skipped_missing``，不报错；
    - 标签带 ``source_analysis_id``，与映射表形成双向可追溯；
    - 不写 ``unchanged``（入参含非变更类直接拒绝，属调用方 bug）。
    """
    result = WriteResult()
    valid = _valid_target_ids(
        session, project_id=analysis.project_id, targets=targets
    )

    written: set[tuple[str, int, str]] = set()
    for target in targets:
        if target.label_type not in APPLIED_LABEL_TYPES:
            raise ValueError(f"产出段不写 {target.label_type} 标签")
        if (target.target_type, target.target_id) not in valid:
            result.skipped_missing.append(target)
            continue
        key = (target.target_type, target.target_id, target.label_type)
        if key in written:
            continue
        written.add(key)

        label = _insert_label(
            session,
            project_id=analysis.project_id,
            revision_id=revision_id,
            target=target,
            analysis=analysis,
            actor=actor,
        )
        session.add(
            IncrementalLabel(
                analysis_id=analysis.id,
                baseline_label_id=label.id,
                revision_id=revision_id,
                target_type=target.target_type,
                target_id=target.target_id,
                label_type=target.label_type,
            )
        )
        session.flush()
        result.labels.append(label)

    return result


__all__ = [
    "CLEAR_REASON",
    "LabelableTarget",
    "WriteResult",
    "clear_previous",
    "collect_labelable",
    "resolve_revision",
    "write_labels",
]
