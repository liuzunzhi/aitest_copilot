# 09 · 自动化执行与测试报告 · 任务清单

> 配套 [spec.md](./spec.md)（AC-181 ~ AC-196）与 [plan.md](./plan.md)。
> 执行口径一律以 [specs/验证约定.md](../验证约定.md) 为准，本文件不重复展开。
> 每个任务 = 一个提交，提交信息写清「做了什么 / 为什么」。
> **未明确要求不推送、不打 tag。**

## 0. 前置条件与基线（2026-11-21 核实）

| 项 | 基线 |
|---|---|
| 08 收官 | T105–T110 完成，两库 head `0023` |
| 后端全量 | **1107 passed**（串行，e2e 默认 `-m "not e2e"`） |
| e2e 全量 | **48 passed**（`scripts\run_e2e.py`） |
| 前端 | `npm run build` 通过；项目详情 **9 个 Tab** |
| PRD | 2.4.6 / 2.4.7 已核对：本期取「扫描入库 + 资产 + 关联 + 执行 + 单次报告」子集 |
| 环境自检 | `python scripts\dev_check.py` 全 `[ OK ]`；跑前台加 `--expect-db e2e` |
| 用户拍板 | 跳过流程基线；Playwright 只读不执行；执行限项目管理员；三条安全红线（路径 / 超时 / communicate） |

## 1. 执行约定

1. **开跑前自检**：`.\.venv\Scripts\python.exe scripts\dev_check.py`，
   任一 `[FAIL]` 先修环境再动代码（验证约定 §2 第 0 条）。
2. **定向 → 全量 → e2e → 构建**：
   - 定向：`.\.venv\Scripts\python.exe -m pytest tests\automation -k ac_XXX -q`
   - 全量：`.\.venv\Scripts\python.exe -m pytest`（**串行**；排查偶发失败时不用 `-n auto`）
   - e2e：`.\.venv\Scripts\python.exe scripts\run_e2e.py`（自带自检与收尾）
   - 构建：`cd web; npm run build`
3. **用例命名**：后端 `test_ac_<AC号>_<场景>`，e2e `test_ac_<AC号>_<场景>_ui`，
   与 spec 的 AC 编号一一对应（一条 AC 可有多个场景函数）。
4. **零真实 socket**：本期不引入任何网络客户端。测试不得出现
   `requests` / `urlopen` / `aiohttp` / `socket.socket`。
5. **不改既有期望值**：01–08 的 1107 条一条不删、不改断言。
6. **不回改 04 / 05 / 07 / 08 的判定逻辑**；T111 的枚举修正是**唯一**例外，
   严格限定在「枚举值改名 + 存量数据迁移 + 消除重复定义」，不动任何判定流程。
7. **迁移成对**：每个迁移有可执行 `downgrade`，两库都要做真实往返，不只看 `upgrade`。
8. **前台必须真点**：前端任务结束在浏览器里走一遍，截图落 `.screenshots/<任务号>/`，
   **文件名含 AC 编号**（验证约定 §2 第 4 条）。
9. **文档回填**：T115 补 `验证约定.md` §5.11；T116 补 §1 现状与 `PROGRESS.md`。
10. **执行器安全三线**（每次动 `app/automation/runner.py` 都要自查）：
    强制超时 / 超时 kill / `communic()` 读输出；**禁止** `PIPE` + `stdout.read()`。

## 2. 任务拆分

### T110.5 工作台待办计数（前置任务）

**前置**：`dev_check.py` 全 `[ OK ]`；两库 head `0023`。

**背景**：PRD 2.3.1 要求工作台展示待办；07 / 08 都因「口径统一」延后
（`PROGRESS.md` §6 两处登记）。本期把**测试主链路上的三环**落地：
待审核基线 / 待评审测试点 / 待评审用例。

**产出**

- `app/projects/service.py`：新增 `get_todos(session, project_id)`
  （三个 `COUNT`，各自限定 `project_id`）
- `app/projects/router.py`：新增 `GET /api/projects/{project_id}/todos`
  （权限 = 成员可读，用 `ensure_readable`）
- `app/projects/schemas.py`（或同文件）：`TodosOut` 响应模型
- `web/src/api/index.ts`：`fetchTodos(projectId)` + `Todos` 类型
- `web/src/pages/ProjectDetailPage.tsx`：概览 Tab 加「我的待办」卡片
  （三个数字 + 跳转按钮，跳到基线管理 / 测试点 / 测试用例 Tab）
- 测试：`tests/projects/test_todos.py`（或 `tests/automation/test_todos.py`）

**验证**

- `pytest tests\projects -k ac_193 -q`
- 三项计数与实际造数一致；`total` = 三项之和
- 另一个项目的待评审数据**不计入**本项目（项目隔离）
- 非项目成员 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404
- 归档项目读接口正常 → 200
- 前端：`npm run build` 通过；浏览器看概览 Tab 出现「我的待办」卡片

**前台核对点**：截图 `.screenshots/T110-5/`（文件名含 AC 编号）
项目详情概览 Tab → 「我的待办」卡片显示三个数字 → 点数字跳到对应 Tab。

**AC**：AC-193
**提交**：`feat(projects): 工作台待办计数与概览卡片`

---

### T111 数据层：迁移 `0024` + 模型 + 错误码 + 配置 + 枚举修正

**前置**：T110.5 已提交；`dev_check.py` 全 `[ OK ]`；两库 head `0023`。

**产出**

- `app/models/automation.py`：`AutomationAsset` / `AutomationRun` / `AutomationRunItem`
  （三个类都 `__test__ = False`）；`app/models/__init__.py` 注册
- `migrations/versions/0024_automation.py`：三表 + **枚举修正**
  （`priority_changed` → `baseline_adjusted`、`duplicate_label` → `backtrace_override`；
  `downgrade` 必做反向 UPDATE）
- `app/common/errors.py`：8 个错误类 + `__all__`
- `app/common/config.py`：`automation_root`（默认 `var/automation`）+
  `automation_exec_timeout_seconds`（默认 300）
- **枚举修正**（spec §4.5）：
  - `app/baselines/service.py` 的 `CLEAR_REASONS`：改 2 个值
  - `app/baselines/schemas.py`：改为 `from app.baselines.service import CLEAR_REASONS`
    （**消除重复定义**，只留一个出处）
  - `web/src/api/index.ts` 的 `ClearReason` 类型：改 2 个值
  - `web/src/pages/baselineMeta.ts` 的 `CLEAR_REASON_META`：改 2 个值 + **改中文文案**
    （`baseline_adjusted: '基线已调整'`、`backtrace_override: '回溯覆盖'`）
  - **不动** `CASCADE_CLEAR_REASON='target_deleted'`、不动 `app/incremental/apply.py` 的 `misjudged`
- `app/automation/__init__.py`（空包）
- 测试：`tests/automation/test_models.py` / `test_migration.py` / `test_clear_reason_enum.py`

**验证**

- `pytest tests\automation -k "ac_181 or ac_195" -q`
- `alembic upgrade head` → `current` = `0024`；`downgrade -1` → `upgrade head` 往返（**两库**）
- 降级后 `SELECT DISTINCT clear_reason FROM baseline_labels` **只剩旧值**
- 枚举 = `requirement_done` / `requirement_cancelled` / `misjudged` /
  `baseline_adjusted` / `backtrace_override` / `other`
- `CASCADE_CLEAR_REASON` 与 `apply.CLEAR_REASON` **未变**
- 三表 CHECK：合法值可插、非法值被拒（3819）
- `app/baselines/service.py` 与 `app/baselines/schemas.py` 的 `CLEAR_REASONS` **只有一处定义**
- **既有测试零回归**：`pytest tests\baselines -q` 全绿（既有期望值未用到被改的两个值）

**前台核对点**：本任务只改前端两处常量。等价核对——浏览器打开「基线管理」Tab，
清除标签的下拉里是「基线已调整」「回溯覆盖」（不是「优先级变化」「标签重复」）。

**AC**：AC-181、AC-195（表结构部分）、AC-196（迁移往返部分）
**提交**：`feat(automation): 建表 0024 与清除原因枚举对齐 PRD`

---

### T112 扫描器 + 入库服务

**前置**：T111 已提交；`dev_check.py` 全 `[ OK ]`。

**产出**

- `app/automation/scanner.py`：**纯函数**
  - `resolve_scan_dir(root, directory)` —— `resolve()` + `is_relative_to(root)` 双检
    + **显式拒绝对路径**
  - `scan_dir(root, directory, limit=2000)` —— 遍历 + 规则匹配 + 置信度
  - `SKIP_DIRS` 硬编码常量；单文件只读前 64KB
  - 规则：pytest / playwright 的文件名正则 + 内容正则（spec §5.3）
- `app/automation/service.py`（起步）：
  - `scan_assets(session, actor, project_id, directory)` —— **只返回清单，不写表**
  - `confirm_assets(session, actor, project_id, payload)` —— 入库；
    **服务端重扫重算** `parse_confidence` / `detected_cases`，不采信前端传值；
    同路径已存在 → 跳过（唯一索引 `uk_autoassets_project_path`）
  - `list_assets` / `get_asset` / `update_asset`（关联用例 / 归档）
- `app/automation/schemas.py`、`app/automation/router.py`：
  `POST /scan`、`GET /assets`、`POST /assets`、`GET /assets/{id}`、`PATCH /assets/{id}`
- `app/main.py` 注册 `automation_router`
- 测试：`tests/automation/test_scanner.py` / `test_assets.py`

**验证**

- `pytest tests\automation -k "ac_182 or ac_183 or ac_184 or ac_189 or ac_190" -q`
- 目录越界（`../../etc`、绝对路径）→ 400 `AUTOMATION_SCAN_PATH_INVALID`，**不扫描**
- `sub/../sub2`（解析后仍在 root 内）→ **放行**
- 响应**不含** `AUTOMATION_ROOT` 的绝对路径
- 扫描后 `automation_assets` 行数**不变**（不写表）
- 规则匹配与置信度符合 spec §3.2 的表；`readme.md` 进 `skipped`
- `__pycache__` / `node_modules` / 隐藏文件**不被扫描**
- 文件数超 2000 → 400 `AUTOMATION_SCAN_TOO_LARGE`
- 入库时服务端重算置信度（前端传 0.99 但实际 0.60 → 库里存 0.60）
- 同路径重复入库 → 不新增行，返回 `skipped` 计数
- 再次扫描 → 已入库项 `status='existing'` 且带 `existing_asset_id`
- 关联用例：必须属本项目；解绑可用
- 审计 `automation.asset.create` / `automation.asset.update`；失败不写审计
- 校验顺序：404 → 409 → 403 → 400

**前台核对点**：本任务只有接口。等价核对——`/docs` 走一次扫描，
响应里的清单与置信度与手工看文件一致；`automation_assets` 表**行数不变**。

**AC**：AC-182、AC-183、AC-184、AC-189、AC-190
**提交**：`feat(automation): 资产扫描与人工确认入库`

---

### T113 执行器（subprocess + 三条安全线）

**前置**：T112 已提交；`dev_check.py` 全 `[ OK ]`。

**产出**

- `app/automation/runner.py`：
  - `run_pytest(exe, root, rel_path, timeout)` —— **强制超时** / **超时 kill** /
    **`communic()` 读输出**（`capture_output=True`）；**禁止** `PIPE` + `stdout.read()`；
    `shell=False`（默认）；`TimeoutExpired.stdout` 用 `_safe_text()` 兜底
  - `parse_pytest_summary(output)` —— 正则解析 `passed` / `failed` / `skipped` / `error`
  - `aggregate_result(counts)` —— 资产级结果聚合（有失败 → failed；全跳过 → skipped；否则 passed）
  - `exe` / `timeout` / `cwd` **全部可注入**（测试用 `tmp_path` 造样例）
- 测试：`tests/automation/test_runner.py`

**验证**

- `pytest tests\automation -k "ac_185 or ac_186 or ac_188" -q`
- **超时测试**：样例文件 `time.sleep(999)`，超时配置 2s → 执行**在有限时间内返回**
  （不挂起）；`error` 含「超时」；**断言子进程已被杀死**
- **死锁测试**：样例文件打印 1MB 输出 → 执行**正常返回**，`log` 含输出片段
- 输出解析：`2 failed, 3 passed, 1 skipped` → 各计数正确
- 无法解析的输出 → `stats={'total': None}`，`log` 保留原文（不抛错）
- 聚合规则：有失败 → failed；全跳过 → skipped；否则 passed
- **不执行平台自身的 `tests/` 目录**：测试断言执行路径在 `tmp_path` 内
- 零真实 socket：`grep -r "requests\|urlopen\|aiohttp\|socket.socket" tests\automation` 无结果

**前台核对点**：本任务只有纯执行层，无界面。等价核对——
在 `AUTOMATION_ROOT` 下放一个 `test_demo.py`（含 1 通过 1 失败），
用 `run_pytest` 跑一次，`exit_code=1`、输出被完整读出、不挂起。

**AC**：AC-185、AC-186、AC-188
**提交**：`feat(automation): Pytest 执行器与超时/死锁防护`

---

### T114 服务层 + 执行接口 + 报告

**前置**：T113 已提交；`dev_check.py` 全 `[ OK ]`。

**产出**

- `app/automation/service.py` 追加：
  - `execute_run(session, actor, project_id, asset_ids)`
    —— 校验 → 建 run → **逐资产执行 + 逐资产 commit** → 汇总 → 审计
  - `list_runs` / `get_run_report`
  - `get_run_report` 的追溯链：**一次 `IN` 批量取 `test_cases`**，读快照字段
- `app/automation/router.py` 追加：`POST /runs`、`GET /runs`、`GET /runs/{id}`
- 审计 `automation.run.execute`；`automation.scan` 审计在 T112 补
- 测试：`tests/automation/test_run_flow.py` / `test_permissions.py`

**验证**

- `pytest tests\automation -k "ac_187 or ac_188 or ac_189 or ac_190 or ac_191 or ac_192" -q`
- 选 Playwright 资产 → 400 `AUTOMATION_FRAMEWORK_NOT_EXECUTABLE`，**不产生执行记录**
- `asset_ids` 为空 → 400 `AUTOMATION_RUN_INPUT_EMPTY`
- 归档资产 / 跨项目资产 → 拒绝
- 正常执行：`automation_runs` 一行 + `automation_run_items` 每资产一行
- `exit_code=1` 时 `status='succeeded'`（进程正常跑完）；`error` 非空时 `status='failed'`
- `stats` 按**资产**维度，与明细行数一致
- 报告的 `traceability` 含用例名称 / 测试点 / 目标 / 章节标题
- 关联用例被 08 物理删除后 → 报告**仍可读**，`source_case_deleted=true`，
  且 **08 的删用例接口仍返回 204**（不因 FK 变 500）
- member / guest → 写接口 403 `NOT_PROJECT_ADMIN`；非成员 → 403 `NOT_PROJECT_MEMBER`
- 归档项目 → 写接口 409 `PROJECT_ARCHIVED`，读接口 200
- 审计 `automation.run.execute` 含 `run_id` / `stats`；失败不写审计

**前台核对点**：本任务只有接口。等价核对——`/docs` 触发一次执行，
`GET /runs/{id}` 返回的明细与追溯链字段齐全。

**AC**：AC-187、AC-188、AC-189、AC-190、AC-191、AC-192
**提交**：`feat(automation): 执行编排与单次报告追溯链`

---

### T115 前端「自动化执行」Tab + e2e + 验证约定 §5.11

**前置**：T114 已提交；`dev_check.py --expect-db e2e` 全 `[ OK ]`。

**产出**

- `web/src/pages/ProjectAutomationTab.tsx`（超 400 行按验证约定 §4.3 拆子组件）
- `web/src/pages/AutomationReportDrawer.tsx`
- `web/src/pages/automationMeta.tsx`（框架 / 结果 / 状态文案与颜色）
- `web/src/api/index.ts`（`automation` 8 个方法 + 类型）、`web/src/api/client.ts`（8 个错误码）
- `ProjectDetailPage.tsx` 加第 **10** 个 Tab（插在「测试用例」之后）
- `tests/e2e/test_automation_ui.py`（`test_ac_194_*_ui`，≥ 3 条）、
  `tests/e2e/support.py` 清理列表按外键倒序补三表
- `specs/验证约定.md`：新增 §5.11（09 前台核对点），§1 现状补「10 个 Tab」

**验证**

- `pytest tests\automation -q` 全绿
- `cd web; npm run build` 通过
- `python scripts\run_e2e.py` → **≥ 51 passed**（原 48 + 新增 ≥ 3）

**前台核对点（截图 `.screenshots/T115/`，文件名含 AC 编号）**

| # | AC | 操作 | 期望 |
|---|---|---|---|
| 1 | 194 | 打开项目详情 | 出现「自动化执行」Tab，位于「测试用例」之后 |
| 2 | 183/184 | 扫描 → 勾选 → 确认入库 | 资产表出现新行，置信度与用例数正确 |
| 3 | 184 | 关联用例 | 资产表显示关联的用例名 |
| 4 | 187/188 | 触发执行 | 执行记录新增一行；点开报告 → 明细、统计、追溯链正确 |
| 5 | 187 | 看 Playwright 资产 | 执行按钮**置灰**，提示「Playwright 执行能力待后续期」 |
| 6 | 189 | 成员登录 | 无扫描 / 入库 / 执行按钮；资产与报告可读 |
| 7 | 193 | 概览 Tab | 「我的待办」卡片三个数字，点击可跳转 |

**AC**：AC-194（并回归 AC-193 的前台入口）
**提交**：`feat(web): 自动化执行 Tab、扫描入库与单次报告`

---

### T116 收尾：全量回归 + 迁移往返 + 文档回填

**前置**：T115 已提交；`dev_check.py` 全 `[ OK ]`。

**产出**

- `PROGRESS.md`：§3 冲刺（09 完成）、§4 现状（10 个 Tab、head `0024`、资产 / 执行数）、
  §6 Backlog（执行器管理 / 凭据 / Playwright 执行 / 趋势 / 导出 / 流程基线 等）
- `specs/09-automation/收官总结.md`（交付清单 / AC 矩阵 / 验证结果 / 红线复核 / 踩坑）
- `specs/验证约定.md` §1 现状与 §7 变更记录补一行
- 本文件 §4 验证记录表回填

**验证**

- 全量串行：`.\.venv\Scripts\python.exe -m pytest` → **≥ 1107 passed**，exit 0，只增不减
- 04 / 05 / 06 / 07 / 08 定向：
  `pytest tests\baselines tests\incremental tests\llm tests\test_points tests\test_cases -q` → 0 failed
- e2e：`python scripts\run_e2e.py` → **≥ 51 passed**
- 两库迁移：`current` 均为 `0024`；`0024 → 0023 → 0024` 往返干净
- 降级后 `SELECT DISTINCT clear_reason` 断言只剩旧值（枚举还原彻底）
- `cd web; npm run build` 通过
- 红线复核：`git diff --stat` 确认 `app/test_points/` / `app/incremental/` / `app/test_cases/` /
  `app/llm/` 为空；`app/baselines/` 只有 `service.py`（枚举值 + 导入）与 `schemas.py`（导入）
- 零真实 socket：`grep -r "requests\|urlopen\|aiohttp\|socket.socket" tests\automation` 无结果
- 执行器三线复核：`git diff app/automation/runner.py` 确认有 `timeout=`、
  `capture_output=True`、**无** `stdout.read()`

**前台核对点**：10 个 Tab 逐个点开无报错（概览 / 成员 / 文档 / 版本快照 / 基线管理 / 申请 /
增量分析 / 测试点 / 测试用例 / 自动化执行）；「自动化执行」完整走
扫描 → 入库 → 关联 → 执行 → 报告，截图存 `.screenshots/T116/`。

**AC**：AC-195、AC-196
**提交**：`docs(progress): 09 期自动化执行与测试报告收官`

## 3. AC → 任务 / 用例映射

| AC | 任务 | 测试位置（`test_ac_<号>_*`） |
|---|---|---|
| 181 | T111 | `test_clear_reason_enum.py` / `test_migration.py` |
| 182 / 183 | T112 | `test_scanner.py` |
| 184 | T112 | `test_assets.py` |
| 185 / 186 | T113 | `test_runner.py` |
| 187 / 188 | T113 / T114 | `test_runner.py` / `test_run_flow.py` |
| 189 / 190 | T112 / T114 | `test_permissions.py` |
| 191 | T114 | `test_run_flow.py` |
| 192 | T112 / T114 | `test_assets.py` / `test_run_flow.py` |
| 193 | T110.5 | `test_todos.py` |
| 194 | T115 | `tests/e2e/test_automation_ui.py` |
| 195 / 196 | T111–T116 | 全量套件断言（无真实 socket / 既有测试零改动） |

## 4. 验证记录表（骨架，执行时逐行回填）

| 任务 | 定向 | 后端全量 | 前端构建 | e2e | 迁移往返 | 截图 | 结论 |
|---|---|---|---|---|---|---|---|
| T110.5 | `tests\projects\test_todos.py` **10 passed**（AC-193 全绿） | **1117 passed**（1107 + 10），exit 0，只增不减 | `npm run build` 通过 | e2e **51 passed**（48 + 新增 3） | 不涉及 | 截图 `.screenshots/T110.5/` 3 张，文件名含 AC 编号 | 通过 |
| T111 | `tests\automation` 全绿 | **1117 passed**，exit 0 | `npm run build` 通过 | 不涉及 | 两库 `0024 → 0023 → 0024` 干净，head 均 `0024`；降级后 `clear_reason` 只剩旧值 | 不涉及 | 通过 |
| T112 | `tests\automation` **85 passed**（AC-182/183/184/189/190 全绿） | **1202 passed**（1117 + 85），exit 0，只增不减 | `npm run build` 通过 | 不涉及 | 不涉及 | 不涉及（纯接口） | 通过 |
| T113 | `tests\automation` **110 passed**（85 + 新增 25）；`pytest tests\automation -k "ac_185 or ac_186 or ac_188" -q` **20 passed**（AC-185 4 + AC-186 10 + AC-188 6） | **1227 passed**（1202 + 25），exit 0，只增不减 | `npm run build` 通过 | 不涉及 | 不涉及 | 不涉及（纯执行层） | 通过 |
| T114 | 待回填 | 待回填 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | 待回填 |
| T115 | 待回填 | 待回填 | 待回填 | 待回填 | 不涉及 | `.screenshots/T115/` | 待回填 |
| T116 | 09 定向 + 04~08 定向 | 待回填 | 待回填 | 待回填 | 两库 `0024 → 0023 → 0024` 干净，head 均 `0024` | `.screenshots/T116/` | 待回填 |

**T110.5 补充记录**

- **权限函数选型**：`/todos` 用 `app/common/permissions.py::ensure_readable`
  而不是本文件其它路由的 `require_project_member_or_system_admin`——
  后者对**不存在的项目**也返 403（查成员表查不到就报「不是成员」），
  而待办接口要区分「项目不存在」(404) 与「不是成员」(403)。
- **Tabs 改为受控**：`ProjectDetailPage.tsx` 的 `Tabs` 加 `activeKey` + `onChange`，
  待办数字才能跳到指定 Tab。
- **卡片独立成文件**：`ProjectTodoCard.tsx`（主文件已接近 400 行，按验证约定 §4.3 拆子组件）。
- **成员与访客也可读**：待办是团队共享的工作队列，不是管理员专属。

**T113 补充记录（执行器）**

- **实测踩到的真坑：平台自己的 pytest 配置会漏进被执行的资产**。
  `AUTOMATION_ROOT` 默认在仓库内（`var/automation`），pytest 从工作目录
  **向上**找配置文件，会捡到**平台自己的** `pyproject.toml`
  （`addopts = "-q -m 'not e2e'"`）。后果有两条，**都很隐蔽**：
  ① `-m 'not e2e'` → 资产里标了 `e2e` 的用例被**静默 deselect**
  （少跑用例却装作跑完了，报告里看不出任何异常）；
  ② `-q` 与我们自己的 `-q` 叠成 `-qq` → **pytest 的统计行整个消失**
  （`-qq` 只输出进度点，没有 `N passed`），计数解析必然拿不到数。

  > **这个坑是实测发现的，不是看文档看出来的**：第一版按 spec 写 `-q`，
  > 跑出来 `parse_pytest_summary` 恒为 `{'total': None}`——
  > 用探针脚本逐个 flag 组合试才发现是 `addopts` 泄漏 + `-qq` 的叠加效应。
  > 06 期「Mock 通过 ≠ 真实模型能跑」是同一个教训：**单看文档会漏掉环境交互**。

- **配置隔离按「资产有没有自己的配置」分流**（`_build_command`）：

  | 情况 | 做法 | 效果 |
  |---|---|---|
  | 资产有自己的 pytest 配置 | `-c <资产自己的配置>` | 平台配置进不来，**资产自己的 `addopts` 照常生效** |
  | 资产没有自己的配置 | `-o addopts=` | 平台配置进不来，资产也没有配置可丢 |

  为什么不统一用 `-o addopts=`：它会**连资产自己的 `addopts` 一起清空**
  （资产写 `addopts = -k demo` 之类就失效了）——这条是写用例时
  被自己的断言抓住的（`test_ac_186_asset_keeps_its_own_pytest_config`）。
  为什么不统一用 `-c`：资产没有配置文件时 `-c` 无从指起，平台配置照样被捡到。
  **「有自己配置」那一支不加 `-q`**：资产自己的 `addopts` 里可能已经有 `-q`，
  两个 `-q` 叠成 `-qq` → 统计行又没了。

- **带 `-s`**：pytest 默认把子进程 stdout 截获进自己的临时文件，
  父进程的管道里什么都没有——那样**既测不出死锁**，日志里也只有一行摘要。
  `-s` 让输出真的流进管道。

- **摘要行按「形状」挑**（末尾带 `in <时长>`），不是「含 passed/failed 就算」——
  子进程自己打印的「3 passed」会被误认成统计行，把业务输出算进计数。
  实测样例：子进程打印 `3 passed`、pytest 真实统计 `1 passed` → 取 1。

- **死锁用例做了变异测试**（把实现改成「管道 + `wait()` + `read()`」）：
  被**两条独立断言**抓住——① 90 秒内没返回（`疑似管道死锁`）；
  ② 源码里出现 `stdout.read(`。改回正确实现后**零 diff**。

- **超时即 kill 的两条证据**：① 样例把 PID 写进文件，执行结束后查该 PID
  → 进程已不存在（Windows 走 `OpenProcess` + `GetExitCodeProcess`，
  **不能用 `os.kill(pid, 0)`**——那在 Windows 上会真的去终止进程）；
  ② 样例睡醒后才写 `finished.marker`，文件始终不存在 → 没跑到自然结束。

- **执行器自己再校验一次路径**：上层服务层已校验过资产路径，
  但执行器是**最后一道闸**——它直接决定「哪个文件会被当成代码跑起来」。
  越界 / 绝对路径 → `AutomationScanPathInvalid`（400），**不执行**。

- **`error` 语义**：`error` 非空 = 「跑不起来」（超时 / 启动失败）；
  `error` 为空 = 进程**正常跑完**——退出码 1 是「有测试失败」，
  那是业务结果，不是系统错误（spec §4.2）。

- **前台等价核对**（无界面）：`AUTOMATION_ROOT` 下放 `test_demo.py`
  （1 通过 1 失败）→ `exit_code=1`、`error=None`、输出完整读出
  （440 字符，含 traceback 与统计行）、耗时 2.23s 不挂起、
  统计解析 `{total:2, passed:1, failed:1}`、聚合结果 `failed`。

**基线口径（不可下调）**

- 后端全量：**≥ 1107 passed**，串行，exit 0，数量只增不减
- e2e 全量：**≥ 48 passed**（T115 起 ≥ 51）
- 迁移 head：两库均为 `0024`；`0024 → 0023 → 0024` 干净
- 04 / 05 / 06 / 07 / 08 定向回归：**0 failed**
- 既有 1107 条测试：**零期望值改动**

## 5. 完成定义（DoD）

对齐验证约定 §2 的五条，逐条落到本期：

- [ ] 每个任务开跑前 `dev_check.py` 通过
- [ ] 该任务的 `pytest -k ac_XXX` 通过
- [ ] 全量 pytest 通过，数量 ≥ 1107 且只增不减
- [ ] Playwright 前台核对通过，截图含 AC 编号
- [ ] AC-181 ~ AC-196 全部有测试或前台证据
- [ ] 两库迁移往返干净，head `0024`；降级后枚举还原彻底
- [ ] 红线 diff 复核：上游模块零改动；执行器三线在位
- [ ] `PROGRESS.md`、`验证约定.md`、收官总结已更新
