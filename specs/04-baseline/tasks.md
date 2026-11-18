# 04 · 功能基线管理 · 任务清单

> 规格 [spec.md](./spec.md) ｜ 方案 [plan.md](./plan.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)

## 执行约定

1. 每个任务开始前重读 `spec.md` 对应 AC 与 `plan.md` 对应小节，不凭记忆写代码。
2. 先写用例再写实现；用例名带 AC 编号（`test_ac_62_module_tree`）。
3. 任务收尾跑：`-k ac_XX` → 全量 `.\.venv\Scripts\python.exe -m pytest`（数量只增不减）；
   全量可加 `-n auto` 并行（约 50s，串行 168s），排查偶发失败时改串行。
4. 前端可用后补 Playwright 前台核对，按 [../验证约定.md](../验证约定.md) 第 2 节落截图；
   前端未就绪时在任务行标「前台待补」，T66 统一补跑。
5. 提交信息用 `feat(baseline): …` / `test(baseline): …`，一个任务一个提交。
6. 开跑前先做环境自检：`.\.venv\Scripts\python.exe scripts\dev_check.py`；
   跑前台用例直接 `.\.venv\Scripts\python.exe scripts\run_e2e.py`（自检 → 起 8001/5174 →
   跑 `tests/e2e` → 收尾），有 `[FAIL]` 先修环境再动代码。
7. 失败一次收齐：一次跑完全部失败用例再集中修，修完先 `-k` 收窄、最后全量一次；
   不逐条「改一行 → 重跑全量」。
8. 前端新增交互元素带 `data-testid`（`区域-动作-目标`），e2e 优先 testid 定位，
   antd 内部类名只作兜底；单页组件超约 400 行或含 3 类以上弹窗时拆子组件。
9. e2e 的通用页面操作（树节点展开、Select 选择、弹窗定位、表单错误断言）用
   `tests/e2e/helpers.py`，不要在各用例文件里再抄一份；等待一律用 `expect`，不写固定 `wait_for_timeout`。

## 前置条件

| 项 | 状态 |
|---|---|
| 01-auth / 02-projects / 03-documents 已完成 | T1–T54 已验收 |
| 后端基线 | 468 passed（2026-11-16，T65 后；e2e 26 条单独跑，默认 `-m "not e2e"`） |
| 前端 | `D:\aitest_copilot\web`，项目详情页含「概览 / 成员 / 文档 / 基线管理 / 版本快照 / 申请」Tab |
| 数据库迁移 head | `0012`（04 基线五张表已建） |
| e2e 环境 | 8001 / 5174 + `aitest_copilot_e2e`，一条命令 `scripts/run_e2e.py`，见验证约定 §3 |

## 任务

- [x] **T55 · 数据模型与迁移**
  - 内容：`app/models/baseline.py` 五个模型（`BaselineModule` / `BaselineFunction` /
    `BaselineFeaturePoint` / `BaselineLabel` / `BaselineRevision`），字段与索引严格对齐 spec §4；
    `Project` 补 `baseline_snapshot_max_count`；迁移 `migrations/versions/0012_baseline.py`；
    注册到 `app/models/__init__.py`。
  - 产出：5 张表 + 1 个新列可 upgrade / downgrade / upgrade；`baseline_labels.active_key` 用
    STORED 生成列（`IF(status='active', CONCAT(...), NULL)`）+ 唯一索引。
  - 验证：`tests/baselines/test_models.py` 覆盖唯一约束、同名冲突、`active_key` 只约束生效标签、
    已清除标签可再打同类型、级联外键删除；全量 `pytest` 数量只增不减。
  - 前台：本期无页面入口，随 T65 一并核对。

- [x] **T56 · 模块管理**
  - 内容：`app/baselines/{schemas,service,router}.py` 骨架 + 模块增删改查；
    删除时功能数 > 0 → 409 `MODULE_NOT_EMPTY` + `extra.available_actions`；
    同项目模块名重复 → 409 `DUPLICATE_MODULE_NAME`；删除级联清功能点与标签。
  - 产出：读接口对成员/访客开放，写接口限项目管理员；归档项目写接口 409。
  - 验证：`-k "ac_62 or ac_64"` 覆盖建/改/删、重名、级联、非成员 403、member 403、归档 409。

- [x] **T57 · 功能与功能点**
  - 内容：功能 CRUD（挂在模块下，`version_no` 每次内容修改 +1）、功能点 CRUD（挂在功能下）；
    同模块功能名重复 409 `DUPLICATE_FUNCTION_NAME`、同功能功能点名重复 409 `DUPLICATE_FEATURE_POINT_NAME`；
    删功能级联删功能点与其标签。
  - 产出：`PATCH /functions/{id}` 只接受名称/描述/状态，追溯字段只读（传了 → 400 `TRACE_FIELDS_READONLY`）。
  - 验证：`-k "ac_62 or ac_63"`。

- [x] **T58 · 功能迁移**
  - 内容：`POST /modules/{module_id}/migrate` 批量迁移功能到同项目其他模块；
    目标不存在/跨项目/等于当前模块 → 400 `INVALID_MIGRATE_TARGET`；
    写 `moved_from_module_id` 保留追溯；审计 `baseline.module.migrate`。
  - 验证：`-k ac_65` 覆盖批量迁移成功、目标非法三种、追溯保留、审计落库。

- [x] **T59 · 两级打标**
  - 内容：`POST /labels` 打标（功能级 + 功能点级，四类标签）；`target_type`/`target_id` 必须存在且属本项目；
    标签类型不在四类 → 400 `INVALID_LABEL_TYPE`；同实体同快照同类型重复 → 409 `DUPLICATE_LABEL`；
    `GET /labels` 支持 `target_type`/`target_id`/`revision_id`/`status` 筛选，默认只返生效。
  - 产出：写入依赖 `baseline_labels.active_key` 唯一索引捕获冲突，不做应用层预查。
  - 验证：`-k ac_66` 覆盖功能级/功能点级独立、重复 409、非法类型、聚合提示数据。

- [x] **T60 · 标签清除与留痕**
  - 内容：`POST /labels/{id}/clear`，原因必填且 6 类枚举内（`other` 需备注）；
    行不删除，置 `status='cleared'` + 记清除人/时间/原因/备注；
    清除后再打同类型 → 新增生效行，原已清除行保留。
  - 产出：清除权限限项目管理员（PRD「标签清除限项目管理员或分析审核人本人」，分析审核人本期未上线）。
  - 验证：`-k "ac_67 or ac_68"` 覆盖必填、枚举外、`other` 缺备注、清除后行仍在、打标再清除、
    新旧快照隔离（级联清除默认关闭）。

- [x] **T61 · 审核流程与快照**
  - 内容：`POST /reviews/submit` → `status='submitted'`；`approve` → 冻结 `structure_json`、
    分配 `version_no`（`v1.{n}`）、写计数、复制上一快照的生效标签为新行；
    `reject` → 必填意见，不占版本号；提交者本人审核 → 403 `SELF_APPROVAL_FORBIDDEN`；
    重复审核 → 409 `INVALID_REVIEW_STATUS`。
  - 产出：`GET /revisions` 只列 approved；快照无更新接口。
  - 验证：`-k "ac_68 or ac_69 or ac_70"` 覆盖提交/通过/驳回/自审/重复审核、
    版本号递增、结构冻结后编辑不改快照、标签随快照复制与隔离。

- [x] **T62 · 保留策略与被引用即保护**
  - 内容：`GET/PATCH /retention` 读写 `baseline_snapshot_max_count`（空 = 不启用）；
    超出上限的最旧快照进待清理候选，不自动删；`DELETE /revisions/{id}` 被标签引用 → 409
    `SNAPSHOT_REFERENCED` + 引用明细；`GET /retention` 返回告警与被引用明细。
  - 产出：删除快照写审计 `baseline.snapshot.delete`；保留上限变更写 `baseline.retention.update`。
  - 验证：`-k "ac_71 or ac_72"` 覆盖默认不启用、上限生效、候选生成、关闭策略、被引用禁止删除、
    未被引用可删、告警文案、审计落库。

- [x] **T63 · 基线检索与概览计数**
  - 内容：`GET /functions` 支持 `module_id`/`source_type`/`label_type`/`keyword` 组合筛选；
    `get_overview` 的 `baseline_count` 改为已审核通过快照数；同步修正
    `tests/documents/test_overview_counts.py` 与 `tests/projects/test_overview.py` 断言。
  - 验证：`-k "ac_73 or ac_76"`。

- [x] **T64 · 审计覆盖**
  - 内容：`tests/common/test_audit_coverage.py` 清单补本期 action
    （`baseline.module.create/update/delete/migrate`、`baseline.function.create/update/delete`、
    `baseline.feature_point.create/update/delete`、`baseline.label.create/clear`、
    `baseline.revision.submit/approve/reject`、`baseline.snapshot.delete`、`baseline.retention.update`）；
    另加一条断言 `project_id`/`actor_id`/`target_type`/`target_id` 的用例。
  - 验证：该文件条数通过；全量 `pytest` 通过。

- [x] **T65 · 前端基线管理页**
  - 内容：`ProjectBaselineTree`（三级树 + 打标 + 清除 + 筛选）与 `ProjectBaselineSnapshots`
    （快照列表、提交审核、审核通过/驳回、保留策略、清理候选、告警）；
    `ProjectDetailPage` 插入「基线管理」Tab，原「基线」Tab 改名「版本快照」；
    `api/index.ts` 增类型与函数；`client.ts` 补错误码中文映射。
  - 产出：访客隐藏写操作按钮；`clear_reason` 下拉 6 类；`other` 时备注必填且前端也拦一道。
  - 验证：`npm run build` 通过；e2e `tests/e2e/test_baselines_ui.py` 覆盖建三级结构、打标、清除、
    提交与审核、快照列表；截图 `.screenshots/T65/`（16 张）。

- [x] **T66 · 全量回归与文档同步**
  - 内容：后端全量 pytest、前端构建、e2e 全量；同步 `specs/验证约定.md` 的前台状态与计数；
    复核 `spec.md` §2.3 待确认项是否需要调整。
  - 验证：三者全绿，计数写入验证约定。
  - 结果：后端 468 passed、`npm run build` 通过、e2e 26 passed；§2.3 复核结论见下。

- [x] **T67 · 快照引用保护扩展（收尾）** ✓ 2026-11-17
  - 内容：把「查引用」从单体函数拆成**来源解析器**架构，新建
    `app/baselines/references.py`；标签引用与增量分析引用各是一个解析器，
    后续测试点/用例/报告落地时只需再注册一个解析器。
    增量分析解析器探测 `incremental_analyses` 表是否存在——05 落地前跳过，
    落地后自动生效，04 无需再改。标签若由某次增量分析产出，
    其 `source_analysis_id` 随标签条目给出，不额外计为一处引用。
    错误文案按来源区分（标签引用 / 增量分析引用），前端补 `incremental_analysis`
    来源映射，并让 `SNAPSHOT_REFERENCED` 以服务端文案为准。
  - 产出：`app/baselines/references.py`、`tests/baselines/test_snapshot_references.py`（11 条）；
    `service.py` 的 `_snapshot_references` 改为委托。
  - 验证：`pytest -k ac_04_cleanup` 11 passed；全量 484 passed；e2e 29 passed；
    `npm run build` 通过。

## 04 补记 · 单人环境免审核（2026-11-18）

### 新增配置项 `allow_baseline_self_approval`（迁移 0018）

**背景**：PRD 要求「提交者不能审核自己的提交」（AC-69）。但本项目是**内部
测试环境**，系统里常常只有**一个**管理员账号（`admin`），此时：

```
admin 提交 → 只有 admin 能审 → admin 不能审自己 → 永久死锁
```

2026-11-18 用户裁决：加**开关**而不是改规则。

| 项 | 值 |
|---|---|
| 配置键 | `system_settings.allow_baseline_self_approval` |
| 默认值 | **True**（内部环境开箱即用） |
| 迁移 | `0018_allow_self_approval.py`（`down_revision="0017"`） |
| 生效范围 | `approve_review` 与 `reject_review` 两条路径 |
| 审计留痕 | `after_data.self_approved = true/false` |

**为什么两条路径都改**：只放开「通过」的话，「只能提交、不能驳回」仍是死路
——提交错了也撤不回来。

**为什么开关缺失时默认放行**（`_self_approval_allowed` 的 `except KeyError`）：
老库没跑 0018 时不至于 500，内部环境宁可能跑通。

**对外发布前**必须把默认值改回 False（或用 `set_setting` 关掉），
恢复 PRD 的双人复核语义。

### 实现要点

- 开关读 `system_settings`，走 `get_setting`（进程内缓存 60s）；
  改配置后最多 60s 生效，需要立即生效时用 `set_setting`（它会失效缓存）。
- `SelfApprovalForbidden` 错误码与 403 语义**完全保留**，只是触发条件变了。

### 验证

- `tests/baselines/test_reviews.py`：
  - `test_ac_69_self_approval_forbidden` —— 开关**关闭**时仍 403；
  - `test_ac_69_self_approval_allowed_when_switch_on` —— 开关**打开**时通过，
    且审计 `self_approved=True`；
  - `test_ac_69_self_reject_allowed_when_switch_on` —— 自审驳回也放行；
  - `test_ac_69_self_approval_switch_defaults_to_true` —— 默认值断言。
- 后端全量 **811 passed**（串行）。

## 04 待办 · 分点审核与从文档推导（2026-11-18 用户提出）

### TOD-03 · 分点审核（局部通过 / 局部驳回）

**现状**：审核是**整包**语义——一次提交 → 整体通过 / 整体驳回 → 冻结整棵结构。

**用户诉求**：管理员要能看到包裹里具体的模块 / 功能 / 功能点，
**勾选部分通过、局部驳回**。

**需要的改动**（跨数据模型 / 接口 / 前端，不是改前端就行）：

1. 新表 `baseline_review_items`：`revision_id` + `entity_type`
   （module / function / feature_point）+ `entity_id` + `decision`
   （approved / rejected）+ `comment`；
2. 审核接口要收「逐项决策」载荷，冻结时**只冻结通过的条目**；
3. 前端审核界面从「通过 / 驳回」两个按钮改成**带勾选框的三级树**
   + 批量通过 / 批量驳回；
4. 快照语义从「整包冻结」变成「子集冻结」。

**待定业务语义**（做之前必须先定）：「部分通过」的条目到底算不算进基线？
若算，05 的增量分析读的是**当前结构表**（`app/incremental/context.py`
的 `baseline_index`），不是快照——那么「部分通过」要生效，得改的是
**结构表**而不是快照，与「快照不可变」的原则冲突。这个语义要先裁决。

> **已实现（2026-11-18）**：[spec-phase4-review.md](./spec-phase4-review.md)。
> 验证记录见下方「T88–T98 验证记录」。关键结论：
> - 表结构：**新增 2 张表**（`baseline_review_rounds` / `baseline_review_items`），
>   **`structure_json` 格式不动**；结构表**不加** `node_status` 列
>   （状态是「某一轮审核的结论」，不是实体自身的属性）；
> - 快照：**只冻结 approved 节点**；驳回节点**留在草稿**（不删不藏，可编辑可重提）；
> - 05 清单：**排除**被驳回节点（`baseline_index()` 按 approved 集合过滤，
>   **只改读取口径，不动判定逻辑**）；
> - 前端：**不改 `ProjectBaselineTree.tsx`**——审核是独立界面，
>   在 `ProjectBaselineSnapshots.tsx` 里新增**审核抽屉**
>   （Checkbox + 顶部批量通过/驳回工具条）；
> - 任务：**T93–T98**（见方案 §9）。

### TOD-04 · 从文档推导基线

spec §2 明确「文档推导、基线反推本期不做（依赖 LLM，见 05）」。
06 期 LLM 已通（迁移 0017 + `OpenAICompatProvider`），技术上可行，
但**从未实现**。

数据模型已预留追溯字段：`source_type='document_derived'`、
`source_document_id` / `source_version_id` / `source_chapter_id` /
`source_method` / `source_analysis_id`。

跨 03 + 04 两个模块，建议单独立项。

> **已实现（2026-11-18）**：[spec-phase4-derive.md](./spec-phase4-derive.md)。
> 验证记录见下方「T88–T98 验证记录」。关键结论：
> - **不新增结构表**——04 的结构表已预留全部追溯字段，本期只加
>   `baseline_derives`（推导记录）+ `baseline_derive_candidates`（候选草稿）两张表；
> - 推导结果**先落候选草稿**，用户确认后才进结构表（模型会抽错，直接落会污染 05 的比对基准）；
> - 同名冲突**绝不覆盖**：提示用户选 复用 / 改名新建 / 跳过；
> - **同步执行**（与 05 一致）；坏 JSON **整次失败**，抽不出内容不算失败；
> - 走 05 已有的 `get_provider` 工厂（无配置 → 自动降级 Mock）与
>   `task_type='document_parse'`（枚举里已预留，至今没人用过）；
> - 采纳后的节点**和手工建的一模一样**，走**同一套审核流程**；
> - 任务：**T88–T92**（见方案 §10）。

### 两个方案的落地顺序与迁移编号

**2026-11-18 用户裁决：先做从文档推导。**

```
T88–T92  从文档推导   -> 迁移 0020_baseline_derive（down_revision = 0019）
T93–T98  分点审核     -> 迁移 0021_review_items（down_revision = 0020）
```

- 两个方案**串行落地，不并行**（都改 `ProjectBaselineTree.tsx` /
  `ProjectBaselineSnapshots.tsx`，并行会撞）；
- AC 编号：从文档推导占 **AC-122~AC-131**，分点审核占 **AC-132~AC-140**；
- 已裁决事项分别见两份方案的「已裁决事项」章节。

## T67 验证记录（2026-11-17）
| 项 | 结果 |
|---|---|
| `pytest -k ac_04_cleanup` | 11 passed（502 deselected） |
| 后端全量 pytest | **484 passed**（473 + 新增 11），`-n 4` 47.00s |
| 前端构建 | `npm run build` 通过（1.50s） |
| e2e 全量 | 29 passed（`scripts/run_e2e.py`；快照引用保护的既有前台断言未受影响） |
| 推送 | 先把此前 17 个未推送提交推到远端（`db0b09b..683cfed`），本地与远端同步 |

### 实现要点

- **一条引用 = 一件可处理的事**：引用列表每项都要对应一个管理员能执行的动作
  （清掉这条标签 / 这份快照是某次分析的比对基准）。同一条标签若带
  `source_analysis_id`，来源信息挂在该条目上，不额外算一条引用——
  否则「引用数」虚高，管理员会以为有两处要处理。
- **05 尚未落地也能测**：MySQL 里没有 `incremental_analyses` 表，
  测试用内存 SQLite（`StaticPool` + `check_same_thread=False`）
  单独造一张，替换解析器指向它来验证「表存在时」的分支，
  不动生产 schema。
- **MySQL DDL 隐式提交**会破坏 pytest 夹具的外层事务，
  所以造表必须在夹具事务开始之前完成——这条约束在测试里用独立引擎规避。


## T88–T98 验证记录（2026-11-18）

| 项 | 结果 |
|---|---|
| 迁移 | 开发库 / e2e 库 head 均到 `0021`（`0020_baseline_derive` → `0021_review_items`） |
| 后端全量 pytest | exit 0（新增 `tests/baselines/test_derive.py` 22 条、`test_review_items.py` 13 条） |
| `tests/baselines` | **115 passed** |
| 前端构建 | `npm run build` 通过 |
| e2e 全量 | **39 passed**（`scripts/run_e2e.py`，135.67s，自动清理 `e2e-` 数据） |
| 真实网络 | 零（推导走 `get_provider`，测试用 `MockProvider`；分点审核不调模型） |

### 实现要点（与方案的偏差）

- **模块行没有追溯列**：`baseline_modules` 只有 `source_type`，没有
  `source_document_id` / `source_version_id` / `source_chapter_id`。按「结构表零改动」
  红线，推导采纳时**只在功能/功能点写完整追溯**，模块只写
  `source_type='document_derived'`。
- **轮次号是项目级单调递增**：`submit_review` 取 `max(round_no) + 1`，
  满足 AC-134「重提后是第 2 轮」；`(revision_id, round_no)` 唯一索引不变。
- **新一轮不隐式继承旧决策**：后端只存本轮 items；§4.3 的「上一轮 approved 预选」
  属于展示层（抽屉打开时全部 pending，旧决策走 `GET /items` 回看）。
- **`ReviewItemDecision` 枚举用 `str`**：非法值要落 400 业务码
  （`INVALID_REVIEW_ITEM` / `INVALID_REVIEW_DECISION`），用 `Literal` 会被
  Pydantic 先拦成 422。
- **修 2 处全表审计断言**：`tests/incremental/test_second_pass_flow.py` 改用
  `project_id` 过滤——开发库有历史审计行时全表查询会命中别的项目。

### 任务对照

| 任务 | 产出 |
|---|---|
| T88–T89 | `app/models/baseline_derive.py`、迁移 `0020` |
| T90 | `app/baselines/derive.py`（纯引擎）+ `service.run_document_derive` / `adopt_derive_candidates` |
| T91 | 前端「从文档推导」按钮 + 选择弹窗 + 候选抽屉（`BaselineDerive*`） |
| T92 | `tests/baselines/test_derive.py` 22 条 |
| T93 | `app/models/baseline_review.py`、迁移 `0021` |
| T94 | `approval.py` 生效集合 + `baseline_index()` 读取口径 |
| T95 | `service.decide_review` / `list_review_tree` / `list_review_items` + 按 items 冻结 |
| T96 | `BaselineReviewDrawer.tsx` + `baselineReviewNodes.tsx`；快照页新增「分点审核」入口 |
| T97 | `tests/baselines/test_review_items.py` 13 条（AC-132~139） |
| T98 | 全量回归 + 两端迁移升级 + 文档回填 |

## T66 验证记录（2026-11-16）

| 项 | 结果 |
|---|---|
| 后端全量 pytest | 473 passed，29 deselected（`-m "not e2e"`）；串行 168s，`-n 4` 约 50s |
| 前端构建 | `npm run build` 通过（`tsc -b` + `vite build`，1.50s；仅 chunk >500 kB 提示） |
| e2e 全量 | 29 passed（`scripts/run_e2e.py`，会话收尾自动回收 `e2e-` 数据；含 AC-73 / AC-74 与 §2.3 归档模块） |
| 环境自检 | `scripts/dev_check.py --expect-db e2e` 通过（8001 连 `aitest_copilot_e2e`） |

### `spec.md` §2.3 复核结论

| 待确认项 | 结论 |
|---|---|
| 1 版本号 `v1.{n}` | 与实现一致（后端 `version_no` 从 0 起，前端 `formatSnapshotVersion` 渲染 `v1.0`） |
| 2 审核与快照合表 | 一致（`baseline_revisions` 一行两义，`status=approved` 才冻结 `structure_json`） |
| 3 写接口限项目管理员 | 一致（04 全部写接口走 `_ensure_admin`，读接口对成员/访客开放） |
| 4 自审 403 | 一致（`SELF_APPROVAL_FORBIDDEN`） |
| 5 模块 `active`/`archived` | 一致（T66 补齐：列表/功能/快照默认排除归档模块，前端加归档入口与状态筛选；`tests/baselines/test_archived_modules.py` 5 条） |
| 6 被引用即保护只查标签 | 一致（`SNAPSHOT_REFERENCED` + `refs` 明细，含对象名称） |

未覆盖：无。AC-73（组合筛选）与 AC-74（权限矩阵）已在 T66 补前台用例
（`test_ac_73_filter_ui` / `test_ac_74_permission_matrix_ui`）；AC-73 的 `module_id` 维度
前端未设控件，由后端用例覆盖。

## T65 验证记录（2026-11-16）

| 项 | 结果 |
|---|---|
| `npm run build` | 通过（`tsc -b` + `vite build`，1.50s） |
| e2e `tests/e2e/test_baselines_ui.py` | 6 passed（AC-62 / AC-64 / AC-65 / AC-66+67 / AC-69+70 / AC-71+72） |
| `tests/baselines` | 61 passed（新增 3 条：revisions 状态过滤、labels 状态过滤、快照 404 口径） |
| 截图 | `.screenshots/T65/`，16 张 |
| 提交 | `61b3996` / `327e4a0` / `e713213` |

### 前台核对暴露的真实缺陷（已修）

1. **打标成功后弹窗不关闭** —— 遮罩挡住树节点，用户打完一个标就得手动关窗。改为成功后 `setLabelModal({open:false})`。
2. **表单校验失败弹「请求失败」** —— `validateFields()` 抛的是 `{errorFields}` 而非 Error，被当成接口异常。改为 `isValidationError()` 识别后就地返回，校验提示只走字段下方。
3. **模块层不展开** —— `defaultExpandAll` 对异步 `treeData` 无效（rc-tree 只在首次渲染生效），功能行与「新增功能点」入口根本露不出来。改为受控 `expandedKeys`，reload 后把 `m-{id}` 并入，并用 `collapsedRef` 记住用户手动收起的模块。
4. **版本号显示成 `V0`** —— 后端 `version_no` 从 0 起（`_next_version_no`），前端拼的是 `V{n}`。按 spec §2.3.1 统一成 `v1.{n}`（`v1.0`、`v1.1`），抽到 `baselineShared.ts` 共用。
5. **UI 暴露内部主键** —— 标签行显示「快照 #3」、候选表引用来源显示「baseline_function #7」。改为快照版本号 + 引用对象业务名称。
6. **快照接口错误码** —— `_load_revision` 一律抛 `REVIEW_NOT_FOUND`，与 spec §7 不符；按调用方语义拆成 `SNAPSHOT_NOT_FOUND` / `REVIEW_NOT_FOUND`。

### 测试环境注意（本轮踩过）

- 8001 端口被连**开发库**的旧 uvicorn 占住时，e2e 前台看起来全通，数据却写进开发库（本轮污染过一次，已按项目名前缀回滚）。`tests/e2e/conftest.py` 加了 session 级守卫：用后端 API 造探针项目，再去两个库确认落点，写错库直接拒绝开跑。
- Vite dev server 默认只绑 IPv6 `::1`，Chromium 解析 `localhost`→127.0.0.1 连不上，必须 `--host 127.0.0.1`。

## T55–T64 验证记录（2026-11-16）

| 项 | 结果 |
|---|---|
| 后端全量 pytest | 465 passed（`--ignore=tests/e2e`；e2e 需前端 5174 在跑，本轮未跑） |
| `tests/baselines` | 58 passed（新增 7 个文件：conftest / helpers / 6 个 AC 文件 + test_overview） |
| `tests/common/test_audit_coverage.py` | 47 passed（清单从 27 个 action 扩到 45 个） |
| 提交 | `7d12c1f` / `ed99ca1` / `1876cea` / `64162bf` / `5d03559` |
| 前台 | 待补（T65 一并核对；T65/T66 本轮未做） |

### 本轮修掉的阻断性缺陷（T56–T62 代码此前从未跑过测试）

1. **service 层无 `session.commit()`** —— 生产写入被 `get_db` 的 `session.close()` 静默回滚，数据不落库。17 个写函数末尾补 commit（顺序：改数据 → flush → `write_audit` → commit）。
2. **唯一索引冲突分支调 `session.rollback()`** —— 会把同会话此前已写入的数据一起抹掉。改为 `session.begin_nested()` 保存点守卫（`_guarded_insert` / `_guarded_update`）；**属性修改必须写在保存点内部**，冲突时 ORM 状态才会随保存点回滚还原。
3. **`delete_function` 未删功能点子行** —— 外键悬空导致 MySQL 1452。
4. **AC-63 未实现** —— 追溯字段被 Pydantic 静默忽略并返 200。改为写模型 `extra="allow"` + 业务层判定，命中即 400 `TRACE_FIELDS_READONLY`（响应带 `fields` 明细）。
5. **列表接口返回裸 list** —— 与 plan §4 不符。4 个列表接口统一改为 `{items,total,page,page_size}` 分页信封，`total` 为过滤后条数。
6. **`FunctionOut.module_name` 硬编码空串** —— 新建/改/迁移接口现在返回真实模块名。
7. **`clear_label` 对已清除标签抛 `INVALID_LABEL_TYPE`** —— code 与语义不符。改为 409 `LABEL_ALREADY_CLEARED`（spec §7 已补该行）。
8. **`get_retention` 候选只给计数** —— 补 `refs` 引用来源明细（AC-72）。

### 与原方案的偏差

- 列表形状：原 plan 写「不做分页」，本轮按裁决改为统一分页信封，spec §8 已同步表述（限定为「快照 structure_json 内部不分页」）。
- `RevisionDetail.structure` 类型由 `dict` 改为 `list[dict]`（实际存的是模块树数组）。
- 标签唯一性仍走 DB 生成列 `active_key` + UNIQUE，未加应用层预查（避免与并发写入竞态）。
- `get_revision` / `delete_revision` 找不到记录时抛 `REVIEW_NOT_FOUND` 而非 spec §7 里的 `SNAPSHOT_NOT_FOUND`，本轮未改口径（两者都是 404），T66 复核。
