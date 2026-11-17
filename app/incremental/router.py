"""增量分析路由（T69 实现四个接口）。

前缀 `/api/projects/{project_id}/incremental`：

- `GET  /analyses`                         记录列表（分页，可按 status 筛选）
- `POST /analyses`                         发起分析（项目管理员）
- `GET  /analyses/{analysis_id}`           详情（含 stats 与丢弃明细）
- `GET  /analyses/{analysis_id}/conclusions` 局部结论列表（分页）

T68 只注册空路由器，接口在 T69 补齐。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/projects/{project_id}/incremental", tags=["incremental"])

__all__ = ["router"]
