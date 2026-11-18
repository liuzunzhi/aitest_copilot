# 05 · 增量分析（第三期 · 产出段）· 规格

> 对齐需求：PRD 2.4.3「审核通过后：基线打标签（功能/功能点两级），生成新快照」「文档推导的新增功能/功能点记录来源分析ID」「若某分析结论的所有标签均被清除，该记录标记「结论已全部撤销」」。
> 上游依赖：第一期（T68~T70）第一遍结论表；第二期（T71~T78）第二遍裁决表 / 冲突表 / 章节引用图；04 的 `baseline_labels` + `baseline_revisions`。
> 本期**只做产出段**：把第二遍的裁决结果落成基线标签，并准备一份待审核的新快照。
> 真实模型接入、模板管理 UI 仍不在本期。

## 1. 背景与目标

第二期把「章节 → 模型比对 → 全局裁决 → 人工裁决」整条链路打通了，
但结果停在 `incremental_decisions` / `incremental_conflicts` 两张表里——**基线本身没有变**。
下游（测试点分析）要看的是「哪些功能被改了」，那得是基线标签。

产出段就是这条「最后一步」：

```
第二期结果
  incremental_decisions（无争议裁决）
  incremental_conflicts（人工已裁决的冲突）
        │
        │  只取 changed / affected（unchanged 不写标签）
        ▼
  baseline_labels（标签，source_analysis_id 记来源分析）
        │
        ▼
  baseline_revisions 一行 status='submitted'（待人工审核 → 定版成新快照）
```

本期目标：

- 裁决结果**可一键落成基线标签**，并能追溯「这个标签来自哪次分析」；
- 新快照走 04 已有的**人工审核**流程定版（不自动批准）；
- 全链路仍然**零真实网络请求**、离线可跑、结果可断言。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 应用产出 | 新增 `POST /analyses/{id}/apply`：把第二遍结果落成标签 + 建待审核快照 |
| 产出记录 | 新表 `incremental_labels`：`analysis_id` ↔ `baseline_label_id` 的映射（双向可追溯） |
| 分析记录扩展 | `incremental_analyses` 增 `apply_*` 列（状态 / 统计 / 错误 / 时间 / 目标 revision） |
| 产出结果查询 | 新增 `GET /analyses/{id}/applied-labels`：这次分析产出了哪些标签、当前状态 |
| 「结论已全部撤销」 | 产出记录列表派生该标记：本次产出标签全被人工清除 → 标记「已撤销」 |
| 前端 | 分析详情抽屉内「应用产出」区块：触发、产出标签列表、撤销标记 |
| 审计 | `incremental.apply.run` |

### 2.2 本期不做（红线，违反即返工）

| 不做 | 原因 |
|---|---|
| **任何真实网络请求** | 产出段不调模型，只落库；仍只有 `MockProvider` |
| **自动批准快照** | PRD 原则二「高风险行为人工确认」；产出段只建 `status='submitted'` 的记录 |
| **自动创建功能 / 功能点实体** | `new` 冲突没有基线实体，产出段**不创建**新实体；只处理已有人工确认的实体 |
| **物理删除任何标签行** | 04 的标签是「可追溯的资产」：清除只置 `cleared`，行留在库里。产出段重跑走**逻辑清除** |
| **写 `unchanged` 标签** | 「确实没变」写成标签噪声大且无下游价值；只写 `changed` / `affected` |
| **改 04 的审核 / 打标 / 清除流程** | 产出段只**调用** 04 的既有方法（`clear_label` 语义、`submitted` revision），不改 04 代码 |
| **级联清除** | PRD「级联清除默认关闭」，本期不实现 |
| **模板管理 UI / 真实 provider** | 第四 / 五期 |

### 2.3 与前两期、04 的兼容约束

1. `incremental_decisions` / `incremental_conflicts` **不删不改语义**；产出段只读它们。
2. `analyses.status` 仍只表达第一遍；`second_pass_status` 仍只表达第二遍；
   产出段状态独立放 `apply_status`，三段互不覆盖。
3. `incremental_analyses` / `incremental_conflicts` / `incremental_decisions` 的响应字段**只追加**。
4. 04 的 `baseline_labels.active_key` 生成列保证「同一快照、同一实体、同一标签类型只一条生效标签」——
   产出段写标签时靠它兜底，重复写会撞唯一索引。
5. 04 的 `_copy_labels_forward` 在审核通过时把上一份快照的生效标签复制到新版本，
   **跳过已存在的同键行**——产出段先写的标签不会被覆盖。

## 3. 角色与权限

| 操作 | guest | member | project_admin | system_admin |
|---|---|---|---|---|
| 产出结果读取 | 可 | 可 | 可 | 可 |
| 触发应用产出 | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |

- 非项目成员 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404 `PROJECT_NOT_FOUND`。
- 归档项目内触发 → 409 `PROJECT_ARCHIVED`（先判归档，再判角色）。

## 4. 数据模型（迁移 0016）

### 4.1 `incremental_labels`（新增，迁移 0016）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| analysis_id | BIGINT | FK → incremental_analyses.id（CASCADE），索引 |
| baseline_label_id | BIGINT | FK → baseline_labels.id（CASCADE），索引 |
| revision_id | BIGINT | FK → baseline_revisions.id，索引（标签挂在哪份快照上） |
| target_type | VARCHAR(16) | 非空，`function` / `feature_point` |
| target_id | BIGINT | 非空（多态，不建 FK） |
| label_type | VARCHAR(16) | 非空，`changed` / `affected` |
| created_at | DATETIME(3) | 非空 |

唯一：`(analysis_id, baseline_label_id)`——一个标签只能被一条映射行指向。
**不能**用 `(analysis_id, target_type, target_id, label_type)` 做唯一键：
重跑产出段时旧映射行（指向已清除标签）必须保留，新映射行会与它同键而撞车。
另建普通索引 `(analysis_id, target_type, target_id, label_type)` 供查询。
CheckConstraint：`target_type IN ('function','feature_point')`、
`label_type IN ('changed','affected')`。

> 与 `baseline_labels.source_analysis_id` 形成**双向可追溯**：
> 从标签能查「哪次分析产的」，从分析能查「产了哪些标签」。

### 4.2 `incremental_analyses` 扩展列（迁移 0016）

| 字段 | 类型 | 约束 |
|---|---|---|
| apply_status | VARCHAR(16) | 可空，`running` / `succeeded` / `failed`；NULL = 未应用 |
| apply_stats | JSON | 可空，见 §4.2.1 |
| apply_revision_id | BIGINT | 可空，FK → baseline_revisions.id（标签挂的那份快照） |
| apply_error_code | VARCHAR(64) | 可空 |
| apply_error_message | VARCHAR(500) | 可空 |
| apply_started_at / apply_finished_at | DATETIME(3) | 可空 |

CheckConstraint：`apply_status IS NULL OR apply_status IN ('running','succeeded','failed')`。

#### 4.2.1 `apply_stats` 结构

```json
{
  "revision_id": 12,
  "revision_status": "submitted",
  "label_count": 3,
  "changed_count": 2,
  "affected_count": 1,
  "skipped_missing_count": 0,
  "skipped_new_count": 1,
  "unchanged_count": 2,
  "conflict_label_count": 1
}
```

### 4.3 迁移与种子

- `0016_incremental_apply.py`：`down_revision="0015"`；
  建 `incremental_labels` → `ALTER` 扩展 `incremental_analyses` → 无种子数据。
- `downgrade`：删 `incremental_labels` → 删 `apply_revision_id` 的 FK →
  逐个 `drop_column` 其余 `apply_*` 列。

## 5. 产出规则

### 5.1 哪些结果会落标签

| 来源 | 条件 | 落标签 |
|---|---|---|
| `incremental_decisions` | `decision IN ('changed','affected')` | 是，`label_type = decision` |
| `incremental_decisions` | `decision = 'unchanged'` | 否 |
| `incremental_conflicts` | `status='confirmed'` 且 `resolved_label_type IN ('changed','affected')` | 是 |
| `incremental_conflicts` | `status='confirmed'` 且 `resolved_label_type='unchanged'` | 否 |
| `incremental_conflicts` | `status='confirmed'` 且 `conflict_type='new'`（无 `target_id`） | 否（无实体可打标） |
| `incremental_conflicts` | `status='rejected'` / `'pending'` | 否 |

### 5.2 目标实体校验

- 标签只能挂在**当前结构里仍存在**的功能 / 功能点上；
- 目标已删除或所属模块已归档 → **跳过**并计入 `skipped_missing_count`（不报错），
  统计里能查，不静默丢。

### 5.3 快照处理

- 产出段需要一份 `baseline_revisions` 行来承载标签（`baseline_labels.revision_id` 必填）：
  - 项目内**已有** `status='submitted'` 的记录 → **复用**它（标签挂上去，
    审核通过后与结构一起定版）；
  - 否则**新建**一条 `status='submitted'` 的记录（`submitted_by` = 触发人，
    `review_comment` 记来源分析）。
- 产出段**不填** `version_no` / `structure_json` / `structure_json` 计数——
  这些由 04 的审核通过流程填写（`approve_review` 冻结结构、分配 `v1.N`）。
- 产出段**不自动批准**；审核由另一位管理员走 04 的既有接口。

### 5.4 幂等与重跑

**不物理删除任何标签行**。重跑产出段时，上一轮产出的标签走 04 的**逻辑清除**：

- 对本次分析产出、且仍为 `active` 的标签，调用 04 的 `clear_label` 接口语义：
  `status='cleared'` + `cleared_by` / `cleared_at` / `clear_reason='misjudged'`；
  **行留在库里**，「谁在什么时候因为什么清掉了它」可追溯。
- 清除后 `active_key` 变为 NULL（`cleared` 状态生成列为 NULL），
  与新标签不冲突——这正是 04 既有机制（AC-67「清除后再打同一类型的标 → 新增一条生效标签」）。
- 因此重跑产出段 = 「先逻辑清除本分析上一轮的标签，再按当前结果重建」，
  结果不累加，历史全部留痕。
- `incremental_labels` 映射行同理**不物理删除**：旧行指向已清除的标签，
  新一轮新增映射行；查询时只取 `baseline_labels.status='active'` 的映射作为「当前产出」。

> 逻辑清除在 04 那边会写 `baseline.label.clear` 审计；产出段额外写
> `incremental.apply.run` 审计，两条都在，留痕完整。

### 5.5 「结论已全部撤销」

- 派生字段，不落库：检查本次分析产出的标签**当前**状态，
  若全部为 `cleared` → 返回 `revoked=true`；
- 记录本身不删除、不改状态（PRD：「标记「结论已全部撤销」（不删除记录）」）。

## 6. 接口

前缀沿用 `/api/projects/{project_id}/incremental`。

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | `/analyses/{analysis_id}/apply` | 触发产出（同步跑完返回） | 项目管理员 |
| GET | `/analyses/{analysis_id}/applied-labels` | 本次分析产出的标签列表 | 项目成员 |

**触发校验顺序**（固定）：
1. 项目存在（404）/ 归档（409）/ 角色（403）；
2. 分析记录存在且属本项目（404 `INCREMENTAL_ANALYSIS_NOT_FOUND`）；
3. 第二遍 `second_pass_status='succeeded'`，否则 409 `APPLY_NOT_READY`；
4. 无 `status='pending'` 的冲突，否则 409 `APPLY_CONFLICTS_PENDING`（先裁决再产出）；
5. 有可落标签的目标，否则 409 `APPLY_NO_LABELABLE_TARGET`（没有 changed / affected 可写）；
6. 置 `apply_status='running'` → 写标签 + 建 / 复用待审核快照 → 回填统计与状态；
   失败置 `failed` 并留 `apply_error_*`，已产出的标签保留。

**响应**（`apply` 与 `applied-labels` 共用同一形状）：

```json
{
  "analysis_id": 8,
  "apply_status": "succeeded",
  "apply_revision_id": 12,
  "apply_stats": { "...": "见 §4.2.1" },
  "labels": [
    {
      "id": 31,
      "baseline_label_id": 45,
      "revision_id": 12,
      "target_type": "function",
      "target_id": 7,
      "target_name": "扫码支付",
      "label_type": "changed",
      "status": "active",
      "cleared_by": null,
      "cleared_at": null,
      "clear_reason": null
    }
  ],
  "revoked": false
}
```

## 7. 验收标准

### AC-98 应用产出写标签

- 第二遍成功、冲突已裁决 → `POST .../apply` → `apply_status='succeeded'`
- `baseline_labels` 新增行：`revision_id` = 目标快照、`target_type` / `target_id` 与裁决一致、
  `label_type` = 裁决值、`source_analysis_id` = 分析 ID、`status='active'`
- `incremental_labels` 新增对应映射行
- `unchanged` 裁决**不产生**标签
- `new` 冲突（无 `target_id`）**不产生**标签，计入 `skipped_new_count`

### AC-99 标签归属待审核快照

- 产出后存在一条 `baseline_revisions` 行，`status='submitted'`，`version_no IS NULL`
- 标签的 `revision_id` 指向该行
- 项目内已有 submitted 记录时**复用**它（不新建第二条）
- 产出段**不**把快照置为 `approved`

### AC-100 幂等重跑（逻辑清除，不物理删除）

- 连续 apply 两次 → `baseline_labels` 中本分析产出的**生效**标签行数**不变**（不累加）
- 上一轮的标签行仍在库里，`status='cleared'`、`cleared_by` / `cleared_at` /
  `clear_reason='misjudged'` 有值——**没有任何标签行被物理删除**
- 新一轮的标签是**新行**（`id` 不同），与已清除行并存
- 两次的 `apply_stats.label_count` 一致

### AC-101 人工撤销标记

- 产出后人工清除其中一条标签 → `applied-labels` 里该行 `status='cleared'` 且带清除人 / 时间 / 原因
- 该分析的**生效**标签**全部**被清除 → `revoked=true`
- 记录本身不被删除
- 被清除的历史行仍可通过 `incremental_labels` 追溯到（历史可查，只是「当前产出」为空）

### AC-102 权限与状态

- 第二遍未成功 → 409 `APPLY_NOT_READY`
- 有 pending 冲突 → 409 `APPLY_CONFLICTS_PENDING`
- 无可落标签目标 → 409 `APPLY_NO_LABELABLE_TARGET`
- 访客 / member → 403 `NOT_PROJECT_ADMIN`；非成员读 → 403 `NOT_PROJECT_MEMBER`
- 归档项目 → 409 `PROJECT_ARCHIVED`

### AC-103 审计

- 产出成功写 `incremental.apply.run`（`target_type='incremental_analysis'`）
- 校验失败不写审计

### AC-104 离线可跑

- 产出段不调模型，零真实网络请求；断网下全量 pytest 与 e2e 全绿

## 8. 错误码

| code | HTTP | 触发 |
|---|---|---|
| `APPLY_NOT_READY` | 409 | 第二遍还没成功 |
| `APPLY_CONFLICTS_PENDING` | 409 | 仍有待裁决冲突 |
| `APPLY_NO_LABELABLE_TARGET` | 409 | 没有可落标签的 changed / affected 目标 |

复用：`INCREMENTAL_ANALYSIS_NOT_FOUND`、`PROJECT_ARCHIVED`、`NOT_PROJECT_ADMIN`、
`NOT_PROJECT_MEMBER`、`DUPLICATE_LABEL`。

## 9. 非功能

- 产出段同步执行（与前两期一致）。
- 标签列表不分页（单次分析的产出量级小）；`applied-labels` 与 `decisions` / `conflicts` 一致用分页信封。
- 阈值（标签置信度门槛、撤销传播衰减）本期**不实现**，留待基准集回填。
