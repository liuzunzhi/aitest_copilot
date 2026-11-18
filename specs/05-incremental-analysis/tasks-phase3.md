# 05 · 增量分析（第三期 · 产出段）· 任务清单

> 规格 [spec-phase3.md](./spec-phase3.md) ｜ 方案 [plan-phase3.md](./plan-phase3.md)
> 上游：第一期（T68~T70）、第二期（T71~T78）已完成。
> 本期把第二遍裁决落成基线标签 + 待审核快照，**仍零真实网络请求、不写 `unchanged` 标签、不自动批准快照**。

## 执行约定

1. 每个任务开跑前先 `.\.venv\Scripts\python.exe scripts\dev_check.py`，有 `[FAIL]` 先修环境。
2. 定向用例跑 `-k ac_XX`，通过后再跑全量（串行，避免 `tests/projects/` 的既有 xdist flaky）。
3. 改了前端就 `cd web; npm run build`；有前台交互就补 e2e 用例并截图到 `.screenshots/T8x/`。
4. 每个任务一个提交，提交信息写清「做了什么 / 为什么」。
5. 红线（违反即返工）：
   - 不写任何真实网络请求代码（仍只有 `MockProvider`）；
   - 不自动批准快照（只建 `status='submitted'`）；
   - 不自动创建功能 / 功能点实体；
   - 不写 `unchanged` 标签；
   - **不物理删除任何已落库的标签行**——重跑走 04 的逻辑清除
     （`status='cleared'` + `clear_reason='misjudged'`），行留在库里；
   - **不改 `app/baselines/` 里的任何现存代码**——只调用 04 的既有方法
     （`clear_label` / submitted revision 语义 / 模型 / `write_audit`）；
   - 不顺手修无关模块。

## 任务

- [x] **T79 · 产出段模型与迁移（0016）**
  - 内容：
    - `app/models/incremental.py`：新增 `IncrementalLabel`（analysis ↔ baseline_label 映射，
      唯一 `(analysis_id,baseline_label_id)`（重跑要保留旧映射行，不能按目标建唯一键），
      Check `label_type IN ('changed','affected')`）；
      `IncrementalAnalysis` 加 `apply_status` / `apply_stats` / `apply_revision_id` /
      `apply_error_code` / `apply_error_message` / `apply_started_at` / `apply_finished_at`。
    - `migrations/versions/0016_incremental_apply.py`：建表 + 扩展列（`down_revision="0015"`）。
    - `app/models/__init__.py` 注册新模型与 `__all__`。
  - 产出：AC-98 的表结构可断言；迁移 head 推进到 `0016`。
  - 验证：`tests/incremental/test_apply_models.py`；
    `alembic downgrade 0015 → upgrade head` 往返。

- [x] **T80 · 产出引擎（标签收集 + 落库）**
  - 内容：
    - `app/incremental/apply.py`：
      - `collect_labelable(decisions, conflicts) -> list[LabelableTarget]`（纯函数，spec §5.1 规则表）；
      - `resolve_revision(session, project_id, actor, analysis)`：复用或新建 `status='submitted'` 的快照；
      - `write_labels(session, analysis, revision_id, targets, actor)`：逐条写
        `baseline_labels`（带 `source_analysis_id`）+ `incremental_labels`；
      - `clear_previous(session, analysis, actor)`：**逻辑清除**本分析上一轮的生效标签
        （`status='cleared'` + `clear_reason='misjudged'`，**行不删**）。
  - 产出：AC-98 / AC-100 在引擎层可断言。
  - 验证：`tests/incremental/test_apply_engine.py`。

- [x] **T81 · 产出服务与接口**
  - 内容：
    - `service.run_apply`：固定校验顺序（§6）→ 置 running → 逻辑清除旧产出 → 落标签 + 快照 →
      回填 `apply_stats` → 写 `incremental.apply.run` 审计；失败置 `failed` + `apply_error_*`。
    - `service.list_applied_labels`：产出标签列表 + `revoked` 派生标记（§5.5）。
    - `router.py`：`POST /analyses/{id}/apply`、`GET /analyses/{id}/applied-labels`。
    - `errors.py`：`APPLY_NOT_READY` / `APPLY_CONFLICTS_PENDING` / `APPLY_NO_LABELABLE_TARGET`。
    - `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补 `incremental.apply.run`。
  - 产出：AC-98 ~ AC-104 可断言。
  - 验证：`tests/incremental/test_apply_flow.py`。

- [x] **T82 · 前端（应用产出区块）**
  - 内容：
    - `web/src/api/index.ts`：追加 `runIncrementalApply` / `listAppliedLabels` + 类型；
      `client.ts` 补 3 个错误码中文映射。
    - `web/src/pages/IncrementalApply.tsx`：状态、触发按钮（admin / 第二遍成功）、
      产出标签表 `incremental-applied-label-table`、撤销提示。
    - `ProjectIncrementalDrawer.tsx` 挂载产出区块（保持 400 行内）。
    - `tests/e2e/test_incremental_apply_ui.py`（`@pytest.mark.task("T82")`）：
      应用产出 → 标签可见 → 撤销标记；访客只读；截图 `.screenshots/T82/`。
  - 产出：页面可应用产出、看产出标签与撤销标记。
  - 验证：`npm run build`；e2e。

- [x] **T83 · 收尾**
  - 内容：全量 pytest 串行、e2e 全量、`dev_check.py`、`npm run build`；
    更新 `specs/验证约定.md`（§5.6 第三期核对点 + 变更记录）、`PROGRESS.md` 计数、
    本文件验证记录与实现要点；确认断网可跑（AC-104）。
  - 产出：验证记录齐全，迁移 head `0016`，计数只增不减。

## 收尾（随 T83 完成）

| 项 | 期望 | 实际 |
|---|---|---|
| 后端全量 pytest | ≥ 589 passed（新增约 20–25 条） | **626 passed**（串行，exit 0） |
| 前端 `npm run build` | 通过 | 通过 |
| e2e 全量 | 34 + 新增 1~2 条，全绿 | **36 passed**（新增 2 条） |
| `scripts/dev_check.py --expect-db e2e` | 通过 | 通过（由 `run_e2e.py` 内联执行并校验 8001 连 e2e 库） |
| 离线可跑 | 断网 / 不配置 provider 时全绿（AC-104） | 全链路只走 `MockProvider`，全量 pytest 与 e2e 均绿 |
| 迁移 | `0015 → 0016`，可 upgrade / downgrade / upgrade | 往返通过（T79），当前 head `0016` |
| 红线 | 未写真实网络请求、未自动批准快照、未创建新实体、未写 `unchanged` 标签、**未物理删除任何标签行**、未改 `app/baselines/` 代码 | 全部遵守 |

## 验证记录

| 任务 | 后端定向 | 后端全量 | 前端构建 | e2e | 截图 |
|---|---|---|---|---|---|
| T79 | 15 passed | 604 passed | — | — | — |
| T80 | 11 passed | 615 passed | — | — | — |
| T81 | 10 passed（另审计覆盖 1 条） | 626 passed | — | — | — |
| T82 | — | — | 通过 | 36 passed（新增 2 条） | `.screenshots/T82/`（3 张） |
| T83 | 626 passed | 626 passed | 通过 | 36 passed | `.screenshots/T82/`（沿用） |

## 实现要点

- T79：`incremental_labels` 唯一键取 `(analysis_id, baseline_label_id)`，按目标的组合只建普通索引
  `idx_ilabels_target`；`label_type` CHECK 直接排除 `unchanged`，不依赖应用层过滤。
  `incremental_analyses` 的 `apply_status` 与第一遍 / 第二遍状态各自独立，NULL = 从未应用。
  迁移 `0016` 无种子数据；downgrade 先删映射表，再删 `apply_revision_id` 外键与状态 CHECK，
  最后逆序删列。验证：`tests/incremental/test_apply_models.py`（15 passed）、全量 604 passed、
  `0015 → 0016 → 0015 → 0016` 往返通过。
- T80：`app/incremental/apply.py` 四个入口全部「只写不 commit」，事务与审计留给 T81。
  `collect_labelable` 按 §5.1 过滤，同目标去重且裁决优先（第二遍已保证不重叠，这里兜底）。
  `resolve_revision` 复用项目内最新的 `submitted` 记录，否则新建（`version_no` 留空，不填结构）。
  `clear_previous` 直接调用 04 的 `clear_label`（`clear_reason='misjudged'`），因此
  `baseline.label.clear` 审计由 04 自动写入；标签行只改状态、不删除，`active_key` 归 NULL 后
  同键新标签可再次插入。`write_labels` 用 SAVEPOINT 包住单条插入，撞 `uk_blabels_active`
  时抛 04 的 `DUPLICATE_LABEL`；目标已删除或所属模块归档则跳过并记入 `skipped_missing`。
  验证：`tests/incremental/test_apply_engine.py`（11 passed）、全量 615 passed。
- T81：`service.run_apply` 严格按 §6 顺序校验，校验失败不写审计、不置 running；
  通过后置 running → `clear_previous` → `resolve_revision` → `write_labels`，
  回填 `apply_stats` 后写 `incremental.apply.run` 审计并 commit。
  `apply_stats` 的 `skipped_new_count` 只算已确认的 new 冲突，
  `unchanged_count` 合并裁决与冲突两个来源，`conflict_label_count` 只算真正落库的冲突目标。
  `list_applied_labels` 返回全部映射行（含已清除历史行），`revoked` 仅在
  「有产出且全部 cleared」时为真；目标名称按 id 反查，删除 / 归档实体也能显示名字。
  新增错误码 `APPLY_NOT_READY` / `APPLY_CONFLICTS_PENDING` / `APPLY_NO_LABELABLE_TARGET`；
  审计覆盖清单补 `incremental.apply.run`。
  验证：`tests/incremental/test_apply_flow.py`（10 passed）、审计覆盖新增 1 条、全量 626 passed。
- T82：`web/src/api/index.ts` 追加 `AppliedLabel` / `ApplyStats` / `ApplyResult` 与
  `runIncrementalApply` / `listAppliedLabels`；`client.ts` 补 3 个错误码中文。
  新增 `IncrementalApply.tsx`：进抽屉即拉 `applied-labels`，状态 tag + 「应用产出 / 重跑产出」
  （仅项目管理员且第二遍成功可见）；产出标签表 `incremental-applied-label-table` 展示
  目标 / 标签 / 生效或已清除（含清除人、时间、原因）/ 快照；`revoked=true` 时渲染
  「结论已全部撤销」告警（记录不删）。失败时本地展示 `incremental-apply-failure-alert` 并刷新状态。
  抽屉只加挂载，未改既有区块。验证：`npm run build` 通过；e2e 全量 **36 passed**
  （`test_incremental_apply_ui.py` 2 条：应用 → 标签生效 → 清除后撤销标记；访客无触发入口），
  截图 `.screenshots/T82/`。
- T83：收尾验证与文档回填。后端全量 **626 passed**（串行）、e2e 全量 **36 passed**、
  `npm run build` 通过、`run_e2e.py` 内联的 `--expect-db e2e` 自检通过、迁移 head 两个库均在 `0016`。
  `specs/验证约定.md` 增 §5.6（第三期前台核对点）与变更记录；PROGRESS.md、本文件计数同步。
  AC-104 复核：产出段不调模型，全链路仍只有 `MockProvider`，无任何真实网络请求。
