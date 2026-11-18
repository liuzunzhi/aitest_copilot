# 05 · 增量分析（第二期 · 第二遍全局裁决）· 规格

> 对齐需求：需求文档 v2.2 §4.2 第二遍全局裁决（2b-1 功能点索引 / 2b-2 按点分治 / 2b-3 图传播）、§4.7 验收第 3–5 条。
> 上游依赖：一期已完成（T68–T70）——`incremental_analyses` / `incremental_conclusions` / `prompt_templates` 与 `MockProvider`。
> 本期**只做第二遍**：消费一期局部结论，产出「功能 / 功能点级裁决结果」与「待人工裁决队列」。
> 产出段（写 `baseline_labels`、生成新快照）与真实模型接入**仍不在本期**。

## 1. 背景与目标

一期把「章节 → 模型比对 → 局部结论落库」打通了，但局部结论有三个天然问题：

1. 同一条变更会在多个章节重复出现，同一功能点可能收到互相矛盾的标签；
2. 第一遍按章节切分，单章看不到功能点的全貌，无法判断「新增」；
3. 章节之间存在引用 / 依赖，A 章改了，B 章可能被连带影响。

第二遍全局裁决就是解决这三件事：

```
一期 incremental_conclusions
        │
        ├─▶ 2b-1 功能点索引（按目标聚合 + 章节引用图）
        │
        ├─▶ 2b-2 按点分治（逐功能点小输入调 Mock，产出裁决）
        │        └─ 同目标多结论不一致 → 冲突队列
        │
        └─▶ 2b-3 图传播（沿章节引用图传播「可能连带变更」→ 冲突队列）
                 │
                 ▼
        incremental_decisions（无冲突的裁决）
        incremental_conflicts（待人工裁决 / 新增 / 可能连带）
```

**本期验收边界**：第二遍流程可跑、结果可断言、冲突一定进人工队列，
且**不写任何基线标签**（产出段下期）。仍然零真实网络请求，全量 pytest / e2e 离线可跑。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 章节引用图 | 新表 `document_chapter_links`；从章节正文按规则抽取（「见第 X 章」「依赖」「前置条件」等），支持人工补链；供 2b-3 使用 |
| 2b-1 功能点索引 | 按 `target_type + target_id` 聚合一期结论；建立「功能 → 功能点」「章节 → 引用章节」索引 |
| 2b-2 按点分治 | 逐功能点组装**小输入**（只带该功能点相关章节结论，不带全量基线），调 `MockProvider` 产出裁决；`new` 只在这里产生 |
| 2b-3 图传播 | 沿引用图从「已变更章节」传播到目标章节，产出 `possible_impact`，**一律进人工队列**，不直接改写裁决 |
| 裁决结果落库 | 新表 `incremental_decisions`（无冲突的最终候选标签）与 `incremental_conflicts`（待人工裁决） |
| 分析记录扩展 | `incremental_analyses` 增第二遍状态、统计、错误与时间列；第二遍独立模板（迁移播种） |
| 第二遍接口 | 触发第二遍、查询裁决、查询冲突、人工裁决冲突 |
| 前端 | 分析详情抽屉：第二遍状态 / 触发 / 裁决列表 / 冲突队列（确认、驳回）；文档版本下查看与补链 |
| 审计 | `incremental.second_pass.run`、`incremental.conflict.resolve`、`document.chapter_link.create` |

### 2.2 本期不做（红线，违反即返工）

| 不做 | 原因 |
|---|---|
| **任何真实网络请求** | 仍只有 `MockProvider`；不引入 `openai` / `httpx` / `jsonschema` / `cryptography` |
| **产出段** | 不写 `baseline_labels`、不生成新快照、不做「结论已全部撤销」标记；下期做 |
| **模板管理 UI / 模板 CRUD 接口** | 第二遍模板同样由迁移播种、只读 |
| **模型供应商配置 / 密钥加密 / 运行日志表** | 无真实 provider，随真实接入期一起做 |
| **自动裁决冲突** | 冲突只能人工确认 / 驳回（C3）；本期裁决结果也不写标签，留给产出段 apply |
| **切分粒度扩展**（whole / chapter_token）与阈值回填 | 阈值与召回策略仍待基准集 |
| **顺手修 03 / 04 无关模块** | 引用抽取代码放 05 的包内，不改 03 的解析器 |

### 2.3 与一期的兼容约束

1. 一期接口与表**不删不改语义**：`incremental_conclusions` 仍是第一遍唯一产物；
   第二遍只新增表与列，`GET /analyses`、`GET /analyses/{id}/conclusions` 响应保持向后兼容（新增字段只追加）。
2. `incremental_analyses.status` 仍只表达**第一遍**状态；第二遍状态放 `second_pass_status`，
   互不覆盖，便于「第一遍成功、第二遍失败」的排查。
3. 一期模板 `task_type='incremental'` 的模板选择逻辑不变；第二遍按模板名前缀
   `增量分析·第二遍` 取 `status='active'` 的最新一条，取不到 → 409 `SECOND_PASS_TEMPLATE_MISSING`。
4. 04 的快照引用解析器已包含 `incremental_analyses`，本期不新增引用来源。

## 3. 角色与权限

| 操作 | guest | member | project_admin | system_admin |
|---|---|---|---|---|
| 章节引用图读取 | 可 | 可 | 可 | 可（兜底） |
| 章节引用规则抽取 / 手动补链 | 403 | 403 | 可 | 可 |
| 触发第二遍 | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |
| 裁决 / 冲突列表读取 | 可 | 可 | 可 | 可 |
| 人工裁决冲突 | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |

- 非项目成员 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404 `PROJECT_NOT_FOUND`。
- 归档项目内触发第二遍 / 补链 / 裁决 → 409 `PROJECT_ARCHIVED`（先判归档，再判角色）。
- 引用图属于文档版本内容，读权限与「文档章节」一致（含访客）。

## 4. 数据模型（迁移 0014 + 0015）

### 4.1 `document_chapter_links`（迁移 0014）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| version_id | BIGINT | FK → document_versions.id，索引 |
| from_chapter_id | BIGINT | FK → document_chapters.id，索引 |
| to_chapter_id | BIGINT | 可空，FK → document_chapters.id，索引 |
| link_type | VARCHAR(24) | 非空，`references` / `depends_on` / `mentions_entity` |
| entity | VARCHAR(128) | 可空，链接到实体名（功能点 / 术语）而非章节 |
| confidence | DECIMAL(3,2) | 可空，规则抽取给固定值，人工补链为空 |
| source | VARCHAR(16) | 非空，`rule` / `manual` |
| created_by | BIGINT | 非空，FK → users.id |
| created_at | DATETIME(3) | 非空 |

- CheckConstraint：
  - `link_type IN ('references','depends_on','mentions_entity')`
  - `source IN ('rule','manual')`
  - **目标二选一**：`((to_chapter_id IS NOT NULL) <> (entity IS NOT NULL))`
- 唯一键（两条，分别管章节目标与实体目标）：
  - `uk_chlinks_to_chapter (version_id, from_chapter_id, link_type, to_chapter_id)`
  - `uk_chlinks_entity (version_id, from_chapter_id, link_type, entity)`
  MySQL 允许多个 NULL，因此两条唯一键互不干扰；同一源章节的重复引用在服务层再兜一次。
- 规则抽取幂等：每次抽取先按 `(version_id, source='rule')` 删除再插入，人工行不受影响。

### 4.2 `incremental_decisions`（迁移 0015）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| analysis_id | BIGINT | FK → incremental_analyses.id（CASCADE），索引 |
| target_type | VARCHAR(16) | 非空，`function` / `feature_point` |
| target_id | BIGINT | 非空（多态，不建 FK） |
| target_name | VARCHAR(255) | 非空，裁决时快照名称 |
| decision | VARCHAR(16) | 非空，`changed` / `affected` / `unchanged` |
| confidence | DECIMAL(3,2) | 可空 |
| rationale | VARCHAR(1000) | 可空 |
| evidence | JSON | 可空，`{chapter_ids:[], conclusion_ids:[], propagated_from:[]}` |
| created_at | DATETIME(3) | 非空 |

唯一：`(analysis_id, target_type, target_id)`。
CheckConstraint：`target_type IN ('function','feature_point')`、
`decision IN ('changed','affected','unchanged')`。

> `new` **不落本表**：新增没有 `target_id`，只能进 `incremental_conflicts`（`conflict_type='new'`）。

### 4.3 `incremental_conflicts`（迁移 0015）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| analysis_id | BIGINT | FK → incremental_analyses.id（CASCADE），索引 |
| target_type | VARCHAR(16) | 非空，`function` / `feature_point` |
| target_id | BIGINT | 可空：`new` 没有 id |
| target_name | VARCHAR(255) | 非空 |
| conflict_type | VARCHAR(16) | 非空，`conflict` / `possible_impact` / `new` |
| candidates | JSON | 非空，候选裁决数组 |
| status | VARCHAR(16) | 非空，默认 `pending`，`pending` / `confirmed` / `rejected` |
| resolved_label_type | VARCHAR(16) | 可空，`changed` / `affected` / `unchanged` |
| resolved_by | BIGINT | 可空，FK → users.id |
| resolved_at | DATETIME(3) | 可空 |
| created_at | DATETIME(3) | 非空 |

CheckConstraint：
`conflict_type IN ('conflict','possible_impact','new')`、
`status IN ('pending','confirmed','rejected')`、
`resolved_label_type IS NULL OR resolved_label_type IN ('changed','affected','unchanged')`、
`(conflict_type = 'new' AND target_id IS NULL) OR (conflict_type <> 'new' AND target_id IS NOT NULL)`。

- **不加数据库唯一键**（`new` 的 `target_id` 为 NULL 会使唯一键失效），去重由服务层保证：
  同一分析内 `(conflict_type, target_type, target_id)` 或 `new` 的 `(target_type, target_name)` 只留一条。
- `candidates` 结构：

```json
[
  {"label_type": "changed", "confidence": 0.8, "rationale": "接口新增字段", "source": "point_pass"},
  {"label_type": "unchanged", "confidence": 0.6, "rationale": "正文未提及实现", "source": "point_pass"}
]
```

### 4.4 `incremental_analyses` 扩展列（迁移 0015）

| 字段 | 类型 | 约束 |
|---|---|---|
| second_pass_template_id | BIGINT | 可空，FK → prompt_templates.id |
| second_pass_status | VARCHAR(16) | 可空，`running` / `succeeded` / `failed`；NULL = 未跑过 |
| second_pass_stats | JSON | 可空，见 §4.4.1 |
| second_pass_error_code | VARCHAR(64) | 可空 |
| second_pass_error_message | VARCHAR(500) | 可空 |
| second_pass_started_at / second_pass_finished_at | DATETIME(3) | 可空 |

CheckConstraint：`second_pass_status IS NULL OR second_pass_status IN ('running','succeeded','failed')`。

#### 4.4.1 `second_pass_stats` 结构

```json
{
  "template_id": 2,
  "template_version": 1,
  "chapter_link_count": 6,
  "point_count": 4,
  "decision_count": 5,
  "new_count": 1,
  "conflict_count": 2,
  "propagated_count": 1,
  "failed_target_type": null,
  "failed_target_id": null
}
```

失败时额外填 `failed_target_type` / `failed_target_id`（解析失败 / Mock 抛错的那一个点）。

### 4.5 迁移与种子

- `0014_chapter_links.py`：建 `document_chapter_links`，`down_revision="0013"`；`downgrade` 直接删表。
- `0015_incremental_second_pass.py`：`down_revision="0014"`；
  建 `incremental_decisions` / `incremental_conflicts`，`ALTER` 扩展 `incremental_analyses`，
  播种一条第二遍模板（`name='增量分析·第二遍·按点分治'`、`task_type='incremental'`、
  `status='active'`、system 以 `[INCREMENTAL_2B_SYSTEM]` 开头、user 以 `[INCREMENTAL_2B_USER]` 开头）。
- `downgrade`：先删两张新表与新增列（新增列逐个 `drop_column`），再删模板行。

## 5. 接口

统一前缀沿用 `/api/projects/{project_id}`。

### 5.1 章节引用图

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/documents/{document_id}/versions/{version_id}/links` | 引用图列表（不分页，单版本量级小），支持 `link_type` / `source` 筛选 | 项目成员 |
| POST | `/documents/{document_id}/versions/{version_id}/links` | 手动补一条 | 项目管理员 |
| POST | `/documents/{document_id}/versions/{version_id}/links/extract` | 按规则重抽取（幂等） | 项目管理员 |

**POST 补链入参**（`to_chapter_id` 与 `entity` 二选一）：

```json
{"from_chapter_id": 12, "link_type": "references", "to_chapter_id": 15, "entity": null}
```

- 两者都传或都不传 → 400 `INVALID_CHAPTER_LINK`；
- 章节不属于该版本 / `from == to` → 400 `INVALID_CHAPTER_LINK`；
- 重复 → 409 `DUPLICATE_CHAPTER_LINK`。

### 5.2 第二遍

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | `/incremental/analyses/{analysis_id}/second-pass` | 触发第二遍（同步跑完返回） | 项目管理员 |
| GET | `/incremental/analyses/{analysis_id}/decisions` | 裁决列表（分页），支持 `target_type` / `decision` | 项目成员 |
| GET | `/incremental/analyses/{analysis_id}/conflicts` | 冲突列表（分页），支持 `status` / `conflict_type` | 项目成员 |
| POST | `/incremental/analyses/{analysis_id}/conflicts/{conflict_id}/resolve` | 人工裁决 | 项目管理员 |

**触发校验顺序**（固定）：
1. 项目存在（404）/ 归档（409）/ 角色（403）；
2. 分析记录存在且属本项目（404 `INCREMENTAL_ANALYSIS_NOT_FOUND`）；
3. 第一遍 `status='succeeded'`，否则 409 `SECOND_PASS_NOT_READY`；
4. 第二遍模板存在且 active，否则 409 `SECOND_PASS_TEMPLATE_MISSING`；
5. 存在 `status='pending'` 的冲突 → 409 `SECOND_PASS_CONFLICTS_PENDING`（先裁决再重跑）；
6. 置 `second_pass_status='running'` → 跑 2b → 回填统计与状态；失败置 `failed` 并留 `second_pass_error_*`，已产出的裁决 / 冲突保留。

**裁决入参**：

```json
{"decision": "confirmed", "label_type": "changed"}
```

- `decision` 只允许 `confirmed` / `rejected`，否则 400 `INVALID_CONFLICT_RESOLUTION`；
- `confirmed` 必须带 `label_type`（三选一），`rejected` 不允许带；
- 冲突不存在或不属于该分析 → 404 `CONFLICT_NOT_FOUND`；
- 已裁决 → 409 `CONFLICT_ALREADY_RESOLVED`；
- **裁决只改冲突行，不写 `baseline_labels`**（AC-93）。

## 6. 第二遍引擎

### 6.1 2b-1 索引（`app/incremental/second_pass.py` 纯函数）

```
build_point_index(session, analysis) -> PointIndex
  - 读本分析全部 incremental_conclusions，按 (target_type, target_id) 聚合
  - 功能 → 功能点子表：baseline_feature_points.function_id（排除归档模块）
  - 章节引用图：document_chapter_links（本期版本）
  - 输出：{target: [LocalConclusion]}、{function_id: [point_ids]}、{chapter_id: [linked_chapter_ids]}
```

### 6.2 2b-2 按点分治

**参与计算的目标集合**：
- 第一遍出现过结论的**功能点**；
- 第一遍出现过结论且**没有功能点**的**功能**（避免功能级结论永远没有出口）。

有功能点的功能不单独计算；其功能级结论作为该功能下所有功能点的补充证据写进作用域，
因此「功能级 `changed` + 点级 `unchanged`」会在点作用域内直接暴露为冲突（AC-91）。

- 遍历上述目标，**先判证据一致性**：
  - 本作用域的局部结论标签不一致 → 不调模型，直接写 `conflict_type='conflict'`，
    候选为各标签去重结果；
  - 一致 → 组装输入调 Mock，模型 `decision` 为准，落 `incremental_decisions`。
- Prompt 组装（功能点用「## 功能点：」、功能用「## 功能：」作为固定锚点）：

```text
system = 第二遍模板.system_prompt
user   = f"{第二遍模板.user_prompt}\n\n## {目标标签}：{name}\n## 局部结论\n{scoped}\n## 关联章节\n{chapters}"
# 目标标签取「功能点」或「功能」；功能点场景固定为「功能点」，AC-89 按此前缀断言
```

  `scoped` **只含该目标及其所辖功能**的结论（C1：不带全量基线，不带其他功能点 id）。
- Mock 返回契约：

```json
{
  "decision": "changed",
  "confidence": 0.8,
  "rationale": "……",
  "new_points": [{"name": "退款审核", "rationale": "……"}]
}
```

- `MockProvider` 增加**第二遍默认响应**（未 `queue` 时）：system 以 `[INCREMENTAL_2B_SYSTEM]`
  开头的请求返回 `{"decision": "unchanged", "confidence": 0.5, "rationale": "mock 默认结论", "new_points": []}`；
  一期请求仍返回原默认 `{"conclusions": []}`。这样 e2e 不预设队列也能跑通第二遍。

- `decision` 不在三值内、或不是合法 JSON → 整次第二遍 `failed`，`second_pass_error_code=LLM_OUTPUT_INVALID`。
- `new_points` 只进 `incremental_conflicts(conflict_type='new')`，不落 `decisions`（C2）；
  跨作用域出现同名新增时按 `(target_type, target_name)` 去重，候选 rationale 合并。
- 同一目标在本作用域的局部结论**互相矛盾**（不同章节给出不同标签，或功能级与点级不一致）→
  不调模型、不落 `decisions`，写一条 `conflict_type='conflict'`，候选数组按 `label_type` 聚合去重。
- 同一目标所有结论一致 → 以模型 `decision` 为准，落一条 `incremental_decisions`。

### 6.3 2b-3 图传播

- 取 `document_chapter_links` 中 `link_type IN ('references','depends_on')` 的边：
  源章节存在 `changed` / `affected` 结论 → 目标章节命中的基线目标写
  `conflict_type='possible_impact'`（候选含来源章节与原始标签）。
- `mentions_entity` 边本期**不参与第二遍计算**，只落图供检索与产出段使用。
- **传播结果一律进冲突队列**，不改写 `decisions`（C4）。
- 目标已在 `decisions` 中被传播命中 → 删除该 `decisions` 行，原标签并入候选，
  保证同一目标只出现在 `decisions` / `conflicts` 之一。
- 同一目标既被 `possible_impact` 又被 `conflict` 命中时，合并为一条冲突，
  `conflict_type='conflict'`（人工裁决优先级更高），候选合并去重。

### 6.4 引用抽取规则（`links.py`）

| 规则 | 命中示例 | link_type | confidence |
|---|---|---|---|
| 显式章节引用 | 「见第 2 章」「详见 2.1」「参见 3.2 节」 | `references` | 0.8 |
| 依赖 / 前置 | 「依赖第 2 章」「前置条件见 2.1」 | `depends_on` | 0.8 |
| 实体提及 | 正文包含基线功能点名称（去空白、长度 ≥ 2） | `mentions_entity` | 0.6 |

- 序号解析：优先按同级序号 / 父级序号拼出完整路径匹配章节 `seq` 路径；
  解析不到、指向自身、跨版本 → 丢弃该条，不报错。
- 同一源章节同类型同目标只留一条（取最高 confidence）。
- 人工补链 `confidence=NULL`、`source='manual'`。

### 6.5 幂等与重跑

- 重跑成功时先删本分析旧的 `decisions` 与 `conflicts` 再重建（同一事务）；
- 失败时保留本次已写入的行，便于排查；再次重跑成功后覆盖。

## 7. 验收标准

### AC-86 章节引用图规则抽取与幂等

- **Given** 版本章节 C1 正文含「详见第 2 章」「依赖 2.1」，C2 / C2.1 存在
- **When** 项目管理员 `POST .../links/extract`
- **Then** 生成 `references`（C1 → C2）与 `depends_on`（C1 → C2.1）边，`source='rule'`
- **Then** 再抽取一次，`rule` 行数不变（先删后插），人工行不丢
- **Then** 引用图 GET 按 `link_type=references` 过滤，命中数与库内一致

### AC-87 手动补链与校验

- 管理员补一条 `references` 章节链接 → 201，`source='manual'`
- 重复补同一条 → 409 `DUPLICATE_CHAPTER_LINK`
- `to_chapter_id` 与 `entity` 同时给 / 都不给、章节不属该版本、`from == to` → 400 `INVALID_CHAPTER_LINK`
- 访客 POST → 403；GET 可读

### AC-88 第二遍状态流转

- 第一遍 `failed` / `running` 时触发 → 409 `SECOND_PASS_NOT_READY`
- 第一遍成功 → 触发返回 `second_pass_status='succeeded'`，`second_pass_started_at` / `finished_at` 有值
- 模板被禁用 → 409 `SECOND_PASS_TEMPLATE_MISSING`
- Mock 抛错 / 返回非 JSON → `second_pass_status='failed'`、`second_pass_error_code` 有值，
  已产出的裁决保留，第一遍 `status` 仍为 `succeeded`

### AC-89 2b-1 / 2b-2 小输入（C1）

- Mock 收到的 `system` 等于第二遍模板 `system_prompt`
- `user` 以模板 `user_prompt` 开头，且**只含当前目标的局部结论**：
  不出现其他功能点的 `target_id`，不出现全量基线结构
- 一次第二遍的 Mock 调用数等于**证据一致**的参与目标数（矛盾目标不调模型）

### AC-90 新增只在第二遍产生（C2）

- 第一遍结论里不存在 `new`（一期已保证）
- 第二遍 Mock 返回 `new_points` → `decisions` 无该条；`conflicts` 新增 `conflict_type='new'`，
  `target_id IS NULL`、`target_name` 为模型给的名字、`status='pending'`
- `second_pass_stats.new_count` 与 new 冲突条数一致

### AC-91 同目标冲突进队列（C3）

- 同一功能点的局部结论互相矛盾（不同章节标签不同，或功能级 `changed` 与点级 `unchanged` 并存）
- **Then** 不写该目标的 `decisions`；`conflicts` 新增 `conflict_type='conflict'`，
  `candidates` 含两种标签、`status='pending'`
- **Then** 目标在所有证据上一致时只写一条 `decisions`

### AC-92 图传播只进人工队列（C4）

- C1 → C2 为 `references`，C1 命中的功能点 F 为 `changed`，C2 命中功能点 G
- **Then** G 写一条 `conflict_type='possible_impact'`，`candidates` 标出传播来源；
  G **不写** `decisions`（若 2b-2 已写，则删除并并入候选）
- `mentions_entity` 边不产生 `possible_impact`
- 同一目标不会同时出现在 `decisions` 与 `conflicts`

### AC-93 人工裁决不写基线标签

- `POST resolve` `{"decision":"confirmed","label_type":"changed"}` →
  冲突行 `status='confirmed'`、`resolved_label_type='changed'`、`resolved_by` / `resolved_at` 有值
- `{"decision":"rejected"}` → `status='rejected'`、`resolved_label_type IS NULL`
- 两次裁决后 `baseline_labels` 行数**不变**（产出段下期）
- 已裁决再裁决 → 409 `CONFLICT_ALREADY_RESOLVED`；`confirmed` 缺 `label_type` → 400

### AC-94 重跑限制

- 存在 `pending` 冲突时触发第二遍 → 409 `SECOND_PASS_CONFLICTS_PENDING`
- 冲突全部裁决后可重跑；成功后旧 `decisions` / `conflicts` 被替换，不累加

### AC-95 权限矩阵

- 读引用图 / 裁决 / 冲突：guest / member / project_admin / system_admin 均可读；非成员 403 `NOT_PROJECT_MEMBER`
- 抽取 / 补链 / 触发第二遍 / 裁决冲突：guest / member → 403 `NOT_PROJECT_ADMIN`
- 归档项目 → 409 `PROJECT_ARCHIVED`（先于角色判定）
- 分析 / 冲突不存在或跨项目 → 404

### AC-96 审计

- 第二遍成功写 `incremental.second_pass.run`（`target_type='incremental_analysis'`、`target_id=分析 ID`）
- 冲突裁决写 `incremental.conflict.resolve`
- 手动补链写 `document.chapter_link.create`
- 校验失败的操作不写审计；`tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补这三个 action

### AC-97 离线可跑

- 第二遍仍只走 `MockProvider`，无任何真实网络调用
- 断网环境下全量 `pytest` 与 e2e 全绿；`second_pass_stats.provider` 恒为 `mock`

## 8. 错误码

| code | HTTP | 触发 |
|---|---|---|
| `INVALID_CHAPTER_LINK` | 400 | 补链目标二选一不满足、章节不属该版本、`from == to` |
| `DUPLICATE_CHAPTER_LINK` | 409 | 同一源章节同类型同目标的链接已存在 |
| `SECOND_PASS_NOT_READY` | 409 | 第一遍未成功，不能跑第二遍 |
| `SECOND_PASS_TEMPLATE_MISSING` | 409 | 第二遍模板缺失或已停用 |
| `SECOND_PASS_CONFLICTS_PENDING` | 409 | 仍有待裁决冲突，禁止重跑 |
| `CONFLICT_NOT_FOUND` | 404 | 冲突不存在或不属于该分析 |
| `CONFLICT_ALREADY_RESOLVED` | 409 | 冲突已确认 / 已驳回 |
| `INVALID_CONFLICT_RESOLUTION` | 400 | `decision` 非法，或 `confirmed` 缺 `label_type` / `rejected` 带了 `label_type` |

复用一期：`INCREMENTAL_ANALYSIS_NOT_FOUND`、`PROJECT_ARCHIVED`、`NOT_PROJECT_ADMIN`、
`NOT_PROJECT_MEMBER`、`LLM_CALL_FAILED`、`LLM_OUTPUT_INVALID`。

新增类进 `app/common/errors.py` 并同步 `__all__`。

## 9. 非功能

- 第二遍同步执行（与一期一致）；单次输入上限沿用模块常量，超限截断并记 WARN。
- 裁决 / 冲突列表沿用分页信封（默认 50，上限 200）；引用图列表不分页。
- 输入规模硬约束（C1）：2b-2 每次只带一个功能点的局部结论 + 相关章节摘要，
  章节正文截断阈值走模块常量占位。
- 阈值（召回策略、置信度门槛、传播衰减）本期**不实现**，留待基准集回填；
  `confidence` 只透传模型值，不做门槛过滤。
- 无新增第三方依赖。

## 10. 后续期（明确不在本期）

| 期 | 内容 |
|---|---|
| 第三期 | 产出段：写 `baseline_labels`（带 `source_analysis_id`）、生成新快照、冲突裁决结果 apply |
| 第四期 | 真实模型接入：模型供应商配置 + 密钥加密 + OpenAI 兼容 Provider + 运行日志 |
| 第五期 | 模板管理（版本化、试运行、上下文声明）与阈值基准集回填 |
