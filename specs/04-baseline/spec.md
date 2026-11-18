# 04 · 功能基线管理 · 规格

> 对齐需求：PRD 2.4.2 基线管理（功能基线子菜单）、需求文档 v2.2 §5.1 核心实体、§5.2 高风险点。
> 上游依赖：03-documents 已提供文档、版本、章节树与文档基线快照。
> 本期只做**手工路径**：模块化三级结构 + 两级打标 + 清除留痕 + 审核快照 + 保留策略。
> 文档推导、基线反推、增量分析关联本期不做（依赖 LLM，见 05）。

## 1. 背景与目标

平台已有项目、成员、文档与文档版本，但没有「被测对象本身」的结构化描述：
需求文档拆出的章节没有落到「模块 → 功能 → 功能点」上，也无法记录
「这个功能相对上一版变了 / 新增了 / 受影响」，变更闭环断在这里。

本期目标：项目内可手工建立模块化功能基线（三级结构），
给功能与功能点打「新增 / 变更 / 受影响 / 无变化」标签，
标签可人工清除并留痕；审核通过后冻结为不可变快照，
并支持「保留上限 + 被引用即保护 + 人工确认清理」的快照生命周期。
做完之后，增量分析（05）有了可以打标的载体。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 三级结构 | 模块 → 功能 → 功能点；模块有名称/描述/排序，功能有名称/描述/版本号，功能点有名称/描述 |
| 来源标记 | 每行记 `source_type`（手工 / 文档推导）与追溯字段（来源文档、版本、章节、生成方式、增量分析 ID） |
| 模块删除策略 | 模块下有功能 → 409 `MODULE_NOT_EMPTY`，响应带「迁移功能」「删除功能」两个入口；无功能 → 可删（二次确认） |
| 功能迁移 | 批量把功能迁到同项目其他模块，保留迁移前模块记录 |
| 两级打标 | 功能级与功能点级均可打标签，类型四选一；同一实体同一快照下同一类型只允许一条生效标签 |
| 标签清除 | 原因必填（6 类枚举），记录清除人/时间/原因；行不删除，状态置 `cleared` |
| 聚合展示 | 功能标签独立存在，不由功能点标签汇总；功能无标签但功能点有标签时弱化提示「含 N 个功能点标签」 |
| 审核与快照 | 草稿 → 提交审核 → 审核通过（冻结结构 + 生成快照 v1.0、v1.1…）/ 驳回；提交者不能自审 |
| 标签随快照 | 标签作用于具体快照；生成新快照时把**当时生效**的标签复制到新快照（独立行） |
| 保留策略 | 项目级 `baseline_snapshot_max_count`（空 = 不启用，默认永久保留）；超限进「待清理候选」，不自动删 |
| 被引用即保护 | 被标签引用的快照禁止删除，只告警并列出引用来源 |
| 检索 | 按模块、来源类型、标签、关键词筛选功能列表 |
| 审计 | 结构增删改、迁移、打标、清除、提交/审核、快照删除、保留上限变更 |

### 2.2 本期不做

- **文档推导模块 / 基线反推**：需要 LLM 直连或 Skill，属 05+；本期只保留追溯字段与只读约束。
- **增量分析记录关联**：表结构留 `source_analysis_id` 与 `source_method='incremental_new'`，本期无写入方。
- **流程基线**（场景/步骤/预期结果）：PRD 2.4.2 的另一个子菜单，本期不做。
- **标签级联清除**：PRD 写「级联清除默认关闭」——本期**不实现**级联清除动作，只保证清除不波及新快照。
- **标签再次编辑**：清除后重新打标 = 新增一条生效标签行，不复用已清除行。

### 2.3 待确认（先按此实现，可评审时改）

1. 快照版本号用 `v1.{n}`（n 从 0 递增），PRD 写 v1.0、v1.1。
2. 审核记录与快照**合表**：`baseline_revisions` 一行既表示一次审核，也表示一份冻结快照（`status=approved` 时 `structure_json` 才有效）。
3. 结构写入（模块/功能/功能点增删改、提交审核、审核、打标、清除、删除快照）限**项目管理员**；读接口对全体成员（含访客）开放。依据 PRD 1.4「默认保守安全优先」。
4. 提交者不能审核自己的提交（同人审批返回 403 `SELF_APPROVAL_FORBIDDEN`）。
5. 模块的「状态」取 `active` / `archived`：归档模块保留历史但不参与新快照与检索默认展示。
   *T66 落地*：`GET /modules`、`GET /functions` 默认 `status=active`（功能列表同时排除挂在
   归档模块下的功能），`status=archived|all` 可查归档；审核冻结的 `structure_json` 与
   各级计数不含归档模块；前端树上管理员可「归档 / 取消归档」，工具栏「状态」切
   在用 / 归档 / 全部。
6. 被引用即保护本期只检查**标签引用**；增量分析记录、测试点、用例、报告尚未上线，引用检查在对应模块落地时补。
   *T67 落地*：引用检查已按「来源解析器」拆开（`app/baselines/references.py`），
   标签引用是内置解析器之一；增量分析引用（分析记录把该快照当比对基准）
   的解析器同时就位，05 落地后自动生效，04 无需再改。
   标签若由某次增量分析产出，其 `source_analysis_id` 随标签条目一起给出，
   **不额外计为一处引用**——一条引用 = 一件可处理的事。

## 3. 角色与权限

| 操作 | guest | member | project_admin | system_admin |
|---|---|---|---|---|
| 模块/功能/功能点列表与详情 | 可 | 可 | 可 | 可（兜底） |
| 标签列表（含已清除） | 可 | 可 | 可 | 可 |
| 快照列表 / 快照详情 | 可 | 可 | 可 | 可 |
| 模块/功能/功能点增删改 | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |
| 功能迁移 | 403 | 403 | 可 | 可 |
| 打标 / 清除标签 | 403 | 403 | 可 | 可 |
| 提交审核 / 审核通过 / 驳回 | 403 | 403 | 可（提交者除外） | 可 |
| 删除快照 / 设置保留上限 | 403 | 403 | 可 | 可 |

非项目成员访问读接口 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404 `PROJECT_NOT_FOUND`。
归档项目内读接口正常，写接口 → 409 `PROJECT_ARCHIVED`（先判归档，再判角色）。

## 4. 数据模型（5 张新表，迁移 0012）

### 4.1 `baseline_modules`（模块）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| name | VARCHAR(128) | 非空 |
| description | VARCHAR(500) | 可空 |
| sort_order | INT | 非空，默认 0 |
| source_type | VARCHAR(16) | 非空，默认 `manual`，取值 `manual` / `document_derived` |
| status | VARCHAR(16) | 非空，默认 `active`，取值 `active` / `archived` |
| created_by / created_at | BIGINT / DATETIME(3) | 非空 |

唯一：`(project_id, name)`（同项目模块名唯一）。

### 4.2 `baseline_functions`（功能）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| module_id | BIGINT | FK → baseline_modules.id，索引 |
| name | VARCHAR(128) | 非空 |
| description | VARCHAR(500) | 可空 |
| version_no | INT | 非空，默认 1，每次内容修改 +1 |
| source_type | VARCHAR(16) | 同模块 |
| status | VARCHAR(16) | 同模块 |
| source_document_id / source_version_id / source_chapter_id | BIGINT | 可空，文档推导来源 |
| source_chapter_title | VARCHAR(255) | 可空 |
| source_method | VARCHAR(32) | 可空，`baseline_reverse` / `incremental_new` |
| source_analysis_id | BIGINT | 可空，增量分析记录 ID |
| created_by / created_at | BIGINT / DATETIME(3) | 非空 |

唯一：`(module_id, name)`。追溯字段在 `source_type='document_derived'` 时只读（接口不提供写入路径）。

### 4.3 `baseline_feature_points`（功能点）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| function_id | BIGINT | FK → baseline_functions.id，索引 |
| name | VARCHAR(128) | 非空 |
| description | VARCHAR(500) | 可空 |
| source_type / status | VARCHAR(16) | 同上 |
| source_* 追溯字段 | 同功能 | 可空 |
| created_by / created_at | BIGINT / DATETIME(3) | 非空 |

唯一：`(function_id, name)`。

### 4.4 `baseline_labels`（标签）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| revision_id | BIGINT | FK → baseline_revisions.id，索引 |
| target_type | VARCHAR(16) | `function` / `feature_point` |
| target_id | BIGINT | 指向功能或功能点（多态，不建 FK） |
| label_type | VARCHAR(16) | `new` / `changed` / `affected` / `unchanged` |
| source_analysis_id | BIGINT | 可空 |
| confirmed_by / confirmed_at | BIGINT / DATETIME(3) | 非空 |
| status | VARCHAR(16) | `active` / `cleared` |
| cleared_by / cleared_at | BIGINT / DATETIME(3) | 可空 |
| clear_reason | VARCHAR(32) | 可空，6 类枚举之一 |
| clear_note | VARCHAR(500) | 可空，`clear_reason='other'` 时必填 |
| active_key | VARCHAR(160) | 生成列 `IF(status='active', CONCAT(revision_id,':',target_type,':',target_id,':',label_type), NULL)` + 唯一索引 |

生成列保证「同一快照、同一实体、同一标签类型只允许一条生效标签」，
已清除的行 `active_key` 为 NULL，不与新标签冲突（MySQL 允许多个 NULL）。
与 03 的 `active_key` 同一手法。

### 4.5 `baseline_revisions`（审核记录 / 基线快照）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| version_no | INT | 可空，审核通过时分配（`v1.{n}`） |
| status | VARCHAR(16) | `submitted` / `approved` / `rejected` |
| structure_json | MEDIUMTEXT | 可空，审核通过时冻结的三级结构 JSON |
| module_count / function_count / feature_point_count | INT | 非空默认 0 |
| label_count | INT | 非空默认 0 |
| submitted_by / submitted_at | BIGINT / DATETIME(3) | 可空 |
| reviewed_by / reviewed_at | BIGINT / DATETIME(3) | 可空 |
| review_comment | VARCHAR(500) | 可空（驳回原因） |
| created_at | DATETIME(3) | 非空 |

唯一：`(project_id, version_no)`（`version_no` 可空，MySQL 允许多个 NULL）。
`status='approved'` 的行即一份不可变快照；`structure_json` 一经写入不再变更。

### 4.6 `projects` 新增列

| 字段 | 类型 | 约束 |
|---|---|---|
| baseline_snapshot_max_count | INT | 可空，空 = 不启用（默认永久保留） |

PRD 要求项目级、空值即不启用，因此放 `projects` 而不是 `system_settings`。

## 5. 接口

统一前缀 `/api/projects/{project_id}/baselines`，全部 JSON。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/modules` | 模块列表（含功能数、功能点标签计数） |
| POST | `/modules` | 新建模块 |
| PATCH | `/modules/{module_id}` | 改名称/描述/排序/状态 |
| DELETE | `/modules/{module_id}` | 删除模块（有功能 → 409 带两个入口） |
| POST | `/modules/{module_id}/migrate` | 批量迁移功能到目标模块 |
| GET | `/functions` | 功能列表，支持 `module_id` / `source_type` / `label_type` / `keyword` / `revision_id` 筛选 |
| POST | `/functions` | 新建功能 |
| PATCH | `/functions/{function_id}` | 改内容（`version_no` +1）/状态 |
| DELETE | `/functions/{function_id}` | 删功能（连带删功能点，级联删除其标签） |
| GET | `/functions/{function_id}/feature-points` | 功能点列表 |
| POST | `/functions/{function_id}/feature-points` | 新建功能点 |
| PATCH | `/feature-points/{point_id}` | 改功能点 |
| DELETE | `/feature-points/{point_id}` | 删功能点（连带删其标签） |
| GET | `/labels` | 标签列表，`target_type` / `target_id` / `revision_id` / `status` 筛选；默认只返回 `active` |
| POST | `/labels` | 打标 |
| POST | `/labels/{label_id}/clear` | 清除标签（原因必填） |
| GET | `/revisions` | 快照列表（只列 `approved`） |
| GET | `/revisions/{revision_id}` | 快照详情（含冻结结构） |
| POST | `/reviews/submit` | 提交审核（生成 `submitted` 记录） |
| POST | `/reviews/{revision_id}/approve` | 审核通过（冻结结构 + 分配版本号 + 复制生效标签） |
| POST | `/reviews/{revision_id}/reject` | 驳回（必填意见） |
| GET | `/retention` | 保留策略状态 + 告警 + 待清理候选 |
| PATCH | `/retention` | 设置 `baseline_snapshot_max_count` |
| DELETE | `/revisions/{revision_id}` | 删除快照（被引用 → 409，仅告警） |

## 6. 验收标准

### AC-62 三级结构手工建立
- **When** 项目管理员建模块 → 建功能 → 建功能点
- **Then** 三级列表各自可见，功能挂在指定模块下，功能点挂在指定功能下
- 同项目模块名重复 → 409 `DUPLICATE_MODULE_NAME`；同模块功能名重复 → 409 `DUPLICATE_FUNCTION_NAME`；同功能功能点名重复 → 409 `DUPLICATE_FEATURE_POINT_NAME`
- 手工添加的行 `source_type='manual'`，追溯字段全空

### AC-63 来源追溯字段只读
- `source_type='document_derived'` 的行，追溯字段（来源文档/版本/章节/标题/生成方式/增量分析 ID）**不出现在任何写接口的入参**里
- `PATCH` 只接受名称/描述/排序/状态，传入追溯字段 → 400 `TRACE_FIELDS_READONLY`

### AC-64 模块删除级联策略
- **Given** 模块下有 2 个功能，**When** 删除该模块
- **Then** 409 `MODULE_NOT_EMPTY`，响应 `extra` 带 `available_actions: ["migrate_functions", "delete_functions"]`
- 模块下无功能 → 200 删除成功；删除后其功能点与标签一并清除
- 有生效标签的功能被删 → 响应带 `warning`，说明标签失效、下游测试点将不再引用

### AC-65 功能批量迁移
- **When** 把功能 A、B 从模块 M1 迁到同项目的 M2
- **Then** 两功能 `module_id` 变为 M2，`moved_from_module_id` 记为 M1，追溯信息保留
- 目标模块不存在 / 跨项目 / 目标即当前模块 → 400 `INVALID_MIGRATE_TARGET`
- 迁移写审计 `baseline.module.migrate`

### AC-66 两级打标
- 给功能打 `changed`、给功能点打 `new` → 200，两条标签各自独立
- 同一实体同一快照同一类型重复打标 → 409 `DUPLICATE_LABEL`
- 功能列表：功能自身的标签展示在功能行；**不由功能点标签汇总**
- 功能无标签但其功能点有标签 → 该功能行弱化提示「含 N 个功能点标签」
- 功能点标签可在详情展开或按 `label_type` 筛选查看

### AC-67 标签清除留痕
- **When** 清除一条生效标签，**Then** 200，行 `status='cleared'`，`cleared_by`/`cleared_at`/`clear_reason` 有值，**行仍在库里**
- `clear_reason` 必填且只能是 6 类之一 → 400 `CLEAR_REASON_REQUIRED` / `INVALID_CLEAR_REASON`
- `clear_reason='other'` 时 `clear_note` 必填 → 400 `CLEAR_NOTE_REQUIRED`
- 清除后再打同一类型的标 → 新增一条生效标签，原已清除行保留

### AC-68 标签随快照
- 标签只对**指定快照**生效：`GET /labels?revision_id=` 按快照过滤
- 生成新快照时，上一快照的**生效**标签被复制成新行（`revision_id` 指向新快照）
- 上一快照的标签被清除 → **不影响**新快照里已复制的行（级联清除默认关闭）
- 已清除的标签不会随快照复制

### AC-69 审核流程
- 提交审核 → 生成 `status='submitted'` 的记录，200
- 审核通过 → `status='approved'`、`version_no` 分配为项目内下一个 `v1.{n}`、`structure_json` 冻结
- 驳回 → `status='rejected'`、`review_comment` 必填（空 → 400 `REVIEW_COMMENT_REQUIRED`），**不生成快照、不占版本号**
- 提交者本人审核 → 403 `SELF_APPROVAL_FORBIDDEN`
- 重复审核同一条记录 → 409 `INVALID_REVIEW_STATUS`
- 审核通过后继续编辑结构 → `structure_json` 不变（快照不可变）

### AC-70 快照不可变与版本递增
- 项目内快照版本号单调递增，`v1.0` → `v1.1`
- `structure_json` 冻结后不随结构编辑变化
- 快照无更新接口（PATCH → 404 / 405），只有删除接口

### AC-71 保留策略
- 默认 `baseline_snapshot_max_count` 为空 → 所有快照永久保留，候选列表为空
- 设为 2 且已有 3 份快照 → 超出的最旧 1 份进入**待清理候选**，不自动删除
- 关闭策略（置空）→ 候选清空，快照全部保留

### AC-72 被引用即保护
- 被标签引用的快照 → 删除返回 409 `SNAPSHOT_REFERENCED`，响应带引用来源明细
- 未被引用的快照 → 可删除，删除写审计 `baseline.snapshot.delete`
- 达到上限但存在被引用快照不可清理 → `GET /retention` 返回告警「N 份快照达到保留上限但因被引用不可清理」并列出引用来源

### AC-73 基线检索
- 功能列表支持 `module_id` / `source_type` / `label_type` / `keyword` 组合筛选
- 筛选结果与库内数据一致，命中数正确

### AC-74 权限矩阵
- 读接口：全体成员（含访客）可读；非成员 → 403 `NOT_PROJECT_MEMBER`；system_admin 可读任意项目
- 写接口：`member` / `guest` → 403 `NOT_PROJECT_ADMIN`
- 归档项目内写接口 → 409 `PROJECT_ARCHIVED`

### AC-75 审计
- 结构增删改写 `baseline.module.*` / `baseline.function.*` / `baseline.feature_point.*`
- 迁移写 `baseline.module.migrate`；打标写 `baseline.label.create`；清除写 `baseline.label.clear`
- 提交写 `baseline.revision.submit`；通过写 `baseline.revision.approve`；驳回写 `baseline.revision.reject`
- 快照删除写 `baseline.snapshot.delete`；保留上限变更写 `baseline.retention.update`
- 每条含 `project_id` / `actor_id` / `target_type` / `target_id`；失败操作不写审计

### AC-76 概览计数
- `GET /projects/{id}/overview` 的 `baseline_count` 改为**已审核通过的快照数**（`baseline_revisions` 中 `status='approved'`），不再是文档基线快照数

## 7. 错误码

| code | HTTP | 触发 |
|---|---|---|
| `MODULE_NOT_FOUND` | 404 | 模块不存在或不属于该项目 |
| `MODULE_NOT_EMPTY` | 409 | 模块下有功能，删除被阻止 |
| `DUPLICATE_MODULE_NAME` | 409 | 同项目模块名重复 |
| `FUNCTION_NOT_FOUND` | 404 | 功能不存在或不属于该项目 |
| `DUPLICATE_FUNCTION_NAME` | 409 | 同模块功能名重复 |
| `FEATURE_POINT_NOT_FOUND` | 404 | 功能点不存在 |
| `DUPLICATE_FEATURE_POINT_NAME` | 409 | 同功能功能点名重复 |
| `INVALID_MIGRATE_TARGET` | 400 | 迁移目标非法 |
| `INVALID_LABEL_TYPE` | 400 | 标签类型不在四类之内 |
| `DUPLICATE_LABEL` | 409 | 同实体同快照同类型已有生效标签 |
| `LABEL_NOT_FOUND` | 404 | 标签不存在 |
| `LABEL_ALREADY_CLEARED` | 409 | 标签已被清除过，不能重复清除 |
| `CLEAR_REASON_REQUIRED` | 400 | 清除原因缺失 |
| `INVALID_CLEAR_REASON` | 400 | 清除原因不在 6 类之内 |
| `CLEAR_NOTE_REQUIRED` | 400 | `other` 原因缺备注 |
| `REVIEW_NOT_FOUND` | 404 | 审核记录不存在 |
| `INVALID_REVIEW_STATUS` | 409 | 重复审核 / 状态不符 |
| `REVIEW_COMMENT_REQUIRED` | 400 | 驳回缺意见 |
| `SELF_APPROVAL_FORBIDDEN` | 403 | 提交者本人审核 |
| `SNAPSHOT_NOT_FOUND` | 404 | 快照不存在 |
| `SNAPSHOT_REFERENCED` | 409 | 快照被标签引用，禁止删除 |
| `TRACE_FIELDS_READONLY` | 400 | 试图写入追溯字段 |

## 8. 非功能

- 结构列表一次查询取全量后在内存聚合，避免按模块逐个查功能的 N+1。
- 标签 `active_key` 由数据库维护，应用层不写该列。
- 快照 `structure_json` 用 MEDIUMTEXT 存 JSON 文本；快照内部的结构树不分页。
- 列表接口统一分页信封：`page`（默认 1）/ `page_size`（默认 50，上限 200），返回 `{items,total,page,page_size}`；
  `total` 为过滤后的条数。涉及 `/baselines/modules`、`/baselines/functions`、`/baselines/labels`、`/baselines/revisions`。
- 无新增第三方依赖。

## 9. 依赖与影响

- **03 的基线 Tab**：项目详情页原有「基线」Tab 展示文档基线快照，改名「版本快照」；新增「基线管理」Tab 展示功能基线。
- **概览**：`get_overview` 的 `baseline_count` 改为已审核快照数（AC-76），同步更新 `tests/documents/test_overview_counts.py` 与 `tests/projects/test_overview.py` 的断言。
- **审计清单**：`tests/common/test_audit_coverage.py` 增加本期 action。
- **迁移**：`0012_baseline`，`down_revision` 指向 `0011`；`downgrade` 严格反序删表，并回退 `projects.baseline_snapshot_max_count` 列。
- **验证约定**：每个任务按 `specs/验证约定.md` 第 2 节走「任务 pytest + 全量 pytest + 前台核对 + 截图」。
