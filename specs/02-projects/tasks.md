# 02-projects · 任务清单（tasks）

> 对应 spec：`specs/02-projects/spec.md`（AC-31 ~ AC-48）
> 对应 plan：`specs/02-projects/plan.md`
> 验证约定：`specs/验证约定.md`
> 代码根目录：`D:\aitest_copilot`

## 前置条件

| 项 | 要求 |
|---|---|
| 01-auth | 已完成，迁移到 `0009`，全量 186 passed |
| 解释器 | `.\.venv\Scripts\python.exe`（系统全局 pytest 会被 deepeval 插件打断） |
| MySQL | 容器 `aitest-mysql`，库 `aitest_copilot_v2` |
| Redis | 容器 `aitest-redis`，`127.0.0.1:6380` |
| 前台验证 | 见 `specs/验证约定.md`：前端 `D:\aitest_copilot\web`（`npm run dev` → 5173），Playwright 用例在 `tests/e2e`，默认不随全量 pytest 跑 |

## 执行约定

1. 一个任务 = 一次提交；先实现，再跑该任务用例，再跑全量 pytest，最后 commit。
2. commit message 用中文，说明「为什么」。
3. 完成一个任务就在本文件勾选，并追加 commit 短哈希。
4. 不跨任务夹带改动；发现 spec 未覆盖的问题先停下确认。
5. 每个任务结束跑 `.\.venv\Scripts\python.exe -m pytest` 全量，保持 186 + 新增全绿；并按 `specs/验证约定.md` 做 Playwright 前台核对（前端未就绪时标注「前台待补」）。

---

## Phase 6 · 项目生命周期

- [x] **T28 · 项目简介字段 + 创建项目** — AC-31 ✓ 2026-11-15（df62519）
  - 产出：`migrations/versions/0010_add_project_description.py`、`app/models/project.py`、`app/projects/router.py::create_project`、`app/projects/service.py::create_project`
  - 内容：`projects.description VARCHAR(500) NULL`；`POST /api/projects` 仅 system_admin；名称 / 简介校验；创建人与 `project_members(project_admin)` 同事务；审计 `project.create`；`ProjectOut` 补 `description`
  - 验证：`alembic upgrade head`；`pytest tests/projects/test_projects.py -k "ac_31 or create"`
  - 注意：创建人写成员必须与创建同事务，失败一起回滚

- [x] **T29 · 编辑项目** — AC-32 ✓ 2026-11-15（e7cb272）
  - 产出：`PATCH /api/projects/{pid}`、`service.py::update_project`
  - 内容：project_admin / system_admin；局部更新（未传不改、显式 null 清空简介）；归档项目 409；审计 `project.update`
  - 验证：`pytest tests/projects/test_projects.py -k ac_32`

- [x] **T30 · 归档接口与幂等** — AC-33 ✓ 2026-11-15（6184507，前台已验证 2026-11-15：可申请列表消失）
  - 产出：`POST /api/projects/{pid}/archive`、`service.py::archive_project` 补 `project.archive` 审计
  - 内容：仅 system_admin；已归档直接 200 且不新增审计；复用关闭 pending
  - 验证：`pytest tests/projects/test_archive.py`

- [x] **T31 · 归档项目只读** — AC-34 ✓ 2026-11-15（7575296，前台已验证 2026-11-15）
  - 产出：`service.py::_locked_active_project`（行锁 + 归档判定）
  - 内容：编辑 / 加成员 / 改角色 / 移除成员统一返回 409 `PROJECT_ARCHIVED`；读接口不受影响
  - 验证：`pytest tests/projects/test_projects.py -k ac_34`

## Phase 7 · 成员管理

- [x] **T32 · 成员列表** — AC-35 ✓ 2026-11-15（89db69a，前台已验证 2026-11-15）
  - 产出：`GET /api/projects/{pid}/members`、`common/deps.py::require_project_member_or_system_admin`
  - 内容：成员或系统管理员可读；只返回 user_id / username / role / joined_at
  - 验证：`pytest tests/projects/test_members.py -k ac_35`

- [x] **T33 · 添加成员** — AC-36 ✓ 2026-11-15（e9e1ee5，前台已验证 2026-11-15）
  - 产出：`POST /api/projects/{pid}/members`、`service.py::add_member`
  - 内容：角色白名单；用户不存在 404；重复添加靠 1062 映射 409；审计 `project.member.add`
  - 验证：`pytest tests/projects/test_members.py -k ac_36`（含并发重复添加）

- [x] **T34 · 修改成员角色** — AC-37 ✓ 2026-11-15（e0b012f，前台已验证 2026-11-15）
  - 产出：`PATCH /api/projects/{pid}/members/{uid}`、`service.py::update_member_role`
  - 内容：项目行锁；最后一名 project_admin 不可降级（409）；审计 `project.member.role`
  - 验证：`pytest tests/projects/test_members.py -k ac_37`（含并发降级）

- [x] **T35 · 移除成员** — AC-38 ✓ 2026-11-15（39dc7ca，前台已验证 2026-11-15）
  - 产出：`DELETE /api/projects/{pid}/members/{uid}`、`service.py::remove_member`
  - 内容：不能移除自己；project_admin 不能移除 system_admin 成员；最后一名 project_admin 不可移除；审计 `project.member.remove`
  - 验证：`pytest tests/projects/test_members.py -k ac_38`

- [x] **T36 · 项目概览** — AC-40 ✓ 2026-11-15（ec162c3，前台已验证 2026-11-15）
  - 产出：`GET /api/projects/{pid}/overview`、`service.py::get_overview`
  - 内容：member_count 真实；document_count / baseline_count 为 0、latest_execution 为 null
  - 验证：`pytest tests/projects/test_overview.py`

## Phase 8 · 申请队列与全局记录

- [x] **T37 · 本项目申请列表** — AC-41 ✓ 2026-11-15（192b3a1，前台已验证 2026-11-15）
  - 产出：`GET /api/projects/{pid}/applications`、`projects/query_service.py`
  - 内容：分页；status 筛选；applicant / reviewer 用户名一次 join 取完；审计不需要
  - 验证：`pytest tests/projects/test_application_lists.py -k ac_41`

- [x] **T38 · 我的申请** — AC-42 ✓ 2026-11-15（eced2a8，前台已验证 2026-11-15）
  - 产出：`app/applications/router.py`、`GET /api/applications/mine`
  - 内容：仅本人记录；分页；带 project 名称
  - 验证：`pytest tests/projects/test_application_lists.py -k ac_42`

- [x] **T39 · 全局申请记录** — AC-43 ✓ 2026-11-15（46f7a85，前台已验证 2026-11-15）
  - 产出：`app/admin/applications_router.py`、`GET /api/admin/applications`
  - 内容：system_admin；project_id / status / applicant_id 组合筛选；分页
  - 验证：`pytest tests/projects/test_application_lists.py -k ac_43`

- [x] **T40 · 代审批回归** — AC-44 ✓ 2026-11-15（89a0bf8，前台已验证 2026-11-15）
  - 产出：复用 01 的 approve 接口，不新增代码（必要时只补测试）
  - 内容：系统管理员从全局列表找到申请并审批，状态在全局列表更新
  - 验证：`pytest tests/projects/test_application_lists.py -k ac_44`

## Phase 9 · 全局角色与收尾

- [x] **T41 · 全局角色分配** — AC-45 / 46 ✓ 2026-11-15（532e697，前台已验证 2026-11-15）
  - 产出：`PATCH /api/admin/users/{uid}/role`、`users/router.py::update_role`
  - 内容：仅 system_admin；不能改自己；角色白名单；审计 `user.role.change`；提升 / 降级对原令牌即时生效
  - 验证：`pytest tests/users/test_roles.py`

- [x] **T42 · 访问控制参数化** — AC-47 / 48 ✓ 2026-11-15（04cafdf，前台已验证 2026-11-15）
  - 产出：`tests/projects/test_member_access.py`、`tests/users/test_roles.py` 补充
  - 内容：非成员 / member / guest 跑全部项目内管理接口；普通用户跑全部 `/api/admin/*`
  - 验证：`pytest tests/projects/test_member_access.py tests/users/test_roles.py`

- [x] **T43 · 审计覆盖核对** — AC-39 ✓ 2026-11-15（7126f4e，前台已验证 2026-11-15）
  - 产出：`tests/common/test_audit_coverage.py` 追加 7 个 action
  - 内容：`project.create / project.update / project.archive / project.member.add / project.member.role / project.member.remove / user.role.change`
  - 验证：`pytest tests/common/test_audit_coverage.py`

- [x] **T44 · 全量回归与覆盖率报告** — AC-31 ~ 48 ✓ 2026-11-15（5489255，前台已验证 2026-11-15）
  - 产出：更新 `reports/coverage.md`（313 passed / 99% / 1326 条语句）
  - 内容：跑全量 pytest + coverage；核对 18 条 AC 都有用例；列缺口
  - 验证：`.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing`

---

## AC 覆盖索引

| AC | 任务 | AC | 任务 |
|---|---|---|---|
| 31 创建项目 | T28 | 40 项目概览 | T36 |
| 32 编辑项目 | T29 | 41 本项目申请列表 | T37 |
| 33 归档（删除） | T30 | 42 我的申请 | T38 |
| 34 归档只读 | T31 | 43 全局申请记录 | T39 |
| 35 成员列表 | T32 | 44 代审批 | T40 |
| 36 添加成员 | T33 | 45 全局角色分配 | T41 |
| 37 修改成员角色 | T34 | 46 角色即时生效 | T41 |
| 38 移除成员 | T35 | 47 项目内边界 | T42 |
| 39 审计 | T43 | 48 全局接口边界 | T42 |

## 第一个任务

**T28 · 项目简介字段 + 创建项目（AC-31）**

- 迁移 `0010` 给 `projects` 加 `description`，改 `app/models/project.py`
- 新增 `POST /api/projects`（system_admin），创建人自动成为 `project_admin`
- 现有 `ProjectOut` / `MyProjectOut` 补 `description`
- 测试：`tests/projects/test_projects.py::test_ac_31_*`
