"""自动化资产的服务层（09-automation T112）。

**固定校验顺序**（与 04 / 05 / 07 / 08 一致）：

    项目 404 → 归档 409 → 角色 403 → 资源/业务校验 400 → 执行

两条核心设计：

1. **扫描只出清单，不写表**。PRD 2.4.6 明确「由人工确认后入库，
   不自动全部导入」——批量新建几十个实体是高风险行为。
   所以 `POST /scan` 不碰 `automation_assets`，入库是另一个动作。
2. **入库时服务端重扫重算**。前端传的值只是「扫描时的快照」，
   文件可能已被改动；更重要的是**不能让前端决定置信度**——
   否则「一个随便写的 0.99」就能进库。
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import permissions
from app.common.audit import write_audit
from app.common.config import get_settings
from app.common.errors import (
    AutomationAssetInvalid,
    AutomationAssetNotFound,
)
from app.models.automation import AutomationAsset
from app.models.test_case import TestCase
from app.models.user import User

from app.automation import scanner
from app.automation.schemas import AssetCreateItem, AssetPatch, AssetsCreate

__all__ = [
    "automation_root",
    "confirm_assets",
    "ensure_readable",
    "get_asset",
    "list_assets",
    "scan_assets",
    "update_asset",
]

# 写接口的动作名——只影响错误文案。
_ACTION_SCAN = "扫描自动化资产"
_ACTION_CONFIRM = "自动化资产入库"
_ACTION_UPDATE = "修改自动化资产"


def automation_root() -> Path:
    """`AUTOMATION_ROOT` 解析后的绝对路径。

    配置里写的是**相对项目根**的路径（`var/automation`），
    与既有的 `upload_dir` 同一写法；这里 resolve 一次，
    之后所有路径判定都基于它。
    """
    return Path(get_settings().automation_root).resolve()


def _root_display_name() -> str:
    """根目录的**相对展示名**。

    响应里**绝不返回绝对路径**——绝对路径会泄露服务器目录结构。
    配置值在项目根之内 → 转成相对路径（`var/automation`）；
    在项目根之外 → 只给最后一段目录名。
    """
    configured = Path(get_settings().automation_root)
    project_root = Path(__file__).resolve().parents[2]
    try:
        return configured.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return configured.name or "automation"


def ensure_readable(session: Session, *, project_id: int, actor: User) -> None:
    """读接口的权限入口（路由调用）。"""
    permissions.ensure_readable(session, project_id=project_id, actor=actor)


def _ensure_admin(session: Session, *, project_id: int, actor: User, action: str) -> None:
    """写接口的权限入口：归档先判、角色后判。"""
    permissions.ensure_writable_project(session, project_id, action=action)
    permissions.ensure_admin(session, project_id=project_id, actor=actor, action=action)


# --------------------------------------------------------------- 扫描


def scan_assets(
    session: Session, *, project_id: int, actor: User, directory: str
) -> dict:
    """扫描目录，产出清单。**不写表**。

    校验顺序：项目 404 → 归档 409 → 角色 403 → 路径 400。
    """
    _ensure_admin(
        session, project_id=project_id, actor=actor, action=_ACTION_SCAN
    )

    root = automation_root()
    target = scanner.resolve_scan_dir(root, directory)
    result = scanner.scan_dir(root, target)

    # 已入库的同路径资产 → 标 `existing` + 给出既有 id。
    existing = _existing_assets(
        session, project_id, [item.file_path for item in result.assets]
    )

    assets = []
    for item in result.assets:
        asset = existing.get(item.file_path)
        assets.append(
            {
                "file_path": item.file_path,
                "name": item.name,
                "framework": item.framework,
                "parse_confidence": item.parse_confidence,
                "detected_cases": item.detected_cases,
                "status": "existing" if asset is not None else "new",
                "existing_asset_id": asset.id if asset is not None else None,
                "low_confidence": item.low_confidence,
            }
        )

    write_audit(
        session,
        "automation.scan",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="automation_scan",
        target_id=None,
        after_data={
            "directory": directory,
            "scanned_files": result.scanned_files,
            "matched": result.matched,
            "skipped": result.skipped,
        },
    )
    session.commit()

    return {
        # **相对展示名**，绝不返回绝对路径——绝对路径泄露服务器目录结构。
        "root": _root_display_name(),
        "directory": directory,
        "scanned_files": result.scanned_files,
        "matched": result.matched,
        "skipped": result.skipped,
        "assets": assets,
    }


def _existing_assets(
    session: Session, project_id: int, file_paths: list[str]
) -> dict[str, AutomationAsset]:
    """一次 `IN` 查询取回同项目下这些路径的既有资产，建 `{file_path: 资产}` 映射。"""
    if not file_paths:
        return {}
    rows = session.scalars(
        select(AutomationAsset).where(
            AutomationAsset.project_id == project_id,
            AutomationAsset.file_path.in_(file_paths),
        )
    ).all()
    return {row.file_path: row for row in rows}


# --------------------------------------------------------------- 入库


def confirm_assets(
    session: Session, *, project_id: int, actor: User, payload: AssetsCreate
) -> dict:
    """人工确认后批量入库。

    **服务端重扫重算**：每一条都重新扫描该文件，置信度与识别到的用例数
    都以重扫结果为准，前端传的值仅作对照。

    同路径已存在 → 跳过（唯一索引 `uk_autoassets_project_path`），
    返回 `skipped` 计数，**不新增行**。
    """
    _ensure_admin(
        session, project_id=project_id, actor=actor, action=_ACTION_CONFIRM
    )

    root = automation_root()
    items: list[AssetCreateItem] = list(payload.assets)
    created_items: list[dict] = []
    created_count = 0
    skipped_count = 0

    for item in items:
        relative = (item.file_path or "").strip()
        if not relative:
            raise AutomationAssetInvalid("资产路径不能为空")
        if item.framework not in ("pytest", "playwright"):
            raise AutomationAssetInvalid(
                "资产框架只能是 pytest 或 playwright"
            )

        # 前端显式标 `skip` → 不入库（用户在弹窗里取消勾选）。
        if item.skip:
            skipped_count += 1
            created_items.append(
                {
                    "file_path": relative,
                    "asset_id": None,
                    "skipped": True,
                    "reason": "skipped_by_user",
                }
            )
            continue

        # 重新扫描该文件：**不采信前端传的值**。
        target = _resolve_asset_path(root, relative)
        matched = scanner.match_file(target, relative)
        if matched is None:
            skipped_count += 1
            created_items.append(
                {
                    "file_path": relative,
                    "asset_id": None,
                    "skipped": True,
                    "reason": "unrecognized",
                }
            )
            continue

        existing = session.scalar(
            select(AutomationAsset).where(
                AutomationAsset.project_id == project_id,
                AutomationAsset.file_path == relative,
            )
        )
        if existing is not None:
            skipped_count += 1
            created_items.append(
                {
                    "file_path": relative,
                    "asset_id": existing.id,
                    "skipped": True,
                    "reason": "already_exists",
                }
            )
            continue

        asset = AutomationAsset(
            project_id=project_id,
            name=matched.name[:255],
            file_path=relative,
            framework=matched.framework,
            source="scanned",
            parse_confidence=matched.parse_confidence,
            detected_cases=matched.detected_cases,
            created_by=actor.id,
        )
        session.add(asset)
        session.flush()
        created_count += 1
        created_items.append(
            {
                "file_path": relative,
                "asset_id": asset.id,
                "skipped": False,
                "reason": None,
            }
        )

    write_audit(
        session,
        "automation.asset.create",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="automation_asset",
        target_id=None,
        after_data={
            "created": created_count,
            "skipped": skipped_count,
            "file_paths": [row["file_path"] for row in created_items][:50],
        },
    )
    session.commit()

    return {
        "created": created_count,
        "skipped": skipped_count,
        "items": created_items,
    }


def _resolve_asset_path(root: Path, relative: str) -> Path:
    """把资产相对路径解析成 root 内的绝对路径。

    与 `resolve_scan_dir` 同一套安全判定：越界 / 绝对路径 → 400。
    入库的路径同样不能越界——否则等于往库里塞一个任意路径引用。
    """
    return scanner.resolve_scan_path(root, relative)


# --------------------------------------------------------------- 资产 CRUD


def _asset_item(
    session: Session, asset: AutomationAsset, cases: dict[int, TestCase]
) -> dict:
    """一个资产的展示 dict。"""
    case = cases.get(asset.linked_case_id) if asset.linked_case_id else None
    return {
        "id": asset.id,
        "project_id": asset.project_id,
        "name": asset.name,
        "file_path": asset.file_path,
        "framework": asset.framework,
        "source": asset.source,
        "parse_confidence": float(asset.parse_confidence)
        if asset.parse_confidence is not None
        else None,
        "detected_cases": asset.detected_cases,
        "linked_case_id": asset.linked_case_id,
        "linked_case_title": case.title if case is not None else None,
        "linked_case_deleted": asset.linked_case_id is not None and case is None,
        "status": asset.status,
        "created_by": asset.created_by,
        "created_at": asset.created_at,
    }


def _cases_by_id(session: Session, assets: list[AutomationAsset]) -> dict[int, TestCase]:
    """一次 `IN` 查询取回所有关联用例（不在循环里查库）。"""
    ids = {asset.linked_case_id for asset in assets if asset.linked_case_id}
    if not ids:
        return {}
    rows = session.scalars(select(TestCase).where(TestCase.id.in_(ids))).all()
    return {row.id: row for row in rows}


def list_assets(
    session: Session,
    *,
    project_id: int,
    framework: str | None = None,
    status: str | None = None,
    linked_case_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """资产列表（按框架 / 状态 / 关联用例筛选，稳定的倒序）。"""
    query = select(AutomationAsset).where(AutomationAsset.project_id == project_id)
    if framework is not None:
        query = query.where(AutomationAsset.framework == framework)
    if status is not None:
        query = query.where(AutomationAsset.status == status)
    if linked_case_id is not None:
        query = query.where(AutomationAsset.linked_case_id == linked_case_id)

    rows = list(
        session.scalars(query.order_by(AutomationAsset.id.desc())).all()
    )
    cases = _cases_by_id(session, rows)
    items = [_asset_item(session, row, cases) for row in rows]
    total = len(items)
    start = max(page - 1, 0) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _load_asset(
    session: Session, *, project_id: int, asset_id: int
) -> AutomationAsset:
    """取资产。不存在 / 不属于本项目 → 404。"""
    asset = session.get(AutomationAsset, asset_id)
    if asset is None or asset.project_id != project_id:
        raise AutomationAssetNotFound("自动化资产不存在")
    return asset


def get_asset(session: Session, *, project_id: int, asset_id: int) -> dict:
    """资产详情。"""
    asset = _load_asset(session, project_id=project_id, asset_id=asset_id)
    cases = _cases_by_id(session, [asset])
    return _asset_item(session, asset, cases)


def update_asset(
    session: Session,
    *,
    project_id: int,
    asset_id: int,
    actor: User,
    payload: AssetPatch,
) -> dict:
    """改资产（项目管理员）：关联 / 解绑用例、归档 / 恢复、刷新用例数。

    关联的用例必须**存在且属于本项目**；不要求 approved
    （与 08 手工用例允许挂 pending 测试点同一思路）。
    """
    _ensure_admin(
        session, project_id=project_id, actor=actor, action=_ACTION_UPDATE
    )
    asset = _load_asset(session, project_id=project_id, asset_id=asset_id)

    extra = getattr(payload, "model_extra", None) or {}
    if extra:
        raise AutomationAssetInvalid(
            f"不支持的字段：{'、'.join(sorted(extra))}"
        )

    before = {
        "linked_case_id": asset.linked_case_id,
        "status": asset.status,
        "detected_cases": asset.detected_cases,
    }

    if payload.status is not None and payload.status not in ("active", "archived"):
        raise AutomationAssetInvalid("资产状态只能是 active 或 archived")

    if "linked_case_id" in payload.model_fields_set:
        case_id = payload.linked_case_id
        if case_id is None:
            asset.linked_case_id = None
        else:
            case = session.get(TestCase, case_id)
            if case is None or case.project_id != project_id:
                raise AutomationAssetInvalid("关联的用例不存在或不属于该项目")
            asset.linked_case_id = case.id

    if payload.status is not None:
        asset.status = payload.status

    if payload.detected_cases is not None:
        if payload.detected_cases < 0:
            raise AutomationAssetInvalid("识别到的用例数不能为负数")
        asset.detected_cases = payload.detected_cases

    session.flush()

    write_audit(
        session,
        "automation.asset.update",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="automation_asset",
        target_id=asset.id,
        before_data=before,
        after_data={
            "linked_case_id": asset.linked_case_id,
            "status": asset.status,
            "detected_cases": asset.detected_cases,
        },
    )
    session.commit()

    return get_asset(session, project_id=project_id, asset_id=asset.id)
