"""自动化资产的服务层（09-automation T112 / T114）。

**固定校验顺序**（与 04 / 05 / 07 / 08 一致）：

    项目 404 → 归档 409 → 角色 403 → 资源/业务校验 400 → 执行

三条核心设计：

1. **扫描只出清单，不写表**。PRD 2.4.6 明确「由人工确认后入库，
   不自动全部导入」——批量新建几十个实体是高风险行为。
   所以 `POST /scan` 不碰 `automation_assets`，入库是另一个动作。
2. **入库时服务端重扫重算**。前端传的值只是「扫描时的快照」，
   文件可能已被改动；更重要的是**不能让前端决定置信度**——
   否则「一个随便写的 0.99」就能进库。
3. **执行限项目管理员**（T114）。执行 pytest = **任意代码执行**，
   风险等级与「发起生成」同级；成员只能**看报告**。
   `status` 表达「系统是否正常完成执行」，
   **退出码 1（用例失败）不是系统错误**——那是业务结果。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import permissions
from app.common.audit import write_audit
from app.common.clock import utcnow_naive
from app.common.config import get_settings
from app.common.errors import (
    AutomationAssetInvalid,
    AutomationAssetNotFound,
    AutomationFrameworkNotExecutable,
    AutomationRunInputEmpty,
    AutomationRunNotFound,
)
from app.models.automation import AutomationAsset, AutomationRun, AutomationRunItem
from app.models.test_case import TestCase
from app.models.user import User

from app.automation import scanner
from app.automation.schemas import AssetCreateItem, AssetPatch, AssetsCreate
from app.automation.runner import (
    aggregate_result,
    first_failure_summary,
    parse_pytest_summary,
    run_pytest,
)

__all__ = [
    "automation_root",
    "confirm_assets",
    "ensure_readable",
    "execute_run",
    "get_asset",
    "get_run_report",
    "list_assets",
    "list_runs",
    "scan_assets",
    "update_asset",
]

# 写接口的动作名——只影响错误文案。
_ACTION_SCAN = "扫描自动化资产"
_ACTION_CONFIRM = "自动化资产入库"
_ACTION_UPDATE = "修改自动化资产"
_ACTION_EXECUTE = "触发自动化执行"

# 日志上限 100KB——超出截断并注明（spec §11）。
LOG_LIMIT_BYTES = 100 * 1024

# 一次执行最多 20 个资产——超出直接拒绝（spec §11）。
# 同步执行跑太久会把 HTTP 请求挂住，超时兜底只保 300s。
MAX_ASSETS_PER_RUN = 20


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


# --------------------------------------------------------------- 执行（T114）


def _truncate_log(text: str) -> str:
    """日志截断到 100KB，并注明「输出已截断」（spec §11）。"""
    if text is None:
        return ""
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= LOG_LIMIT_BYTES:
        return text
    clipped = raw[:LOG_LIMIT_BYTES].decode("utf-8", errors="ignore")
    return clipped + "\n\n... [输出已截断：超过 100KB]"


def _exec_timeout() -> int:
    """单次执行的超时秒数（配置项，默认 300）。"""
    return get_settings().automation_exec_timeout_seconds


def _load_assets_for_run(
    session: Session, project_id: int, asset_ids: list[int]
) -> list[AutomationAsset]:
    """校验并取出待执行的资产。

    校验顺序（spec §7）：**存在 / 属本项目 → 框架可执行 → 状态可用**。
    任何一条不满足都直接拒，**不产生执行记录**。

    - 含 Playwright → `AutomationFrameworkNotExecutable`（400）——
      本期只执行 Pytest（Playwright 需要 node + 浏览器二进制）。
    - 归档资产 → 不可执行（`AutomationAssetInvalid`）。
    """
    rows = list(
        session.scalars(
            select(AutomationAsset).where(AutomationAsset.id.in_(asset_ids))
        ).all()
    )
    by_id = {row.id: row for row in rows}

    assets: list[AutomationAsset] = []
    for asset_id in asset_ids:
        asset = by_id.get(asset_id)
        if asset is None or asset.project_id != project_id:
            raise AutomationAssetNotFound("自动化资产不存在或不属于该项目")
        assets.append(asset)

    if any(asset.framework != "pytest" for asset in assets):
        raise AutomationFrameworkNotExecutable(
            "Playwright 执行能力待后续期，本期只执行 Pytest"
        )
    if any(asset.status != "active" for asset in assets):
        raise AutomationAssetInvalid("归档的自动化资产不可执行")

    return assets


def _cases_by_id(session: Session, assets: list[AutomationAsset]) -> dict[int, TestCase]:
    """一次 `IN` 查询取回所有关联用例（不在循环里查库）。"""
    ids = {asset.linked_case_id for asset in assets if asset.linked_case_id}
    if not ids:
        return {}
    rows = session.scalars(select(TestCase).where(TestCase.id.in_(ids))).all()
    return {row.id: row for row in rows}


def _cases_by_ids(session: Session, case_ids: set[int]) -> dict[int, TestCase]:
    """一次 `IN` 查询取回关联用例，建 `{case_id: 用例}` 映射。

    **防 N+1**：明细行可能有几十条，逐条查库就是几十次往返。
    """
    if not case_ids:
        return {}
    rows = session.scalars(select(TestCase).where(TestCase.id.in_(case_ids))).all()
    return {row.id: row for row in rows}


def _traceability(
    item: AutomationRunItem, case: TestCase | None
) -> dict:
    """一条明细的追溯链。

    字段全部来自 08 已落库的**用例快照**（`test_point_name` / `target_name` /
    `chapter_title`）——**读快照，不联表**，也不受上游删除影响。

    `source_case_deleted` = 关联的用例已被 08 物理删除 →
    此时 `case_title` 仍显示**执行时**的快照值（明细行上落的那份）。
    """
    return {
        "linked_case_id": item.linked_case_id,
        "case_title": item.case_title,
        "test_point_name": case.test_point_name if case else None,
        "target_name": case.target_name if case else None,
        "chapter_title": case.chapter_title if case else None,
        "source_case_deleted": item.linked_case_id is not None and case is None,
    }


def execute_run(
    session: Session, *, project_id: int, actor: User, asset_ids: list[int]
) -> dict:
    """触发一次执行（**同步**跑完）。

    流程：校验 → 建 run → **逐资产执行 + 逐资产 commit** → 汇总 → 审计。

    **逐资产 commit**：某个资产超时/失败不影响后续资产继续跑
    （与 05 的「逐章节落库」同一思路）。

    **`status` 的语义**（spec §4.2）：
    - `succeeded` = pytest 进程**正常跑完**（哪怕退出码是 1——
      那只是「有测试失败」，是业务结果，**不是系统错误**）；
    - `failed` = 跑不起来（超时 / 启动失败），此时 `error` 非空。

    两者靠 `error` 字段区分，**不靠退出码**。
    """
    # 权限：**执行限项目管理员**（执行 pytest = 任意代码执行）。
    _ensure_admin(
        session, project_id=project_id, actor=actor, action=_ACTION_EXECUTE
    )

    ids = [int(value) for value in asset_ids]
    if not ids:
        raise AutomationRunInputEmpty("请选择要执行的自动化资产")
    if len(ids) > MAX_ASSETS_PER_RUN:
        raise AutomationRunInputEmpty(
            f"一次最多执行 {MAX_ASSETS_PER_RUN} 个资产"
        )

    # 校验在建行之前——**任何一步失败都不产生执行记录**。
    assets = _load_assets_for_run(session, project_id, ids)

    root = automation_root()
    timeout = _exec_timeout()

    run = AutomationRun(
        project_id=project_id,
        framework="pytest",
        status="running",
        started_at=utcnow_naive(),
        created_by=actor.id,
    )
    session.add(run)
    session.commit()

    linked_case_ids = {
        asset.linked_case_id for asset in assets if asset.linked_case_id
    }
    cases = _cases_by_ids(session, linked_case_ids)

    item_results: list[dict] = []
    exit_code: int | None = None
    run_error: str | None = None
    logs: list[str] = []

    for asset in assets:
        started = time.monotonic()
        result = run_pytest(sys.executable, root, asset.file_path, timeout=timeout)
        duration_ms = int((time.monotonic() - started) * 1000)

        counts = parse_pytest_summary(result.output)
        # 跑不起来（超时 / 启动失败）→ 该资产判 failed；否则按计数聚合。
        if result.error:
            asset_result = "failed"
            item_error = result.error
        else:
            asset_result = aggregate_result(counts)
            item_error = first_failure_summary(result.output)

        item = AutomationRunItem(
            project_id=project_id,
            run_id=run.id,
            asset_id=asset.id,
            linked_case_id=asset.linked_case_id,
            case_title=(
                cases[asset.linked_case_id].title
                if asset.linked_case_id in cases
                else None
            ),
            result=asset_result,
            error=item_error[:1000] if item_error else None,
            duration_ms=duration_ms,
        )
        session.add(item)
        # 逐资产提交——后面的资产接着跑。
        session.commit()

        item_results.append(
            {
                "asset_id": asset.id,
                "file_path": asset.file_path,
                "framework": asset.framework,
                "result": asset_result,
                "duration_ms": duration_ms,
                "error": item.error,
                "traceability": _traceability(
                    item, cases.get(asset.linked_case_id)
                    if asset.linked_case_id
                    else None
                ),
            }
        )
        logs.append(f"===== {asset.file_path} =====\n{result.output}")
        if exit_code is None:
            exit_code = result.exit_code
        if result.error and run_error is None:
            # 第一个「跑不起来」的原因——它才是系统级错误。
            run_error = result.error

    # 汇总：`stats` 按**资产**维度（与明细行数一致，spec §6.3）。
    stats = {
        "total": len(item_results),
        "passed": sum(1 for row in item_results if row["result"] == "passed"),
        "failed": sum(1 for row in item_results if row["result"] == "failed"),
        "skipped": sum(1 for row in item_results if row["result"] == "skipped"),
    }

    run.status = "failed" if run_error else "succeeded"
    run.exit_code = exit_code
    run.stats = stats
    run.log = _truncate_log("\n".join(logs))
    run.error = run_error[:500] if run_error else None
    run.finished_at = utcnow_naive()
    session.flush()

    write_audit(
        session,
        "automation.run.execute",
        actor_id=actor.id,
        actor_role=actor.global_role,
        project_id=project_id,
        target_type="automation_run",
        target_id=run.id,
        after_data={
            "run_id": run.id,
            "asset_ids": ids,
            "stats": stats,
            "status": run.status,
        },
    )
    session.commit()

    return _run_out(run, item_results)


def _load_run(session: Session, project_id: int, run_id: int) -> AutomationRun:
    """取执行记录。不存在 / 不属于本项目 → 404。"""
    run = session.get(AutomationRun, run_id)
    if run is None or run.project_id != project_id:
        raise AutomationRunNotFound("执行记录不存在")
    return run


def _run_items(session: Session, run_id: int) -> list[AutomationRunItem]:
    """取一次执行的全部明细（按 id 排序，保证顺序稳定）。"""
    return list(
        session.scalars(
            select(AutomationRunItem)
            .where(AutomationRunItem.run_id == run_id)
            .order_by(AutomationRunItem.id)
        ).all()
    )


def _run_duration_ms(run: AutomationRun) -> int | None:
    """本次执行的总耗时（毫秒）。

    从 `started_at` / `finished_at` 算——不另存一列，避免两份口径漂移。
    """
    if run.started_at is None or run.finished_at is None:
        return None
    return int((run.finished_at - run.started_at).total_seconds() * 1000)


def _run_out(
    run: AutomationRun, items: list[dict], *, include_log: bool = False
) -> dict:
    """执行记录的展示 dict（列表与详情共用）。

    `include_log=True` 才带 `log`——列表响应体不带执行输出，
    否则几十条记录能把响应撑爆。
    """
    payload = {
        "id": run.id,
        "project_id": run.project_id,
        "framework": run.framework,
        "status": run.status,
        "exit_code": run.exit_code,
        "stats": run.stats,
        "error": run.error,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_ms": _run_duration_ms(run),
        "created_by": run.created_by,
        "created_at": run.created_at,
        "items": items,
    }
    if include_log:
        payload["log"] = run.log
    return payload


def list_runs(
    session: Session, *, project_id: int, page: int = 1, page_size: int = 50
) -> dict:
    """执行记录列表（新记录在前）。

    列表**不返回明细**——明细只在单次报告里给，避免列表响应体膨胀。
    """
    rows = list(
        session.scalars(
            select(AutomationRun)
            .where(AutomationRun.project_id == project_id)
            .order_by(AutomationRun.id.desc())
        ).all()
    )
    total = len(rows)
    start = max(page - 1, 0) * page_size
    page_rows = rows[start : start + page_size]
    return {
        "items": [_run_out(run, []) for run in page_rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_run_report(session: Session, *, project_id: int, run_id: int) -> dict:
    """单次报告：明细 + 追溯链 + 统计 + 日志。

    **追溯链读快照，不联表**：08 已把 `test_point_name` / `target_name` /
    `chapter_title` 落库在用例行上，报告直接读这些字段，
    **一次 `IN` 查询批量取**（防 N+1），**不受上游删除影响**。
    """
    run = _load_run(session, project_id, run_id)
    items = _run_items(session, run.id)

    asset_ids = [item.asset_id for item in items]
    assets = (
        list(
            session.scalars(
                select(AutomationAsset).where(AutomationAsset.id.in_(asset_ids))
            ).all()
        )
        if asset_ids
        else []
    )
    assets_by_id = {asset.id: asset for asset in assets}

    # 一次 IN 批量取用例快照——**绝不在循环里查库**。
    case_ids = {item.linked_case_id for item in items if item.linked_case_id}
    cases = _cases_by_ids(session, case_ids)

    item_outs: list[dict] = []
    for item in items:
        asset = assets_by_id.get(item.asset_id)
        case = cases.get(item.linked_case_id) if item.linked_case_id else None
        item_outs.append(
            {
                "asset_id": item.asset_id,
                "file_path": asset.file_path if asset else None,
                "framework": asset.framework if asset else None,
                "result": item.result,
                "duration_ms": item.duration_ms,
                "error": item.error,
                "traceability": _traceability(item, case),
            }
        )

    return _run_out(run, item_outs, include_log=True)
