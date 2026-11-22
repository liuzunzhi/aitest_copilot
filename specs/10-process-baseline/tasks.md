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
- `git diff --stat app\models\incremental.py` → **只有 2 行**（TASK_TYPES + CHECK 字符串）
- **既有测试零回归**：`pytest tests\baselines tests\llm tests\incremental -q` 全绿
  （既有期望值未用到新枚举值）

**前台核对点**：本任务只改后端与两处前端无关的常量。等价核对——
浏览器打开「系统设置」页 → 提示词模板面板，**多出一条** `task_type='process_baseline'`
的模板「流程基线推导·场景抽取」，且**编辑它**不影响其它类型的模板。

**AC**：AC-197、AC-210、AC-211、AC-214
**提交**：`feat(process-baseline): 建表 0025 与流程基线提示词模板`

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
| T117 | `tests\process_baselines` 待回填 | 待回填 | `npm run build` 待回填 | 不涉及 | 两库 `0025 → 0024 → 0025` 待回填 | 不涉及（纯后端） | 待回填 |
| T118 | `tests\process_baselines` 待回填 | 待回填 | `npm run build` 待回填 | 不涉及 | 不涉及 | 不涉及（纯接口） | 待回填 |
| T119 | `tests\process_baselines` 待回填 | 待回填 | `npm run build` 待回填 | 不涉及 | 不涉及 | 不涉及（纯接口） | 待回填 |
| T120 | `tests\process_baselines` 待回填 | 待回填 | `npm run build` 待回填 | 不涉及 | 不涉及 | 不涉及（纯接口） | 待回填 |
| T121 | `tests\process_baselines` + `tests\common` 待回填 | 待回填 | `npm run build` 待回填 | 不涉及 | 不涉及 | 不涉及（纯接口） | 待回填 |
| T122 | `tests\process_baselines` 待回填 | 待回填 | `npm run build` 待回填 | e2e 全量待回填（原 58 + 新增 ≥ 2） | 不涉及 | `.screenshots/T122/` 待回填 | 待回填 |
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
