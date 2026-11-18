# 05 · 增量分析（第二期 · 第二遍全局裁决）· 任务清单

> 规格 [spec-phase2.md](./spec-phase2.md) ｜ 方案 [plan-phase2.md](./plan-phase2.md) ｜ 一期 [tasks.md](./tasks.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)

## 执行约定

1. 每个任务开始前重读 `spec-phase2.md` 对应 AC 与 `plan-phase2.md` 对应小节，不凭记忆写代码。
2. 先写用例再写实现；用例名带 AC 编号（`test_ac_89_point_scope_prompt`）。
3. 任务收尾跑：`-k ac_8X` → 全量 `.\.venv\Scripts\python.exe -m pytest`（数量只增不减，一期基线 **516**）。
4. 前端可用后补 Playwright 前台核对，截图落仓库根 `.screenshots/T7X/`；未就绪时在任务行标「前台待补」，T77 统一补跑。
5. 提交信息用 `feat(incremental): …` / `test(incremental): …`，一个任务一个提交。
6. 开跑前环境自检：`.\.venv\Scripts\python.exe scripts\dev_check.py`；
   前台直接 `.\.venv\Scripts\python.exe scripts\run_e2e.py`（自检 → 8001/5174 → `tests/e2e` → 收尾）。
7. 失败一次收齐：先跑完全部失败用例再集中修；修完先 `-k` 收窄、最后全量一次。
8. 前端新增交互元素带 `data-testid`（`区域-动作-目标`）；单页组件超约 400 行时拆子组件。
9. e2e 通用页面操作走 `tests/e2e/helpers.py`，等待一律用 `expect`，不写固定 `wait_for_timeout`。
10. **本期红线**（spec-phase2 §2.2）：零真实网络请求、不做模板管理 UI/CRUD、不写 `baseline_labels`、
    不生成新快照、不自动裁决冲突、不顺手改 03/04 无关模块。越界即返工。

## 前置条件

| 项 | 状态 |
|---|---|
| 一期 | T68–T70 已验收（后端 516 passed、e2e 31 passed、构建通过） |
| 迁移 head | `0013`（第二期用 `0014` / `0015`） |
| 模型/引擎 | `app/models/incremental.py`、`app/incremental/{context,engine,service,router}.py`、`app/llm/` |
| 04 引用解析器 | 已含 `incremental_analyses`，本期不新增引用来源 |
| e2e 环境 | 8001 / 5174 + `aitest_copilot_e2e`，截图 `.screenshots/` |

## 任务

- [x] **T71 · 章节引用图（0014 + 抽取 + 接口）**
  - 内容：
    - `app/models/chapter_link.py`：`DocumentChapterLink`（字段 / 双唯一键 / 目标二选一 Check）。
    - `migrations/versions/0014_chapter_links.py`，`down_revision="0013"`，`downgrade` 直接删表。
    - `app/incremental/links.py`：规则抽取（「见第 X 章」「详见/参见」「依赖/前置」→ `references` /
      `depends_on`；正文命中功能点名称 → `mentions_entity`），解析章节序号时丢弃 `from == to` 与不存在序号；
      幂等：按 `(version_id, source='rule')` 先删后插。
    - `app/incremental/links_router.py`：`GET /links`、`POST /links`、`POST /links/extract`，
      前缀 `/api/projects/{project_id}/documents/{document_id}/versions/{version_id}/links`；
      注册进 `app/main.py`。
    - `app/common/errors.py`：`INVALID_CHAPTER_LINK` / `DUPLICATE_CHAPTER_LINK` + `__all__`。
    - 补链写审计 `document.chapter_link.create`；`tests/common/test_audit_coverage.py` 补该 action。
  - 产出：AC-86 / AC-87 可断言；引用图可读、可补、可幂等重抽。
  - 验证：`tests/incremental/test_chapter_links.py`，`-k "ac_86 or ac_87"`。

- [x] **T72 · 第二遍模型与迁移（0015 + 模板种子 + 响应字段）**
  - 内容：
    - `app/models/incremental.py` 追加 `IncrementalDecision` / `IncrementalConflict`；
      `IncrementalAnalysis` 加 `second_pass_template_id/status/stats/error_code/error_message/started_at/finished_at`；
      常量 `DECISION_TYPES` / `CONFLICT_TYPES` / `CONFLICT_STATUSES`；同步 `app/models/__init__.py`。
    - `migrations/versions/0015_incremental_second_pass.py`，`down_revision="0014"`：
      建两表 → `ALTER incremental_analyses` → 播种第二遍模板
      （`name='增量分析·第二遍·按点分治'`、`[INCREMENTAL_2B_SYSTEM]` / `[INCREMENTAL_2B_USER]` 前缀）；
      `downgrade` 反序。
    - `app/incremental/schemas.py`：`AnalysisOut` 追加第二遍字段（只追加）；
      `ChapterLinkOut/Create`、`DecisionOut`、`ConflictOut/Resolve`。
  - 产出：3 表可 upgrade / downgrade / upgrade；第二遍模板唯一；一期接口响应兼容。
  - 验证：`tests/incremental/test_second_pass_models.py`（约束、级联、模板种子、老记录 `second_pass_status IS NULL`）。

- [x] **T73 · 2b-1 功能点索引 + 2b-2 按点分治**
  - 内容：
    - `app/incremental/context2b.py`：第二遍 Prompt 组装，`user` 固定为
      `模板.user_prompt + "\n\n## 功能点：{name}\n## 局部结论\n…\n## 关联章节\n…"`；
      只带该功能点及其所属功能的结论，章节只给标题 + 截断摘要。
    - `app/incremental/second_pass.py`：`build_point_index`（按目标聚合 + 功能→点 + 引用图）、
      `run_point_pass`（证据一致性判定 → 一致才调 Mock；解析、`decision` 三值校验、
      `new_points` 收集；矛盾目标直接写冲突候选）。
    - `app/llm/mock.py`：加第二遍默认响应（按 `[INCREMENTAL_2B_SYSTEM]` 前缀识别，一期不变）。
    - 失败语义：非 JSON / 非法 decision → `LLM_OUTPUT_INVALID`，整次第二遍终止。
  - 产出：AC-89（小输入作用域）/ AC-90（new 来源）/ AC-91（冲突判定）在引擎层可断言。
  - 验证：`tests/incremental/test_second_pass_index.py` + `test_second_pass_engine.py`，
    `-k "ac_89 or ac_90 or ac_91"`；Mock 断言 `calls[-1].user` 不含其他功能点 id。

- [x] **T74 · 2b-3 图传播与冲突合并**
  - 内容：
    - `second_pass.py` 追加 `propagate_impacts`：`references` / `depends_on` 一跳传播；
      源章节 `changed` / `affected` → 目标章节目标写 `possible_impact` 候选；
      `mentions_entity` 不传播。
    - 同目标 `conflict` + `possible_impact` 合并为 `conflict`，候选按
      `(label_type, source)` 去重；传播命中已有 `decisions` 的目标时删除该行并并入候选，
      保证同一目标只出现在 `decisions` / `conflicts` 之一。
  - 产出：AC-92 可断言；传播只做一跳。
  - 验证：`-k "ac_92"`（引擎层直接构造章节 / 链接 / 结论）。

- [x] **T75 · 第二遍服务与接口**
  - 内容：
    - `service.run_second_pass`：固定校验顺序（§5.2）→ 置 running → 无 rule 边时自动抽取 →
      重跑先删后建 → 2b-1/2/3 → 回填 `second_pass_stats`；
      失败置 `failed` + `second_pass_error_*`，保留已产出结果。
    - `service.list_decisions` / `list_conflicts`（分页信封）。
    - `router.py`：`POST /analyses/{id}/second-pass`、`GET /decisions`、`GET /conflicts`。
    - 审计 `incremental.second_pass.run`；`SCENARIOS` 补该 action。
  - 产出：AC-88 / AC-94 / AC-95（第二遍部分）/ AC-96 / AC-97 可断言。
  - 验证：`tests/incremental/test_second_pass_flow.py`，
    `-k "ac_88 or ac_94 or ac_95 or ac_96 or ac_97"`。

- [x] **T76 · 人工裁决接口**
  - 内容：
    - `service.resolve_conflict`：`confirmed` 必带 `label_type`、`rejected` 不允许带；
      只改冲突行（`status/resolved_*`），**不写 `baseline_labels`**。
    - `router.py`：`POST /analyses/{id}/conflicts/{conflict_id}/resolve`；
      错误码 `CONFLICT_NOT_FOUND` / `CONFLICT_ALREADY_RESOLVED` / `INVALID_CONFLICT_RESOLUTION`。
    - 审计 `incremental.conflict.resolve`；`SCENARIOS` 补齐三个 action。
  - 产出：AC-93 可断言（含 `baseline_labels` 行数不变）。
  - 验证：`-k "ac_93"`。

- [x] **T77 · 前端最小展示（第二遍 + 引用图）**
  - 内容：
    - `web/src/api/index.ts` 追加 `/* ---- 增量分析第二期 ---- */`：类型 + 7 个函数；
      `client.ts` 补 8 个错误码中文映射。
    - `web/src/pages/IncrementalSecondPass.tsx`：状态、触发按钮（admin / 第一遍成功）、
      裁决表 `incremental-decision-table`、冲突表 `incremental-conflict-table`、
      确认 / 驳回弹窗（确认需选标签）；有 pending 冲突时禁用触发。
    - `ProjectIncrementalDrawer.tsx` 挂载第二遍区块；保持主文件 400 行内。
    - `ProjectDocumentsTab.tsx`：版本行「引用图」按钮 + 抽屉（列表 / 管理员补链）。
    - `data-testid`：`incremental-second-pass-btn`、`incremental-conflict-resolve-btn-{id}`、
      `chapter-link-btn-{versionId}`、`chapter-link-create-btn`。
  - 产出：页面可发起第二遍、看裁决与冲突、完成裁决；可看 / 补引用图。
  - 验证：`npm run build`；`tests/e2e/test_incremental_second_pass_ui.py`
    （`@pytest.mark.task("T77")`）：发起第二遍 → 裁决 / 冲突出现 → 确认一条 → 状态更新；
    访客只读；截图 `.screenshots/T77/`。

- [x] **T78 · 收尾**
  - 内容：全量 pytest 串行、e2e 全量、`dev_check.py --expect-db e2e`、`npm run build`；
    更新 `specs/验证约定.md`（§5.5 第二期核对点 + 变更记录）、`PROGRESS.md` 计数、
    本文件验证记录与实现要点；确认断网可跑（AC-97）。
  - 产出：验证记录齐全，迁移 head `0015`，计数只增不减。

## 收尾（随 T78 完成）

| 项 | 期望 | 实际 |
|---|---|---|
| 后端全量 pytest | ≥ 516 passed（新增约 25–30 条） | **589 passed**（新增 73 条） |
| 前端 `npm run build` | 通过 | 通过 |
| e2e 全量 | 31 + 新增 1~2 条，全绿 | **34 passed**（新增 3 条） |
| `scripts/dev_check.py --expect-db e2e` | 通过 | 通过（`run_e2e.py` 内置自检，两库均在 0015） |
| 离线可跑 | 断网 / 不配置 provider 时全绿（AC-97） | 通过（`second_pass_stats.provider` 恒为 `mock`，零真实网络请求） |
| 迁移 | `0013 → 0015`，可 upgrade / downgrade / upgrade | 通过（`0015 → 0014 → 0015` 往返验证） |
| 红线 | 未写真实网络请求、未做模板管理、未写 `baseline_labels` / 新快照 | 全部遵守（AC-93 断言 `baseline_labels` 行数不变） |

## 验证记录

| 任务 | 后端定向 | 后端全量 | 前端构建 | e2e | 截图 |
|---|---|---|---|---|---|
| T71 | 12 passed（`-k "ac_86 or ac_87 or ac_96 or chapter_link"`） | 528 passed | — | — | — |
| T72 | 19 passed（模型两文件） | 540 passed | — | — | 0015 upgrade→downgrade 0014→upgrade 通过 |
| T73 | 9 passed（index + engine） | 549 passed | — | — | — |
| T74 | 8 passed（propagation） | 557 passed | — | — | — |
| T75 | 14 passed（flow + 审计场景） | 572 passed | — | — | — |
| T76 | 17 passed（resolve + 审计场景） | 589 passed | — | — | — |
| T77 | — | 589 passed | build 通过 | 34 passed（新增 3 条） | `.screenshots/T77/` 5 张 |
| T78 | — | **589 passed**（串行） | build 通过 | **34 passed**（全量） | `.screenshots/T77/` 5 张 |

**收尾复验命令与结果**（2026-11-17）：

```powershell
.\.venv\Scripts\python.exe scripts\dev_check.py                  # 两库迁移均在 0015，环境自检通过
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -rN
# → 589 passed, 34 deselected, 1 warning in 156.36s
.\.venv\Scripts\python.exe scripts\run_e2e.py
# → 环境自检通过（8001 实连 aitest_copilot_e2e）；34 passed in 92.73s
cd web; npm run build                                            # → ✓ built in 1.50s
```

> `dev_check.py --expect-db e2e` 单独跑会因 8001 未起而报 `[FAIL]`（它要的是**活着的**
> e2e 后端）；`scripts/run_e2e.py` 会先起服务再自检，因此以它为准。

## 实现要点

- **T71**：迁移 head 推进到 `0014`。新增 `app/models/chapter_link.py`、`app/incremental/links.py`、
  `app/incremental/links_router.py`；`schemas.py` 追加 `ChapterLinkCreate/Out`（`link_type` 用普通
  `str`，非法值在服务层报 400，避免 pydantic 变成 422）；`errors.py` 增 `InvalidChapterLink` /
  `DuplicateChapterLink`。抽取序号解析：标题自带编号时按编号路径匹配（精确 → 前缀），
  全无编号时退化为「第 N 章 = 第 N 个一级章节」；解析不到 / 自引用直接丢弃。
  人工边优先：规则重抽命中同一条（同源同类型同目标）时跳过，避免撞唯一键。
- **T72**：head 推进到 `0015`。`incremental_decisions` 唯一键 `uk_idecisions_target`；
  `incremental_conflicts` 不建唯一键，目标 Check 为
  `(new AND target_id IS NULL) OR (非 new AND target_id IS NOT NULL)`；
  `second_pass_status` 为 NULL 表示未跑，Check 只允许三值。
  downgrade 顺序：删两表 → 删 FK/Check → 逐个 drop_column → 删模板行（MySQL 不允许
  直接删被外键引用的列）。因第二遍模板同属 `task_type='incremental'`，
  `helpers.seed_template` 与审计用例改为按模板名取第一遍模板。
- **T73**：新增 `context2b.py`（固定锚点 `## 功能点：` / `## 功能：`，摘要截断）与
  `second_pass.py`（`PointIndex` / `build_point_index` / `participating_targets` /
  `scoped_conclusions` / `run_point_pass`）。引擎只算不写库，返回 `PendingDecision` /
  `PendingConflict`；证据标签不一致时不调模型，`prompted_count` 即 Mock 调用数。
  功能点作用域并入其所辖功能的结论，因此「功能级 changed + 点级 unchanged」会直接成冲突。
  `MockProvider` 按 `[INCREMENTAL_2B_SYSTEM]` 前缀返回第二遍默认响应
  （`unchanged` / 0.5），一期默认响应不变。
- **T74**：`second_pass.py` 追加 `propagate_impacts(index, result)`，就地改写 2b-2 的结果：
  只沿 `references` / `depends_on` 走一跳，源章节有 `changed` / `affected` 才触发；
  传播候选 `label_type='affected'`、`source='chapter:{from_chapter_id}'`。
  命中已有 `decisions` 的目标 → 删除该裁决、原标签与置信度并入候选；
  与 2b-2 产的 `conflict` 合并时保持 `conflict` 类型（人工裁决优先级更高），
  候选按 `(label_type, source, rationale)` 去重，重复传播不产生重复冲突。
- **T75**：`service.run_second_pass` 按固定顺序校验（项目 → 归档 → 角色 → 分析存在 →
  第一遍 succeeded → 模板可用 → 无 pending 冲突），随后置 `second_pass_status='running'`，
  无规则边时自动抽一次引用图，重跑先删旧裁决 / 冲突再重建，跑 2b-1/2b-2/2b-3 后回填
  `second_pass_stats` 与 `finished_at`，并写 `incremental.second_pass.run` 审计。
  失败时置 `failed` + `second_pass_error_*`，第一遍 `status` 不受影响。
  第二遍模板按名字前缀 `增量分析·第二遍%` + `status='active'` 取最新一条
  （与第一遍同属 `task_type='incremental'`，不能靠 task_type 区分）。
  新增错误码 `SECOND_PASS_NOT_READY` / `SECOND_PASS_TEMPLATE_MISSING` /
  `SECOND_PASS_CONFLICTS_PENDING`；接口 `POST .../second-pass`、`GET .../decisions`、
  `GET .../conflicts`。
- **T76**：`service.resolve_conflict` 只改冲突行本身
  （`status` / `resolved_label_type` / `resolved_by` / `resolved_at`），
  **不写 `baseline_labels`**（AC-93 断言行数不变）。
  入参校验：只允许 `confirmed` / `rejected`；`confirmed` 必带 `label_type`
  （三选一），`rejected` 不允许带 → 否则 400 `INVALID_CONFLICT_RESOLUTION`。
  冲突不存在 / 不属于该分析 → 404 `CONFLICT_NOT_FOUND`；已裁决 → 409
  `CONFLICT_ALREADY_RESOLVED`。校验顺序与第二遍一致：项目 → 归档 → 角色 →
  分析存在 → 冲突存在 → 未裁决 → 入参合法。
  新增错误码 `CONFLICT_NOT_FOUND` / `CONFLICT_ALREADY_RESOLVED` /
  `INVALID_CONFLICT_RESOLUTION`；审计 `incremental.conflict.resolve`。
- **T77**：新增 `IncrementalSecondPass.tsx`（第二遍状态 / 触发 / 裁决表 / 冲突队列 /
  确认弹窗）与 `ChapterLinkDrawer.tsx`（引用图列表 + 补链 + 重抽）；
  `ProjectIncrementalDrawer.tsx` 挂载第二遍区块并加「第二遍」描述项；
  `ProjectDocumentsTab.tsx` 版本行加「引用图」入口。
  `web/src/api/index.ts` 追加第二期类型与 7 个函数，`client.ts` 补 8 个错误码中文映射；
  `incrementalMeta.tsx` 追加第二遍状态 / 冲突类型 / 冲突状态 / 链接类型的 Tag 元数据。
  `ProjectDocumentsTab.tsx` 因加入口涨到 403 行，把纯渲染的 `ChapterNodes`
  抽到 `chapterNodes.tsx`（回到 387 行，符合 400 行阈值）。
  e2e：`tests/e2e/test_incremental_second_pass_ui.py` 三条（触发第二遍 → 裁决 / 冲突可见
  → 确认一条 → 状态更新；访客只读；引用图列表与补链），
  `support.py` 补 `seed_chapter_links` / `seed_second_pass_rows`，
  cleanup 语句补 `incremental_decisions` / `incremental_conflicts` / `document_chapter_links`。
- **T78**：收尾复验全绿——后端全量 589 passed（串行）、e2e 34 passed、
  `npm run build` 通过、`dev_check.py` 两库迁移均在 `0015`、`0015 → 0014 → 0015` 往返通过。
  红线复核：`app/llm/` 只有 `MockProvider` 一个实现，全仓 `app/` 无 `httpx` / `requests` /
  `openai` / `aiohttp` 引用；无模板管理 UI / CRUD；无任何写 `baseline_labels` 的新代码
  （AC-93 断言裁决前后行数不变）。文档同步：`specs/验证约定.md` §1 状态表、
  新增 §5.5 第二期核对点、§7 变更记录；`PROGRESS.md` §2 / §3 / §4 计数与新增 §5.1
  两期收尾清单、§6 待办补第三~五期。
