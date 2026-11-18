# 05 · 增量分析（第一期）· 任务清单

> 规格 [spec.md](./spec.md) ｜ 方案 [plan.md](./plan.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)
> 第二期（第二遍全局裁决）见 [spec-phase2.md](./spec-phase2.md) / [plan-phase2.md](./plan-phase2.md) / [tasks-phase2.md](./tasks-phase2.md)。
> 第三期（产出段）见 [spec-phase3.md](./spec-phase3.md) / [plan-phase3.md](./plan-phase3.md) / [tasks-phase3.md](./tasks-phase3.md)。

## 执行约定

1. 每个任务开始前重读 `spec.md` 对应 AC 与 `plan.md` 对应小节，不凭记忆写代码。
2. 先写用例再写实现；用例名带 AC 编号（`test_ac_77_conclusion_persisted`）。
3. 任务收尾跑：`-k ac_7X` → 全量 `.\.venv\Scripts\python.exe -m pytest`（数量只增不减，基线 **484**）；
   全量可加 `-n 4` 并行（约 47s，串行 134s），排查偶发失败时改串行。
4. 前端可用后补 Playwright 前台核对，按 [../验证约定.md](../验证约定.md) 第 2 节落截图；
   前端未就绪时在任务行标「前台待补」，T70 统一补跑。
5. 提交信息用 `feat(incremental): …` / `test(incremental): …`，一个任务一个提交。
6. 开跑前先做环境自检：`.\.venv\Scripts\python.exe scripts\dev_check.py`；
   跑前台用例直接 `.\.venv\Scripts\python.exe scripts\run_e2e.py`（自检 → 起 8001/5174 →
   跑 `tests/e2e` → 收尾），有 `[FAIL]` 先修环境再动代码。
7. 失败一次收齐：一次跑完全部失败用例再集中修，修完先 `-k` 收窄、最后全量一次。
8. 前端新增交互元素带 `data-testid`（`区域-动作-目标`），e2e 优先 testid 定位；
   单页组件超约 400 行时拆子组件。
9. e2e 的通用页面操作走 `tests/e2e/helpers.py`，等待一律用 `expect`，不写固定 `wait_for_timeout`。
10. **本期红线**（spec §2.2）：不写任何真实网络请求代码、不做模板管理 UI、不做第二遍、不写产出段、
    不顺手修无关模块。越界即返工。

## 前置条件

| 项 | 状态 |
|---|---|
| 01-auth / 02-projects / 03-documents / 04-baseline | T01–T67 已验收 |
| 后端基线 | 484 passed（2026-11-17，T67 后；e2e 默认 `-m "not e2e"`） |
| 前端 | `D:\aitest_copilot\web`，项目详情页含「概览 / 成员 / 文档 / 基线管理 / 版本快照 / 申请」6 个 Tab |
| 数据库迁移 head | `0012`（05 建 `0013`） |
| 04 的引用解析器 | `app/baselines/references.py` 已含 `incremental_analyses` 探测，05 落地自动生效 |
| e2e 环境 | 8001 / 5174 + `aitest_copilot_e2e`，一条命令 `scripts/run_e2e.py`，见验证约定 §3 |

## 任务

- [x] **T68 · 建表与 Mock** ✓ 2026-11-17
  - 内容：
    - `app/models/incremental.py` 三个模型（`PromptTemplate` / `IncrementalAnalysis` /
      `IncrementalConclusion`），字段与索引严格对齐 spec §4；
      注册到 `app/models/__init__.py` 的 import 与 `__all__`。
    - `migrations/versions/0013_incremental.py`，`down_revision="0012"`；
      三表按外键顺序建、`downgrade` 反序直接删表；播种 1 条 `incremental` 种子模板
      （`system_prompt` 以 `[INCREMENTAL_SYSTEM]` 开头，`user_prompt` 以 `[INCREMENTAL_USER]` 开头）。
    - `app/llm/` 包：`schemas.py`（`LLMRequest` / `LLMResponse` / `TokenUsage`）、
      `provider.py`（`LLMProvider` Protocol + `get_provider()` 工厂）、
      `mock.py`（`MockProvider`：`calls` 记录请求、`queue` 预设返回、`raw` 回带请求）。
    - `app/incremental/` 骨架：`__init__.py` / `schemas.py` / `context.py` / `engine.py` /
      `service.py` / `router.py`（空实现 + 路由注册进 `app/main.py`）。
  - 产出：
    - 3 张表可 upgrade / downgrade / upgrade；
    - `incremental_conclusions` 唯一键 `(analysis_id, chapter_id, target_type, target_id)` 生效；
    - `label_type` CheckConstraint 只允许 `changed`/`affected`/`unchanged`；
    - `incremental_analyses.baseline_revision_id` 与 `status` 两列存在（04 解析器依赖）；
    - `MockProvider` 能返回固定 JSON，且 `calls` 里能拿到收到的 `system` / `user`。
  - 验证：`tests/incremental/test_models.py`（唯一约束、CheckConstraint、外键级联、种子模板存在）
    + `tests/incremental/test_llm_provider.py`（Mock 的 `calls` / `queue` / `raw` 契约）；
    `-k "ac_77 or ac_78 or ac_84"` 中属于本任务的用例先行通过；全量 `pytest` 数量只增不减。
  - 前台：本期无页面入口，随 T70 一并核对。

- [x] **T69 · 后端第一遍业务流** ✓ 2026-11-17
  - 内容：
    - `app/incremental/context.py`：Prompt 组装（`system = template.system_prompt`；
      `user = f"{template.user_prompt}\n\n## 章节：{title}\n{content}"`）+ 基线索引
      （当前结构的 `function` / `feature_point` id → name，排除归档模块及其下属）。
    - `app/incremental/engine.py`：`run_first_pass`，逐章节调 Provider，
      `json.loads` 解析、缺 `conclusions` 字段 → `LLM_OUTPUT_INVALID`；
      两条丢弃规则（越界 → `INCREMENTAL_TARGET_OUT_OF_BASELINE`；`new` → `INCREMENTAL_LABEL_NEW_DROPPED`）；
      超 `INCREMENTAL_MAX_INPUT_CHARS` 截断并记 WARN。
    - `app/incremental/service.py`：固定校验顺序（模板 → 快照 → 文档版本，spec §5）、
      建行 → 跑第一遍 → 回填 `stats` / `status` / `finished_at`；
      失败置 `status='failed'` 并写 `error_code` / `error_message`；审计 `incremental.analysis.create`。
    - `app/incremental/router.py` 四个接口：`GET/POST /analyses`、
      `GET /analyses/{id}`、`GET /analyses/{id}/conclusions`。
    - `app/common/errors.py` 新增 9 个错误类并同步 `__all__`。
    - `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补 `incremental.analysis.create`。
  - 产出：AC-77 / AC-78 / AC-79 / AC-80 / AC-81 / AC-82 / AC-83 全部可断言。
  - 验证：
    - `tests/incremental/test_analysis_flow.py` —— AC-77 落库、AC-78 Prompt 来源与两份模板异常
      （删除 → 404、禁用 → 409，均不产生记录）
    - `tests/incremental/test_discards.py` —— AC-79 越界丢弃、AC-80 `new` 丢弃
    - `tests/incremental/test_analysis_status.py` —— AC-81 状态流转与失败留痕
    - `tests/incremental/test_permissions.py` —— AC-82 权限矩阵（读 / 发起、归档 409、非成员 403）
    - `tests/incremental/test_snapshot_ref.py` —— AC-85 04 引用自动生效
    - `-k "ac_77 or ac_78 or ac_79 or ac_80 or ac_81 or ac_82 or ac_83 or ac_85"`

- [x] **T70 · 前端最小展示** ✓ 2026-11-17
  - 内容：
    - `web/src/pages/ProjectIncrementalTab.tsx`：发起表单（基线快照 / 文档版本 / 模板，
      切分粒度固定 `chapter` 只读）+ 记录列表（状态 / 时间 / 章节数 / 结论数 / 丢弃数）
      + 详情抽屉（结论列表 + 丢弃明细）。控制在 400 行内。
    - `ProjectDetailPage.tsx` 插入第 7 个 Tab「增量分析」（`key: 'incremental'`）。
    - `web/src/api/index.ts` 增 `/* ---- 增量分析（05） ---- */` 分节 + 类型。
    - `web/src/api/client.ts` 补本期 9 个错误码中文映射。
    - 非项目管理员隐藏「发起分析」按钮；`data-testid`：`incremental-create-btn`、
      `incremental-detail-btn-{id}`、`incremental-conclusion-table`。
  - 产出：`npm run build` 通过；e2e 覆盖「发起 → 记录出现 → 详情看到结论」。
  - 验证：`npm run build`；`tests/e2e/test_incremental_ui.py`
    （`@pytest.mark.task("T70")`）：发起分析 → 列表出现 `succeeded` 记录 →
    详情抽屉结论可见；访客无发起入口；截图落 `.screenshots/T70/`。

## 收尾（随 T70 一并完成）

| 项 | 期望 |
|---|---|
| 后端全量 pytest | ≥ 484 passed（新增约 20–25 条） |
| 前端 `npm run build` | 通过 |
| e2e 全量 | 29 + 新增 1~2 条，全绿 |
| `scripts/dev_check.py --expect-db e2e` | 通过 |
| 离线可跑 | 断网 / 不配置任何 provider 时，全量 pytest 与 e2e 仍全绿（AC-84） |
| `specs/验证约定.md` | 补 §5.4 增量分析前台核对点 + 计数 |
| `PROGRESS.md` | 第 3 节冲刺任务勾选，第 4 节计数同步 |

## 验证记录（待填）

| 任务 | 后端定向 | 后端全量 | 前端构建 | e2e | 截图 |
|---|---|---|---|---|---|
| T68 | 11 passed（`tests/incremental`） | 495 passed（串行；`-n 4` 偶发审计用例死锁，单跑通过） | — | — | — |
| T69 | 31 passed（`tests/incremental`）+ 审计 `incremental.analysis.create` 1 passed | 516 passed（串行） | — | — | — |
| T70 | — | 516 passed（串行） | 通过 | 31 passed（全量；新增 `test_incremental_ui.py` 2 条） | `.screenshots/T70/`（3 张） |

### 实现要点（待补）

- T68：迁移按 `prompt_templates → incremental_analyses → incremental_conclusions` 建表，
  `downgrade` 直接反序删表（不先删索引，避开 MySQL 1553）；种子模板的
  `[INCREMENTAL_SYSTEM]` / `[INCREMENTAL_USER]` 前缀是 AC-78 的稳定锚点，改文案不破用例。
  引擎 / 服务的章节循环在 T69 实现，已按「单章失败即整体 failed、立即抛出」写入模块契约。
- （待 T69 后补：Prompt 组装的可断言形状、丢弃判定为何不进业务表）
  - T69：`user` 固定为 `模板 user_prompt + "\n\n## 章节：标题\n正文"`，超
    `INCREMENTAL_MAX_INPUT_CHARS`（默认 8000）只截断正文、前缀与标题保留，
    因此 AC-78 的「以模板 user_prompt 开头」恒成立。
    > **2026-11-18 更新（06 期 L2 真实联调）**：`user` 现在多一段
    > `## 可对照的基线目标`（基线功能 / 功能点清单），位置在模板正文与
    > 章节标题之间。AC-78 的「以模板 user_prompt 开头」依然成立。
    > 详见 `specs/06-real-llm/tasks.md` 的「L2 真实联调发现」。
  - T69：丢弃结论只进 `analyses.stats.discarded`，不落 `incremental_conclusions`；
    越界优先于 `new` 判定，`dropped_new_count` 由 discarded 里
    `INCREMENTAL_LABEL_NEW_DROPPED` 的条数推导，避免两份计数漂移。
  - T69：同步执行下，引擎单章失败立即抛错；服务层逐章 `flush` 落库，
    失败时把已落库结论保留在事务里再 `commit`，并在 `stats` 记
    `failed_chapter_id` / `failed_chapter_title`，不续跑后续章节。
- （待 T70 后补：前台核对暴露的真实缺陷）
  - T70：模板下拉只有系统默认一条——本期后端不提供模板列表接口（spec §2.2 不做模板 CRUD），
    `template_id` 固定为迁移播种的 `1`；模板与切分粒度均为只读展示，模板管理留给后续期。
  - T70：发起分析失败时后端已把记录落成 `failed`，前端在 catch 里仍刷新列表，
    避免「界面报错但看不到失败记录」；详情抽屉单独拉 `GET /analyses/{id}` + 结论分页。
  - T70：e2e 截图目录默认改为仓库根 `.screenshots/`（`E2E_SCREENSHOT_DIR` 仍可覆盖），
    并清理了文档 / 约定里残留的旧工作区绝对路径。
  - T70：前台核对未发现 05 自身的展示缺陷；唯一注意点是 Mock 默认空结论，
    结论 / 丢弃明细由 `support.seed_analysis_conclusions` 补数后核对展示。
  - T70：按执行约定第 8 条拆组件——`ProjectIncrementalTab`（表单 + 列表，301 行）、
    `ProjectIncrementalDrawer`（详情抽屉，165 行）、`incrementalMeta.tsx`（状态/标签/说明常量，42 行）。
