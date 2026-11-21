"""测试用例分析路由（08-test-case-analysis）。

前缀 `/api/projects/{project_id}/test-cases`：

- `GET    /analyses`             生成记录列表（分页）
- `POST   /analyses`             发起生成（项目管理员，同步执行）
- `GET    /analyses/{id}`        详情（含统计与产出用例）
- `DELETE /analyses/{id}`        删除生成记录（连带删用例）
- `GET    /cases`                用例列表（分页 + 筛选）
- `POST   /cases`                手工新增用例
- `GET    /cases/export`         导出 `.xlsx`（一步一行）
- `GET    /cases/{id}`           用例详情（含步骤）
- `PATCH  /cases/{id}`           改元数据（名称 / 类型 / 优先级 / 前置条件）
- `DELETE /cases/{id}`           删用例（步骤级联删除）
- `PUT    /cases/{id}/steps`     整体覆盖步骤
- `POST   /cases/{id}/review`    评审：通过 / 驳回
- `POST   /cases/{id}/ack`       确认已复核

**`/cases/export` 注册在 `/cases/{case_id}` 之前**——FastAPI 按注册顺序匹配，
写在后面会被路径参数吞掉（`export` 被当 id 解析成 422）。

**权限在服务层判定**（与 04 / 05 / 07 一致）：
「归档先判、角色后判」的顺序只有一个出处——`app/common/permissions.py`。
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import current_user
from app.llm.provider import get_provider
from app.models.user import User

from app.test_cases import exporter, service
from app.test_cases.schemas import (
    AnalysisCreate,
    AnalysisDetailOut,
    AnalysisOut,
    CaseCreate,
    CaseOut,
    CaseUpdate,
    Page,
    ReviewRequest,
    StepsReplace,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/test-cases", tags=["test-cases"]
)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/analyses", response_model=Page[AnalysisOut])
def list_analyses(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[AnalysisOut]:
    """生成记录列表，新记录在前。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_analyses(
        session, project_id=project_id, page=page, page_size=page_size
    )
    return Page[AnalysisOut](
        items=[AnalysisOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/analyses", response_model=AnalysisDetailOut, status_code=201)
def create_analysis(
    project_id: int,
    payload: AnalysisCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
    provider=Depends(get_provider),
) -> AnalysisDetailOut:
    """发起生成。同步跑完后返回，响应直接带上产出的用例与步骤。"""
    analysis = service.run_analysis(
        session,
        project_id=project_id,
        actor=user,
        payload=payload,
        provider=provider,
    )
    return AnalysisDetailOut(
        **service.get_analysis(
            session, project_id=project_id, analysis_id=analysis.id
        )
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetailOut)
def get_analysis(
    project_id: int,
    analysis_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AnalysisDetailOut:
    """生成详情，含 `stats`、丢弃明细与产出的用例。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return AnalysisDetailOut(
        **service.get_analysis(
            session, project_id=project_id, analysis_id=analysis_id
        )
    )


@router.delete("/analyses/{analysis_id}", status_code=204)
def delete_analysis(
    project_id: int,
    analysis_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """删除生成记录（项目管理员）。已有评审通过的用例 → 409。"""
    service.delete_analysis(
        session, project_id=project_id, analysis_id=analysis_id, actor=user
    )
    return Response(status_code=204)


@router.get("/cases", response_model=Page[CaseOut])
def list_cases(
    project_id: int,
    status: str | None = Query(
        default=None, pattern="^(pending|approved|rejected)$"
    ),
    test_point_id: int | None = Query(default=None),
    target_type: str | None = Query(
        default=None, pattern="^(function|feature_point)$"
    ),
    target_id: int | None = Query(default=None),
    analysis_id: int | None = Query(default=None),
    needs_review: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[CaseOut]:
    """用例列表，新记录在前。`needs_review` 是读时派生的筛选条件。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_cases(
        session,
        project_id=project_id,
        status=status,
        test_point_id=test_point_id,
        target_type=target_type,
        target_id=target_id,
        analysis_id=analysis_id,
        needs_review=needs_review,
        page=page,
        page_size=page_size,
    )
    return Page[CaseOut](
        items=[CaseOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/cases", response_model=CaseOut, status_code=201)
def create_case(
    project_id: int,
    payload: CaseCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CaseOut:
    """手工新增用例（项目管理员）。允许挂 pending / rejected 的测试点。"""
    return CaseOut(
        **service.create_case(
            session, project_id=project_id, actor=user, payload=payload
        )
    )


# ↓ 必须注册在 `/cases/{case_id}` 之前：FastAPI 按注册顺序匹配。
@router.get("/cases/export")
def export_cases(
    project_id: int,
    status: str | None = Query(
        default=None, pattern="^(pending|approved|rejected)$"
    ),
    test_point_id: int | None = Query(default=None),
    target_type: str | None = Query(
        default=None, pattern="^(function|feature_point)$"
    ),
    target_id: int | None = Query(default=None),
    analysis_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """导出 `.xlsx`（一步一行）。导出是读操作：不写审计。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    cases = service.export_cases(
        session,
        project_id=project_id,
        status=status,
        test_point_id=test_point_id,
        target_type=target_type,
        target_id=target_id,
        analysis_id=analysis_id,
    )
    content = exporter.export_bytes(cases)
    filename = exporter.filename_for(project_id, service.utc_now())
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case(
    project_id: int,
    case_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CaseOut:
    """用例详情（含步骤与来源追溯字段）。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return CaseOut(
        **service.get_case(session, project_id=project_id, case_id=case_id)
    )


@router.patch("/cases/{case_id}", response_model=CaseOut)
def update_case(
    project_id: int,
    case_id: int,
    payload: CaseUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CaseOut:
    """改用例元数据（项目管理员）。只接受名称 / 类型 / 优先级 / 前置条件。"""
    return CaseOut(
        **service.update_case(
            session,
            project_id=project_id,
            case_id=case_id,
            actor=user,
            payload=payload,
        )
    )


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(
    project_id: int,
    case_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """删用例（项目管理员）。步骤由数据库级联删除。"""
    service.delete_case(
        session, project_id=project_id, case_id=case_id, actor=user
    )
    return Response(status_code=204)


@router.put("/cases/{case_id}/steps", response_model=CaseOut)
def replace_steps(
    project_id: int,
    case_id: int,
    payload: StepsReplace,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CaseOut:
    """整体覆盖步骤（项目管理员）。`step_no` 由服务端按数组顺序重排。"""
    return CaseOut(
        **service.replace_steps(
            session,
            project_id=project_id,
            case_id=case_id,
            actor=user,
            payload=payload,
        )
    )


@router.post("/cases/{case_id}/review", response_model=CaseOut)
def review_case(
    project_id: int,
    case_id: int,
    payload: ReviewRequest,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CaseOut:
    """评审用例（项目管理员）：通过 / 驳回。已评审过的 → 409。"""
    return CaseOut(
        **service.review_case(
            session,
            project_id=project_id,
            case_id=case_id,
            actor=user,
            payload=payload,
        )
    )


@router.post("/cases/{case_id}/ack", response_model=CaseOut)
def ack_case(
    project_id: int,
    case_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CaseOut:
    """确认已复核（项目管理员）：刷新源测试点快照，之后不再提示。"""
    return CaseOut(
        **service.ack_case(
            session, project_id=project_id, case_id=case_id, actor=user
        )
    )
