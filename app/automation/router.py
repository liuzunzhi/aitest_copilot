"""自动化执行路由（09-automation T112 / T114）。

前缀 `/api/projects/{project_id}/automation`：

- `POST   /scan`          扫描目录，返回清单 + 置信度 + 统计（**不写表**）
- `GET    /assets`         资产列表（框架 / 状态 / 关联用例 筛选，分页）
- `POST   /assets`         人工确认批量入库（从扫描结果采纳）
- `GET    /assets/{id}`    资产详情
- `PATCH  /assets/{id}`    改关联用例 / 归档 / 刷新用例数
- `POST   /runs`           触发执行（**项目管理员**，同步跑完返回）
- `GET    /runs`           执行记录列表（分页）
- `GET    /runs/{id}`      单次报告（明细 + 追溯链 + 统计 + 日志）

**权限在服务层判定**（与 04 / 05 / 07 / 08 一致）：
「归档先判、角色后判」的顺序只有一个出处——`app/common/permissions.py`。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.deps import current_user
from app.models.user import User

from app.automation import service
from app.automation.schemas import (
    AssetOut,
    AssetPatch,
    AssetsCreate,
    AssetsCreateOut,
    Page,
    RunCreate,
    RunOut,
    RunReportOut,
    ScanOut,
    ScanRequest,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/automation", tags=["automation"]
)


@router.post("/scan", response_model=ScanOut)
def scan(
    project_id: int,
    payload: ScanRequest,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ScanOut:
    """扫描目录。**只出清单，不入库**——入库是另一个动作（人工确认）。"""
    return ScanOut(
        **service.scan_assets(
            session,
            project_id=project_id,
            actor=user,
            directory=payload.directory,
        )
    )


@router.get("/assets", response_model=Page[AssetOut])
def list_assets(
    project_id: int,
    framework: str | None = Query(
        default=None, pattern="^(pytest|playwright)$"
    ),
    status: str | None = Query(default=None, pattern="^(active|archived)$"),
    linked_case_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[AssetOut]:
    """资产列表，新记录在前。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_assets(
        session,
        project_id=project_id,
        framework=framework,
        status=status,
        linked_case_id=linked_case_id,
        page=page,
        page_size=page_size,
    )
    return Page[AssetOut](
        items=[AssetOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/assets", response_model=AssetsCreateOut, status_code=201)
def create_assets(
    project_id: int,
    payload: AssetsCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AssetsCreateOut:
    """人工确认后批量入库。置信度与用例数由服务端重扫重算。"""
    return AssetsCreateOut(
        **service.confirm_assets(
            session, project_id=project_id, actor=user, payload=payload
        )
    )


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(
    project_id: int,
    asset_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AssetOut:
    """资产详情。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return AssetOut(
        **service.get_asset(session, project_id=project_id, asset_id=asset_id)
    )


@router.patch("/assets/{asset_id}", response_model=AssetOut)
def update_asset(
    project_id: int,
    asset_id: int,
    payload: AssetPatch,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AssetOut:
    """改资产（项目管理员）：关联 / 解绑用例、归档 / 恢复。"""
    return AssetOut(
        **service.update_asset(
            session,
            project_id=project_id,
            asset_id=asset_id,
            actor=user,
            payload=payload,
        )
    )


# --------------------------------------------------------------- 执行（T114）


@router.post("/runs", response_model=RunOut)
def create_run(
    project_id: int,
    payload: RunCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RunOut:
    """触发执行（**项目管理员**）。

    同步跑完才返回——执行 pytest = 任意代码执行，风险等级与
    「发起生成」同级，所以限项目管理员（成员只能看报告）。
    """
    return RunOut(
        **service.execute_run(
            session,
            project_id=project_id,
            actor=user,
            asset_ids=payload.asset_ids,
        )
    )


@router.get("/runs", response_model=Page[RunOut])
def list_runs(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page[RunOut]:
    """执行记录列表，新记录在前。列表**不带明细与日志**。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    result = service.list_runs(
        session, project_id=project_id, page=page, page_size=page_size
    )
    return Page[RunOut](
        items=[RunOut(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/runs/{run_id}", response_model=RunReportOut)
def get_run_report(
    project_id: int,
    run_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RunReportOut:
    """单次报告：明细 + 追溯链 + 统计 + 日志。"""
    service.ensure_readable(session, project_id=project_id, actor=user)
    return RunReportOut(
        **service.get_run_report(session, project_id=project_id, run_id=run_id)
    )
