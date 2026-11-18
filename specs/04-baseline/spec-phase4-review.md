# 04 补期 A · 分点审核（局部通过 / 局部驳回）· 规格

> 对齐需求：PRD 2.4.2 基线管理「审核通过后冻结基线快照」；用户 2026-11-18 追加诉求：
> 「管理员能看到包裹里具体的模块 / 功能 / 功能点，并能勾选部分通过、局部驳回」。
> 上游依赖：04 主体（T55–T67）已完成；05 三期已完成；06 期 LLM 已通。
> 本文是**待 review 的方案**，未写任何业务代码。评审通过后才拆任务落地。

## 0. 一句话结论（先看这个）

| 问题 | 结论 |
|---|---|
| 表结构怎么改 | **新增两张表**（`baseline_review_items` 逐项决策 + `baseline_review_rounds` 审核轮次），**`structure_json` 格式不动** |
| 要不要 `node_status` | **要，但不是挂在结构表上**——挂在 `baseline_review_items.decision` 上（`pending/approved/rejected`）。结构表**不加**状态列 |
| 快照含什么 | **只含 approved 节点**；被驳回的节点**留在草稿里**（不删、不藏），用户改完可再次提交 |
| 驳回节点去哪了 | **既不丢弃、也不合并进基线**——它仍留在结构表里参与下一轮审核，只是**不进快照**、**不进 05 的比对清单** |
| 前端 | **不是改 `ProjectBaselineTree.tsx`**，而是**在 `ProjectBaselineSnapshots.tsx` 里新增一个「审核抽屉」**——树组件加了 Checkbox 会污染日常编辑场景 |

> 三个最容易踩的坑，第 1 节展开讲：**05 读的是当前结构表、不是快照**；**快照冻结的是"目录"不是"实体状态"**；
> **驳回不等于删除**。

---

## 1. 现状盘点（先讲事实，再讲设计）

### 1.1 现在审核是怎么工作的

```
POST /baselines/reviews/submit          → 建 baseline_revisions 一行 status='submitted'
POST /baselines/reviews/{id}/approve    → _freeze_structure() 冻结**当前整棵结构** → structure_json
                                          → 分配 version_no → 复制上一快照的生效标签
POST /baselines/reviews/{id}/reject     → 整条置 status='rejected'，意见必填
```

- 审核**没有"看内容"的入口**：`baseline_revisions` 在 `status='submitted'` 期间
  `structure_json` 是 **NULL**，内容全是空的。要看内容必须先冻结，而冻结只发生在 approve 那一刻。
- 计数（`module_count` / `function_count` / …）**在 approve 时才填**，所以审核中的记录全是 0——
  这正是用户看到的「统计全是 0」。**这不是 Bug，是"计数在冻结时才产生"的设计**，但对审核者毫无意义。
- 前端 `ProjectBaselineSnapshots.tsx` 的审核表只有两个按钮：**通过 / 驳回**。

### 1.2 关键事实：05 读的是**当前结构表**，不是快照

这是整份方案最重要的一条约束。查证结果：

| 读什么 | 在哪读 | 读的是 |
|---|---|---|
| 基线比对清单 | `app/incremental/context.py::baseline_index()` | **当前结构表**（`baseline_modules/functions/feature_points`，排除归档） |
| 第二遍功能点索引 | `app/incremental/second_pass.py::_active_function_points()` | **当前结构表** |
| 打标目标有效性 | `app/incremental/apply.py::_valid_target_ids()` | **当前结构表** |
| 快照内容 | `GET /baselines/revisions/{id}` → `structure_json` | 快照（**只给人看**） |

**推论**：

1. `baseline_revision_id` 在 05 里只是**"这次分析以哪份快照为基准"的溯源标记**，
   模型实际看到的清单来自**当前结构表**。
2. 因此「部分通过」如果只改快照（只冻结部分节点），**05 根本感知不到**——
   模型照样会看到全部节点，甚至看到被驳回的节点。
3. 要让「部分通过」真正生效，**必须同时决定：被驳回的节点在 05 的清单里出不出现**。

### 1.3 关键事实：快照冻结的是「目录」，不是「实体状态」

`_freeze_structure()` 冻结的是**当时的 id / name / description / version_no / source_type**，
**不是** `status` 字段本身。也就是说：

- 一个「当前是 active、但审核时被驳回」的节点，仍然留在结构表里、仍是 `active`。
- 下一个快照**如果不加过滤，会把它重新冻进去**。

所以「部分通过」要真正成立，必须有一个**持久化的"这一轮哪些节点通过了"记录**，
让下一次冻结能引用它——或者每次冻结都从审核轮次的决策里取。

---

## 2. 业务语义裁决（方案的核心，✅ 已裁决）

### 2.1 「部分通过」到底改变了什么

| 对象 | 部分通过后的状态 |
|---|---|
| **快照**（`structure_json`） | **只含 approved 节点**——被驳回的节点不出现在这份快照里 |
| **结构表**（modules/functions/points） | **不动**——驳回的节点仍在表里、仍是 active、可编辑、可再次提交 |
| **05 的比对清单**（`baseline_index`） | **只含 approved 节点**（已裁决，见 §2.2） |
| **标签**（`baseline_labels`） | 挂在 approved 节点上的照常复制到新快照；挂在 rejected 节点上的**不复制** |

### 2.2 05 的清单要不要排除被驳回的节点（✅ 已裁决：排除）

这是本方案**唯一一处业务语义空白**，有三个选项：

| 选项 | 05 清单内容 | 优点 | 缺点 |
|---|---|---|---|
| **A. 只按 approved 过滤**（✅ **已选**） | 只含 approved 节点 | 语义最一致：「审核通过什么，模型就看什么」；驳回 = 这段内容不存在 | 要改 `baseline_index`（05 侧一处读取口径改动） |
| B. 全部保留 | 全部 active 节点 | 05 零改动 | 被驳回的节点照样喂给模型，**「部分通过」形同虚设** |
| C. 驳回节点降级为「只比对不改」 | 全部节点，但 rejected 的不产生 changed 结论 | 信息不丢失 | 语义复杂，且要改 05 的判定逻辑（06 期红线：判定逻辑不改） |

**2026-11-18 用户裁决：选项 A（排除）。** 理由：

- 它是唯一让「局部驳回」产生**实际业务效果**的选项；
- 改动面小：只改 `baseline_index()` 一个函数的**读取口径**（加一个 approved 集合的过滤），
  **不改 05 的判定逻辑、不改字段校验、不改错误码**——符合 06 期红线；
- 过滤依据来自**审核轮次的决策表**，不依赖快照（快照只是给人看的）。

> ⚠️ 选项 A 会让 `baseline_index()` 依赖「当前是否有已批准的审核轮次」，
> 这是一个**新的耦合点**。缓解办法见 §4.4。

### 2.3 被驳回的节点：留草稿还是丢弃（✅ 已裁决：留草稿）

**裁决：留在草稿里，不丢弃。** 理由与具体规则：

| 场景 | 处理 |
|---|---|
| 驳回一个**功能点** | 该点仍留在结构表；驳回意见记在审核决策表里，前端在树上打「已驳回」标 |
| 驳回一个**功能** | 该功能及其**所有功能点**都不进快照（父被驳，子无意义） |
| 驳回一个**模块** | 该模块及其下全部功能、功能点都不进快照 |
| 用户改完再次提交 | 新建一个审核轮次，旧轮次的决策**保留可查**（不覆盖） |
| 用户不想再提交这条 | 可以直接**删除该节点**（走现有删除接口，走审计） |

**为什么不是"丢弃"**：

1. PRD 的基调是「清除 = 逻辑清除、行不删」——04 已经有这个原则
   （`baseline_labels` 清除只置 `cleared`）。丢弃会与之矛盾。
2. 丢掉了管理员就**失去了修改机会**——驳回的业务含义是"这条写得不对，改一下"，
   不是"这条不存在"。
3. 审核意见需要**留痕**——丢弃 = 意见悬空，没人知道当时为什么被否。

**但要防止"驳回的节点无限期混在基线里"**：见 §4.3 的「生效集合」定义。

---

## 3. 数据模型（新增 2 张表，`structure_json` 不动）

### 3.1 `baseline_review_rounds`（审核轮次）

**为什么需要这张表**：现在的 `baseline_revisions` 一行既是「审核记录」又是「快照」。
分点审核时，**一轮审核 = 多个逐项决策 + 一个最终结论**，
如果全塞进 `baseline_revisions`，`structure_json` 就得从"一棵冻结树"变成"树 + 决策表"，
两边格式纠缠。拆开更干净：

- `baseline_revisions`：**继续是快照容器**（`structure_json` 格式一个字不改）
- `baseline_review_rounds`：**一轮审核的过程记录**（谁提的、什么时候决的、整体结论）
- `baseline_review_items`：**逐项决策**

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| revision_id | BIGINT | FK → baseline_revisions.id，索引（CASCADE） |
| round_no | INT | 非空，项目内递增（同一 revision 多次提交审核时区分轮次） |
| status | VARCHAR(16) | 非空：`pending` / `approved` / `rejected` |
| submitted_by / submitted_at | BIGINT / DATETIME(3) | 非空 / 可空 |
| reviewed_by / reviewed_at | BIGINT / DATETIME(3) | 可空 / 可空 |
| summary_comment | VARCHAR(500) | 可空，整体审核意见 |
| created_at | DATETIME(3) | 非空 |

唯一：`(revision_id, round_no)`。
CheckConstraint：`status IN ('pending','approved','rejected')`。

### 3.2 `baseline_review_items`（逐项决策）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| round_id | BIGINT | FK → baseline_review_rounds.id，索引（CASCADE） |
| revision_id | BIGINT | FK → baseline_revisions.id，索引（CASCADE） |
| entity_type | VARCHAR(16) | 非空：`module` / `function` / `feature_point` |
| entity_id | BIGINT | 非空（多态，不建 FK） |
| entity_name | VARCHAR(128) | 非空，**决策时快照名称**（实体后来改名不影响历史） |
| decision | VARCHAR(16) | 非空：`pending` / `approved` / `rejected` |
| comment | VARCHAR(500) | 可空，**该条目的驳回意见** |
| decided_by / decided_at | BIGINT / DATETIME(3) | 可空 / 可空 |
| created_at | DATETIME(3) | 非空 |

唯一：`(round_id, entity_type, entity_id)`——一轮里同一实体只有一条决策。
索引：`(round_id, decision)`、`(project_id, entity_type, entity_id)`。
CheckConstraint：`entity_type IN ('module','function','feature_point')`、
`decision IN ('pending','approved','rejected')`。

### 3.3 为什么**不改** `structure_json`

用户问的是「怎么改造 `structure_json` 或新增表」。逐条对比：

| 维度 | 改造 `structure_json`（加 `node_status`） | 新增 `baseline_review_items` 表 |
|---|---|---|
| 快照兼容 | ❌ 旧快照没有 `node_status`，`get_revision` 的解析、前端的树渲染全要兼容两种格式 | ✅ 旧快照零改动 |
| 查询 | ❌ 要从 MEDIUMTEXT 里解析 JSON 再过滤，MySQL 侧**无法索引** | ✅ 普通索引，`WHERE decision='approved'` 直接命中 |
| 审计 | ❌ 决策历史被覆盖在 JSON 里，无法回答"第 2 轮谁把 X 改了" | ✅ 一轮一行，决策历史完整 |
| 可追溯 | ❌ 快照冻结后 JSON 不再变（AC-70 不可变原则），但决策是**审核过程中**发生的 | ✅ 决策表独立于快照生命周期 |
| 05 侧读取 | ❌ 05 读的是**当前结构表**，根本读不到快照 JSON——改了也白改 | ✅ 05 从决策表取「生效集合」，一次查询搞定 |

**结论**：走新增表这条路。`structure_json` 保持"一棵干净的冻结树"这个单一职责。

> 唯一需要动 `structure_json` 的地方是**它的内容来源**：
> `_freeze_structure()` 从"当前结构表全量"改为"当前结构表 ∩ 本轮 approved 集合"。

### 3.4 为什么结构表**不加** `node_status` 列

用户问「是否需要引入 `node_status`（pending/approved/rejected）记录每个功能/功能点的状态」。

**结论：结构表不加。** 三个理由：

1. **状态是「某一轮审核的结论」，不是「实体自身的属性」**。
   同一个功能在第 1 轮被驳回、第 2 轮被通过——它的"状态"变了，但实体本身没变。
   把轮次相关的状态固化到实体行上，就得再加一个 `last_review_round_id` 字段，
   状态语义就变成了"最近一轮的结果"，历史仍然丢失。
2. **审核是可选流程**。手工建基线的用户可能**从不提交审核**。
   如果 `node_status` 挂在结构行上，默认值是什么？`pending`（永远待审核）？
   那所有从未审核过的节点都会被 `baseline_index` 过滤掉，基线直接空了。
3. **结构表是 05/产出段/前端树三处的公共读取源**。加一列意味着每一处读取
   都要考虑"这个节点是不是 pending"——`baseline_index`、`_active_function_points`、
   `_valid_target_ids` 三处都要改，改动面反而更大。

> 折中：结构表**加一个 `review_state` 派生列**（只读、不由应用层写），
> 记录"最近一次审核里这个节点是什么结论"。**本期不做**——先不加，
> 等审核轮次跑起来后如果前端确实需要"在树上一眼看出哪些被驳回过"，
> 再用一个 `LEFT JOIN` 的查询接口补，不动表。

### 3.5 迁移

`migrations/versions/0021_review_items.py`，`down_revision = "0020_baseline_derive"`。

upgrade：`baseline_review_rounds` → `baseline_review_items`（外键依赖顺序）。
downgrade：反序删表。
**无种子数据**（不改任何既有数据）。

> **迁移编号归属（2026-11-18 用户裁决：先做从文档推导）**：
> 从文档推导 = `0020_baseline_derive`（先落地），
> 分点审核 = `0021_review_items`（`down_revision = "0020"`）。
> 两个方案**不并行**，按此顺序串行落地。

---

## 4. 服务层设计

### 4.1 「生效集合」（approved set）的定义

**这是整个方案的核心抽象。** 定义一个函数：

```
approved_entities(session, project_id) -> set[(entity_type, entity_id)]
```

规则：

1. 取项目内**最近一轮 `status='approved'` 的审核轮次**；
2. 该轮 `baseline_review_items` 里 `decision='approved'` 的条目 → 进集合；
3. **父被驳回 → 子自动出局**：
   - 模块不在集合 → 其下功能全部不在集合；
   - 功能不在集合 → 其下功能点全部不在集合；
4. **没有任何已批准的审核轮次** → 集合 = **空**。

> ⚠️ 第 4 条是个**重要的兼容性陷阱**：
> 手工建的基线（从不提交审核）如果集合为空，05 就什么都比不了。
>
> **缓解办法（✅ 已裁决）**：`baseline_index()` 的过滤规则改为
> **「有已批准轮次 → 按 approved 集合过滤；没有已批准轮次 → 不过滤（全量 active）」**。
> 也就是：**只有真正用过分点审核的项目才受过滤影响**，传统项目行为完全不变。

### 4.2 审核流程改造

```
POST /baselines/reviews/submit
    → 建 baseline_revisions(status='submitted')
    → 建 baseline_review_rounds(status='pending', round_no=1)
    → 快照「待审内容」= 当前结构树（供前端渲染审核树，不写 structure_json）
    → 返回 round_id + 内容树
```

新增接口：

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/baselines/reviews/{revision_id}/items` | 该轮**逐项决策**（含 entity_name、decision、comment） | 项目成员可读 |
| GET | `/baselines/reviews/{revision_id}/tree` | 该轮**待审内容树**（模块/功能/功能点 + 当前决策 + 父链） | 项目成员可读 |
| POST | `/baselines/reviews/{revision_id}/decide` | **逐项决策**（可批量）：`{items:[{entity_type,entity_id,decision,comment}]}` | 项目管理员 |
| POST | `/baselines/reviews/{revision_id}/approve` | 整体通过（**按逐项决策冻结**） | 项目管理员 |
| POST | `/baselines/reviews/{revision_id}/reject` | 整体驳回（意见必填） | 项目管理员 |

`decide` 接口的语义：**保存决策草稿，不冻结**。可以多次调用（逐个勾、或批量），
最后一次 `approve` 才冻结。

`approve` 的改造：

```
approve_review(revision_id, decisions=None)
    1. 校验：status='submitted'、自审开关（沿用 allow_baseline_self_approval）
    2. 取该轮所有 items；**没决策的条目默认 = rejected**（保守：不决策 = 不通过）
       —— 或者由请求体显式传 `default_decision` 决定
    3. 校验：至少有一条 approved（否则 409 空审核）
    4. _freeze_structure(session, project_id, approved_set=...)  ← 只冻结通过的
    5. 分配 version_no、status='approved'、写计数
    6. 复制上一快照的生效标签 → **只复制 approved 节点上的标签**
    7. 写 baseline_review_rounds.status='approved' + reviewed_by/at
    8. 审计 baseline.revision.approve（after_data 带 approved/rejected 计数 + self_approved）
```

**兼容性**：原来的 `POST /reviews/{id}/approve`（不传 decisions）**继续可用**，
语义 = "全部通过"（approved_set = 全量 active）。旧前端与旧用例**零改动**。

### 4.3 驳回节点在下一轮怎么办

- **不影响**下一轮提交：用户可以**只改被驳回的那几条**，改完再提交；
- 下一轮提交时**新建一个 round**（`round_no + 1`），
  旧 round 的决策**保留**（可查"第 1 轮谁否了 X"）；
- 新一轮的 approved 集合**完全重新计算**，不看上一轮——
  这符合直觉：每一轮是独立的审核。

> ⚠️ 由此产生一个**已裁决的问题**：用户改了被驳回的节点后重新提交，
> 新一轮**未勾选**的节点怎么办？
>
> **✅ 裁决：新一轮的默认决策继承上一轮的**（上一轮 approved → 新一轮预选 approved；
> 上一轮 rejected → 新一轮预选 pending）。
> 这样用户"改了再提交"时不用重新勾一遍。
> 这个默认值由前端在打开审核抽屉时**预填勾选状态**体现，后端不做隐式继承。

### 4.4 05 侧改动（选项 A 前提下的最小改动）

只改 `app/incremental/context.py::baseline_index()` 的**读取口径**：

```
def baseline_index(session, project_id):
    # 现状：查当前结构表里 active 的模块/功能/功能点
    # 改为：
    #   1. 取 approved_set（§4.1）
    #   2. 没有已批准轮次 → 集合为空 → 保持原逻辑（全量 active）
    #   3. 有已批准轮次 → 只返回集合内的条目
```

**一行不改的**（06 期红线）：
- `app/incremental/engine.py` 的 `_parse_conclusion` / 越界判定 / `new` 丢弃规则 —— 不动
- `app/incremental/second_pass.py` —— 不动
- `app/incremental/apply.py` —— 不动
- 错误码 —— 不动

> `second_pass.py::_active_function_points()` 也读当前结构表。
> 它管的是"功能 → 其功能点"的映射，**不参与 05 的越界判定**（越界判定用 `baseline_index`），
> 所以本期**不动它**。若将来 approved 集合里出现"功能通过但功能点全被驳回"，
> `_active_function_points` 会返回该功能下**不在集合**的功能点——
> 这只影响 `scoped_conclusions` 的证据作用域宽窄，**不影响结论正确性**。
> 本期接受这个差异，spec §5.1 明确记录。

---

## 5. 接口契约（详细）

### 5.1 `GET /baselines/reviews/{revision_id}/tree`

**用途**：审核抽屉渲染一棵**带勾选状态**的三级树。

```json
{
  "revision_id": 12,
  "round_id": 3,
  "round_no": 1,
  "status": "pending",
  "tree": [
    {
      "entity_type": "module",
      "entity_id": 5,
      "name": "支付模块",
      "description": "...",
      "source_type": "manual",
      "decision": "pending",
      "comment": null,
      "children": [
        {
          "entity_type": "function",
          "entity_id": 9,
          "name": "扫码支付",
          "version_no": 2,
          "decision": "approved",
          "comment": null,
          "children": [
            {
              "entity_type": "feature_point",
              "entity_id": 21,
              "name": "确认付款",
              "decision": "rejected",
              "comment": "与需求 3.2 不符",
              "children": []
            }
          ]
        }
      ]
    }
  ],
  "stats": { "total": 12, "approved": 7, "rejected": 2, "pending": 3 }
}
```

**关键设计**：
- 树里**只含"当前 active 的节点"**——归档节点不参与审核（与快照口径一致）。
- `decision` 是**该节点自己的**决策；前端需要显示"父被驳回时子也出局"时，
  **由前端在渲染时推导**（父 rejected → 子显示为"随父驳回"），
  **后端不替前端算**，避免两处逻辑漂移。
- `stats` 给前端显示进度。

### 5.2 `POST /baselines/reviews/{revision_id}/decide`

**请求**：

```json
{
  "items": [
    { "entity_type": "function", "entity_id": 9, "decision": "approved", "comment": null },
    { "entity_type": "feature_point", "entity_id": 21, "decision": "rejected", "comment": "与需求 3.2 不符" }
  ]
}
```

**校验顺序**（固定）：
1. 项目存在（404）/ 归档（409）/ 角色（403 `NOT_PROJECT_ADMIN`）；
2. 记录存在且属本项目（404 `REVIEW_NOT_FOUND`）；
3. 状态为 `submitted`（409 `INVALID_REVIEW_STATUS`）；
4. `entity_type` 合法（400 `INVALID_REVIEW_ITEM`）；
5. `decision` 合法（400 `INVALID_REVIEW_DECISION`）；
6. `entity_id` 对应的实体**存在且属本项目**（404 `REVIEW_ITEM_NOT_FOUND`）；
7. `decision='rejected'` → `comment` 必填（400 `REVIEW_ITEM_COMMENT_REQUIRED`）。

**副作用**：写 `baseline_review_items`（upsert 语义：同轮同实体覆盖旧决策），
写审计 `baseline.review.decide`（after_data 只记 `entity_type/entity_id/decision`，
**不记整棵树**——审计不是数据仓库）。

**响应**：`{ "updated": 2, "stats": {...} }`

### 5.3 `POST /baselines/reviews/{revision_id}/approve`

请求体扩展（**向后兼容**）：

```json
{
  "comment": "整体通过",
  "items": [ ... ]          // 可选：与 decide 同一形状，最后一次决策
}
```

- 不传 `items` → **全部 approved**（旧行为）；
- 传了 `items` → 先应用这些决策，**未出现在 `items` 里的节点按"未决策"处理**。

**"未决策"怎么处理 —— 两个选项**：

| 选项 | 行为 | 评价 |
|---|---|---|
| **默认 rejected**（✅ **已选**） | 没勾 = 不通过 | 保守，符合"审核"的语义；管理员漏勾的节点不会意外进基线 |
| 默认 approved | 没勾 = 通过 | 危险：管理员只勾了要驳回的，结果全进了 |

> **✅ 裁决：默认 rejected**，并在响应里返回
> `stats.pending_count`，让前端提示"还有 N 条未决策，将按未通过处理"。

**新增错误码**：

| code | HTTP | 触发 |
|---|---|---|
| `INVALID_REVIEW_ITEM` | 400 | `entity_type` 非法 |
| `INVALID_REVIEW_DECISION` | 400 | `decision` 非法 |
| `REVIEW_ITEM_NOT_FOUND` | 404 | 实体不存在或不属于该项目 |
| `REVIEW_ITEM_COMMENT_REQUIRED` | 400 | 驳回条目缺意见 |
| `EMPTY_REVIEW_APPROVAL` | 409 | 一条都没通过 |

---

## 6. 前端设计

### 6.1 关键结论：**不改 `ProjectBaselineTree.tsx`**

用户问「`ProjectBaselineTree.tsx` 怎么改造？是不是要在每个节点前加 Checkbox？」

**答案：不在这个组件上加 Checkbox。** 理由：

1. `ProjectBaselineTree.tsx` 是**日常编辑页**——建模块、加功能、打标签、归档、迁移。
   在它的每个节点前挂 Checkbox，会让用户在"编辑"和"审核"两种心智模型之间反复切换：
   **勾选框点了是干嘛的？选了会删东西吗？** 这是典型的交互污染。
2. 它已有 5 类节点内操作按钮（新增功能 / 重命名 / 迁移 / 归档 / 删除 / 标签 / 删除功能点），
   再加 Checkbox 会让节点标题**塞不下**（现在是 `<Space size={6} wrap>`，会换行）。
3. 审核是**有时才发生**的动作（提交审核 → 等待审核 → 审核通过），
   应该是一个**独立的、有明确边界的界面**，而不是把树变成一个永远带勾选框的控件。

**结论**：`ProjectBaselineTree.tsx` 与 `baselineTreeNodes.tsx` **一行不改**。

### 6.2 审核抽屉放在 `ProjectBaselineSnapshots.tsx`

```
ProjectBaselineSnapshots.tsx
  ├── Card「基线快照」
  │     ├── Table「审核中」
  │     │     └── 操作列：通过 / 驳回  ← 改成：
  │     │           ├── 「分点审核」按钮  → 打开审核抽屉
  │     │           └── 「整包通过」按钮  → 直接调 approve（不带 items）
  │     │           └── 「整包驳回」按钮  → 打开驳回弹窗（意见必填）
  │     └── Table「审核通过」
  └── ★ 新增：审核抽屉（Drawer，width=720）
        ├── 顶部工具条：进度（已选 7 / 共 12）、全选、清除选择
        ├── 批量操作条：通过所选 / 驳回所选  ← 批量按钮放这里
        └── 树：Checkbox + 名称 + 状态标签 + 驳回意见
```

**批量按钮的位置**：**放在抽屉顶部的工具条里**（紧挨进度条），**不在树的节点里**。

理由：
- 批量操作是"作用于一批选中项"的动作，天然属于**集合上下文**，不属于某个节点；
- 放在节点里意味着"批量通过这个节点"——语义不成立；
- 放在抽屉底部容易被用户滚到底才看见（树可能很长）；
- 顶部工具条同时放「进度 / 全选 / 批量通过 / 批量驳回」，用户一眼知道当前选了几个。

### 6.3 审核树的节点长什么样

```
☑  支付模块                                    [全部通过]
   ☑  扫码支付                         [已通过]
        ☑  确认付款                     [已通过]
        ☐  退款到原路                   [未决策]
   ☐  退款管理                         [已驳回]  意见：与需求 3.2 不符
        ☐  原路退款                     [未决策]  （随父驳回）
```

**渲染规则**：

| 元素 | 规则 |
|---|---|
| Checkbox | 放在节点标题**最左侧**（在 `<Space>` 之外，用 `Tree` 的 `checkable` + 自定义 title） |
| 勾选含义 | **勾 = 本次通过**（`approved`），不勾 = 待决策。**不勾 ≠ 驳回**——两态区分：未决策 vs 明确驳回 |
| 父节点状态 | 三个子态都选上 → 父半选（`indeterminate`）；全选 → 父勾上 |
| 明确驳回 | 单独一个「驳回」按钮（行内），点了要填意见；驳回后 Checkbox 取消勾选 + 节点显示红标 + 意见内联展示 |
| 层级联动 | 勾选父节点 → **级联勾选全部子节点**（antd `checkable` 默认行为）；驳回父节点 → 子节点全部取消勾选并显示"随父驳回" |
| 归档节点 | 不出现在审核树里（与快照口径一致） |

> 「勾选 = 通过」这个语义有个好处：**它与"审核=挑选要保留什么"的心智一致**，
> 用户不需要理解 pending/approved/rejected 三态——UI 上只有「勾上/没勾上」两态，
> 三态在数据层表达（没勾 = pending 或 rejected，由是否填了驳回意见区分）。

### 6.4 前端文件落点

| 文件 | 改动 |
|---|---|
| `web/src/pages/ProjectBaselineSnapshots.tsx` | **新增审核抽屉**（组件主体）；审核表操作列改按钮 |
| `web/src/pages/BaselineReviewDrawer.tsx` | **新建**：审核抽屉（树 + Checkbox + 批量条） |
| `web/src/pages/baselineReviewNodes.tsx` | **新建**：审核树的节点渲染（与 `baselineTreeNodes.tsx` 同构但独立） |
| `web/src/api/index.ts` | 新增 3 个接口 + 类型（`BaselineReviewTree` / `BaselineReviewItem` / `BaselineReviewStats`） |
| `web/src/api/client.ts` | 补 5 个新错误码中文 |
| `web/src/pages/ProjectBaselineTree.tsx` | **不改** |
| `web/src/pages/baselineTreeNodes.tsx` | **不改** |

> 组件行数：`ProjectBaselineSnapshots.tsx` 现状 478 行，加抽屉会超标。
> 抽屉**单独成文件** `BaselineReviewDrawer.tsx`，符合任务清单约定第 8 条
> （单页组件超约 400 行时拆子组件）。

### 6.5 交互流程（管理员视角）

```
1. 项目详情 →「基线管理」Tab → 「基线快照」Card
2. 「审核中」表格里有一行 → 点「分点审核」
3. 抽屉打开：加载待审树，所有节点默认**未勾选**
   （若上一轮有决策，预填勾选状态 —— §4.3）
4. 逐个勾选要通过的；不想要的点「驳回」填意见
5. 顶部显示「已选 7 / 共 12」
6. 点「通过所选」→ 批量把勾选的标成 approved（可多次点）
7. 也可以点「提交审核结论」→ 打开带 items 的 approve
   → 冻结只含 approved 的快照
8. 提示："本次通过 7 项、驳回 2 项、未决策 3 项（未决策按未通过处理）"
```

---

## 7. 审计

新增 action：

| action | 触发 |
|---|---|
| `baseline.review.submit` | 提交审核（创建轮次） |
| `baseline.review.decide` | 保存逐项决策（批量合并成一条审计） |
| `baseline.revision.approve` | 整体通过（**沿用现有 action**，`after_data` 增 `approved_count` / `rejected_count` / `pending_count` / `round_id`） |
| `baseline.revision.reject` | 整体驳回（沿用现有 action） |

`after_data` 里**不记整棵树**，只记计数与 ID 列表（截断）。

---

## 8. 验收标准

### AC-132 分点决策落库
- 提交审核 → 建 `baseline_revisions(submitted)` + `baseline_review_rounds(pending, round_no=1)`
- `decide` 逐项决策 → `baseline_review_items` 按 `(round_id, entity_type, entity_id)` upsert
- 同轮同实体重复决策 → **覆盖**旧行，不新增行
- 驳回条目缺意见 → 400 `REVIEW_ITEM_COMMENT_REQUIRED`

### AC-133 分点通过只冻结 approved
- 3 个功能，勾 2 个通过、驳 1 个 → `approve`（带 items）
- 快照 `structure_json` **只含 2 个功能**（及它们的功能点）
- `module_count` / `function_count` / `feature_point_count` **只计 approved**
- 驳回的功能**不出现在**快照里，但**仍在结构表**里（`GET /functions` 还能查到）

### AC-134 驳回节点留在草稿
- 驳回后 `GET /functions` 仍返回该功能（status 仍 `active`）
- 该功能可被编辑（`PATCH` 成功，`version_no` +1）
- 再次提交审核 → 新建 `round_no=2` 的轮次；旧的 round 1 决策**仍可查**
- 前端树可见"该节点上一轮被驳回"的提示（走 §4.3 的预填 + 意见回显）

### AC-135 父驳回子出局
- 驳回一个功能 → 它的功能点**不进快照**
- 驳回一个模块 → 它下面所有功能、功能点**不进快照**
- 前端展示"随父驳回"标记

### AC-136 整包审核向后兼容
- 旧调用 `POST /reviews/{id}/approve`（不传 items）→ 行为与现在**完全一致**（全量冻结）
- 旧用例 `test_ac_69_approve_freezes` 等**不改即通过**

### AC-137 05 只看 approved 节点（✅ 已裁决：排除）
- 项目有已批准轮次，驳回了功能 F → `baseline_index()` **不含** F
- 项目**没有**已批准轮次（纯手工基线）→ `baseline_index()` **含全部** active 节点（行为不变）
- 05 的判定逻辑 / 字段校验 / 错误码**零改动**（`git diff` 自证）

### AC-138 标签只复制 approved 节点的
- 驳回节点上有生效标签 → 新快照**不复制**这条标签
- approved 节点上的标签正常复制
- 驳回节点**不删除**旧快照上的标签（旧快照不可变）

### AC-139 权限与审计
- `decide` / `approve` 限项目管理员；member → 403 `NOT_PROJECT_ADMIN`
- 读 `tree` / `items` 成员可读；非成员 → 403 `NOT_PROJECT_MEMBER`
- 归档项目 → 409 `PROJECT_ARCHIVED`
- 每次 `decide` 写审计 `baseline.review.decide`

### AC-140 离线可跑
- 本期**不调用任何模型**，零真实网络请求；断网下全量 pytest 与 e2e 全绿

---

## 9. 任务拆分（待评审通过后执行）

| 任务 | 内容 |
|---|---|
| T93 | 模型 + 迁移 0021（`baseline_review_rounds` / `baseline_review_items`）+ 模型注册 |
| T94 | 服务层：`approved_entities` / `decide` / `list_tree` / `approve` 改造（只冻结 approved） |
| T95 | 路由 + schemas + 5 个错误码 + 审计 |
| T96 | 05 侧：`baseline_index()` 按 approved 集合过滤 + 回归 |
| T97 | 前端：审核抽屉 + 审核树 + api + 错误码映射 |
| T98 | 收尾：全量 pytest + e2e + 文档回填 |

**依赖**：T93 → T94 → T95 → T97；T96 依赖 T94 的 `approved_entities`。

> **任务编号**：从文档推导方案占用 T88–T92（先做），
> 本方案顺延到 **T93–T98**。

---

## 10. 已裁决事项（2026-11-18 用户拍板）

> 本节记录用户 review 时确认的决策。**方案正文已按这些裁决写定**，
> 下表只是把「为什么是这么定的」留档，便于日后回溯。

| # | 问题 | 裁决 | 落地位置 |
|---|---|---|---|
| 1 | 05 的清单要不要排除被驳回节点？ | **排除**（选项 A）：`baseline_index()` 按 approved 集合过滤 | §2.2、§4.4 |
| 2 | 没有已批准审核轮次的项目，05 清单要不要过滤？ | **不过滤**（保持全量 active，传统项目零影响） | §4.1 |
| 3 | 驳回节点留草稿 vs 丢弃？ | **留草稿**（不删不藏，可编辑可重提） | §2.3 |
| 4 | 未决策的节点在 approve 时怎么处理？ | **按 rejected 处理**（保守），响应返回 `pending_count` 提示 | §5.3 |
| 5 | 驳回是否强制填意见？ | **强制**（逐条意见 + 整体意见） | §5.2 |
| 6 | 新一轮是否继承上一轮的勾选状态？ | **继承**（前端预填，后端不隐式继承） | §4.3 |
| 7 | 分点审核是否要做"整体驳回"入口？ | **保留**（意见必填，与现状一致） | §5.3 |
| 8 | 旧 `approve`（不带 items）接口保留吗？ | **保留**，语义=全部通过 | §4.2、§8 AC-136 |
| 9 | 结构表要不要加 `node_status` / `review_state` 列？ | **不加**（先不加，等审核跑起来看需不要） | §3.4 |
| 10 | 审核界面放哪里？ | **独立审核抽屉**，`ProjectBaselineTree.tsx` 一行不改 | §6.1、§6.2 |
| 11 | 先做审核还是先做推导？ | **先做从文档推导**（本方案顺延到 T93–T98） | §3.5、§9 |

---

## 11. 与既有 spec 的关系

- 本文**不改** `specs/04-baseline/spec.md` 的既有条款（AC-62~AC-76 全部继续有效）；
- 本文**不改** `specs/05-incremental-analysis/spec*.md` 的判定逻辑与业务语义；
- 本文**不改** `specs/06-real-llm/spec.md` 的任何红线；
- 本文新增的 AC 编号从 **AC-132** 起（从文档推导方案占用 AC-122~AC-131）；
- 04 的 `spec.md` §2.2「本期不做：文档推导」由
  `spec-phase4-derive.md` 承接（另一个方案）。
