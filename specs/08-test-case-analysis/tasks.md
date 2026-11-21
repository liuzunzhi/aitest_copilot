# 08 · 测试用例分析 · 任务清单

> 配套 [spec.md](./spec.md)（AC-159 ~ AC-180）与 [plan.md](./plan.md)。
> 执行口径一律以 [specs/验证约定.md](../验证约定.md) 为准，本文件不重复展开。
> 每个任务 = 一个提交，提交信息写清「做了什么 / 为什么」。
> **未明确要求不推送、不打 tag。**

## 0. 前置条件与基线（2026-11-20 核实）

| 项 | 基线 |
|---|---|
| 07 收官 | T99–T104 完成，两库 head `0022` |
| 后端全量 | **966 passed**（串行，e2e 默认 `-m "not e2e"`） |
| e2e 全量 | **42 passed**（`scripts\run_e2e.py`） |
| 前端 | `npm run build` 通过；项目详情 8 个 Tab |
| PRD | 2.4.5 已核对：用例 7 字段；「批量导入导出」本期只做导出 |
| 环境自检 | `python scripts\dev_check.py` 全 `[ OK ]`；跑前台加 `--expect-db e2e` |

## 1. 执行约定

1. **开跑前自检**：`.\.venv\Scripts\python.exe scripts\dev_check.py`，
   任一 `[FAIL]` 先修环境再动代码（验证约定 §2 第 0 条）。
2. **定向 → 全量 → e2e → 构建**：
   - 定向：`.\.venv\Scripts\python.exe -m pytest tests\test_cases -k ac_XXX -q`
   - 全量：`.\.venv\Scripts\python.exe -m pytest`（**串行**；排查偶发失败时不用 `-n auto`）
   - e2e：`.\.venv\Scripts\python.exe scripts\run_e2e.py`（自带自检与收尾）
   - 构建：`cd web; npm run build`
3. **用例命名**：后端 `test_ac_<AC号>_<场景>`，e2e `test_ac_<AC号>_<场景>_ui`，
   与 spec 的 AC 编号一一对应（一条 AC 可有多个场景函数）。
4. **零真实 socket**：新测试一律 Mock Provider / `httpx.MockTransport`。
5. **不改既有期望值**：01–07 的 966 条一条不删、不改断言。
6. **不回改 04 / 05 / 07 业务代码**；`app/llm/` 只允许 `mock.py` 加前缀分支。
7. **迁移成对**：每个迁移有可执行 `downgrade`，两库都要做真实往返，不只看 `upgrade`。
8. **前台必须真点**：前端任务结束在浏览器里走一遍，截图落 `.screenshots/<任务号>/`，
   **文件名含 AC 编号**（验证约定 §2 第 4 条）。
9. **文档回填**：T109 补 `验证约定.md` §5.10；T110 补 §1 现状与 `PROGRESS.md`。

## 2. 任务拆分

### T105 数据层：迁移 `0023` + 模型 + 错误码 + 模板播种 + Mock 前缀

**前置**：`dev_check.py` 全 `[ OK ]`；两库 head `0022`。

**产出**

- `app/models/test_case.py`：`TestCaseAnalysis` / `TestCase` / `TestCaseStep`
  （**三个类都要 `__test__ = False`**，07 的 `TestPoint` 已有先例）；
  `app/models/__init__.py` 注册
- `migrations/versions/0023_test_cases.py`：三表 + `llm_run_logs` CHECK 扩 `'test_case'`
  （先 `drop_constraint` 再 `create_check_constraint`）+ 播种 1 条模板
- `app/common/errors.py`：9 个错误类 + `__all__`（继承 `ApiError`，无需再设 `__test__`）
- `app/llm/mock.py`：`[TEST_CASE_SYSTEM]` 分支（默认 1 条 2 步骤用例），既有分支零改动
- `pyproject.toml`：`openpyxl>=3.1`，并实际安装
- `app/test_cases/__init__.py`（空包）
- 测试：`tests/test_cases/test_models.py` / `test_migration.py` / `test_mock_prefix.py`

**验证**

- `python -m pip install -e .` 成功，`import openpyxl` 可用
- `pytest tests\test_cases -k "ac_159 or ac_176" -q`
- `alembic upgrade head` → `current` = `0023`；`downgrade -1` → `upgrade head` 往返（**两库**）
- 直插 `llm_run_logs.task_type='test_case'` 成功、`'bogus'` 报 3819
- `prompt_templates` 中 `task_type='test_case'` 恰好 1 条 active
- 全量 pytest 无 "cannot collect test class" 警告

**前台核对点**：本任务不改前端。等价核对——浏览器打开任一项目详情，
Tab 仍是现有 8 个、无报错（确认没提前动前端、没回归）。

**AC**：AC-159、AC-176（前置）、AC-179（Mock 部分）
**提交**：`feat(test-cases): 建表 0023 与测试用例模型/错误码/模板播种`

---

### T106 上下文与引擎

**前置**：T105 已提交；`dev_check.py` 全 `[ OK ]`。

**产出**

- `app/test_cases/context.py`：`build_case_context()`（模板 → 测试点 → 章节，空章节省略，只截正文）
- `app/test_cases/engine.py`：`analyze_point()` / `normalize_cases()` / `CaseDraft`
- 测试：`tests/test_cases/test_context.py` / `test_engine.py`

**验证**

- `pytest tests\test_cases -k "ac_164 or ac_165 or ac_166 or ac_176" -q`
- 段落顺序断言（模板 → 测试点 → 章节）；空章节 / 章节缺失 → 无 `## 来源章节`
- 超预算 → 前缀完整、仅正文被截
- 丢弃 / 归一张（缺 title、空 steps、非法枚举、重复 title、expected 缺失）
- 坏 JSON → `TestCaseInvalid`；围栏 / think 块 JSON → 正常解析

**前台核对点**：纯函数，无界面。等价核对——T107 的接口返回里
`stats.discarded` 的文案能逐条解释丢弃原因（可直接渲染，不出现异常堆栈）。

**AC**：AC-164、AC-165、AC-166、AC-176
**提交**：`feat(test-cases): Prompt 分段组装与输出校验引擎`

---

### T107 生成链路：服务层 + 路由 + 留痕 + 审计

**前置**：T106 已提交；`dev_check.py` 全 `[ OK ]`。

**产出**

- `app/test_cases/service.py`：`run_analysis` / `list_analyses` / `get_analysis` / `list_cases` / `get_case`
- `app/test_cases/schemas.py`、`app/test_cases/router.py`（生成相关 6 个路由）
- `app/main.py` 注册路由
- 测试：`tests/test_cases/test_generate_flow.py` / `test_run_log.py` / `test_permissions.py`

**验证**

- `pytest tests\test_cases -k "ac_160 or ac_161 or ac_162 or ac_163 or ac_165 or ac_173 or ac_174 or ac_175" -q`
- 只取 approved（Mock 调用次数 = approved 条数）
- 显式 ids 含非 approved / 非本项目 / 不存在 → 400 `TEST_CASE_POINT_NOT_FOUND`
- 0 条可用 → 400 `TEST_CASE_INPUT_EMPTY` 且**无生成记录**
- 逐点落库：3 个点 → 3 组用例可分别查到
- 模型中途抛错 → `failed` + `error_code`，不再调后续点（断言调用次数）
- `llm_run_logs.call_count` 两次连跑均为单次值（跑前记基线、跑完相减）
- 审计 `test_case.analysis.create`；失败不写审计
- 校验顺序：404 → 409 → 403 → 400

**前台核对点**：本任务只有接口。等价核对——浏览器打开 `/docs` 发起一次生成，
响应含 `analysis.stats` 与带步骤的用例；同时确认「测试点」Tab 等既有 8 个 Tab 无回归。

**AC**：AC-160、AC-161、AC-162、AC-163、AC-173、AC-174、AC-175
**提交**：`feat(test-cases): 基于已评审测试点生成用例的服务与接口`

---

### T108 评审 / 手工 CRUD / 步骤 / 待复核 / 导出

**前置**：T107 已提交；`dev_check.py` 全 `[ OK ]`。

**产出**

- `service.py` 追加：`review_case` / `create_case` / `update_case` / `delete_case` /
  `replace_steps` / `ack_case` / `delete_analysis` / `derive_needs_review`
- `app/test_cases/fingerprint.py`：源测试点内容指纹（唯一字段清单）
- `router.py` 追加 7 个路由（`/cases/export` **注册在** `/cases/{case_id}` **之前**）
- `app/test_cases/exporter.py`、`app/test_cases/labels.py`
- 测试：`test_manual_and_review.py` / `test_needs_review.py` / `test_export.py`

**验证**

- `pytest tests\test_cases -k "ac_167 or ac_168 or ac_169 or ac_170 or ac_171 or ac_172 or ac_177" -q`
- 评审：通过 / 驳回 / 重复评审 409 / 审计含 `self_approved`
- 手工新增：`source_type='manual'`、`analysis_id=NULL`、快照字段齐全；允许挂非 approved 测试点
- `PATCH` 只允许 4 字段；传 `status` / `test_point_id` → 400
- 删除用例 → 步骤级联消失
- `PUT /steps`：覆盖成功；空数组 / action 空 / >100 步 → 400 且**原步骤不变**
- 删生成记录：有 approved → 409；否则连带删用例与步骤
- 改测试点任一字段（`_FIELDS` 逐字段）→ `needs_review=true` + 原因；改 `updated_at` → **不触发**
- 删测试点 → **07 的删除接口仍成功、不 500**；用例内容不变，原因为 `source_point_deleted`
- `ack` 后消失；再改重现；源已删除时 `ack` → 指纹置 NULL、不再提示
- 导出：3 步骤 → 3 行；列名与中文状态正确；筛选生效；member 200

**前台核对点**：本任务只有接口。等价核对——`/docs` 走「评审 → 改步骤 → 确认复核」，
并用 Excel 打开 `/cases/export` 的产物确认表头与行数（界面操作在 T109 验）。

**AC**：AC-167 ~ AC-172、AC-177
**提交**：`feat(test-cases): 用例评审、手工维护、步骤覆盖与导出`

---

### T109 前端「测试用例」Tab + e2e + 验证约定 §5.10

**前置**：T108 已提交；`dev_check.py --expect-db e2e` 全 `[ OK ]`。

**产出**

- `web/src/pages/ProjectTestCasesTab.tsx`（超 400 行按验证约定 §4.3 拆子组件）
- `web/src/pages/TestCaseDrawer.tsx` / `TestCaseStepsEditor.tsx` / `testCaseMeta.tsx`
- `web/src/api/index.ts`（`testCases` 13 个方法）、`web/src/api/client.ts`（9 个错误码）
- `ProjectDetailPage.tsx` 加第 9 个 Tab
- `tests/e2e/test_test_cases_ui.py`（`test_ac_178_*_ui`，≥ 3 条）、
  `tests/e2e/support.py` 清理列表按外键倒序补三表
- `specs/验证约定.md`：新增 §5.10（08 前台核对点），§1 现状补「9 个 Tab」

**验证**

- `pytest tests\test_cases -q` 全绿
- `cd web; npm run build` 通过
- `python scripts\run_e2e.py` → **≥ 45 passed**（原 42 + 新增 ≥ 3）

**前台核对点（截图 `.screenshots/T109/`，文件名含 AC 编号）**

| # | AC | 操作 | 期望 |
|---|---|---|---|
| 1 | 178 | 打开项目详情 | 出现「测试用例」Tab，位于「测试点」之后 |
| 2 | 178 | 发起生成（默认模板） | 记录变「已成功」，统计显示 1 条用例 / 2 个步骤 |
| 3 | 178 | 点开用例详情 | 步骤表 2 行；来源显示测试点与目标 |
| 4 | 178 | 评审通过 | 列表状态变「已通过」，评审入口消失 |
| 5 | 178 | 手工新增 + 编辑步骤 | 详情步骤表与编辑结果一致 |
| 6 | 171 | 改源测试点后刷新 | 出现「待复核」标签；「确认已复核」后消失 |
| 7 | 177 | 点导出 | 下载 `.xlsx`，Excel 首行表头正确 |
| 8 | 178 | 访客登录 | 只读可见，无生成 / 评审 / 编辑按钮 |

**AC**：AC-178（并回归 AC-171 / 177 的前台入口）
**提交**：`feat(web): 测试用例 Tab、详情抽屉与 Excel 导出`

---

### T110 收尾：全量回归 + 迁移往返 + 文档回填

**前置**：T109 已提交；`dev_check.py` 全 `[ OK ]`。

**产出**

- `PROGRESS.md`：§3 冲刺（08 完成）、§4 现状（9 个 Tab、head `0023`、用例数）、
  §6 Backlog（Excel 导入 / 工作台待评审计数 / 用例版本历史 / 编号流水 / Skill 模式）
- `specs/08-test-case-analysis/收官总结.md`（交付清单 / AC 矩阵 / 验证结果 / 红线复核 / 踩坑）
- `specs/验证约定.md` §1 现状与 §7 变更记录补一行
- 本文件 §4 验证记录表回填

**验证**

- 全量串行：`.\.venv\Scripts\python.exe -m pytest` → **≥ 966 passed**，exit 0，只增不减
- 04 / 05 / 06 / 07 定向：`pytest tests\baselines tests\incremental tests\llm tests\test_points -q` → 0 failed
  （基线 115 / 154 / 174 / 既有测试点数）
- e2e：`python scripts\run_e2e.py` → **≥ 45 passed**
- 两库迁移：`current` 均为 `0023`；`0023 → 0022 → 0023` 往返干净
- `cd web; npm run build` 通过
- 红线复核：`git diff --stat` 确认 `app/test_points/` / `app/baselines/` / `app/incremental/` 为空，
  `app/llm/` 只有 `mock.py`
- 零真实 socket：`grep -r "requests\|urlopen\|aiohttp\|socket.socket" tests\test_cases` 无结果

**前台核对点**：9 个 Tab 逐个点开无报错（概览 / 成员 / 文档 / 版本快照 / 基线管理 / 申请 /
增量分析 / 测试点 / 测试用例）；「测试用例」完整走生成 → 评审 → 编辑 → 待复核 → 导出，
截图存 `.screenshots/T110/`。

**AC**：AC-179、AC-180
**提交**：`docs(progress): 08 期测试用例分析收官`

## 3. AC → 任务 / 用例映射

| AC | 任务 | 测试位置（`test_ac_<号>_*`） |
|---|---|---|
| 159 | T105 | `test_migration.py` |
| 160 / 161 / 162 / 163 | T107 | `test_generate_flow.py` |
| 164 / 165 / 166 | T106 | `test_engine.py` |
| 167 | T108 | `test_manual_and_review.py` |
| 168 / 169 / 170 | T108 | `test_manual_and_review.py` |
| 171 / 172 | T108 | `test_needs_review.py` |
| 173 / 174 | T107 / T108 | `test_permissions.py` |
| 175 | T107 | `test_run_log.py` |
| 176 | T105 / T106 | `test_mock_prefix.py` / `test_context.py` |
| 177 | T108 | `test_export.py` |
| 178 | T109 | `tests/e2e/test_test_cases_ui.py` |
| 179 / 180 | T105–T110 | 全量套件断言（无真实 socket / 既有测试零改动） |

## 4. 验证记录表（骨架，执行时逐行回填）

| 任务 | 定向 | 后端全量 | 前端构建 | e2e | 迁移往返 | 截图 | 结论 |
|---|---|---|---|---|---|---|---|
| T105 | `tests\test_cases` 29 passed | **995 passed**（966 + 29），exit 0；04/05/06/07 定向 544 passed / 0 failed | 不涉及 | 不涉及 | 两库 `0023 → 0022 → 0023` 干净，head `0023` | 不涉及（`web/` 零改动） | 通过 |
| T106 | `tests\test_cases` 63 passed（AC-164/165/166/176 全绿） | **1029 passed**（995 + 34），exit 0 | 不涉及 | 不涉及 | 不涉及 | 不涉及（纯函数） | 通过 |
| T107 | `tests\test_cases` 87 passed（AC-160/161/162/163/165/166/173/174/175/176 全绿） | **1053 passed**（1029 + 24），exit 0 | 不涉及 | OpenAPI 4 条路径 / 6 个操作 | 不涉及 | 不涉及 | 通过 |
| T108 | `tests\test_cases` 141 passed（AC-167~172 / AC-177 全绿） | **1107 passed**（1053 + 54），exit 0 | 不涉及 | OpenAPI 8 条路径 / 13 个操作 | 不涉及 | 不涉及 | 通过 |
| T109 | `tests\test_cases` 141 passed（不变） | **1107 passed**（1053 + 54），exit 0 | `npm run build` 通过 | e2e **46 passed**（42 + 新增 4） | 不涉及 | 截图 `.screenshots/T109/` 8 张，文件名含 AC 编号 | 通过 |
| T110 | 08 定向 **141 passed**；04/05/06/07 定向 **544 passed** 零回归 | **1107 passed**（串行，exit 0，只增不减） | `npm run build` 通过 | e2e **48 passed**（46 + Tab 核对 2；连跑全绿） | 两库 `0023 → 0022 → 0023` 干净，head 均 `0023` | 截图 `.screenshots/T109/` 8 张 + `.screenshots/T110/` 2 张（9 个 Tab 逐个点开） | 通过 |

**基线口径（不可下调）**

- 后端全量：**≥ 966 passed**，串行，exit 0，数量只增不减
- e2e 全量：**≥ 42 passed**（T109 起 ≥ 45）
- 迁移 head：两库均为 `0023`；`0023 → 0022 → 0023` 干净
- 04 / 05 / 06 / 07 定向回归：**0 failed**

## 5. 完成定义（DoD）

对齐验证约定 §2 的五条，逐条落到本期：

- [x] 每个任务开跑前 `dev_check.py` 通过
- [x] 该任务的 `pytest -k ac_XXX` 通过
- [x] 全量 pytest 通过，数量 ≥ 966 且只增不减 —— 实测 **1107 passed**
- [x] Playwright 前台核对通过，截图 `.screenshots/T109/`（8 张）、`T110/`（2 张）含 AC 编号
- [x] AC-159 ~ AC-180 全部有测试或前台证据
- [x] 两库迁移往返干净，head `0023`
- [x] 红线 diff 复核为空（实测仅 `app/llm/mock.py` +29/-4）
- [x] `PROGRESS.md`、`验证约定.md`、收官总结已更新
