# 10 · 流程基线 · 任务清单

> 配套 [spec.md](./spec.md)（AC-197 ~ AC-214）与 [plan.md](./plan.md)。
> 执行口径一律以 [specs/验证约定.md](../验证约定.md) 为准，本文件不重复展开。
> 每个任务 = 一个提交，提交信息写清「做了什么 / 为什么」。
> **未明确要求不推送、不打 tag。**

## 0. 前置条件与基线（2026-11-22 核实）

| 项 | 基线 |
|---|---|
| 09 收官 | T110.5–T116 完成，两库 head `0024` |
| 后端全量 | **1259 passed**（串行，e2e 默认 `-m "not e2e"`） |
| e2e 全量 | **58 passed**（`scripts\run_e2e.py`） |
| 前端 | `npm run build` 通过；项目详情 **10 个 Tab**；基线管理 Tab 内**纵向堆叠、无子 Tab** |
| 迁移 head | 两库均 `0024` |
| PRD | 2.4.2「流程基线」（`:442-445`）+「通用能力」（`:447-464`）已核对；本期取「场景 + 步骤 + 关联 + 反推 + 审核快照」子集 |
| 环境自检 | `python scripts\dev_check.py` 全 `[ OK ]`；跑前台加 `--expect-db e2e` |
| 用户拍板 | ① 独立建表 ② 标签不做 ③ 保留策略 / 被引用即保护不做 ④ 关联单向 + 关联表 + 不建 FK + 名称快照 ⑤ 提交时冻结 ⑥ 基线管理内二级 Tabs |
| AC 编号 | **AC-197 ~ AC-214**（09 期最后一号是 AC-196，必须连续） |
| 任务号 | **T117 ~ T123**（09 期收尾是 T116） |
| 迁移号 | **`0025`**（`down_revision = "0024"`） |

## 1. 执行约定

1. **开跑前自检**：`.\.venv\Scripts\python.exe scripts\dev_check.py`，
   任一 `[FAIL]` 先修环境再动代码（验证约定 §2 第 0 条）。
2. **定向 → 全量 → e2e → 构建**：
   - 定向：`.\.venv\Scripts\python.exe -m pytest tests\process_baselines -k ac_XXX -q`
   - 全量：`.\.venv\Scripts\python.exe -m pytest`（**串行**；排查偶发失败时不用 `-n auto`）
   - e2e：`.\.venv\Scripts\python.exe scripts\run_e2e.py`（自带自检与收尾）
   - 构建：`cd web; npm run build`
3. **用例命名**：后端 `test_ac_<AC号>_<场景>`，e2e `test_ac_<AC号>_<场景>_ui`，
   与 spec 的 AC 编号一一对应（一条 AC 可有多个场景函数）。
4. **零真实 socket**：本期不引入任何网络客户端。测试不得出现
   `requests` / `urlopen` / `aiohttp` / `socket.socket`。
5. **不改既有期望值**：01–09 的 1259 条一条不删、不改断言。
6. **不回改 04 / 05 / 07 / 08 / 09 的判定逻辑**；本期对上游目录**零改动**，
   **仅两处例外**（spec §11 已声明）：① `app/llm/mock.py` 加一个前缀分支
   （既有五个分支行为一个字节不变，用 `git diff --stat` 实测）；
   ② `app/models/incremental.py` 的 `prompt_templates.task_type` CHECK 扩
   `'process_baseline'`（`TASK_TYPES` 与 `ck_ptemplates_task_type` 各一行）。
7. **迁移成对**：每个迁移有可执行 `downgrade`，两库都要做真实往返，不只看 `upgrade`。
8. **前台必须真点**：前端任务结束在浏览器里走一遍，截图落 `.screenshots/<任务号>/`，
   **文件名含 AC 编号**（验证约定 §2 第 4 条）。
9. **文档回填**：T122 补 `验证约定.md` §5.13；T123 补 §1 现状与 `PROGRESS.md`。
10. **审核期锁定的实现位置**：锁定检查（`ProcessBaselineInReview`）必须放在
    **服务层的每个写入口**（`update_scenario` / `delete_scenario` /
    `replace_steps` / `replace_links`），**不要只在前端禁用按钮**——
    前端禁用是体验，端 409 才是保证。
11. **全量 pytest 不能用 `-o addopts=`**：平台 `addopts` 含 `-m 'not e2e'`，
    覆盖掉会把 58 条 e2e 收进来 → 58 个 error（它们要连 8001 端口）。
    **要看用例数用 `-m "not e2e"`**，别动 `addopts`。
    （这是 09 期 T114 实测踩到的坑。）

## 2. 任务拆分

### T117 数据层：迁移 `0025` + 4 个模型 + 8 个错误码 + 模板 CHECK 扩枚举

**前置**：`dev_check.py` 全 `[ OK ]`；两库 head `0024`。

**背景**：流程基线要独立建表（spec §3.1），且提示词模板要有一个自己的
`task_type`——否则 04 的推导下拉会混进流程基线模板，选错不报错、静默产出错误结构
（spec §11「为什么第 2 处不能省」）。本期对上游的改动**只有两处**，
本任务落其中一处（`app/models/incremental.py`）与 Mock 前缀分支。

**产出**

- `app/models/process_baseline.py`：`ProcessBaseline` / `ProcessBaselineStep` /
  `ProcessBaselineLink` / `ProcessBaselineRevision`（四个类都 `__test__ = False`）；
  `app/models/__init__.py` 注册（import + `__all__`）
- `migrations/versions/0025_process_baselines.py`：四表 + `prompt_templates`
  的 CHECK 扩枚举 + 播种模板（spec §4.5 的 upgrade / downgrade 顺序）
- `app/common/errors.py`：8 个错误类 + `__all__`
  （`ProcessBaselineNotFound` / `Invalid` / `DuplicateName` / `StepInvalid` /
  `LinkInvalid` / `RevisionNotFound` / `ReviewStatusInvalid` / `InReview`）
- `app/models/incremental.py`：`TASK_TYPES` 与 `ck_ptemplates_task_type`
  各加一个 `'process_baseline'`（**只加这一处**，`llm_run_logs` 的 CHECK 不动）
- `app/llm/mock.py`：新增 `PROCESS_BASELINE_SYSTEM_PREFIX = "[PROCESS_BASELINE_SYSTEM]"`
  与 `PROCESS_BASELINE_DEFAULT_RESPONSE`（一个最小场景：1 个场景 / 2 个步骤 / 0 个关联）
  + 一个 `startswith` 分支；**既有五个分支一个字节不改**
- `app/process_baselines/__init__.py`（空包）
- 测试：`tests/process_baselines/test_models.py` / `test_migration.py`

**验证**

- `pytest tests\process_baselines -k "ac_197 or ac_210 or ac_211" -q`
- `alembic upgrade head` → `current` = `0025`；`downgrade -1` → `upgrade head`
  往返（**两库**都跑）
- 四表 CHECK：合法值可插、非法值被拒（**3819**）
- `uk_pbaselines_project_name` / `uk_pbsteps_baseline_no` /
  `uk_pblinks_baseline_target` / `uk_pbrevisions_project_no` 全部生效
- `prompt_templates` 里 `task_type='process_baseline'` 的模板**有且只有一条 active**
- **降级后** `SELECT DISTINCT task_type FROM prompt_templates` 只剩旧的四个值
  （`downgrade` 必须先删模板行再重建旧 CHECK）
- **两套版本号互不干扰**：同项目里功能基线发 `v1.0` 后，流程基线仍发 `v1.0`
- `git diff --stat app\llm\mock.py` → 只增一个分支，**既有五个分支的返回值逐字节不变**
- `git diff --stat app\models\incremental.py` → **只有 2 处**：
  `TASK_TYPES` 常量 + `ck_ptemplates_task_type` 的 CHECK 字符串（各一处，不含注释）
- **既有测试零回归**：`pytest tests\baselines tests\llm tests\incremental -q` 全绿
  （既有期望值未用到新枚举值）

**前台核对点**：本任务只改后端与两处前端无关的常量。等价核对——
浏览器打开「系统设置」页 → 提示词模板面板，**多出一条** `task_type='process_baseline'`
的模板「流程基线推导·场景抽取」，且**编辑它**不影响其它类型的模板。

**AC**：AC-197、AC-210、AC-211、AC-214
**提交**：`feat(process-baseline): 建表 0025 与流程基线提示词模板`

**T117 补充记录（执行情况）**

- **迁移往返（两库各跑一遍）**：开发库 `aitest_copilot_v2` 与 e2e 库
  `aitest_copilot_e2e` 均 `0024 → 0025 → 0024 → 0025` 干净，head 均 `0025`。
- **降级后逐字节核对**：`prompt_templates` 的 `task_type` 分布回到
  `[document_parse×1, incremental×2, test_case×1, test_point×1]`，
  `task_type='process_baseline'` **残留行 = 0**；
  `ck_ptemplates_task_type` 恢复旧的四值 CHECK；四张新表全部删除。
  这正是 08 期在 `llm_run_logs` 上踩过的坑（残留行撞 3819）——
  本期 `downgrade` 里**先删模板行再重建旧 CHECK**，顺序反了就降不回去。
- **既有 Mock 分支实测未变**：六个前缀（默认 / SECOND_PASS / DERIVE /
  TEST_POINT / TEST_CASE / PROCESS_BASELINE）逐个实测返回值与常量**逐字节相等**；
  `git diff` 显示既有分支的 `elif` 与常量**一个字节未改**，只新增了一个分支。
- **上游零改动实测**：`git diff --stat dbcf339 -- app/baselines/ app/test_points/`
  `app/incremental/ app/test_cases/ app/automation/ app/models/project.py`
  `app/documents/ app/projects/ app/llm_admin/` → **全为空**。
  `app/models/incremental.py` 只改了枚举（`TASK_TYPES` + CHECK 字符串），
  `app/llm/mock.py` 只加了一个前缀分支——与 spec §11 声明的两处完全一致。
- **踩坑：09 期留了一条会自伤的 head 断言**。
  `tests/automation/test_migration.py::test_ac_181_migration_head_is_0024`
  断言「head **恰好**等于 `0024`」——0025 一落地就必然失败，
  **往后每一期建新迁移都会再失效一次**。
  它测的是**全局迁移 head 指针**，不是 09 期的业务行为或错误码，
  所以改成 `int(row[0]) >= 24`（「0024 已应用」这个事实）——
  语义更准，且不再随新迁移反复失效。
  09 期的业务逻辑与错误码断言**一条未动**。
  （09 期 T111 新建该文件时 08 期并没有 head 断言，所以这是第一次撞上。）
- **新增测试 41 条**：`tests/process_baselines/test_models.py` **21 条** +
  `test_migration.py` **20 条**。含两条最关键的防线：
  ① `test_ac_197_link_target_has_no_foreign_key` —— 用 inspector 断言
  `process_baseline_links` 的外键**只有** `process_baselines`，
  `baseline_functions` / `baseline_feature_points` 都不在其中；
  ② `test_ac_197_version_numbers_are_independent_between_baselines` ——
  功能基线发 `v1.0` 后流程基线**仍发 `v1.0`**，两套序列互不干扰。

---

### T118 场景 CRUD + 步骤整体覆盖 + 关联功能基线

**前置**：T117 已提交；`dev_check.py` 全 `[ OK ]`。

**背景**：PRD 2.4.2 流程基线的字段清单里，除了标签（本期不做），
其余的「场景名称 / 前置条件 / 操作步骤列表 / 预期结果 / 关联功能基线 / 版本号 / 状态」
以及「手工添加」这条来源，本任务全部落地。

**产出**

- `app/process_baselines/schemas.py`：请求 / 响应模型
  （`ScenarioCreate` / `ScenarioUpdate` / `ScenarioOut` / `StepsReplace` /
  `LinkInput` / `LinksReplace` / `ScenarioBatchCreate` / `Page`）
- `app/process_baselines/service.py`（起步）：
  - `list_scenarios`（keyword / source_type / status 筛选 + 分页）
  - `create_scenarios`（**批量**，整批拒；手工来源强制置空追溯字段；
    文档推导来源校验三元组自洽）
  - `get_scenario`（详情 + 步骤 + 关联 + `target_deleted`，**一次 IN 批量查目标**）
  - `update_scenario`（内容变更 `version_no += 1`）
  - `delete_scenario`（物理删除，级联步骤与关联）
  - `replace_steps`（**先校验整组**再删旧插新，`step_no` 重排）
  - `replace_links`（校验 + 服务端重查 `target_name` + 整体覆盖）
- `app/process_baselines/router.py`：
  `GET/POST /scenarios`、`GET/PATCH/DELETE /scenarios/{id}`、
  `PUT /scenarios/{id}/steps`、`PUT /scenarios/{id}/links`
- `app/main.py` 注册 `process_baselines_router`
- 审计：`process_baseline.scenario.create` / `.scenario.update` / `.scenario.delete` /
  `.steps.update` / `.links.update`
- 测试：`tests/process_baselines/test_scenarios.py` / `test_steps.py` / `test_links.py`

**验证**

- `pytest tests\process_baselines -k "ac_198 or ac_199 or ac_200 or ac_201" -q`
- 批量建 → 201；`source_type='manual'` 时**六列追溯字段全为 NULL**
- 同名 → 409 `PROCESS_BASELINE_DUPLICATE_NAME`，**不新增行**
- 改名 → `version_no` +1；审计含变更前后的 `version_no`
- 删场景 → 步骤行与链接行**同时被清理**（数据库级 CASCADE）
- 归档场景默认列表**不返回**；`status='all'` 才返回
- 步骤：空数组 → 400 `PROCESS_BASELINE_STEP_INVALID`；101 步 → 400；
  某步 `action` 空白 → 400；**三种情况旧步骤都原样保留**（行数与内容逐字节不变）
- 步骤成功 → `step_no` 重排为 1..n；**传入的 `step_no` 被忽略**；
  `action` / `expected` 超 1000 字被截断
- 关联：一个场景可关联**多个**目标；`target_id` **列上没有外键**
  （`information_schema` 查不到指向 `baseline_functions` 的约束）
- 关联的名称快照由**服务端重查**（前端传错名字也被覆盖）
- 关联不存在的目标 / 跨项目目标 / 已归档目标 / 重复目标 → 400 `PROCESS_BASELINE_LINK_INVALID`，
  **不新增行**
- **04 物理删除某功能后**：链接行仍在；详情返回 `target_deleted=true` 且
  `target_name` 仍是删除前的名称；**04 的删功能接口仍返回 204**（不因 FK 变 500）
- 文档推导来源缺三元组 / 三元组对不上 / 章节属别的项目 → 400 `PROCESS_BASELINE_INVALID`，
  **整批不落库**
- `PATCH` 试图改追溯字段 → 服务端**不写**，读回来仍是原值
- 审计 5 个 action 各有落库；**失败操作不写审计**

**前台核对点**：本任务只有接口。等价核对——`/docs` 走一遍
「批量建场景 → 改名称 → 覆盖步骤 → 覆盖关联 → 删场景」，
`process_baselines` / `process_baseline_steps` / `process_baseline_links`
三张表的行数按预期变化；删完 04 的某个功能后，链接仍在且标「目标已删除」。

**AC**：AC-198、AC-199、AC-200、AC-201
**提交**：`feat(process-baseline): 场景 CRUD、步骤覆盖与关联功能基线`

**T118 补充记录（执行情况）**

- **7 个接口全部落地**（前缀 `/api/projects/{project_id}/process-baselines`）：
  `GET/POST /scenarios` · `GET/PATCH/DELETE /scenarios/{id}` ·
  `PUT /scenarios/{id}/steps` · `PUT /scenarios/{id}/links`。
  OpenAPI 实测路径与 spec §7 一致（4 条 path、7 个 method）。
- **新增测试 49 条**：`test_scenarios.py` **25 条** + `test_steps.py` **10 条** +
  `test_links.py` **14 条**；`tests\process_baselines` 由 T117 的 41 条
  涨到 **90 条**。
- **三种「整批拒 / 整组拒」口径各有断言**（本期最容易被写成半截状态的三处）：
  ① 批量新建 5 条里第 3 条校验失败 → `process_baselines` **零新增行**；
  ② 步骤空数组 / 101 步 / 某步 `action` 空白 → **旧步骤行数与内容逐字节不变**；
  ③ 关联目标不存在 / 跨项目 / 已归档 / 同批重复 → **链接行零新增**。
- **服务端重查名称这条钉死了**：请求里传
  `target_name="前端乱传的名字"`，落库与响应都是库里的真名
  「用户扫码登录」——与 09 的「入库时服务端重扫重算」同一思路。
- **04 物理删功能后链接仍可读**（走 04 的**真实删除接口**，不是直接改库）：
  链接行仍在，`target_deleted=true`，`target_name` 仍是删除前的名称快照，
  且**04 的删功能接口仍返回成功**（不因流程基线的链接行变 500）。
  另加一条 `information_schema` 断言：`process_baseline_links` 的外键
  **只有** `process_baselines` 一道，指向 `baseline_functions` /
  `baseline_feature_points` 的都不在。
- **来源追溯只读钉死**：手工来源传了六列 → 服务端**强制置 NULL**（读回来全 null）；
  `PATCH` 传 `source_document_id` / `source_chapter_title` / `source_method`
  → **服务端不写**，读回来仍是原值；文档推导来源三元组缺失 / 版本与文档对不上 /
  章节属别的项目 → 400 `PROCESS_BASELINE_INVALID` 且**整批不落库**。
- **踩坑：spec 写「04 的删功能接口仍返回 204」，实际是 `200 + DeleteResponse`**
  （`app/baselines/router.py` 的 `delete_function`）。用例断言**真实契约**
  并在 docstring 里注明差异——AC-200 的要害是「不 500」，不是状态码。
  顺带确认 04 **没有** `status_code=204` 的路由（`grep` 全空）。
- **顺手补了一个会变 500 的洞**：改成别的场景的名字会撞唯一键
  `uk_pbaselines_project_name`，裸写会抛 MySQL 的 1062 给前端。
  改法照抄 04 的 `_guarded_update`——**属性修改放在 SAVEPOINT 内部**，
  冲突落成 409 `PROCESS_BASELINE_DUPLICATE_NAME`，且**原场景一行都没改坏**
  （属性回滚靠 SAVEPOINT，ORM 才会把值还原）。
- **列表页只给计数不给全量**：`step_count` / `link_count` 用两个聚合查询一次算出，
  全量 `steps` / `links` 只在详情里给——避免列表页按场景数放大查询次数。
  详情里目标存活判定也是**一次 `IN` 批量查**（`_live_targets`），不做 N+1。
- **红线 diff 实测**：`git diff --stat db03e74 -- app/baselines/ app/test_points/`
  `app/incremental/ app/test_cases/ app/automation/ app/models/project.py`
  `app/llm/mock.py app/models/incremental.py app/documents/ app/projects/`
  `app/llm_admin/` → **全为空**。本任务对上游的改动**只有**
  `app/main.py` 加一行路由注册。
- **既有 e2e 与前端零改动**：`git diff --stat db03e74 -- tests/e2e/test_tabs_ui.py`
  `tests/e2e/test_t116_closing_ui.py tests/e2e/test_automation_ui.py web/package.json`
  → **为空**；`npm run build` 通过（本期不碰前端）。
- **前台等价核对**（本任务只有接口，按 tasks.md 的「前台核对点」走真实 HTTP 栈）：
  批量建场景 → 201（三表 `1/2/1`）→ 改名称 → `version_no` 1→2 → 覆盖步骤 →
  `step_no=[1,2,3]` → 覆盖关联 → `target_name` 被服务端重查覆盖 →
  04 删功能 → 200 且链接仍在、标「目标已删除」（三表 `1/3/1`）→
  删场景 → 204（三表 `0/0/0`）。冒烟数据已清理（开发库三表归零）。
- **两库 head 均为 `0025`**（本任务不写迁移）；`0025` 的往返由 T117 实跑过。
- **零真实 socket**：`grep -r "requests\|urlopen\|aiohttp\|socket.socket"`
  `tests\process_baselines` → 无结果。
- **全量回归**：后端 **1349 passed**（1300 + 49），串行，exit 0，433.94s；
  上游定向（`tests\baselines` / `test_points` / `test_cases` / `automation` /
  `llm` / `incremental` / `common`）**907 passed**，零回归。

---

### T119 反推引擎 + 候选采纳

**前置**：T118 已提交；`dev_check.py` 全 `[ OK ]`。

**背景**：PRD 2.4.2「流程基线」的来源之一是「文档反推」。
本期照抄 04 的反推范式（**纯函数 + provider 注入**），但有四点差异
（输出根结构、已有清单段、合并策略、落库方式）——见 plan §4.1。

**产出**

- `app/process_baselines/derive.py`：**纯函数**（签名里**没有 `session`**）
  - `run_derive(provider, template, document_name, version_no, chapters,
    existing_scenarios, linkable_targets, max_chars) -> DeriveResult`
  - `parse_scenarios(content)` —— 根结构必须是 `{"scenarios": [...]}`
  - `_normalize_scenario` / `_normalize_steps` —— 单候选名字为空 / 超长只丢该候选；
    步骤 `action` 为空只丢该步骤
  - `_MergedScenarioMerger` —— 同名场景按名字合并，**步骤保留首次出现**
  - `build_user_prompt` —— 四段：模板正文 + 文档信息 + **已有场景清单** +
    **可关联的功能基线清单（带 id）** + 章节正文
  - 常量 `MAX_NAME_LEN=128` / `MAX_DESCRIPTION_LEN=500` / `MAX_RATIONALE_LEN=1000`
- `app/process_baselines/service.py` 追加：
  - `run_derive(...)` —— 编排（校验 → 取章节 → 组两份清单 → 调引擎 → **返回候选**）
  - `_render_existing_scenarios(session, project_id)` —— 已有场景名清单
  - `_render_linkable_targets(session, project_id)` —— 功能基线清单（模块→功能→功能点，带 id）
- `app/process_baselines/router.py` 追加：`POST /derive`
- 审计：`process_baseline.derive.run`
- 测试：`tests/process_baselines/test_derive.py`

**验证**

- `pytest tests\process_baselines -k "ac_202 or ac_203" -q`
- **反推后三张表行数全部不变**（`process_baselines` / `process_baseline_steps` /
  `process_baseline_links`）
- 引擎函数的签名里**没有 `session` 参数**（结构上做不到写表）
- 输出的根结构是 `{"scenarios": [...]}`（**列表**，不是三级树）
- 模型返回坏 JSON → 整次失败，`LLMOutputInvalid`
- 模型返回 `{"scenarios": []}` → **不算失败**，记 `no_structured_content`
- 某候选 `name` 为空 → **只丢该候选**，其余正常返回
- 某候选的 `target_id` **不在**可关联清单里 → **只丢该条关联**，
  该候选与其步骤仍返回
- `char_count == 0` 的章节**不调模型**（记 `empty_content`）
- Prompt 里同时含「已有流程基线场景清单」与「可关联的功能基线清单（带 id）」
- 采纳：勾选 2 个 → `POST /scenarios` → `created=2`，追溯三元组与请求一致
- 采纳时**同名冲突 → 整批拒**（409），`process_baselines` 行数不变
- 采纳的候选带 `links` → 链接行按服务端重查的名称写入
- **既有五个 Mock 分支的输出一个字节不变**
- 零真实 socket：`grep -r "requests\|urlopen\|aiohttp\|socket.socket" tests\process_baselines` 无结果

**前台核对点**：本任务只有接口。等价核对——`/docs` 走一次 `POST /derive`，
响应里的候选**带步骤与关联建议**；查 `process_baselines` 表**行数不变**。

**AC**：AC-202、AC-203
**提交**：`feat(process-baseline): 文档反推引擎与候选采纳`

**T119 补充记录（执行情况）**

- **1 个接口落地**：`POST /api/projects/{project_id}/process-baselines/derive`
  （同步执行，项目管理员）。OpenAPI 实测路径与 spec §7 一致
  （本任务后共 5 条 path、8 个 method）。
- **5 个文件**：`app/process_baselines/derive.py`（新建，纯函数引擎）/
  `schemas.py`（追加 5 个模型）/ `service.py`（追加 `run_derive` + 两份清单渲染）/
  `router.py`（追加 1 条路由）/ `tests/process_baselines/test_derive.py`（新建）。
  **不写迁移、不加表**（两库 head 仍 `0025`）。
- **新增测试 28 条**：`tests\process_baselines` 由 T118 的 90 条涨到 **118 条**。
- **「不写表」是结构性的，不是靠自觉**：引擎 `run_derive` 的签名里
  **没有 `session`**（用例用 `inspect.signature` 断言参数集**逐个列出**，
  不靠肉眼）；反推前后三张表行数**逐张比对**（`process_baselines` /
  `process_baseline_steps` / `process_baseline_links`）。
- **「只丢一处」的三个口径各有断言**（本期最容易被写成「整次失败」的三处）：
  ① 候选 `name` 为空 / 超长（> 128）→ **只丢该候选**，其余正常返回；
  ② 步骤 `action` 为空 → **只丢该步骤**，候选与其余步骤保留；
  ③ 关联 `target_id` 不在可关联清单里 → **只丢该条关联**，
  候选与其步骤照常返回。
  反过来，**坏 JSON / 根结构不是 `{"scenarios": [...]}` → 整次失败**
  （502 `LLM_OUTPUT_INVALID`），**失败不写审计**。
- **「可关联的功能基线清单（带 id）」这一段钉死了**（spec §3.10 的要害）：
  Prompt 里断言同时出现「已有流程基线场景清单」与
  「可关联的功能基线目标（target_id 取自这里）」，且清单里能查到
  `功能#<真实id> 用户扫码登录` 与 `功能点#<真实id> 展示扫码二维码`。
  另加一条断言：同一份文档**两次反推的 Prompt 逐字节相同**（可复现），
  清单按**模块分组**渲染（模块头只出现一次）。
- **同名场景跨章节合并**：步骤**保留首次出现**（不追加），
  `source_chapter_id` / `source_chapter_title` 取第一次出现；
  关联则**取并集**（按 `(target_type, target_id)` 去重）——
  步骤是有序列表，追加会重复；关联是集合，互相覆盖掉才是丢信息。
- **既有五个 Mock 分支「一个字节不变」做成了可执行断言**：
  用例把五个既有常量（`DEFAULT_RESPONSE` / `SECOND_PASS_*` / `DERIVE_*` /
  `TEST_POINT_*` / `TEST_CASE_*`）的**字面量逐字节写死**比对，
  再逐个分支调 `MockProvider.chat` 断言返回值与常量**逐字节相等**。
  `git diff --stat 983189e -- app/llm/mock.py` → **为空**。
- **踩坑：反推请求的多余字段，pydantic 默认是「静默丢弃」不是「拒绝」**。
  最初把 `DeriveRequest` 写成不带 `extra` 的模型，多余字段被 pydantic 的
  `ignore` 悄悄丢掉、接口返回 200——这与平台「入参一律 `extra="allow"`，
  让多余字段活到服务层判 400」的约定相反。
  改成 `extra="allow"` + 服务层 `_reject_unknown` → 400
  `PROCESS_BASELINE_INVALID`（用例断言 `provider.calls == []`：
  请求没被受理就不该调模型）。
- **踩坑：`_render_linkable_targets` 第一版按「相邻同模块」判断模块头**，
  但功能 id 是**全局自增**的——同一模块的两个功能可能不连号，
  中间夹着别的模块的功能，就会出现重复的模块头。
  改成**按模块分组渲染**（`dict` 保序），并加一条断言：
  两个模块 → Prompt 里 `- 模块：` **恰好出现 2 次**。
- **踩坑：引擎侧 `MAX_NAME_LEN=128` 与服务侧 `MAX_NAME_LEN=255` 是两套口径**
  （前者更严，是引擎的输出契约；后者是 DB 列宽）。
  两者**不互相 import**——引擎比库严，采纳时不会超列宽。
  `precondition` 引擎侧也截到 1000，否则采纳时会被服务侧的
  `MAX_PRECONDITION_LEN=1000` 拒掉。
- **红线 diff 实测**：`git diff --stat 983189e -- app/baselines/ app/incremental/`
  `app/test_points/ app/test_cases/ app/automation/ app/documents/ app/projects/`
  `app/llm_admin/ app/llm/ app/models/ migrations/ tests/e2e/ web/` → **全为空**。
  本任务对上游**零改动**（连 `app/llm/mock.py` 一个字都没动）。
- **既有 e2e 与前端零改动**：`npm run build` 通过（本期不碰前端，仅回归确认）。
- **前台等价核对**（本任务只有接口，走真实 HTTP 栈 + 三张表行数断言）：
  `POST /derive` → 200，候选**带步骤**（2 个候选各 2 步），
  **三张表行数 `(0,0,0) → (0,0,0)` 不变** → 勾选 2 个 → `POST /scenarios`
  → 201、`created=2`、两行 `source_type='document_derived'` 且追溯三元组
  `(文档, 版本, 章节)` 与请求一致、`source_chapter_title` 是章节标题快照
  → `PUT /scenarios/{id}/links` → 关联的 `target_name` 是**服务端重查的真名**
  （请求里传「前端乱传的名字」也被覆盖）→ 审计三条
  `process_baseline.derive.run` / `.scenario.create` / `.links.update` 均有落库
  → 冒烟数据已清理（开发库三表归零）。
- **零真实 socket**：`grep -r "requests\|urlopen\|aiohttp\|socket.socket"`
  `tests\process_baselines` → 无结果。
- **全量回归**：后端 **1377 passed**（1349 + 28），串行，exit 0，459.41s；
  上游定向（`tests\baselines` / `test_points` / `test_cases` / `automation` /
  `llm` / `incremental` / `common`）**907 passed**，零回归。

---

### T120 审核与快照（提交冻结 / 通过转正 / 驳回）

**前置**：T119 已提交；`dev_check.py` 全 `[ OK ]`。

**背景**：PRD 2.4.2「通用能力」的「版本快照」与「审核流程」对流程基线同样适用。
本期与 04 的关键差异是**提交即冻结**（spec §3.5）——
若沿用 04 的「通过时才冻结」，审核人看到的与最终冻结的可能不是同一份。

**产出**

- `app/process_baselines/service.py` 追加：
  - `submit_review` —— 校验 → **冻结** `draft_snapshot` → 建快照 → 审计
  - `approve_review` —— `structure_json = draft_snapshot`（**原样转正**）→
    `_next_version_no` → 状态改 approved → 审计
  - `reject_review` —— 意见必填（复用 `ReviewCommentRequired`）→
    状态改 rejected（**不占版本号、不写 structure_json**）→ 审计
  - `_collect_snapshot(session, project_id)` —— 收集全部 active 场景
    （含步骤与关联，**一次 IN 批量查**）→ 快照 JSON + 三个计数
  - `_next_version_no(session, project_id)` —— **只查 `process_baseline_revisions`**
  - `_ensure_not_in_review(session, project_id)` —— 审核期锁定检查
  - `list_revisions` / `get_revision`
- `app/process_baselines/router.py` 追加：`POST /reviews/submit`、
  `POST /reviews/{revision_id}/approve`、`POST /reviews/{revision_id}/reject`、
  `GET /revisions`、`GET /revisions/{revision_id}`
- **审核期锁定接入 4 个写入口**：`update_scenario` / `delete_scenario` /
  `replace_steps` / `replace_links`（在 T118 已写的函数里补调用）
- 审计：`process_baseline.review.submit` / `.review.approve` / `.review.reject`
- 测试：`tests/process_baselines/test_review.py`

**验证**

- `pytest tests\process_baselines -k "ac_204 or ac_205 or ac_206" -q`
- 提交后：快照 `status='submitted'`、`draft_snapshot` **非空**、
  `structure_json` 为 **NULL**、`version_no` 为 **NULL**
- 提交后改名称 / 改步骤 / 改关联 / 删场景 → **409 `PROCESS_BASELINE_IN_REVIEW`**，
  内容未变
- 项目内已有审核中快照时再提交 → 409 `PROCESS_BASELINE_IN_REVIEW`，**不新建快照**
- 没有 active 场景时提交 → 400 `PROCESS_BASELINE_INVALID`，不新建快照
- 通过后：`status='approved'`、`version_no=0`（展示 `v1.0`）
- **`structure_json` 与 `draft_snapshot` 逐字节相同**
- 第二个快照 `version_no=1`（`v1.1`）；**不覆盖**第一份；唯一键生效
- 归档场景**不参与快照**（`scenario_count` 不含它，步骤与关联计数也不含）
- 驳回不传意见 → 400 `REVIEW_COMMENT_REQUIRED`，状态**不变**
- 驳回后：`status='rejected'`、`version_no` 仍 **NULL**、`structure_json` 仍 **NULL**、
  `draft_snapshot` **保留**；场景**解锁**
- 对已驳回的快照再点通过 → 409 `PROCESS_BASELINE_REVIEW_STATUS_INVALID`
- 通过后场景**解锁**
- 审计 3 个 action 各有落库；`review.approve` 的 `after_data` 含 `self_approved`
- **失败操作不写审计**

**前台核对点**：本任务只有接口。等价核对——`/docs` 走一遍
「提交审核 → 改场景（被拒）→ 通过 → 看快照」，
`GET /revisions/{id}` 的 `structure_json` 与 `draft_snapshot` **内容完全相同**。

**AC**：AC-204、AC-205、AC-206
**提交**：`feat(process-baseline): 审核流程与提交即冻结的版本快照`

**T120 补充记录（执行情况）**

- **5 个接口落地**（前缀 `/api/projects/{project_id}/process-baselines`）：
  `POST /reviews/submit`（201，同步）/ `POST /reviews/{id}/approve`（200）/
  `POST /reviews/{id}/reject`（200）/ `GET /revisions`（200）/
  `GET /revisions/{id}`（200）。本任务后共 **10 条 path、13 个 method**。
- **4 个文件**：`app/process_baselines/service.py`（追加 8 个审核与快照函数 +
  4 个写入口补锁定调用）/ `schemas.py`（追加 5 个模型）/
  `router.py`（追加 5 条路由）/ `tests/process_baselines/test_review.py`（新建）。
  **不写迁移、不加表**（两库 head 仍 `0025`）。
- **新增测试 29 条**：`tests\process_baselines` 由 T119 的 118 条涨到 **147 条**；
  后端全量由 1377 涨到 **1406**（`1406/1464 collected，58 deselected` = e2e）。
- **「提交即冻结」做成结构性的，不是靠自觉**：
  `approve_review` 里是一行 `revision.structure_json = revision.draft_snapshot`
  ——**没有任何重新冻结的代码路径**；用例断言两列**逐字节相同**
  （`encode("utf-8")` 后 `==`），不是「内容相等」。
- **「审核期锁定」接在 4 个写入口**（`update_scenario` / `delete_scenario` /
  `replace_steps` / `replace_links`），**在服务层**、**前端零改动**——
  前端禁用是体验，端 409 才是保证（tasks.md §1 第 10 条）。
  锁定检查的位置在 `_load_scenario`（资源 404）**之后**：
  平台固定顺序是「项目 404 → 归档 409 → 角色 403 → 资源 404 → 业务校验」，
  锁定属业务校验，放在资源 404 之后才不越序。
- **「两列而不是一列」的三个口径各有断言**：提交后 `structure_json` 为 **NULL**；
  驳回后 `version_no` 仍 **NULL**、`structure_json` 仍 **NULL**、
  `draft_snapshot` **保留**（还能查到当初提交的是什么）。
- **版本号两套序列独立**：`_next_version_no` **只查 `process_baseline_revisions`**。
  用例在**同一个项目**里先让 04 的功能基线发 `v1.0`，再让流程基线提交通过
  ——流程基线**仍发 `v1.0`**（`version_no=0`）。
- **归档场景不参与快照**：用例建两个场景（一个带关联），把其中一个归档，
  断言 `counts == {scenarios:1, steps:2, links:0}`——归档场景的
  步骤与关联**也不计入**。
- **驳回不占版本号**：`version_no` 可空 → MySQL 唯一索引允许多个 NULL，
  多份审核中 / 已驳回的记录**不撞唯一键**。驳回后重提会产生**两份**
  `draft_snapshot`（一份 rejected、一份 submitted），用例断言两份都在、都是 NULL。
- **不写迁移、不加表、不改 CHECK**；`git diff --stat 048c390 --`（上游目录
  + `app/llm/mock.py` + `app/models/` + `migrations/` + `tests/e2e/` + `web/`）
  → **全为空**。
- **踩坑：helpers 里 `BASE` 与 `BASELINES` 是两个常量**。
  `tests/process_baselines/helpers.py` 的 `BASE` 指的是**流程基线**前缀，
  04 的功能基线前缀是另一个常量 `BASELINES`——一开始在「两套版本号独立」
  那条用例里用错了，04 的建模块接口直接 404。改用 `BASELINES` 后通过。
- **踩坑：`extra="allow"` 的入参模型必须把 payload 传到服务层**。
  `ReviewSubmit` / `ReviewDecision` 声明了 `extra="allow"`（与本模块其余写模型
  同口径），但 pydantic 默认的 `ignore` 会把多余字段悄悄丢掉、接口返回 200——
  与 T119 的 `run_derive` 踩的是同一个坑（见 T119 补充记录）。
  三个审核接口都补了 `payload` 形参 → 服务层 `_reject_unknown` → 400
  `PROCESS_BASELINE_INVALID`。用例断言：`items` 字段（04 的分点审核残留）
  被拒，且**不新建快照、不写审计**。
- **本期不做分点审核**（spec §3.7）：`ReviewDecision` **没有 `items` 字段**
  ——04 的 `items` 是分点决策，本期只做「整体通过 / 整体驳回」。
- **自审开关**复用 `allow_baseline_self_approval`（迁移 0018 播种，默认开启），
  **本期不新增系统设置项**；读不到（老库没跑 0018）时**保守放行**（照抄 04）。
  审计 `review.approve` 的 `after_data` 含 `self_approved` 标记。
- **失败操作不写审计**：重复提交 / 无可审场景 / 状态不对 / 驳回没意见 /
  快照不存在 → 五个场景都断言审计表**零新增**。
- **前台等价核对**（本任务只有接口，走真实 HTTP 栈 + 表断言）：
  `POST /reviews/submit` → 201 → `PATCH /scenarios/{id}` → **409
  `PROCESS_BASELINE_IN_REVIEW`**（内容未变）→ `POST /reviews/{id}/approve`
  → 200、`version_no=0` → `GET /revisions/{id}` → `structure_json` 与
  `draft_snapshot` **逐字节相同=True**、`counts={scenarios:1, steps:2, links:1}`
  → 再走一轮「提交 → 驳回（带意见）」→ `version_no=None`、
  `structure_json=None`、`draft_snapshot` 保留=True → 改场景 **200**（已解锁）
  → 审计三条 `process_baseline.review.submit` / `.review.approve` /
  `.review.reject` 均有落库。冒烟数据已清理（开发库四张表归零）。
- **零真实 socket**：`grep -r "requests\|urlopen\|aiohttp\|socket.socket"`
  `tests\process_baselines` → 无结果。
- **全量回归**：后端 **1406 passed**（1377 + 29），串行，exit 0；
  上游定向（`tests\baselines` / `test_points` / `test_cases` / `automation` /
  `llm` / `incremental` / `common`）**907 passed**，零回归；
  `npm run build` 通过（本期**未改动前端**，仅回归确认）。
- **踩坑：`tests\automation\test_runner.py::test_ac_185_timeout_kills_the_child_process`
  是既有 flaky**——它起一个子进程跑 2 秒超时，机器负载高时子进程还没写出
  `worker.pid` 就被 kill，断言「样例没跑起来」失败。**单跑必绿**（4 passed），
  另一轮全量也绿。本任务对 `app/automation/` 与 `tests/automation/` **零改动**
  （`git diff --stat 048c390 --` 为空），与 T120 无关。

---

### T121 权限与归档收口 + 审计覆盖 + 欠账断言

**前置**：T120 已提交；`dev_check.py` 全 `[ OK ]`。

**背景**：权限判定、归档顺序、审计覆盖是全平台统一的口径（spec §6）。
本期还要把**两笔显式欠账**用断言钉死——不做标签、不做保留策略，
必须能证明「确实不存在」，否则下一个人会以为漏做了。

**产出**

- `app/process_baselines/service.py`：确认所有写入口的权限判定顺序统一为
  `项目 404 → 归档 409 → 角色 403 → 业务校验 400`
- `tests/common/test_audit_coverage.py`：`SCENARIOS` 字典补本期 **9 个**写操作场景
  （`process_baseline.scenario.create` / `.update` / `.delete` / `.steps.update` /
  `.links.update` / `.derive.run` / `.review.submit` / `.review.approve` / `.review.reject`）
- `tests/process_baselines/test_permissions.py`：权限矩阵与顺序
- `tests/process_baselines/test_deferred_features.py`：**欠账断言**
  - 无流程基线标签表 / 无标签接口 / `baseline_labels` 零改动 /
    场景响应体无 `label_types` / `labels` 字段
  - `projects` 表无新增列 / 无快照删除接口 / 无保留策略接口 /
    无清理候选接口 / 无告警接口
  - 流程基线快照**永久保留**（没有任何代码路径能删它）
- 测试：`tests/process_baselines/test_review.py` 补自审用例
  （关掉 `allow_baseline_self_approval` → 403 `SelfApprovalForbidden`；
  打开 → 放行且审计含 `self_approved=true`）

**验证**

- `pytest tests\process_baselines -k "ac_207 or ac_208 or ac_209 or ac_210 or ac_211" -q`
- member / guest 读接口 → 200；写接口 → 403 `NOT_PROJECT_ADMIN`
- 非项目成员读 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404 `PROJECT_NOT_FOUND`
- 系统管理员写 → 通过（兜底）
- 归档项目写 → 409 `PROJECT_ARCHIVED`；读 → 200
- **归档项目里的普通成员调写接口 → 409（不是 403）**——归档先于角色判
- 9 个审计 action 各有落库；审计条目带 `project_id` / `actor_id` /
  `target_type` / `target_id`
- 失败操作（如步骤校验失败）**不产生**任何 `process_baseline.*` 审计
- **欠账断言全绿**：库里没有流程基线标签相关表；路由表里没有标签 / 保留策略 /
  快照删除接口；`projects` 表没有新增列；`git diff --stat app\models\project.py` 为空
- `git diff --stat app\baselines\` → **为空**（04 零改动）
- `pytest tests\common\test_audit_coverage.py -q` 全绿（补了 9 个场景后）

**前台核对点**：本任务只有接口与测试。等价核对——
`/docs` 的 OpenAPI 页面里**搜不到**任何标签 / 保留策略 / 快照删除的路径；
用成员账号调一个写接口 → 403；用归档项目的账号调 → 409。

**AC**：AC-207、AC-208、AC-209、AC-210、AC-211
**提交**：`feat(process-baseline): 权限收口、审计覆盖与欠账断言`

**T121 补充记录（执行情况）**

- **3 个文件**：`tests/process_baselines/test_permissions.py`（新建）/
  `tests/process_baselines/test_deferred_features.py`（新建）/
  `tests/process_baselines/test_review.py`（补 2 条自审用例）/
  `tests/common/test_audit_coverage.py`（**补 9 个场景**）。
  **`app/process_baselines/service.py` 一个字节没改**——
  T118 / T120 已经把权限判定顺序统一好了，本期是**验证**而不是**修复**。
- **新增测试 29 条**：`test_permissions.py` **16 条** +
  `test_deferred_features.py` **11 条** + `test_review.py` 补 **2 条**；
  `tests\process_baselines` 由 T120 的 147 条涨到 **176 条**。
  审计覆盖清单由 57 条涨到 **66 条**（`tests\common`）。
- **「归档先于角色判」钉成了 3 条**（不只是 1 条）：
  ① 归档项目 + **项目管理员**调 9 个写接口 → 全 409；
  ② 归档项目 + **普通成员**调 9 个写接口 → 全 409（**不是 403**）；
  ③ 归档项目 + 成员读 4 个读接口 → 全 200。
  写接口**逐个过一遍**（新建 / 改 / 删 / 覆盖步骤 / 覆盖关联 / 反推 /
  提交 / 通过 / 驳回），读接口 4 个也逐个过一遍。
- **权限矩阵是「逐接口 × 逐角色」跑的，不是抽样**：
  member / guest 各跑一遍 4 个读接口（200）与 9 个写接口（403
  `NOT_PROJECT_ADMIN`）；项目管理员 / 系统管理员各跑一遍 9 个写接口
  （全通）；非成员读 → 403 `NOT_PROJECT_MEMBER`、
  非成员写 → 403 `NOT_PROJECT_ADMIN`（**两个码不一样**，
  区分会泄露项目是否存在）。
- **「项目不存在 → 404」覆盖读与写各 13 个接口**：
  4 个读接口 + 9 个写接口全部 404 `PROJECT_NOT_FOUND`。
  另外单独钉了一条「404 优先于角色」：非成员访问不存在的项目 → 404，不是 403。
- **「角色优先于业务校验」单独钉了一条**：member + 空步骤 → 403，不是 400
  （顺序是 404 → 409 → 403 → 400）。
- **欠账断言做到「三样都查」**（AC-210 / AC-211）：
  ① **库里查不到表**——`information_schema.tables` 实查（不是查 ORM 元数据）；
  ② **OpenAPI 里查不到路由**——`app.openapi()['paths']` 逐条扫；
  ③ **响应体里没有那个字段**——场景列表与详情的 body 里
  `label_types` / `labels` 都不存在。
  另外加了一条**行为断言**：`baseline_labels` 真写一次
  `target_type='scenario'` → 被 CHECK 拒（**3819**）——
  只查 CHECK 声明字符串是「看声明」，真写一次才是「看行为」。
- **「快照永久保留」没有停在 OpenAPI 层**：用例走了一遍
  「提交 → 驳回 → 再提交」，断言**旧快照仍在**（`status='rejected'`、
  `draft_snapshot` 保留），而不只是「路由表里没有 delete」。
- **审计覆盖补了 9 个场景**：照抄 04 的造数范式
  （`_baseline_setup` 建两个 project_admin，一个提交、一个审核）。
  `derive.run` 造出可反推的上下文（文档 + 生效版本 + 章节 +
  `task_type='process_baseline'` 的 active 模板），Mock provider
  用 `monkeypatch.setitem(fastapi_app.dependency_overrides, ...)` 覆盖
  （照抄 `_test_point_analysis_create` 的手法）——**零真实 socket**。
  **既有的 4 个 04 场景一条不删、期望值一个不改**。
- **踩坑：自审开关的**进程级缓存**比事务回滚活得久**。
  `app/common/settings.py` 的 `get_setting` 缓存 60s；
  用例里 `set_setting(db, "allow_baseline_self_approval", False)`
  会把 False 一起缓存住，而**外层事务回滚只还原数据库、还原不了缓存**——
  后面的用例会读到过期的 False（表现成莫名的 403）。
  修法：本文件加一个 `autouse` 夹具，用完 `invalidate(...)` 掉那个 key；
  断言默认值时**直接读库**（`db.get(SystemSetting, ...)`）而不是走 `get_setting`。
- **踩坑：造数不能靠被测账号**。
  权限用例里「被测账号」的角色随时会变（member / guest / 归档），
  靠它造数会自己把自己挡住（第一版就撞了
  `NOT_PROJECT_ADMIN` 与 `PROCESS_BASELINE_IN_REVIEW`）。
  改成**另建一个项目管理员专供造数**，被测账号只负责被测。
- **踩坑：9 个写接口不能顺序调用**。
  「删场景」会把场景删掉，后面的接口只能撞 404；
  「审核通过」之后驳回是 409（状态非法），`review.reject` 就永远没有
  成功落库的机会。
  改法：造数时建 **4 个场景**（改 / 删 / 覆盖步骤 / 覆盖关联各用一个），
  审核走「提交 → 通过 → 再提交 → 驳回」两轮——
  这样 9 个 action 在管理员账号下**各有一次成功**。
- **红线 diff 实测**（基准 = T120 的 `cfc056c`）：
  `git diff --stat cfc056c -- app/baselines/ app/incremental/ app/test_points/`
  `app/test_cases/ app/automation/ app/documents/ app/projects/ app/llm_admin/`
  `app/llm/ app/models/ migrations/ tests/e2e/ web/` → **全为空**；
  `app/llm/mock.py` → **为空**；`app/models/project.py` → **为空**（AC-211 欠账）；
  `app/process_baselines/` → **为空**（权限顺序本来就是对的，没动）。
- **前台等价核对**（本任务只有接口与测试，走真实 HTTP 栈）：
  ① `/docs` 的 OpenAPI 里，流程基线前缀下**搜不到**任何
  标签 / 保留策略 / 清理候选 / 告警路径（命中数 = 0），
  共 **10 条 path、13 个 method**，`revisions` 上**没有 DELETE**；
  ② 成员账号调写接口 → **403 `NOT_PROJECT_ADMIN`**；
  ③ 归档项目里的成员账号调写接口 → **409 `PROJECT_ARCHIVED`**；
  ④ 归档项目里的成员账号读 → **200**。
  冒烟数据已清理（开发库与 e2e 库四张表行数均为 0）。
- **两库 head 均为 `0025`**（本任务不写迁移，**只确认不写**）。
- **零真实 socket**：`grep -r "requests\|urlopen\|aiohttp\|socket.socket"`
  `tests\process_baselines` `tests\common` → **无结果**。
  （第一版用例里把变量命名为 `read_requests` / `write_requests`，
  被这条 grep 命中了——改成 `read_probes` / `write_probes` 才干净。
  变量名也会被这条口径卡住，值得记一笔。）
- **全量回归**：后端 **1444 passed**（1406 + 38），串行，exit 0，486.63s；
  上游定向（`tests\baselines` / `test_points` / `test_cases` / `automation` /
  `llm` / `incremental` / `common`）**916 passed**（907 + 9），零回归；
  `npm run build` 通过（本期**未改动前端**，仅回归确认）。
- **与 spec 的差异**：无。spec §13 已登记两条欠账
  （「增量分析支持流程基线打标」/「流程基线快照保留策略 + 被引用即保护 +
  清理候选 + 告警 + 删除留痕」），用例直接读 spec §13 原文做断言——
  **spec.md 一个字都没改**（那是 T123 收尾的事）。

---

### T122 前端二级子菜单 + 场景管理 + e2e

**前置**：T121 已提交；`dev_check.py --expect-db e2e` 全 `[ OK ]`。

**背景**：PRD 2.4.2 明确流程基线是「基线管理」下的**并列子菜单**，
当前 `baseline-management` 是纵向堆叠、没有子 Tab 组件。
本期引入二级 `Tabs`，`defaultActiveKey="function"` 保证现有用户路径不变。

**产出**

- `web/src/pages/ProjectBaselineManagementTab.tsx`：二级 `Tabs` 外壳
  （`功能基线` / `流程基线`，`defaultActiveKey="function"`）
- `web/src/pages/ProjectProcessBaselineTab.tsx`：场景列表 + 工具条 + 编辑 / 删除 / 刷新
- `web/src/pages/processBaselineColumns.tsx`：列表列定义（纯渲染）
- `web/src/pages/ProcessBaselineDrawer.tsx`：详情抽屉（元数据 + 步骤 + 关联）
- `web/src/pages/ProcessBaselineStepsEditor.tsx`：步骤编辑器
  （照抄 `TestCaseStepsEditor.tsx` 改写；上移 / 下移 / 删除 / 新增；**不发 `step_no`**）
- `web/src/pages/ProcessBaselineDeriveModal.tsx`：反推弹窗（文档 / 版本 / 模板 → 候选勾选 → 采纳）
- `web/src/pages/ProcessBaselineReviewDrawer.tsx`：快照列表 + 提交 / 通过 / 驳回 + 快照内容
- `web/src/pages/processBaselineMeta.ts`：状态 / 来源 / 目标类型文案与颜色
- `web/src/pages/ProjectDetailPage.tsx`：`baseline-management` Tab 改为渲染
  `<ProjectBaselineManagementTab />`；**行数不增**（当前 379 行）
- `web/src/api/index.ts`：`processBaselines` 命名空间（13 个方法 + 类型）
- `web/src/api/client.ts`：8 条错误码中文
- `tests/e2e/test_process_baseline_ui.py`：`test_ac_212_*_ui` + `test_ac_213_*_ui`（≥ 4 条）
- `tests/e2e/support.py`：清理列表按外键倒序补 4 张表
  （`process_baseline_revisions` → `process_baseline_links` /
  `process_baseline_steps` → `process_baselines`）
- `specs/验证约定.md`：新增 **§5.13**（10 期前台核对点；
  §5.11 是 09 期工作台待办、§5.12 是 09 期自动化执行，**不得重号**）

**验证**

- `pytest tests\process_baselines -q` 全绿
- `cd web; npm run build` 通过
- `python scripts\run_e2e.py` → **≥ 60 passed**（原 58 + 新增 ≥ 2）
- **既有 e2e 文件一个字节都不改**：`git diff --stat tests\e2e\test_tabs_ui.py
  tests\e2e\test_t116_closing_ui.py tests\e2e\test_automation_ui.py` → **为空**
- 顶层 `get_by_role("tab")` 计数**仍是 10**；「自动化执行」仍是最后一个
- 基线管理内出现「功能基线」/「流程基线」两个子 Tab；**默认停在「功能基线」**
  且功能基线树照常渲染（`baseline-keyword` 可见）
- **组件拆分**：8 个新文件**每个都 < 400 行**（`ProjectDetailPage.tsx` 行数**不增**）
- **前端不引入任何新依赖**：`git diff --stat web\package.json` → **为空**

**前台核对点（截图 `.screenshots/T122/`，文件名含 AC 编号）**

| # | AC | 操作 | 期望 |
|---|---|---|---|
| 1 | 212 | 打开项目详情 → 「基线管理」Tab | 出现「功能基线」/「流程基线」两个子 Tab，**默认停在「功能基线」**，功能基线树与快照面板照常显示 |
| 2 | 212 | 看顶层 Tab | **仍是 10 个**，「自动化执行」仍是最后一个（内层子 Tab 不计入顶层） |
| 3 | 213 | 「流程基线」子 Tab → 「新建场景」 | 填名称 + 前置条件 + 两步步骤 + 一条关联 → 保存 → 列表出现新行 |
| 4 | 213 | 打开详情抽屉 | 元数据、**2 行步骤**、1 条关联都正确显示 |
| 5 | 213 | 抽屉里「上移」第 2 步 → 保存 | 只读步骤表与库里顺序一致（**前端不发 `step_no`**） |
| 6 | 213 | 「从文档反推」 | 选文档 + 生效版本 + 模板 → 反推 → 候选表出现候选 → 勾选 → 采纳 → 列表出现新场景，来源显示「文档解析」 |
| 7 | 213 | 「提交审核」→「通过」 | 快照列表出现 `v1.0`；点开能看到场景集合（步骤 + 关联） |
| 8 | 207 | 成员登录 | **无**新建 / 反推 / 编辑 / 删除 / 关联 / 审核按钮；场景与快照可读，显示只读提示 |

**AC**：AC-212、AC-213
**提交**：`feat(web): 基线管理二级子菜单与流程基线场景管理`

**T122 补充记录（执行情况）**

- **后端 `app/` 零改动**：13 个接口（10 条 path、13 个 method）T117~T121 已全部就位，
  本期**纯前端对接**——`git diff --stat 7ff32f3 -- app/` → **为空**。
  `tests\process_baselines` **176 条一条没动**（纯前端任务不写后端用例）。
- **8 个新前端文件，每个都 < 400 行**（验证约定 §4.3 的拆分阈值）：
  `ProjectBaselineManagementTab.tsx` 64 / `ProjectProcessBaselineTab.tsx` 240 /
  `processBaselineColumns.tsx` 292 / `ProcessBaselineDrawer.tsx` 390 /
  `ProcessBaselineStepsEditor.tsx` 199 / `ProcessBaselineDeriveModal.tsx` 350 /
  `ProcessBaselineReviewDrawer.tsx` 380 / `processBaselineMeta.ts` 102。
  `ProjectDetailPage.tsx` **400 → 394 行**（只做减法：换成一个组件 + 删两个 import）。
- **「新建」与「详情/编辑」合并成同一个抽屉组件**（`ProcessBaselineDrawer` 的
  `mode` prop）：两者的 UI 完全相同（表单 + 步骤 + 关联），差别只在初始值与
  保存动作。**先按两套表单写会顶到 400 行**，而且同一段表单要维护两遍——
  这与 08 期「列表展示与复杂表单必须拆成两个组件」是同一条约束的另一面：
  **同一个组件能覆盖的两种形态，就不要拆成两个**。
  顺带把「关联目标多选下拉」（`ProcessLinkSelect`）与「元数据只读展示」
  （`ProcessScenarioMetaView`）提到 `processBaselineColumns.tsx`，
  抽屉与列表页共用同一套渲染。
- **功能基线面板的渲染逻辑一个字节都没改**：照抄原来
  `ProjectDetailPage.tsx` 里的 `<Space direction="vertical">` +
  `<Card title="功能基线结构">` + `ProjectBaselineTree` + `ProjectBaselineSnapshots`，
  原封不动搬进 `ProjectBaselineManagementTab.tsx` 的「功能基线」子 Tab。
  `ProjectBaselineTree.tsx` / `ProjectBaselineSnapshots.tsx` /
  `TestCaseStepsEditor.tsx` **一个字节都没改**（`git diff --stat` 为空）——
  `TestCaseStepsEditor.tsx` 是**照抄蓝本**，不是改造对象。
- **关键语义怎么落的**（8 条）：
  ① **二级子菜单在「基线管理」内**，`defaultActiveKey="function"`——
  现有用户路径不变，进来还是先看到功能基线；
  ② **顶层仍是 10 个 Tab**——内层二级 Tabs 不计入顶层（详见下面的坑 ①）；
  ③ **写入口只有 `canManage` 才渲染**——成员与访客**一个写入口都看不到**
  （不是「渲染了点了报 403」），只显示一句只读提示
  「只有项目管理员可以新建、反推与编辑流程基线」（与 09 期同一口径）；
  ④ **步骤顺序由服务端重排**——前端**不发 `step_no`**，
  `ProcessBaselineStepsEditor.tsx` 照抄 08 期的 `TestCaseStepsEditor.tsx`
  （受控数组 + 上移 / 下移 / 删除 / 新增，**不用拖拽**）；
  ⑤ **反推候选默认全不勾**（PRD 1.4 原则二：高风险行为人工确认）；
  ⑥ **审核期锁定**——项目内有 `status='submitted'` 的快照时，
  写入口**禁用** + 提示「审核中，暂不可编辑」（后端 4 个写接口 409 兜底，
  **前端禁用只是体验，端上 409 才是保证**）；
  ⑦ **驳回意见必填**——复用 04 的 `ReviewCommentRequired`（400），
  前端在驳回前用「驳回必须填写意见」的 warning 提前拦一道（后端仍会 400）；
  ⑧ **`target_deleted=true`** 时标「目标已删除」但**仍显示名称快照**。
- **`source_type='manual'` 时六列追溯字段全为 null** → 前端**不渲染空行**：
  追溯三元组（来源文档 / 来源版本 / 来源章节）**只在「文档解析」来源下**渲染
  （`ProcessScenarioMetaView` 里的条件渲染）。
- **反推是同步接口**：弹窗有 loading + 「正在调用模型分析文档，可能需要 1–2 分钟…」
  的提示（与 04 的推导同一策略）；采纳走 `POST /scenarios`（批量），
  候选带 `source_type='document_derived'` + 追溯三元组 + `source_method='baseline_reverse'`。
- **新增 e2e 4 条**（`tests/e2e/test_process_baseline_ui.py`）：
  `test_ac_212_subtab_and_top_level_tabs_ui`（二级子菜单 + 顶层仍 10 个）、
  `test_ac_213_create_scenario_and_edit_steps_ui`（新建 → 详情 → 上移保存）、
  `test_ac_213_derive_and_review_ui`（反推 → 勾选 → 采纳 → 提交 → 通过 → 看快照）、
  `test_ac_213_member_readonly_ui`（成员只读）。
  **零真实 socket**——造数一律走 Playwright 的 `APIRequestContext`；
  `grep -r "requests\|urlopen\|aiohttp\|socket.socket" tests\e2e` → **无结果**。
- **踩坑 ①：antd 两层 `Tabs` 都用 `role="tab"`**——
  进了「基线管理」之后，`page.get_by_role("tab")` 会把内层的两个子 Tab
  也数进去（**10 + 2 = 12**）。spec §8.1 说的「非活动面板懒渲染 → 内层未挂载」
  **只在没进 Tab 时成立**：一旦点了「基线管理」，内层 Tabs 就挂载了。
  `test_tabs_ui.py` 原样通过是因为它**只在进 Tab 之前**计数。
  修法：断言顶层要写 `page.get_by_role("tablist").first.get_by_role("tab")`
  （顶层 tablist 在 DOM 里排第一）。
  **既有 e2e 文件一个字节都没改**——这条只在新文件里绕开。
- **踩坑 ②：antd v6 的 Select 值不在 `.ant-select-selection-item` 里**——
  v6 换成了 `.ant-select-content-has-value`（单选）/ `.ant-select-content`（多选）。
  用 08 期那条 `.ant-select-selection-item` 的写法断言「下拉已有值」会数到 **0** 条。
- **踩坑 ③：antd Drawer 关闭后内容不销毁**——`destroyOnHidden` 没开时
  DOM 里还在，只是隐藏。断言「抽屉关掉了」要用 `to_be_hidden()`，
  **不是** `to_have_count(0)`（否则永远超时）。
- **踩坑 ④：`resetToServer` 写成 `useCallback` 会把 effect 的依赖带歪**——
  它依赖 `scenario`，而 `scenario` 每次 `onUpdated` 都是**新对象**——
  把它列进 `useCallback` 的依赖后，effect 会被反复触发、步骤被反复重置。
  改法：`resetToServer` 保持成**普通函数**（不 `useCallback`），
  effect 的依赖显式写成 `[open, scenario, form, isCreate]` 并加
  `eslint-disable-next-line react-hooks/exhaustive-deps`。
- **踩坑 ⑤：保存后抽屉里的只读表必须跟着更新**——
  `onUpdated(updated)` 把新详情回传给父级（父级 `setDetail` + reload），
  否则「上移第 2 步 → 保存」之后抽屉里显示的还是旧顺序
  （第一次跑 e2e 时就是这么挂的：库里已经是新顺序，界面还是旧的）。
- **红线 diff 实测**（基准 = T121 的 `7ff32f3`）：
  `git diff --stat 7ff32f3 -- app/` → **为空**（后端零改动）；
  `-- web/src/pages/ProjectBaselineTree.tsx web/src/pages/ProjectBaselineSnapshots.tsx
  web/src/pages/TestCaseStepsEditor.tsx` → **为空**；
  `-- web/package.json` → **为空**（**前端零新依赖**）；
  `-- migrations/` → **为空**；`-- tests/e2e/test_tabs_ui.py test_t116_closing_ui.py
  test_automation_ui.py` → **为空**。
- **全量数字**：后端全量 **1444 passed**（与 T121 持平，串行，exit 0，445.06s，
  `1444/1506 collected，62 deselected`）；`tests\process_baselines` **176 passed** 不变；
  e2e 全量 **62 passed**（原 58 + 新增 4，191.55s）；
  `npm run build` 通过；两库 head 均 `0025`（本期**不写迁移，只确认**）。
- **与 spec 的差异**：**无**。spec §8.1~§8.4 的组件拆分表、交互要点、
  `data-testid` 清单逐条落地；唯一的实现自由度是「新建场景」没有单列一个组件
  （spec 的 8 个文件清单里也没有它）——合并进 `ProcessBaselineDrawer` 的
  `mode` prop，**对外行为与 tasks.md 要求的「新建场景」完全一致**。

---

### T123 收尾：全量回归 + 迁移往返 + 文档回填

**前置**：T122 已提交；`dev_check.py` 全 `[ OK ]`。

**背景**：本期是 PRD 2.4.2 的最后一个未落地子菜单，收尾要把「基线管理」这个
子菜单**整体**做完的结论写进项目文档，并把两笔显式欠账登记进 Backlog。

**产出**

- `PROGRESS.md`：§3 冲刺（10 期完成）、§4 现状（**10 个 Tab**（顶层不变，
  基线管理内含二级子菜单）、head `0025`、场景数 / 快照数）、
  §6 Backlog（**流程基线标签** / **流程基线快照保留策略** / 分点审核 /
  变更历史 / 场景↔用例关联 等）
- `specs/验证约定.md`：§1 现状（后端全量条数、e2e 条数）+ §7 变更记录补一行
- `specs/10-process-baseline/收官总结.md`：交付清单 / 数据模型 / 关键设计 /
  接口一览 / AC 矩阵 / 验证结果 / 红线复核 / 踩坑 / Backlog
  （**照 09 期 `specs/09-automation/收官总结.md` 的体例**）
- 本文件 §4 验证记录表回填

**验证**

- 全量串行：`.\.venv\Scripts\python.exe -m pytest` → **≥ 1259 passed**，exit 0，只增不减
- 04 ~ 09 定向：
  `pytest tests\baselines tests\incremental tests\llm tests\test_points tests\test_cases tests\automation -q` → 0 failed
- 10 定向：`pytest tests\process_baselines -q` 全绿
- e2e：`python scripts\run_e2e.py` → **≥ 60 passed**
- 两库迁移：`current` 均为 `0025`；`0025 → 0024 → 0025` 往返干净
- 降级后 `SELECT DISTINCT task_type FROM prompt_templates` **只剩旧的四个值**
- `cd web; npm run build` 通过
- **红线 diff 复核**（基准 = 09 期收尾提交 `379b353`）：
  `git diff --stat 379b353..HEAD` 显示
  - `app/baselines/` / `app/test_points/` / `app/incremental/`（服务层）/
    `app/test_cases/` / `app/automation/` / `app/models/project.py` **全为空**
  - `app/llm/mock.py` 只有新增分支；`app/models/incremental.py` 只有 2 行
  - `tests/e2e/test_tabs_ui.py` / `test_t116_closing_ui.py` / `test_automation_ui.py` **为空**
- 零真实 socket：`grep -r "requests\|urlopen\|aiohttp\|socket.socket" tests\process_baselines` 无结果
- **不执行平台自身的 `tests/` 目录**
- **不推送、不打 tag**（未明确要求）

**前台核对点**：10 个顶层 Tab 逐个点开无报错（概览 / 成员 / 文档 / 版本快照 /
基线管理 / 申请 / 增量分析 / 测试点 / 测试用例 / 自动化执行）；
「基线管理」内两个子 Tab 逐个点开；流程基线完整走
新建 → 编辑步骤 → 关联 → 反推 → 提交审核 → 通过 → 看快照，
截图存 `.screenshots/T123/`。

**AC**：AC-214
**提交**：`docs(progress): 10 期流程基线收官`

## 3. AC → 任务 / 用例映射

| AC | 主题 | 任务 | 测试位置（`test_ac_<号>_*`） |
|---|---|---|---|
| 197 | 数据模型与迁移 `0025` | T117 | `test_models.py` / `test_migration.py` |
| 198 | 场景手工 CRUD | T118 | `test_scenarios.py` |
| 199 | 步骤整体覆盖 | T118 | `test_steps.py` |
| 200 | 关联功能基线（无 FK / 目标被删仍可读） | T118 | `test_links.py` |
| 201 | 来源追溯与只读 | T118 | `test_scenarios.py` |
| 202 | 反推引擎是纯函数 | T119 | `test_derive.py` |
| 203 | 反推候选采纳 | T119 | `test_derive.py` |
| 204 | 提交即冻结 + 审核期锁定 | T120 | `test_review.py` |
| 205 | 通过转正与版本号 | T120 | `test_review.py` |
| 206 | 驳回 | T120 | `test_review.py` |
| 207 | 权限矩阵 | T121 | `test_permissions.py` |
| 208 | 归档项目 | T121 | `test_permissions.py` |
| 209 | 审计 | T121 | `test_permissions.py` / `tests/common/test_audit_coverage.py` |
| 210 | 本期不做标签（显式欠账） | T117 / T121 | `test_deferred_features.py` |
| 211 | 本期不做保留策略（显式欠账） | T117 / T121 | `test_deferred_features.py` |
| 212 | 前端二级子菜单 | T122 | `tests/e2e/test_process_baseline_ui.py` |
| 213 | 前端场景管理 | T122 | `tests/e2e/test_process_baseline_ui.py` |
| 214 | 零回归与红线 | T117 / T123 | 全量套件断言（无真实 socket / 既有测试零改动 / diff 复核） |

## 4. 验证记录表（骨架，执行时逐行回填）

| 任务 | 定向 | 后端全量 | 前端构建 | e2e | 迁移往返 | 截图 | 结论 |
|---|---|---|---|---|---|---|---|
| T117 | `tests\process_baselines` **41 passed**（AC-197/210/211 全绿）；`tests\automation` **141 passed**（09 期零回归） | **1300 passed**（1259 + 41），串行，exit 0，463.09s | 未改动前端，**不涉及** | 不涉及 | 两库 `0025 → 0024 → 0025` **干净**，head 均 `0025`；**降级后 `prompt_templates.task_type` 只剩旧四值**、`process_baseline` 残留行 = 0 | 不涉及（纯后端） | 通过 |
| T118 | `tests\process_baselines` **90 passed**（T117 的 41 + 新增 49；AC-198/199/200/201 全绿）；上游定向（baselines / test_points / test_cases / automation / llm / incremental / common）**907 passed**，零回归 | **1349 passed**（1300 + 49），串行，exit 0，433.94s | `npm run build` 通过（**未改动前端**，仅回归确认） | 不涉及 | 不涉及（本任务不写迁移，两库 head 仍 `0025`） | 不涉及（纯接口，按「前台核对点」走真实 HTTP 栈等价核对） | 通过 |
| T119 | `tests\process_baselines` **118 passed**（T118 的 90 + 新增 28；AC-202/203 全绿）；上游定向（baselines / test_points / test_cases / automation / llm / incremental / common）**907 passed**，零回归 | **1377 passed**（1349 + 28），串行，exit 0，459.41s | `npm run build` 通过（**未改动前端**，仅回归确认） | 不涉及 | 不涉及（本任务不写迁移，两库 head 仍 `0025`） | 不涉及（纯接口，按「前台核对点」走真实 HTTP 栈等价核对） | 通过 |
| T120 | `tests\process_baselines` **147 passed**（T119 的 118 + 新增 29；AC-204/205/206 全绿，29 passed / 118 deselected）；上游定向（baselines / test_points / test_cases / automation / llm / incremental / common）**907 passed**，零回归 | **1406 passed**（1377 + 29），串行，exit 0（`1406/1464 collected，58 deselected`） | `npm run build` 通过（**未改动前端**，仅回归确认） | 不涉及 | 不涉及（本任务不写迁移，两库 head 仍 `0025`） | 不涉及（纯接口，按「前台核对点」走真实 HTTP 栈等价核对） | 通过 |
| T121 | `tests\process_baselines` **176 passed**（T120 的 147 + 新增 29；AC-207/208/209/210/211 全绿，29 passed / 147 deselected）；`tests\common\test_audit_coverage.py` **66 passed**（57 + 补 9 个场景）；上游定向（baselines / test_points / test_cases / automation / llm / incremental / common）**916 passed**（907 + 9），零回归 | **1444 passed**（1406 + 38），串行，exit 0，486.63s | `npm run build` 通过（**未改动前端**，仅回归确认） | 不涉及 | 不涉及（本任务不写迁移，两库 head 仍 `0025`） | 不涉及（纯接口，按「前台核对点」走真实 HTTP 栈等价核对） | 通过 |
| T122 | `tests\process_baselines` **176 passed**（**零改动**，本期纯前端）；新增 `tests\e2e\test_process_baseline_ui.py` **4 passed**（AC-212 1 条 + AC-213 3 条） | **1444 passed**（与 T121 持平，串行，exit 0，445.06s；`1444/1506 collected，62 deselected`） | `npm run build` 通过（`tsc -b && vite build`） | **62 passed**（原 58 + 新增 4），191.55s | 不涉及（本任务不写迁移，两库 head 仍 `0025`） | `.screenshots/T122/` **9 张**（文件名含 AC 编号） | 通过 |
| T123 | 10 定向 + 04~09 定向 待回填 | 待回填（≥ 1259 passed，串行，exit 0） | `npm run build` 待回填 | e2e 全量待回填（≥ 60 passed） | 两库 `0025 → 0024 → 0025` 待回填；降级后 `task_type` 只剩旧四值 | `.screenshots/T123/` 待回填 | 待回填 |

**基线口径（不可下调）**

- 后端全量：**≥ 1259 passed**，串行，exit 0，数量只增不减
- e2e 全量：**≥ 60 passed**（T122 起 ≥ 60）
- 迁移 head：两库均为 `0025`；`0025 → 0024 → 0025` 干净
- 04 / 05 / 06 / 07 / 08 / 09 定向回归：**0 failed**
- 既有 1259 条测试：**零期望值改动**
- 顶层 Tab：**仍是 10 个**（本期只加基线管理内的二级子菜单）

## 5. 完成定义（DoD）

对齐验证约定 §2 的五条，逐条落到本期：

- [ ] 每个任务开跑前 `dev_check.py` 通过
- [ ] 该任务的 `pytest -k ac_XXX` 通过
- [ ] 全量 pytest 通过，数量 ≥ 1259 且只增不减（**串行，exit 0**）
- [ ] Playwright 前台核对通过，截图含 AC 编号（`.screenshots/T122/` + `.screenshots/T123/`）
- [ ] AC-197 ~ AC-214 全部有测试或前台证据（AC 矩阵见 §3 与收官总结）
- [ ] 两库迁移往返干净，head `0025`；降级后 `prompt_templates.task_type`
      **只剩旧的四个值**
- [ ] 红线 diff 复核：上游模块零改动（只有 `app/llm/mock.py` 新增分支 +
      `app/models/incremental.py` 两行）；既有 e2e 文件零改动
- [ ] `PROGRESS.md`、`验证约定.md`、收官总结已更新
- [ ] 两笔显式欠账（流程基线标签 / 流程基线快照保留策略）已登记进 `PROGRESS.md` §6 Backlog
