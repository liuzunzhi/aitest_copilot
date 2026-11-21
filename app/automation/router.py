"""自动化执行路由（09-automation T112）。

前缀 `/api/projects/{project_id}/automation`：

- `POST   /scan`          扫描目录，返回清单 + 置信度 + 统计（**不写表**）
- `GET    /assets`         资产列表（框架 / 状态 / 关联用例 筛选，分页）
- `POST   /assets`         人工确认批量入库（从扫描结果采纳）
- `GET    /assets/{id}`    资产详情
- `PATCH  /assets/{id}`    改关联用例 / 归档 / 刷新用例数

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
