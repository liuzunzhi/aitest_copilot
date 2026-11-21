"""测试用例生成的服务层（08-test-case-analysis T107）。

**固定校验顺序**（spec §6.2）：

    项目 404 → 归档 409 → 角色 403 → 模板 400 → 批次 404 →
    测试点 400 → 输入为空 400 → 跑模型

校验阶段失败**不建行**：不会留下「没有输入却有一条失败记录」的脏数据。
（这与 05 的「失败留痕」不同，与 07 一致。）

生成过程与 07 同构：

    insert(status='running') → 逐测试点调模型、逐点落库 → 回填 stats/status

**逐点落库**的意义：第 2 个点模型抛错时，第 1 个点已产出的用例不丢，
且不再调用后续测试点（调用次数可断言）。失败时记录 `status='failed'` +
`error_code`，已落库的用例保留（留痕便于排查）。

写库口径：先写 `test_cases` 再 `flush` 拿 id，再批量写 `test_case_steps`；
`step_no` 一律按数组顺序重排为 `1..n`（spec §5.4）。

审计遵循「改数据 → flush → write_audit → commit」，`write_audit` 内部不 commit。
运行留痕的 `calls` **跑前记基线、跑完相减**——`provider.calls` 是累计的。
"""

import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import permissions
from app.common.audit import write_audit
from app.common.errors import (
    AppError,
    LLMCallFailed,
    TestCaseAnalysisHasApproved,
    TestCaseAnalysisNotFound,
    TestCaseInputEmpty,
    TestCaseInvalid,
    TestCaseNotFound,
    TestCasePointNotFound,
    TestCaseReviewStateInvalid,
    TestCaseStepInvalid,
    TestCaseTemplateInvalid,
)
from app.llm import run_log
from app.llm.provider import LLMProvider
from app.models.document import DocumentChapter
from app.models.incremental import PromptTemplate
from app.models.test_case import (
    CASE_PRIORITIES,
    CASE_TYPES,
    TestCase,
    TestCaseAnalysis,
    TestCaseStep,
)
from app.models.test_point import TestPoint
from app.models.user import User

from app.test_cases import engine
from app.test_cases.context import build_case_context
from app.test_cases.fingerprint import derive_needs_review, fingerprint_point
from app.test_cases.schemas import (
    AnalysisCreate,
    CaseCreate,
    CaseUpdate,
    ReviewRequest,
    StepsReplace,
)

# 写接口的动作名——只影响错误文案。
_ACTION = "发起测试用例生成"

TEMPLATE_TASK_TYPE = "test_case"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now() -> datetime:
    """当前 UTC 时间（naive）——导出文件名用它拼日期。"""
    return _now()


def _page(items: list, page: int, page_size: int) -> dict:
    total = len(items)
    start = max(page - 1, 0) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------- 权限


def ensure_readable(session: Session, *, project_id: int, actor: User) -> None:
    """读接口的权限入口（路由调用）。"""
    permissions.ensure_readable(session, project_id=project_id, actor=actor)


# ------------------------------------------------------------ 资源校验


def _load_template(session: Session, template_id: int) -> PromptTemplate:
    """取模板。必须 `task_type='test_case'` 且已启用。"""
    template = session.get(PromptTemplate, template_id)
    if template is None:
        raise TestCaseTemplateInvalid("提示词模板不存在")
    if template.task_type != TEMPLATE_TASK_TYPE:
        raise TestCaseTemplateInvalid("提示词模板类型不是「测试用例生成」")
    if template.status != "active":
        raise TestCaseTemplateInvalid("提示词模板已停用")
    return template


def _load_point_analysis(
    session: Session, *, project_id: int, analysis_id: int
) -> None:
    """校验 07 的测试点生成记录存在且属于本项目（批次筛选依据）。"""
    from app.models.test_point import TestPointAnalysis

    analysis = session.get(TestPointAnalysis, analysis_id)
    if analysis is None or analysis.project_id != project_id:
        raise TestCaseAnalysisNotFound("测试点生成记录不存在")


def _select_points(
    session: Session, *, project_id: int, payload: AnalysisCreate
) -> list[TestPoint]:
    """挑出本次要处理的测试点（**只吃 approved**）。

    - 显式给 `test_point_ids` → **严格**：任一不存在 / 跨项目 / 未评审通过
      都 400，不静默过滤（用户以为测了，其实没测到才是真事故）；
    - 不给 → 按章节 / 目标 / 批次筛 `approved`；都不给 = 全项目。
    """
    if payload.test_point_ids is not None:
        points: list[TestPoint] = []
        for point_id in dict.fromkeys(payload.test_point_ids):
            point = session.get(TestPoint, point_id)
            if point is None or point.project_id != project_id:
                raise TestCasePointNotFound(f"测试点 {point_id} 不存在或不属于该项目")
            if point.status != "approved":
                raise TestCasePointNotFound(f"测试点「{point.name}」未评审通过")
            points.append(point)
        return points

    query = select(TestPoint).where(
        TestPoint.project_id == project_id,
        TestPoint.status == "approved",
    )
    if payload.chapter_ids:
        query = query.where(TestPoint.chapter_id.in_(payload.chapter_ids))
    if payload.target_type is not None and payload.target_id is not None:
        query = query.where(
            TestPoint.target_type == payload.target_type,
            TestPoint.target_id == payload.target_id,
        )
    if payload.test_point_analysis_id is not None:
        query = query.where(TestPoint.analysis_id == payload.test_point_analysis_id)
    return list(session.scalars(query.order_by(TestPoint.id)).all())


def _stats(
    *,
    point_count: int,
    cases: list[TestCase],
    step_count: int,
    discarded: list[dict],
) -> dict:
    return {
        "test_point_count": point_count,
        "case_count": len(cases),
        "step_count": step_count,
        "discarded_count": len(discarded),
        "discarded": discarded,
    }


# ------------------------------------------------------------ 发起生成


def run_analysis(
    session: Session,
    *,
    project_id: int,
    actor: User,
    payload: AnalysisCreate,
    provider: LLMProvider,
) -> TestCaseAnalysis:
    """发起一次用例生成（**同步执行**）。

    校验顺序固定（spec §6.2）：项目 404 → 归档 409 → 角色 403 → 模板 400 →
    批次 404 → 测试点 400 → 输入为空 400 → 跑模型。
    **任何一步失败都不产生生成记录**（校验在建行之前）。
    """
    permissions.ensure_writable_project(session, project_id, action=_ACTION)
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action=_ACTION
    )

    template = _load_template(session, payload.template_id)

    if payload.test_point_analysis_id is not None:
        _load_point_analysis(
            session,
            project_id=project_id,
            analysis_id=payload.test_point_analysis_id,
        )

    points = _select_points(session, project_id=project_id, payload=payload)
    if not points:
        raise TestCaseInputEmpty("没有可用的已评审测试点，无法生成用例")

    analysis = TestCaseAnalysis(
        project_id=project_id,
        template_id=template.id,
        template_version=template.version_no,
        provider=provider.name,
        test_point_analysis_id=payload.test_point_analysis_id,
        chapter_ids=payload.chapter_ids,
        status="running",
        started_at=_now(),
        created_by=actor.id,
    )
    session.add(analysis)
    session.flush()

    write_audit(
        session,
        "test_case.analysis.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_case_analysis",
        target_id=analysis.id,
        after_data={
            "template_id": template.id,
            "template_version": template.version_no,
            "point_count": len(points),
            "test_point_ids": [point.id for point in points],
            "chapter_ids": payload.chapter_ids,
            "test_point_analysis_id": payload.test_point_analysis_id,
            "provider": provider.name,
        },
    )
    session.commit()

    cases: list[TestCase] = []
    discarded: list[dict] = []
    step_count = 0

    def _persist(point: TestPoint, result: engine.CaseAnalysis) -> None:
        """一个测试点跑完立刻落库：后续点失败时这一点的结果不会丢。"""
        nonlocal step_count
        fingerprint = fingerprint_point(point)
        for draft in result.cases:
            case = TestCase(
                project_id=project_id,
                analysis_id=analysis.id,
                test_point_id=point.id,
                test_point_name=point.name,
                title=draft.title,
                case_type=draft.case_type,
                priority=draft.priority,
                precondition=draft.precondition,
                target_type=point.target_type,
                target_id=point.target_id,
                target_name=point.target_name,
                chapter_id=point.chapter_id,
                chapter_title=point.chapter_title,
                status="pending",
                source_type="llm",
                source_point_fingerprint=fingerprint,
                created_by=actor.id,
            )
            session.add(case)
            session.flush()

            rows = [
                TestCaseStep(
                    case_id=case.id,
                    step_no=index,
                    action=action,
                    expected=expected,
                )
                for index, (action, expected) in enumerate(draft.steps, start=1)
            ]
            session.add_all(rows)
            session.flush()

            cases.append(case)
            step_count += len(rows)

        discarded.extend(
            {
                "test_point_id": point.id,
                "test_point_name": point.name,
                "title": item["title"],
                "code": item["code"],
            }
            for item in result.discarded
        )

    # 运行留痕：跑前记调用基线，跑完相减算本次调用了几次。
    calls_before = run_log.call_count(provider)
    started_at = time.monotonic()

    try:
        for point in points:
            chapter = (
                session.get(DocumentChapter, point.chapter_id)
                if point.chapter_id is not None
                else None
            )
            system, user = build_case_context(template, point, chapter)
            result = engine.analyze_point(provider, system, user)
            _persist(point, result)
    except AppError as exc:
        _mark_failed(
            session,
            analysis,
            code=exc.code,
            message=exc.message,
            point_count=len(points),
            cases=cases,
            step_count=step_count,
            discarded=discarded,
        )
        run_log.record_run(
            session,
            task_type="test_case",
            provider=provider,
            calls=run_log.call_count(provider) - calls_before,
            started_at=started_at,
            status="failed",
            error_code=exc.code,
            error_message=exc.message,
            project_id=project_id,
            analysis_id=analysis.id,
            template_id=template.id,
            template_version=template.version_no,
        )
        session.commit()
        raise
    except Exception as exc:  # 内部异常同样立刻失败，不让前端干等
        message = f"测试用例生成失败：{exc}"
        _mark_failed(
            session,
            analysis,
            code=LLMCallFailed.code,
            message=message,
            point_count=len(points),
            cases=cases,
            step_count=step_count,
            discarded=discarded,
        )
        run_log.record_run(
            session,
            task_type="test_case",
            provider=provider,
            calls=run_log.call_count(provider) - calls_before,
            started_at=started_at,
            status="failed",
            error_code=LLMCallFailed.code,
            error_message=message,
            project_id=project_id,
            analysis_id=analysis.id,
            template_id=template.id,
            template_version=template.version_no,
        )
        session.commit()
        raise LLMCallFailed("测试用例生成失败") from exc

    analysis.status = "succeeded"
    analysis.finished_at = _now()
    analysis.stats = _stats(
        point_count=len(points),
        cases=cases,
        step_count=step_count,
        discarded=discarded,
    )
    run_log.record_run(
        session,
        task_type="test_case",
        provider=provider,
        calls=run_log.call_count(provider) - calls_before,
        started_at=started_at,
        status="succeeded",
        project_id=project_id,
        analysis_id=analysis.id,
        template_id=template.id,
        template_version=template.version_no,
    )
    session.flush()
    session.commit()
    return analysis


def _mark_failed(
    session: Session,
    analysis: TestCaseAnalysis,
    *,
    code: str,
    message: str,
    point_count: int,
    cases: list[TestCase],
    step_count: int,
    discarded: list[dict],
) -> None:
    """把生成记录标成失败。**已落库的用例保留**（便于排查）。"""
    analysis.status = "failed"
    analysis.error_code = code
    analysis.error_message = message[:500]
    analysis.finished_at = _now()
    analysis.stats = _stats(
        point_count=point_count,
        cases=cases,
        step_count=step_count,
        discarded=discarded,
    )
    session.flush()


# ------------------------------------------------------------ 查询


def _analysis_item(session: Session, analysis: TestCaseAnalysis) -> dict:
    template = session.get(PromptTemplate, analysis.template_id)
    return {
        "id": analysis.id,
        "project_id": analysis.project_id,
        "template_id": analysis.template_id,
        "template_name": template.name if template else None,
        "template_version": analysis.template_version,
        "provider": analysis.provider,
        "test_point_analysis_id": analysis.test_point_analysis_id,
        "chapter_ids": analysis.chapter_ids,
        "status": analysis.status,
        "error_code": analysis.error_code,
        "error_message": analysis.error_message,
        "stats": analysis.stats,
        "started_at": analysis.started_at,
        "finished_at": analysis.finished_at,
        "created_by": analysis.created_by,
        "created_at": analysis.created_at,
    }


def _case_item(
    session: Session,
    case: TestCase,
    *,
    point: TestPoint | None = None,
    current_fingerprint: str | None = None,
) -> dict:
    """一条用例的展示 dict。

    `needs_review` 是**派生值**：由 `fingerprint.derive_needs_review` 按源测试点的
    当前内容算出来，**不落库**（spec §6.5）。
    """
    steps = list(
        session.scalars(
            select(TestCaseStep)
            .where(TestCaseStep.case_id == case.id)
            .order_by(TestCaseStep.step_no)
        ).all()
    )
    needs_review, reason = derive_needs_review(case, point, current_fingerprint)
    return {
        "id": case.id,
        "project_id": case.project_id,
        "analysis_id": case.analysis_id,
        "test_point_id": case.test_point_id,
        "test_point_name": case.test_point_name,
        "title": case.title,
        "case_type": case.case_type,
        "priority": case.priority,
        "precondition": case.precondition,
        "target_type": case.target_type,
        "target_id": case.target_id,
        "target_name": case.target_name,
        "chapter_id": case.chapter_id,
        "chapter_title": case.chapter_title,
        "status": case.status,
        "reviewed_by": case.reviewed_by,
        "reviewed_at": case.reviewed_at,
        "review_comment": case.review_comment,
        "source_type": case.source_type,
        "needs_review": needs_review,
        "needs_review_reason": reason,
        "needs_review_ack_at": case.needs_review_ack_at,
        "created_by": case.created_by,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "steps": [
            {
                "step_no": step.step_no,
                "action": step.action,
                "expected": step.expected,
            }
            for step in steps
        ],
    }


def _points_by_id(session: Session, cases: list[TestCase]) -> dict[int, TestPoint]:
    """一次 `IN` 查询取回所有源测试点（不在循环里查库）。"""
    ids = {case.test_point_id for case in cases}
    if not ids:
        return {}
    rows = session.scalars(select(TestPoint).where(TestPoint.id.in_(ids))).all()
    return {row.id: row for row in rows}


def _cases_with_review(
    session: Session, cases: list[TestCase]
) -> list[dict]:
    """批量算 `needs_review` 后转成展示 dict。"""
    points = _points_by_id(session, cases)
    return [
        _case_item(
            session,
            case,
            point=points.get(case.test_point_id),
        )
        for case in cases
    ]


def list_analyses(
    session: Session, *, project_id: int, page: int = 1, page_size: int = 50
) -> dict:
    """生成记录列表（新记录在前）。"""
    rows = list(
        session.scalars(
            select(TestCaseAnalysis)
            .where(TestCaseAnalysis.project_id == project_id)
            .order_by(TestCaseAnalysis.id.desc())
        ).all()
    )
    items = [_analysis_item(session, row) for row in rows]
    return _page(items, page, page_size)


def _analysis_cases(session: Session, analysis_id: int) -> list[dict]:
    rows = list(
        session.scalars(
            select(TestCase)
            .where(TestCase.analysis_id == analysis_id)
            .order_by(TestCase.id)
        ).all()
    )
    return _cases_with_review(session, rows)


def get_analysis(session: Session, *, project_id: int, analysis_id: int) -> dict:
    """生成记录详情 + 它产出的用例（含步骤）。"""
    analysis = session.get(TestCaseAnalysis, analysis_id)
    if analysis is None or analysis.project_id != project_id:
        raise TestCaseAnalysisNotFound("生成记录不存在")
    item = _analysis_item(session, analysis)
    item["cases"] = _analysis_cases(session, analysis.id)
    return item


def list_cases(
    session: Session,
    *,
    project_id: int,
    status: str | None = None,
    test_point_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    analysis_id: int | None = None,
    needs_review: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """用例列表（按状态 / 测试点 / 目标 / 批次筛选，新记录在前）。

    `needs_review` 筛选在 **Python 层**做：它是读时派生的值，
    库里没有这一列（spec §6.5）。列表本来就是全量取再分页，
    多一次过滤不改变复杂度。
    """
    query = select(TestCase).where(TestCase.project_id == project_id)
    if status is not None:
        query = query.where(TestCase.status == status)
    if test_point_id is not None:
        query = query.where(TestCase.test_point_id == test_point_id)
    if target_type is not None:
        query = query.where(TestCase.target_type == target_type)
    if target_id is not None:
        query = query.where(TestCase.target_id == target_id)
    if analysis_id is not None:
        query = query.where(TestCase.analysis_id == analysis_id)

    rows = list(session.scalars(query.order_by(TestCase.id.desc())).all())
    items = _cases_with_review(session, rows)
    if needs_review is not None:
        items = [row for row in items if bool(row["needs_review"]) is needs_review]
    return _page(items, page, page_size)


def get_case(session: Session, *, project_id: int, case_id: int) -> dict:
    """用例详情（含步骤）。"""
    case = session.get(TestCase, case_id)
    if case is None or case.project_id != project_id:
        raise TestCaseNotFound("用例不存在")
    point = session.get(TestPoint, case.test_point_id)
    return _case_item(session, case, point=point)


def export_cases(
    session: Session,
    *,
    project_id: int,
    status: str | None = None,
    test_point_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    analysis_id: int | None = None,
) -> list[dict]:
    """导出用的用例列表（复用列表筛选参数，**不分页**）。"""
    query = select(TestCase).where(TestCase.project_id == project_id)
    if status is not None:
        query = query.where(TestCase.status == status)
    if test_point_id is not None:
        query = query.where(TestCase.test_point_id == test_point_id)
    if target_type is not None:
        query = query.where(TestCase.target_type == target_type)
    if target_id is not None:
        query = query.where(TestCase.target_id == target_id)
    if analysis_id is not None:
        query = query.where(TestCase.analysis_id == analysis_id)

    rows = list(session.scalars(query.order_by(TestCase.id.desc())).all())
    return _cases_with_review(session, rows)


# ------------------------------------------------------------ 评审


def review_case(
    session: Session,
    *,
    project_id: int,
    case_id: int,
    actor: User,
    payload: ReviewRequest,
) -> dict:
    """评审一条用例：通过 / 驳回。

    **已评审过的不能重复评审**（409）——评审意见一次定稿，
    反复改会让人搞不清哪条意见是最终结论。
    """
    permissions.ensure_writable_project(session, project_id, action="评审测试用例")
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="评审测试用例"
    )

    if payload.action not in ("approve", "reject"):
        raise TestCaseInvalid("评审动作只能是 approve 或 reject")

    case = session.get(TestCase, case_id)
    if case is None or case.project_id != project_id:
        raise TestCaseNotFound("用例不存在")
    if case.status != "pending":
        raise TestCaseReviewStateInvalid("该用例已评审过，不能重复评审")

    case.status = "approved" if payload.action == "approve" else "rejected"
    case.reviewed_by = actor.id
    case.reviewed_at = _now()
    case.review_comment = payload.comment
    case.updated_at = _now()
    session.flush()

    write_audit(
        session,
        "test_case.review",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_case",
        target_id=case.id,
        before_data={"status": "pending"},
        after_data={
            "status": case.status,
            "action": payload.action,
            # 自审留痕：单人管理员是常态，但要知道这条是不是自己批的。
            "self_approved": case.created_by == actor.id,
        },
        reason=payload.comment,
    )
    session.commit()
    return get_case(session, project_id=project_id, case_id=case_id)


# ------------------------------------------------------------ 手工增删改


def create_case(
    session: Session,
    *,
    project_id: int,
    actor: User,
    payload: CaseCreate,
) -> dict:
    """手工新增一条用例。

    `source_type='manual'`、`analysis_id=NULL`——手工新增没有生成来源。
    挂靠口径与生成不同：**允许挂任意已存在的测试点**（含 pending / rejected），
    人工补录不该被评审状态卡死（spec §6.1）。
    """
    permissions.ensure_writable_project(session, project_id, action="手工新增测试用例")
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="手工新增测试用例"
    )

    title = (payload.title or "").strip()
    if not title:
        raise TestCaseInvalid("用例名称不能为空")
    if payload.case_type not in CASE_TYPES:
        raise TestCaseInvalid("用例类型只能是 functional / api / ui")
    if payload.priority not in CASE_PRIORITIES:
        raise TestCaseInvalid("优先级只能是 high / medium / low")

    point = session.get(TestPoint, payload.test_point_id)
    if point is None or point.project_id != project_id:
        raise TestCasePointNotFound("测试点不存在或不属于该项目")

    steps = _validate_steps([row.model_dump() for row in payload.steps])

    case = TestCase(
        project_id=project_id,
        analysis_id=None,
        test_point_id=point.id,
        test_point_name=point.name,
        title=title[:255],
        case_type=payload.case_type,
        priority=payload.priority,
        precondition=(payload.precondition or "")[:1000],
        target_type=point.target_type,
        target_id=point.target_id,
        target_name=point.target_name,
        chapter_id=point.chapter_id,
        chapter_title=point.chapter_title,
        status="pending",
        source_type="manual",
        source_point_fingerprint=fingerprint_point(point),
        created_by=actor.id,
    )
    session.add(case)
    session.flush()

    session.add_all(
        [
            TestCaseStep(
                case_id=case.id,
                step_no=index,
                action=action,
                expected=expected,
            )
            for index, (action, expected) in enumerate(steps, start=1)
        ]
    )
    session.flush()

    write_audit(
        session,
        "test_case.case.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_case",
        target_id=case.id,
        after_data={
            "title": case.title,
            "case_type": case.case_type,
            "priority": case.priority,
            "test_point_id": point.id,
            "step_count": len(steps),
            "source_type": "manual",
        },
    )
    session.commit()
    return get_case(session, project_id=project_id, case_id=case.id)


def update_case(
    session: Session,
    *,
    project_id: int,
    case_id: int,
    actor: User,
    payload: CaseUpdate,
) -> dict:
    """手工改用例元数据。

    **只接受 4 个字段**：名称 / 类型 / 优先级 / 前置条件。
    状态、来源测试点、步骤都不该在这里改——那会破坏追溯链或评审生命周期。
    """
    permissions.ensure_writable_project(session, project_id, action="修改测试用例")
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="修改测试用例"
    )

    case = session.get(TestCase, case_id)
    if case is None or case.project_id != project_id:
        raise TestCaseNotFound("用例不存在")

    before = {
        "title": case.title,
        "case_type": case.case_type,
        "priority": case.priority,
        "precondition": case.precondition,
    }

    updates = payload.model_dump(exclude_unset=True)
    # `extra="allow"` 留下的多余字段也在 `model_extra` 里——
    # 它们**必须被判 400**，否则用户以为改了状态，其实被悄悄丢掉。
    extras = payload.model_extra or {}
    forbidden = (
        set(updates) - {"title", "case_type", "priority", "precondition"}
    ) | set(extras)
    if forbidden:
        raise TestCaseInvalid(f"这些字段不允许手工修改：{sorted(forbidden)}")

    if "title" in updates and updates["title"] is not None:
        title = updates["title"].strip()
        if not title:
            raise TestCaseInvalid("用例名称不能为空")
        case.title = title[:255]
    if "case_type" in updates and updates["case_type"] is not None:
        if updates["case_type"] not in CASE_TYPES:
            raise TestCaseInvalid("用例类型只能是 functional / api / ui")
        case.case_type = updates["case_type"]
    if "priority" in updates and updates["priority"] is not None:
        if updates["priority"] not in CASE_PRIORITIES:
            raise TestCaseInvalid("优先级只能是 high / medium / low")
        case.priority = updates["priority"]
    if "precondition" in updates and updates["precondition"] is not None:
        case.precondition = updates["precondition"][:1000]

    case.updated_at = _now()
    session.flush()

    write_audit(
        session,
        "test_case.case.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_case",
        target_id=case.id,
        before_data=before,
        after_data={
            "title": case.title,
            "case_type": case.case_type,
            "priority": case.priority,
            "precondition": case.precondition,
        },
    )
    session.commit()
    return get_case(session, project_id=project_id, case_id=case.id)


def delete_case(session: Session, *, project_id: int, case_id: int, actor: User) -> None:
    """删用例（物理删除）。步骤由数据库级 `ON DELETE CASCADE` 清理。"""
    permissions.ensure_writable_project(session, project_id, action="删除测试用例")
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="删除测试用例"
    )

    case = session.get(TestCase, case_id)
    if case is None or case.project_id != project_id:
        raise TestCaseNotFound("用例不存在")

    before = {
        "title": case.title,
        "case_type": case.case_type,
        "priority": case.priority,
        "status": case.status,
        "test_point_id": case.test_point_id,
    }
    session.delete(case)
    session.flush()

    write_audit(
        session,
        "test_case.case.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_case",
        target_id=case_id,
        before_data=before,
    )
    session.commit()


# ------------------------------------------------------------ 步骤覆盖

MAX_STEPS = 100


def _validate_steps(steps: list[dict]) -> list[tuple[str, str]]:
    """校验整组步骤。**不合法就整组拒**（不留半截状态）。"""
    if not steps:
        raise TestCaseStepInvalid("步骤不能为空")
    if len(steps) > MAX_STEPS:
        raise TestCaseStepInvalid(f"步骤不能超过 {MAX_STEPS} 步")

    cleaned: list[tuple[str, str]] = []
    for row in steps:
        action = (row.get("action") or "").strip()
        if not action:
            raise TestCaseStepInvalid("步骤的操作不能为空")
        expected = (row.get("expected") or "").strip()
        cleaned.append((action[:1000], expected[:1000]))
    return cleaned


def replace_steps(
    session: Session,
    *,
    project_id: int,
    case_id: int,
    actor: User,
    payload: StepsReplace,
) -> dict:
    """整体覆盖步骤：旧的全删，新的按数组顺序重排为 1..n。

    **先校验整组再动手**——校验不过时旧步骤原样保留（spec AC-169）。
    """
    permissions.ensure_writable_project(session, project_id, action="修改测试用例步骤")
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="修改测试用例步骤"
    )

    case = session.get(TestCase, case_id)
    if case is None or case.project_id != project_id:
        raise TestCaseNotFound("用例不存在")

    steps = _validate_steps([row.model_dump() for row in payload.steps])

    old_rows = list(
        session.scalars(
            select(TestCaseStep)
            .where(TestCaseStep.case_id == case.id)
            .order_by(TestCaseStep.step_no)
        ).all()
    )
    before_actions = [row.action for row in old_rows]

    for row in old_rows:
        session.delete(row)
    session.flush()

    session.add_all(
        [
            TestCaseStep(
                case_id=case.id,
                step_no=index,
                action=action,
                expected=expected,
            )
            for index, (action, expected) in enumerate(steps, start=1)
        ]
    )
    case.updated_at = _now()
    session.flush()

    write_audit(
        session,
        "test_case.steps.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_case",
        target_id=case.id,
        before_data={"before_count": len(old_rows), "actions": before_actions},
        after_data={"after_count": len(steps)},
    )
    session.commit()
    return get_case(session, project_id=project_id, case_id=case.id)


# ------------------------------------------------------------ 确认已复核


def ack_case(session: Session, *, project_id: int, case_id: int, actor: User) -> dict:
    """确认已复核：把当前源测试点内容刷成新快照。

    - 源测试点存在 → `source_point_fingerprint` 写成当前指纹；
    - 源测试点已删除 → 置 NULL（表示「已知源被删，不再提示」）。

    两种情况都写 `needs_review_ack_at`。
    """
    permissions.ensure_writable_project(session, project_id, action="确认已复核")
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="确认已复核"
    )

    case = session.get(TestCase, case_id)
    if case is None or case.project_id != project_id:
        raise TestCaseNotFound("用例不存在")

    point = session.get(TestPoint, case.test_point_id)
    before = {
        "source_point_fingerprint": case.source_point_fingerprint,
        # 审计列是 JSON 列——datetime 不能直接塞进去。
        "needs_review_ack_at": case.needs_review_ack_at.isoformat()
        if case.needs_review_ack_at is not None
        else None,
    }

    case.source_point_fingerprint = (
        fingerprint_point(point) if point is not None else None
    )
    case.needs_review_ack_at = _now()
    case.updated_at = _now()
    session.flush()

    write_audit(
        session,
        "test_case.case.ack",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_case",
        target_id=case.id,
        before_data=before,
        after_data={
            "source_point_fingerprint": case.source_point_fingerprint,
            # 审计列是 JSON 列——datetime 不能直接塞进去。
            "needs_review_ack_at": case.needs_review_ack_at.isoformat()
            if case.needs_review_ack_at is not None
            else None,
            "source_point_exists": point is not None,
        },
    )
    session.commit()
    return get_case(session, project_id=project_id, case_id=case.id)


# ------------------------------------------------------------ 删生成记录


def delete_analysis(
    session: Session, *, project_id: int, analysis_id: int, actor: User
) -> None:
    """删除一次生成记录，**连带删除它产出的用例与步骤**。

    已有评审通过的用例 → 409：评审通过的用例可能已被下游引用，
    不能因为删一次生成记录就把它带走。
    """
    permissions.ensure_writable_project(
        session, project_id, action="删除测试用例生成记录"
    )
    permissions.ensure_admin(
        session, project_id=project_id, actor=actor, action="删除测试用例生成记录"
    )

    analysis = session.get(TestCaseAnalysis, analysis_id)
    if analysis is None or analysis.project_id != project_id:
        raise TestCaseAnalysisNotFound("生成记录不存在")

    cases = list(
        session.scalars(
            select(TestCase).where(TestCase.analysis_id == analysis.id)
        ).all()
    )
    approved = [row for row in cases if row.status == "approved"]
    if approved:
        raise TestCaseAnalysisHasApproved(
            f"这次生成已产出 {len(approved)} 条评审通过的用例，不允许连带删除"
        )

    for row in cases:
        session.delete(row)
    session.delete(analysis)
    session.flush()

    write_audit(
        session,
        "test_case.analysis.delete",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="test_case_analysis",
        target_id=analysis_id,
        before_data={
            "status": analysis.status,
            "template_id": analysis.template_id,
            "case_count": len(cases),
        },
    )
    session.commit()


__all__ = [
    "MAX_STEPS",
    "TEMPLATE_TASK_TYPE",
    "ack_case",
    "create_case",
    "delete_analysis",
    "delete_case",
    "ensure_readable",
    "export_cases",
    "get_analysis",
    "get_case",
    "list_analyses",
    "list_cases",
    "replace_steps",
    "review_case",
    "run_analysis",
    "update_case",
    "utc_now",
]
