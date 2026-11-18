# 05 · 增量分析（第三期）· 技术方案

> 规格 [spec-phase3.md](./spec-phase3.md) ｜ 第二期 [spec-phase2.md](./spec-phase2.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)
> 迁移：0016（产出映射表 + analyses 产出列）；head 从 `0015` 推进到 `0016`。

## 1. 总体结构

第二期结束时，链路是「读第二遍结果 → 写两张 05 自己的表」。
第三期只多做一件事：**把结果写进 04 的基线**。

```
incremental_decisions（无争议裁决）
incremental_conflicts（人工已裁决的冲突）
        │
        ▼
  app/incremental/apply.py（产出引擎 · 纯函数算 + 服务层落库）
        │  ├─ baseline_labels（label_type = changed / affected，source_analysis_id 记来源）
        │  └─ baseline_revisions 一行 status='submitted'（待人工审核）
        ▼
  incremental_labels（映射表：analysis ↔ baseline_label）
        │
        ▼
  app/incremental/router.py：POST /analyses/{id}/apply、GET /analyses/{id}/applied-labels
```

**不推翻前两期**：`decisions` / `conflicts` 只读不改，产出段是纯下游。

## 2. 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 产出段触发方式 | 独立 `POST /apply` 接口，人工点 | PRD 原则一「自动变更资产默认关闭」；先看完裁决与冲突再决定写不写 |
| 新快照怎么处理 | 建 `status='submitted'` 记录，人工审核后定版 | PRD 原则二「高风险行为人工确认」；产出段不自动批准，`version_no` 由 04 的 `approve_review` 分配 |
| `unchanged` 写不写标签 | **不写** | 「确实没变」写成标签噪声大，下游只关心变更 / 受影响 |
| `new` 冲突怎么处理 | 不写标签，计入 `skipped_new_count` | `new` 没有基线实体；创建功能 / 功能点是基线结构写操作，不在产出段职责内 |
| 冲突裁决结果怎么落 | `status='confirmed'` 且 `resolved_label_type` 是变更类 → 落标签 | 第二期已把冲突收敛成「人工裁决结果」，产出段直接消费，不再二次确认 |
| 目标已删除怎么办 | 跳过并计入 `skipped_missing_count`，不报错 | 标签是附属产物，不该因为个别实体被删就整次失败 |
| 产出幂等 | 上一轮的标签走 04 的**逻辑清除**（`status='cleared'` + `clear_reason='misjudged'`），再重建 | 04 的标签是可追溯资产，**行永不物理删除**；清除后 `active_key` 变 NULL，新标签不冲突 |
| 产出段是否物理删任何行 | **一律不删**，映射行也只追加 | 留痕要求：「谁在什么时候因为什么清掉了它」可追溯 |
| 「结论已全部撤销」 | 派生字段，不落库 | PRD 说「标记」但不删记录；派生比落库更不容易漂移 |
| 产出段是否调模型 | 不调 | 产出是纯落库动作，零网络请求，离线可断言 |

## 3. 落库与幂等细节

### 3.1 事务边界

```
apply:
  1. 校验（§6 固定顺序）
  2. apply_status='running'，commit
  3. try:
       - 逻辑清除本分析上一轮的「生效」标签（04 的 clear_label 语义，行保留）
       - 找或建待审核快照（baseline_revisions status='submitted'）
       - 收集可落标签的目标（decisions + confirmed conflicts）
       - 逐目标写 baseline_labels + incremental_labels，逐条 flush
       - 回填 apply_stats / apply_revision_id / apply_status='succeeded' / finished_at
       - write_audit('incremental.apply.run')
       - commit
     except AppError / Exception:
       - apply_status='failed' + apply_error_*，commit（已产出的标签保留）
       - raise
```

- **逐条 flush**：单个目标撞唯一索引时不回滚整批，已写入的标签保留，便于排查。
- 逻辑清除与写入新产出在**同一事务**里，中途失败不会留下「清了一半」的库。
- **全程没有物理 DELETE**：标签行只从 `active` 变 `cleared`，映射行只追加。

### 3.2 待审核快照的取用

```
submitted = SELECT * FROM baseline_revisions
            WHERE project_id = ? AND status = 'submitted' LIMIT 1
if submitted:
    revision_id = submitted.id          # 复用，不新建
else:
    revision = BaselineRevision(project_id, status='submitted',
                                submitted_by=actor.id,
                                review_comment='增量分析 #N 产出')
    revision_id = revision.id
```

- 复用已有 submitted 记录符合 04 的语义：项目内同时只允许一份审核中的记录
  （`submit_review` 会拒绝第二份），产出段若新建第二条会破坏这个不变量。
- 产出段**不填** `version_no` / `structure_json` / 三级计数——这些由
  `approve_review` 冻结结构时填写。

### 3.3 标签落库

```python
label = BaselineLabel(
    project_id=..., revision_id=revision_id,
    target_type=..., target_id=..., label_type=...,
    source_analysis_id=analysis.id,      # 双向可追溯的来源
    confirmed_by=actor.id,
)
```

- `active_key` 生成列保证「同一快照、同一实体、同一标签类型只一条生效标签」；
  上一轮的标签已被逻辑清除（`active_key` 变 NULL），新标签不冲突。
- `source_analysis_id` 让 04 的 `references.py` 的标签引用条目能带出「来自哪次分析」，
  零改动生效（04 早已预留该列）。

### 3.4 逻辑清除上一轮产出

```
previous = SELECT l.* FROM baseline_labels l
            JOIN incremental_labels m ON m.baseline_label_id = l.id
            WHERE m.analysis_id = :id AND l.status = 'active'
for label in previous:
    label.status = 'cleared'
    label.cleared_by = actor.id
    label.cleared_at = now()
    label.clear_reason = 'misjudged'     # 04 的 6 类原因之一
```

- **没有 DELETE**：标签行留在库里，可追溯。
- `clear_reason='misjudged'`（04 的「误判」类）：语义是「上一轮产出被新一轮结果取代」，
  属 04 既有枚举，不需要新增。
- 逻辑清除会写 `baseline.label.clear` 审计（复用 04 的 `write_audit` 调用方式），
  产出段再写 `incremental.apply.run`，两条审计都在。
- `incremental_labels` 映射行**不删**，只追加新一轮的映射；
  查询「当前产出」时只取映射指向 `status='active'` 标签的那些行。

### 3.5 撤销标记

```
applied-labels 返回：
  labels  = 本次分析产出的标签（含 cleared 的，历史可查）
  revoked = bool(生效标签) and all(生效标签.status == 'cleared')
```

- 「产出了标签但生效的那批全被清了」→ `revoked=true`；「一条都没产出」→ `revoked=false`
  （没有标签不等于被撤销）。

## 4. 文件级改动清单

### 后端

| 文件 | 动作 |
|---|---|
| `app/models/incremental.py` | 新增 `IncrementalLabel`；`IncrementalAnalysis` 加 `apply_*` 列；同步 `__all__` |
| `app/models/__init__.py` | 注册新模型与 `__all__` |
| `migrations/versions/0016_incremental_apply.py` | 建 `incremental_labels`、扩展 `analyses` |
| `app/incremental/apply.py` | 产出引擎：收集可落标签目标 + 逻辑清除上一轮 + 落库 |
| `app/incremental/schemas.py` | `AppliedLabelOut`、`ApplyResultOut`；`AnalysisOut` 追加 `apply_*` 字段 |
| `app/incremental/service.py` | `run_apply`、`list_applied_labels`、固定校验顺序、审计 |
| `app/incremental/router.py` | `POST /analyses/{id}/apply`、`GET /analyses/{id}/applied-labels` |
| `app/common/errors.py` | 3 个新错误类 + `__all__` |

> **不改 `app/baselines/` 的任何现存代码**。产出段只**调用** 04 的既有方法：
> `clear_label`（逻辑清除）、`submit_review` 的 submitted revision 语义、
> `BaselineLabel` / `BaselineRevision` 模型、`write_audit`。
> 不在 04 里注册路由，也不往 04 加导入。

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/incremental/test_apply_models.py` | 表约束、级联、`apply_status` CHECK |
| `tests/incremental/test_apply_engine.py` | 标签收集规则（AC-98）、目标缺失跳过、幂等（AC-100） |
| `tests/incremental/test_apply_flow.py` | 接口 + 库断言（AC-98 ~ AC-104） |

### 前端

| 文件 | 动作 |
|---|---|
| `web/src/api/index.ts` | 第二期分节追加 `runIncrementalApply` / `listAppliedLabels` + 类型 |
| `web/src/api/client.ts` | 3 个新错误码中文映射 |
| `web/src/pages/IncrementalApply.tsx` | 「应用产出」区块：触发按钮、产出标签表、撤销标记 |
| `web/src/pages/ProjectIncrementalDrawer.tsx` | 挂载产出区块 |
| `tests/e2e/test_incremental_apply_ui.py` | e2e：应用产出 → 标签可见 → 撤销标记 |

## 5. 测试策略

- **纯引擎优先**：`apply.py` 的「收集可落标签目标」是纯函数，直接喂
  `PendingDecision` / 冲突行断言，不起 HTTP。
- **接口层**：复用 `tests/incremental/helpers.py` 的造数（项目 / 快照 / 文档版本 / 分析 / 裁决）。
- **离线**：不配 provider、不发网络。
- **计数**：后端基线 589，预计新增 20–25 条；e2e 34 → 36 左右。

## 6. 前端交互

- 详情抽屉内追加「应用产出」区块：
  - 未应用：状态「未应用」+「应用产出」按钮（admin，且第二遍成功）；
  - running / succeeded / failed：状态 Tag + 统计（标签数 / 变更 / 受影响 / 跳过）；
  - failed：红条展示 `apply_error_message`；
  - 产出标签表 `incremental-applied-label-table`：目标、标签、状态、清除原因；
  - `revoked=true` 时展示黄色提示「该分析的结论已全部撤销」。

## 7. 迁移与回滚

- `0016`：建 `incremental_labels` → `add_column` 扩展 `analyses` → `create_foreign_key`。
- `downgrade`：删 `incremental_labels` → 删 `apply_revision_id` 的 FK → 逐个 `drop_column`。
- 老数据兼容：一期 / 二期分析记录 `apply_status IS NULL`，前端显示「未应用」。

## 8. 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q -k "ac_98 or ac_99 or ac_100 or ac_101 or ac_102 or ac_103 or ac_104"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -rN
.\.venv\Scripts\python.exe scripts\run_e2e.py -k incremental_apply
cd web; npm run build
```

## 9. 主要风险

| 风险 | 应对 |
|---|---|
| 复用已有 submitted 快照时，它已有别人的标签 | 产出段只**追加**自己的标签，不动已有行；上一轮自己的标签已逻辑清除 |
| 产出后标签把基线快照「撑脏」 | 产出段只写 changed / affected，且必须人工审核才定版 |
| `active_key` 唯一索引撞车 | 上一轮标签先逻辑清除（`active_key` 变 NULL），新标签不冲突；单条失败不回滚整批 |
| 清空后重跑产出段把人工清除的标签复活 | 只逻辑清除**本分析自己产出**的标签；人工在 04 那边单独清除的标签不受产出段影响 |
| 04 的审核流程被绕过 | 产出段只建 submitted 行，`version_no` / `structure_json` 仍由 `approve_review` 填 |
| 有人误以为产出段会删数据 | 全程零 DELETE；清除只置 `cleared` + 记原因，审计两条都在 |
