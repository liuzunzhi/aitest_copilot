# 04 补期 B · 从文档推导基线 · 规格

> 对齐需求：PRD 2.4.2 基线管理「文档推导 / 基线反推」；用户 2026-11-18 追加诉求：
> 「基线管理界面没有从文档推导基线的按钮」。
> 上游依赖：03-documents（T46–T58）已完成（文档 / 版本 / 章节树 / 文档基线快照）；
> 04 主体（T55–T67）已完成；05 三期已完成；06 期 LLM 已通（迁移 `0017` +
> `OpenAICompatProvider` + `parse_llm_json` 容错）。
> 本文是**待 review 的方案**，未写任何业务代码。评审通过后才拆任务落地。

## 0. 一句话结论（先看这个）

| 问题 | 结论 |
|---|---|
| 数据落哪 | **直接落结构表**（`baseline_modules/functions/feature_points`），`source_type='document_derived'`，追溯字段全填 |
| 是不是要新表 | **不要新表**——04 的结构表**已经预留了全部追溯字段**（`source_document_id` / `source_version_id` / `source_chapter_id` / `source_chapter_title` / `source_method`） |
| 走什么模型 | **走 05 已有的 `get_provider` 工厂**（无配置 → 自动降级 Mock），**不新建模型层** |
| 怎么保证不污染 | **推导结果先落「草稿」，用户确认后才进结构表**；不进审核流程的话永远只是草稿 |
| 会不会覆盖已有基线 | **绝不覆盖**。同名节点 → 提示"已存在"，让用户决定跳过 / 合并 / 重命名 |
| 审核怎么走 | 推导出的节点**和手工建的一样**，走**同一个审核流程**（分点审核也认它们） |

---

## 1. 现状盘点（事实先摆清楚）

### 1.1 已经有的（不用重做）

| 已有件 | 位置 | 能直接复用的部分 |
|---|---|---|
| 文档 / 版本 / 章节树 | `app/models/document.py` | `documents` / `document_versions` / `document_chapters` 三张表 |
| 章节树读取 | `app/documents/service.py::list_chapters()` | 直接返回嵌套树，带 `id / level / title / content / char_count` |
| 多格式解析 | `app/documents/parser.py` | `.md/.docx/.txt/.pdf` 已全部支持（T84-PDF 落地） |
| 文档基线快照 | `app/models/document.py::BaselineSnapshot` | 03 侧的"文档版本 → 基线序号"，与 04 的功能基线**不是一回事**，别混 |
| 追溯字段（结构表） | `app/models/baseline.py` | `source_type` / `source_document_id` / `source_version_id` / `source_chapter_id` / `source_chapter_title` / `source_method` / `source_analysis_id` **全部已存在** |
| 模型工厂 | `app/llm/provider.py::get_provider()` | 查库取默认配置 → 没有就降级 `MockProvider` |
| JSON 容错解析 | `app/llm/json_utils.py::parse_llm_json()` | 剥围栏 / 剥 `<think>` 思考块 |
| 运行留痕 | `app/llm/run_log.py` | 统一的写入口 |
| 提示词模板表 | `prompt_templates` | `task_type` 枚举里**已经预留了 `document_parse`**（至今没人用过） |

### 1.2 缺的（本期要补）

| 缺的 | 说明 |
|---|---|
| **推导引擎** | 章节 → 模块/功能/功能点的抽取逻辑，没有 |
| **推导记录表** | 一次推导的输入（文档+版本）、输出（候选树）、状态、统计，**没有** |
| **接口** | 发起推导 / 查推导结果 / 采纳候选，没有 |
| **前端按钮** | 「基线管理」页没有「从文档推导」入口，用户明确点了这一条 |
| **模板** | `prompt_templates` 里没有 `task_type='document_parse'` 的模板（枚举里有类型，没种子数据） |

### 1.3 与 05 增量分析的关系（**必须分清**）

两者都调模型、都从文档出发，但**目的相反**：

| | 05 增量分析 | 本期·从文档推导基线 |
|---|---|---|
| 输入 | 旧文档版本 vs **新**文档版本 | **一份**文档（需求文档） |
| 基线 | **已存在**（比对方） | **不存在**（要造出来） |
| 输出 | 标签（changed/affected/…） | **实体**（模块/功能/功能点） |
| 方向 | 找**差异** | 找**结构** |

> 所以本期**不能复用 05 的引擎**，但可以复用 05 的**基础设施**
> （provider 工厂、JSON 容错、运行留痕、模板表）。

---

## 2. 业务语义裁决（方案核心）

### 2.1 推导结果**先落草稿，不直接进结构表**（✅ 已裁决）

这是本方案最关键的一条。理由：

1. **模型会抽错**。抽出来的"功能"可能是文档里的一句话、一个小节标题。
   直接落结构表 = 把噪声塞进基线，而基线是 05 比对的**基准**——
   基准里有一条噪声，05 就多一个越界判断的噪声源。
2. **现有 UI 只能编辑已落库的结构**（`ProjectBaselineTree.tsx` 的操作按钮都是对已存在节点的操作）。
   要让用户在采纳前**修改**候选（改名、删掉不想要的、调层级），候选必须**先有 ID**，
   否则没法挂编辑动作。
3. PRD 原则二「高风险行为人工确认」——批量新建几十个实体是高风险行为。

**因此引入一张「推导记录」表 + 一个「候选草稿」阶段**：

```
上传文档（03 已有）
   │
   ▼
发起推导 → 选文档版本 → 选模板 → 跑模型
   │
   ▼
推导记录 status='succeeded'，候选树落「候选草稿表」
   │
   ▼
前端「推导结果」抽屉：候选树 + 每个候选可改名 / 删除 / 调整层级
   │
   ▼
用户点「采纳」→ 选中的候选写入结构表（source_type='document_derived' + 追溯字段）
   │
   ▼
走**和手工建的一样的审核流程** → 通过后进快照
```

### 2.2 候选草稿要不要单独建表

**要。** 但不建"模块/功能/功能点"三张候选表——那样太重。
建**一张统一的候选表**，用 `entity_type` 区分层级：

#### `baseline_derive_candidates`（候选草稿）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| derive_id | BIGINT | FK → baseline_derives.id，索引（CASCADE） |
| parent_id | BIGINT | 可空，FK → 本表 id（父候选）——自引用 |
| entity_type | VARCHAR(16) | 非空：`module` / `function` / `feature_point` |
| name | VARCHAR(128) | 非空 |
| description | VARCHAR(500) | 可空 |
| source_chapter_id | BIGINT | 可空，FK → document_chapters.id（**这行是从哪个章节抽出来的**） |
| source_chapter_title | VARCHAR(255) | 可空，章节标题快照 |
| confidence | DECIMAL(3,2) | 可空，模型给的置信度 |
| rationale | VARCHAR(1000) | 可空，模型给的依据 |
| status | VARCHAR(16) | 非空：`pending` / `adopted` / `skipped` |
| adopted_entity_type | VARCHAR(16) | 可空，采纳后写进结构表的是哪种实体 |
| adopted_entity_id | BIGINT | 可空，采纳后写进结构表的行 id |
| created_at | DATETIME(3) | 非空 |

索引：`(derive_id, entity_type)`、`(derive_id, parent_id)`、`(derive_id, status)`。
唯一：`(derive_id, parent_id, name, entity_type)`——同一父下同名同级候选只留一条。

> `parent_id` 自引用 + `entity_type` 组合表达三层结构：
> `parent_id IS NULL` → 模块；父是 module → 功能；父是 function → 功能点。
> **加一个 `level` 冗余列**更好读，但可以由 `entity_type` 推出，不加。

### 2.3 推导记录表 `baseline_derives`

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| document_id | BIGINT | FK → documents.id，索引 |
| document_version_id | BIGINT | FK → document_versions.id，索引 |
| template_id | BIGINT | FK → prompt_templates.id，索引 |
| template_version | INT | 非空，模板版本快照 |
| provider | VARCHAR(32) | 非空，模型来源（`mock` / `openai_compat`） |
| status | VARCHAR(16) | 非空：`running` / `succeeded` / `failed` |
| stats | JSON | 可空，统计 |
| error_code / error_message | VARCHAR(64) / VARCHAR(500) | 可空 |
| started_at / finished_at | DATETIME(3) | 可空 |
| created_by | BIGINT | 非空 |
| created_at | DATETIME(3) | 非空 |

> `stats` 结构：
> ```json
> {
>   "chapter_count": 12,
>   "processed_count": 12,
>   "candidate_count": 47,
>   "module_count": 5, "function_count": 30, "feature_point_count": 12,
>   "skipped_chapters": [{"chapter_id": 3, "reason": "empty_content"}]
> }
> ```

### 2.4 采纳时的**同名冲突**怎么处理

结构表有唯一索引：模块 `(project_id, name)`、功能 `(module_id, name)`、功能点 `(function_id, name)`。

**绝不覆盖、绝不静默跳过**。三种处理，前端让用户选：

| 冲突 | 前端给的选择 |
|---|---|
| 同名模块已存在 | **① 复用该模块**（把候选功能挂到已有模块下）② **新建模块**（重命名后新建）③ **跳过该候选** |
| 同名功能已存在 | ① 复用 ② 跳过 |
| 同名功能点已存在 | ① 复用 ② 跳过 |

- **复用** = 候选的 `adopted_entity_id` 指向已有行，**不写追溯字段**
  （已有行可能本来就是手工的，改它的追溯字段会污染语义）。
- **新建** = 写新行 + 填全部追溯字段。
- **跳过** = 候选 `status='skipped'`。

> **为什么不做「自动合并」**：合并会改已有实体的名字/描述，那是**审核前的静默修改**，
> 与「高风险行为人工确认」冲突。

### 2.5 推导出来的节点，审核怎么走

**和手工建的完全一样**：

- 采纳后进入结构表 → 出现在 `ProjectBaselineTree.tsx` 的树上 → 可编辑 / 可打标 / 可归档；
- 提交审核 → 走**同一个** `submit_review` / `approve_review`；
- 如果同时落地分点审核，推导出的节点**也出现在审核树里**，管理员可以逐条勾。

> 这一点很重要：**推导只是"批量造数据"的手段，审核才是"把关"的关口**。
> 不给推导结果单独搞一套审核，会变成两套规则。

---

## 3. 数据模型

### 3.1 汇总

| 表 | 动作 | 理由 |
|---|---|---|
| `baseline_derives` | **新增** | 一次推导的输入 / 输出 / 状态 / 统计 |
| `baseline_derive_candidates` | **新增** | 候选草稿（带 id，可编辑、可删） |
| `baseline_modules` / `functions` / `feature_points` | **只写不改结构** | 已有 `source_type` + 追溯字段，够用 |
| `baseline_revisions` | **不改** | 审核快照，与手工路径共用 |
| `prompt_templates` | **加一条种子** | `task_type='document_parse'` 的模板 |

### 3.2 追溯字段的填写口径

采纳候选写入结构表时：

| 字段 | 值 |
|---|---|
| `source_type` | `'document_derived'` |
| `source_document_id` | 推导记录.document_id |
| `source_version_id` | 推导记录.document_version_id |
| `source_chapter_id` | 候选.source_chapter_id（该实体是从哪个章节抽出来的） |
| `source_chapter_title` | 候选.source_chapter_title |
| `source_method` | `'baseline_reverse'`（04 的模型注释里已经写好的枚举值） |
| `source_analysis_id` | NULL（这不是增量分析产出的） |

> `source_method` 的取值：模型注释写的是 `baseline_reverse` / `incremental_new`。
> 本期用 `baseline_reverse`——正是"基线反推"。

### 3.3 迁移

`migrations/versions/0020_baseline_derive.py`，`down_revision = "0019"`。

upgrade 顺序：
1. `baseline_derives`
2. `baseline_derive_candidates`（自引用 FK + 外键到 `baseline_derives`）
3. **种子**：`prompt_templates` 插一条 `task_type='document_parse'` 的模板

downgrade：反序删表 + 删种子模板。

> **迁移编号归属（2026-11-18 用户裁决：先做从文档推导）**：
> 从文档推导 = `0020_baseline_derive`，分点审核 = `0021_review_items`
> （`down_revision = "0020"`）。两个方案**不并行**，按此顺序串行落地。

---

## 4. 推导引擎设计

### 4.1 整体流程

```
POST /baselines/derive
    1. 校验：项目存在 / 归档 / 角色（项目管理员）
    2. 校验：文档版本存在、属本项目、status='active'（只有生效版本可推导）
    3. 校验：模板存在、status='active'、task_type='document_parse'
    4. 建 baseline_derives(status='running')
    5. 取章节树（list_chapters）
    6. 逐章节调模型：
       - 跳过 char_count == 0 的章节
       - 解析模型返回的 JSON → 该章节的候选列表
       - 候选挂到该章节的父章节候选下（章节层级 → 候选层级）
    7. 落候选表 + 回填 stats + status='succeeded'
    8. 写审计 baseline.derive.run
```

### 4.2 Prompt 组装

**复用 05 的组装模式**（`app/incremental/context.py` 的做法）：

```
system = template.system_prompt

user   = template.user_prompt
       + "\n\n## 文档信息\n"
       + f"- 文档名：{document_name}\n- 版本：v{version_no}"
       + "\n\n## 已有基线结构（避免重复）\n" + 已有结构清单
       + f"\n\n## 章节：{chapter.title}\n{chapter.content}"
```

> **「已有基线结构」这一段很重要**：不给它，模型每次都把整个文档的结构重复抽一遍，
> 多次推导会产生大量重复候选。加上它，模型倾向于只抽"文档里新出现的"内容。
>
> 代价是 Prompt 变长——沿用 05 的 `BASELINE_BRIEF_MAX_RATIO = 0.4` 截断策略，
> 超预算时截断并注明省略了多少条。

### 4.3 模型输出契约

模型返回（每章节一次）：

```json
{
  "modules": [
    {
      "name": "用户登录",
      "description": "账号密码与验证码登录",
      "functions": [
        {
          "name": "账号密码登录",
          "description": "...",
          "feature_points": [
            { "name": "密码错误次数限制", "description": "..." }
          ]
        }
      ]
    }
  ]
}
```

**校验规则**（比 05 宽松一档，因为这是"建议"不是"结论"）：

| 情况 | 处理 |
|---|---|
| 某章节没有结构化内容（纯背景描述） | **不算失败**，该章节跳过，记 `skipped_chapters` |
| 某个候选名字为空 / 超长 | **丢弃该候选**，不失败 |
| 某章节返回不是合法 JSON | **整次推导失败**（与 05 一致：坏 JSON 是真问题，不能默默跳过） |
| 返回的 JSON 结构不是 `{modules:[...]}` | **整次推导失败** |

> 这里与 05 的差异要说清楚：05 是"章节局部结论"，坏 JSON 必须失败；
> 本期是"结构抽取"，一个章节抽不出东西是**正常的**（很多章节是背景介绍），
> 但**抽出了乱码**必须失败。

### 4.4 层级映射（章节层级 → 候选层级）

**不做章节 → 模块的机械映射**。模型的输出自带三层结构（modules/functions/feature_points），
**章节只是"这段内容出自哪里"的出处标记**，不是层级来源。

```
章节 C（level=2）
  └─ 模型抽出一个 module「用户登录」
       └─ function「账号密码登录」
            └─ feature_point「密码错误次数限制」
```

- 每个候选的 `source_chapter_id` = 它所属的**最叶子章节** id；
- `source_chapter_title` = 该章节标题（快照，章节改名不影响历史）；
- **同一个模块在多个章节里出现** → 按名字合并成**一个**候选（父为 NULL），
  其功能点合并进来；`source_chapter_id` 取**第一次出现**的章节。
  合并时同名功能点去重。

> **为什么合并**：同一个"用户登录"模块往往散落在文档的 2.1 和 3.4 两节里。
> 不合并就会产出两个同名模块候选，采纳时必然撞唯一索引。

### 4.5 与 05 的红线对齐

| 06 期红线 | 本期怎么遵守 |
|---|---|
| 不改 05 的判定逻辑与业务语义 | **不改 `app/incremental/` 任何文件**（除了可选的 `baseline_index` 过滤，见分点审核方案） |
| API Key 绝不明文落库 / 不出现在日志 | 复用 `app/llm/crypto.py` + `app/llm/provider.py` 的既有链路 |
| 任何测试不允许产生真实 socket | 推导引擎的 provider **依赖注入**，测试用 `httpx.MockTransport` |
| 不引入无超时的网络调用 | 复用 `OpenAICompatProvider` 的 `httpx.Timeout` |
| JSON 容错 | 复用 `parse_llm_json`（含 `<think>` 剥离） |

---

## 5. 接口契约

前缀：`/api/projects/{project_id}/baselines/derive`

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | `/derive` | 发起推导（**同步跑完返回**） | 项目管理员 |
| GET | `/derive` | 推导记录列表 | 项目成员 |
| GET | `/derive/{derive_id}` | 推导详情 + 候选树 | 项目成员 |
| POST | `/derive/{derive_id}/adopt` | **采纳候选**（写入结构表） | 项目管理员 |
| DELETE | `/derive/{derive_id}/candidates/{candidate_id}` | 删一个候选（草稿阶段） | 项目管理员 |

### 5.1 `POST /derive`

**请求**：

```json
{
  "document_id": 3,
  "document_version_id": 7,
  "template_id": 2
}
```

**校验顺序**（固定）：
1. 项目存在（404 `PROJECT_NOT_FOUND`）/ 归档（409 `PROJECT_ARCHIVED`）/ 角色（403 `NOT_PROJECT_ADMIN`）；
2. 文档存在且属本项目（404 `DOCUMENT_NOT_FOUND`）；
3. 版本存在且属该文档（404 `DOCUMENT_VERSION_NOT_FOUND`）；
4. 版本状态为 `active`（409 `DOCUMENT_VERSION_NOT_ANALYZABLE`）；
5. 模板存在且 `task_type='document_parse'` 且 `status='active'`
   （400 `PROMPT_TEMPLATE_INVALID`）。

**响应**（同步跑完）：

```json
{
  "id": 5,
  "status": "succeeded",
  "provider": "openai_compat",
  "document_id": 3,
  "document_version_id": 7,
  "template_id": 2,
  "stats": {
    "chapter_count": 12, "processed_count": 12,
    "candidate_count": 47,
    "module_count": 5, "function_count": 30, "feature_point_count": 12,
    "skipped_chapters": []
  },
  "error_code": null,
  "error_message": null
}
```

> **同步执行**与 05 一致（05 第一遍也是同步）。理由：现有架构没有后台队列，
> 同步是最简单且行为一致的选择。**推导耗时会长**（12 章 × 一次模型调用），
> 前端要有 loading 提示 + 超时放宽（前端 axios 超时要单独调大，或改走轮询）。

### 5.2 `GET /derive/{derive_id}` —— 候选树

```json
{
  "id": 5,
  "status": "succeeded",
  "document_name": "需求规格说明书",
  "stats": { "...": "见 §2.3" },
  "candidates": [
    {
      "id": 30,
      "parent_id": null,
      "entity_type": "module",
      "name": "用户登录",
      "description": "账号密码与验证码登录",
      "source_chapter_title": "3.1 登录模块",
      "confidence": 0.92,
      "rationale": "章节 3.1 明确描述了登录相关功能",
      "status": "pending",
      "children": [
        {
          "id": 31, "parent_id": 30, "entity_type": "function",
          "name": "账号密码登录", "description": "...",
          "source_chapter_title": "3.1 登录模块",
          "confidence": 0.9, "rationale": "...",
          "status": "pending",
          "children": [
            { "id": 32, "parent_id": 31, "entity_type": "feature_point",
              "name": "密码错误次数限制", "description": "...",
              "source_chapter_title": "3.1.2 密码策略",
              "confidence": 0.88, "rationale": "...",
              "status": "pending", "children": [] }
          ]
        }
      ]
    }
  ]
}
```

**关键设计**：
- 候选树**直接带 `status`**（`pending`/`adopted`/`skipped`），前端据此显示已采纳 / 已跳过；
- **不带 `children: []` 的空数组**——前端渲染更简单；
- `source_chapter_title` **给的是标题不是 id**——用户认章节靠标题；
  `source_chapter_id` 在服务端内部用，不外露（呼应"UI 不暴露内部主键"那条约定）。

### 5.3 `POST /derive/{derive_id}/adopt`

**请求**：

```json
{
  "candidates": [
    {
      "candidate_id": 30,
      "action": "reuse",       // reuse | create | skip
      "name": "用户登录",       // create 时可改名
      "existing_entity_id": 12 // reuse 时必填
    },
    { "candidate_id": 31, "action": "create" },
    { "candidate_id": 32, "action": "create" }
  ]
}
```

**服务端规则**：

| `action` | 行为 |
|---|---|
| `create` | 新建行 + 填 `source_type='document_derived'` + 全部追溯字段 |
| `reuse` | **不写任何行**，只把候选的 `status` 置 `'adopted'`、`adopted_entity_id` 指向已有行 |
| `skip` | 候选 `status='skipped'`，不写行 |

**约束**：
- 采纳是**层级递归**的：采纳一个模块时，它下面的功能、功能点**自动一起采纳**
  （不能只采纳模块不采纳功能——那样功能点会挂到不存在的功能上）；
- 因此请求体**只传顶层模块候选 + action**，子候选跟着走；
  要单独跳过某个子候选 → 先在草稿阶段**删掉它**（`DELETE /derive/{id}/candidates/{cid}`）。
- **`reuse` 的目标必须是"同类型的同级实体"**：
  模块候选只能 reuse 一个模块；功能候选只能 reuse 一个**同模块下**的功能。
  跨层级 / 跨模块 → 400 `REVIEW...` 不对，是 `ADOPT_TARGET_INVALID`。
- 已 `adopted` / `skipped` 的候选**不能重复采纳**（409 `ADOPT_ALREADY_DECIDED`）。

**响应**：

```json
{
  "derive_id": 5,
  "adopted_count": 42,
  "created": { "modules": 5, "functions": 28, "feature_points": 9 },
  "reused": { "modules": 0, "functions": 2, "feature_points": 0 },
  "skipped": { "modules": 0, "functions": 0, "feature_points": 5 },
  "items": [
    { "candidate_id": 30, "entity_type": "module", "entity_id": 88, "name": "用户登录", "action": "create" }
  ]
}
```

**采纳后**：推导记录 `status` 不变（还是 `succeeded`），但**候选的 status 变成 adopted/skipped**，
前端据此显示"已采纳"。再加一个 `adopted_at` 字段到候选表？——**不加**，
`status` + `adopted_entity_id` 已经够了，采纳时间在审计里。

### 5.4 新增错误码

| code | HTTP | 触发 |
|---|---|---|
| `BASELINE_DERIVE_NOT_FOUND` | 404 | 推导记录不存在 |
| `BASELINE_DERIVE_STATUS_INVALID` | 409 | 推导未成功 / 候选已决策 |
| `ADOPT_TARGET_INVALID` | 400 | reuse 的目标类型/层级不匹配 |
| `ADOPT_ALREADY_DECIDED` | 409 | 候选已被采纳或跳过 |
| `ADOPT_CANDIDATE_NOT_FOUND` | 404 | 候选不存在 |
| `DOCUMENT_VERSION_NOT_ANALYZABLE` | 409 | 版本不是 active（复用 05 的错误码） |
| `PROMPT_TEMPLATE_INVALID` | 400 | 模板不存在/停用/类型不对（**复用 06 期的**） |
| `DOCUMENT_VERSION_NOT_FOUND` | 404 | 版本不存在（复用 03 的） |

> **复用优先**：03 / 05 / 06 已有同义错误码的**直接复用**，不新造同义码。
> `DOCUMENT_NOT_FOUND` / `DOCUMENT_VERSION_NOT_FOUND` / `PROJECT_ARCHIVED` /
> `NOT_PROJECT_ADMIN` / `NOT_PROJECT_MEMBER` 全部复用。

---

## 6. 前端设计

### 6.1 「从文档推导基线」按钮放哪

用户明确说「基线管理界面，没有从文档推导基线的按钮」。

**位置**：`ProjectBaselineTree.tsx` 的**工具条**，紧挨「新增模块」按钮。

```
[搜索功能名] [标签类型▾] [来源类型▾]  [＋新增模块] [从文档推导]  [刷新] [状态▾]
```

- 挂在**工具条**而不是节点里：它是**项目级**动作，不是某个节点的动作；
- 与「新增模块」并列：两者都是"往基线里加东西"的入口；
- `canWrite &&` 控制显示（与「新增模块」一致）；
- `data-testid="derive-from-document"`（按约定「区域-动作-目标」）。

### 6.2 推导流程的前端界面

```
点「从文档推导」
   │
   ▼
Modal「从文档推导基线」
  ├── Select「需求文档」      ← 列出项目内的文档
  ├── Select「文档版本」      ← 只列 active 版本
  ├── Select「提示词模板」    ← task_type='document_parse' 的 active 模板
  └── [开始推导]  ← loading 态（文案："正在调用模型分析文档，可能需要 1–2 分钟"）
   │
   ▼
Drawer「推导结果」width=800
  ├── 顶部统计：模块 5 / 功能 30 / 功能点 12 / 跳过章节 2
  ├── 候选树（可展开）
  │     ├── 每行：Checkbox（是否采纳）+ 名称（可编辑）+ 出处章节 Tag + 置信度 + 依据
  │     └── 冲突提示：同名已存在 → Tag「已存在同名模块」+ 下拉选「复用 / 改名新建 / 跳过」
  ├── [全选] [全不选]
  └── 底部：[采纳所选]  ← 关闭抽屉 → reload 树
```

### 6.3 前端文件落点

| 文件 | 改动 |
|---|---|
| `web/src/pages/ProjectBaselineTree.tsx` | **只加一个按钮**（工具条），其余不改 |
| `web/src/pages/BaselineDeriveModal.tsx` | **新建**：发起推导弹窗（文档 / 版本 / 模板三个 Select） |
| `web/src/pages/BaselineDeriveDrawer.tsx` | **新建**：推导结果抽屉（候选树 + 采纳） |
| `web/src/pages/baselineDeriveNodes.tsx` | **新建**：候选树节点渲染 |
| `web/src/api/index.ts` | 新增 5 个接口 + 类型（`BaselineDerive` / `BaselineDeriveCandidate` / `BaselineDeriveStats`） |
| `web/src/api/client.ts` | 补新错误码中文 |
| `app/baselines/service.py` | 新增推导相关的服务函数（与现有结构 CRUD 并列） |
| `app/baselines/derive.py` | **新建**：推导引擎（纯逻辑 + provider 注入） |

> **候选树的 Checkbox 语义**：勾 = 采纳；**但与分点审核的 Checkbox 语义不同**
> （那里勾 = 通过）。两个界面在不同 Tab / 不同抽屉里，语义不冲突，但**文案要区分**：
> 推导抽屉用「采纳」，审核抽屉用「通过」。

### 6.4 与分点审核的前端关系

两个方案**共用**的部分：

| 共用件 | 说明 |
|---|---|
| `ProjectBaselineTree.tsx` | 分点审核**不改**它；推导**只加一个按钮** |
| 结构树渲染 | 两边**各写各的**：审核树要 Checkbox + 决策态，候选树要 Checkbox + 出处 + 置信度 + 冲突提示。**不复用同一个组件**——语义不同，强行复用会出一堆 `variant` 分支 |
| `api/index.ts` / `client.ts` | 同一个文件，加各自的接口与错误码 |

---

## 7. 提示词模板

### 7.1 种子模板

迁移 `0021` 播种一条 `prompt_templates`：

| 字段 | 值 |
|---|---|
| `name` | `基线推导·文档结构抽取` |
| `task_type` | `'document_parse'` |
| `status` | `'active'` |
| `version_no` | 1 |

**System Prompt 要点**：

```
[DERIVE_SYSTEM] 你是需求文档结构分析助手。
从给定的章节正文中抽取「模块 → 功能 → 功能点」三层结构。
只输出 JSON：{"modules":[{"name":"...","description":"...",
  "functions":[{"name":"...","description":"...",
    "feature_points":[{"name":"...","description":"..."}]}]}]}。
规则：
1. 只抽正文里明确写到的内容，不要臆造、不要补全常识；
2. 章节是背景介绍、没有可抽取的功能时，输出 {"modules": []}；
3. 名称用文档里的原词，不要改写；
4. 不要输出 JSON 之外的任何内容。
```

**User Prompt 要点**：

```
从下面章节中抽取功能基线结构。
若下方「已有基线结构」里已有同名模块 / 功能，优先复用已有名称，不要重复抽取。

## 文档信息
- 文档名：{document_name}
- 版本：v{version_no}

## 已有基线结构（避免重复抽取）
{existing_brief}

## 章节：{chapter_title}
{chapter_content}
```

> **`task_type='document_parse'` 这个枚举值 06 期就已经预留了**
> （`app/models/incremental.py` 的 `TASK_TYPES` 里有），
> 至今没人用过——本期正好用它，不需要改枚举，也不需要改表。

### 7.2 模板管理 UI

06 期的 `AdminSettingsPage` 已经能列出并编辑 `prompt_templates`（按 `task_type` 分）。
**本期不新增模板管理界面**——新模板从系统设置页编辑即可。
只需要确认 `AdminSettingsPage` 的模板 Tab 能按 `document_parse` 过滤出来。

---

## 8. 审计

| action | 触发 | after_data |
|---|---|---|
| `baseline.derive.run` | 发起推导 | `document_id` / `document_version_id` / `template_id` / `provider` / `stats` |
| `baseline.derive.adopt` | 采纳候选 | `derive_id` / `created` 计数 / `reused` 计数 / `skipped` 计数（**不记整棵树**） |

失败（校验不通过 / 模型调用失败）**不写** `baseline.derive.run` 审计——
只在记录行里留 `error_code` / `error_message`。

> 与 05 的 `incremental.apply.run` 口径一致：**失败留痕在业务记录上，不污染审计流水**。

---

## 9. 验收标准

### AC-122 推导记录与候选落库
- 发起推导 → `baseline_derives` 新增一行（`status='running'` → `'succeeded'`）
- 候选落 `baseline_derive_candidates`，`parent_id` 组成三层
- `stats` 计数与实际候选数一致
- 模型调用失败 → `status='failed'` + `error_code`，**不写** `baseline.derive.run` 审计

### AC-123 章节为空可跳过，坏 JSON 必须失败
- 某章节无结构化内容（模型返回 `{"modules": []}`）→ **不失败**，记入 `skipped_chapters`
- 某章节返回非 JSON → **整次推导失败**，`status='failed'`
- `char_count == 0` 的章节 → 跳过，不调模型（**不计入调用次数**）

### AC-124 跨章节同名合并
- 两个章节都抽出「用户登录」模块 → 候选表里**只有一条** module 候选
- 其下的同名功能点去重；`source_chapter_id` 取第一次出现的章节

### AC-125 已有基线结构进 Prompt
- 项目已有基线 → Prompt 的 user 部分含「已有基线结构」清单
- 清单超预算 → 截断并注明省略条数（沿用 05 的 `BASELINE_BRIEF_MAX_RATIO`）
- 同一份 Prompt 渲染两次 → 内容一致（可复现）

### AC-126 采纳写入结构表 + 追溯字段
- 采纳后结构表新增行，`source_type='document_derived'`
- `source_document_id` / `source_version_id` / `source_chapter_id` /
  `source_chapter_title` / `source_method='baseline_reverse'` 全部有值
- `source_analysis_id` 为 NULL
- **结构表定义零改动**（`git diff app/models/baseline.py` 为空）

### AC-127 同名冲突不覆盖
- 同名模块已存在 → **不覆盖**；`reuse` 复用已有行（不改其追溯字段）
- `create` 时改名 → 新建行，名字是用户给的新名
- `skip` → 不写行，候选 `status='skipped'`
- 已有模块行的 `source_type` / `source_document_id` **一字未改**

### AC-128 采纳是层级递归的
- 采纳一个模块 → 它的功能、功能点**一起采纳**
- 请求体只传顶层候选即可；子候选被单独删掉后不再被采纳

### AC-129 推导结果走同一套审核
- 采纳后的节点出现在 `GET /functions` 里，`source_type='document_derived'`
- 可提交审核、可审核通过 → 进快照
- 分点审核落地后，推导节点也出现在审核树里，可逐条勾选

### AC-130 权限与审计
- 发起推导 / 采纳 → 项目管理员；member → 403 `NOT_PROJECT_ADMIN`
- 读推导记录 / 候选 → 项目成员；非成员 → 403 `NOT_PROJECT_MEMBER`
- 归档项目 → 409 `PROJECT_ARCHIVED`
- 非 active 文档版本 → 409 `DOCUMENT_VERSION_NOT_ANALYZABLE`
- 成功写 `baseline.derive.run` + `baseline.derive.adopt`

### AC-131 离线可跑
- 推导引擎的 provider **可注入**；测试用 `httpx.MockTransport`，**零真实 socket**
- 无默认大模型配置 → 自动降级 `MockProvider`（返回空模块列表，推导成功但 0 候选）
- 断网下全量 pytest 与 e2e 全绿

---

## 10. 任务拆分（待评审通过后执行）

| 任务 | 内容 |
|---|---|
| T88 | 模型 + 迁移 0020（`baseline_derives` / `baseline_derive_candidates`）+ 种子模板 |
| T89 | 推导引擎 `app/baselines/derive.py`（章节遍历 / Prompt 组装 / JSON 解析 / 层级合并） |
| T90 | 服务层 + 路由 + schemas + 错误码 + 审计（发起 / 列表 / 详情 / 采纳 / 删候选） |
| T91 | 前端：`ProjectBaselineTree.tsx` 加按钮 + 推导弹窗 + 结果抽屉 + 候选树 + api |
| T92 | 收尾：全量 pytest + e2e + 文档回填 |

**依赖**：T88 → T89 → T90 → T91。

> **任务编号**：本方案（先做）占用 **T88–T92**；
> 分点审核方案顺延到 **T93–T98**，迁移 `0021_review_items`。
> 两份文档的任务编号表见 `tasks.md` 的「两个方案的落地顺序与迁移编号」。

---

## 11. 已裁决事项（2026-11-18 用户拍板）

> 本节记录用户 review 时确认的决策。**方案正文已按这些裁决写定**，
> 下表只是把「为什么是这么定的」留档，便于日后回溯。

| # | 问题 | 裁决 | 落地位置 |
|---|---|---|---|
| 1 | 推导结果直接进结构表，还是先落草稿？ | **先落候选草稿**，用户确认后采纳 | §2.1、§2.2 |
| 2 | 同名冲突怎么处理？ | **绝不覆盖**，提示用户选 复用 / 改名新建 / 跳过 | §2.4、§5.3 |
| 3 | 同一模块在多个章节出现怎么办？ | **合并成一条候选**（同名去重） | §4.4 |
| 4 | 推导失败是整次失败，还是跳过该章节继续？ | **坏 JSON 整次失败**；**抽不出内容不算失败**（记 `skipped_chapters`） | §4.3 |
| 5 | 采纳时能否只采纳模块不采纳功能？ | **不能**（层级递归，单独排除请先删候选） | §5.3 |
| 6 | 是否要做"增量推导"（只补差异，不重复抽）？ | 本期**不做**（靠「已有基线结构」进 Prompt 降低重复） | §4.2 |
| 7 | 草稿候选保留多久？ | **永久保留**（表里带 `status`，不自动清理） | §2.2 |
| 8 | 推导要不要支持"不指定文档版本，用最新 active 版本"？ | **支持**（前端默认选中 active 版本） | §5.1 |
| 9 | 同步跑还是异步？ | **同步**（与 05 一致），前端 loading + 放宽超时 | §5.1、§6.2 |
| 10 | 是否复用 05 的 `task_type='document_parse'` 枚举位？ | **复用**（枚举已预留，不改表） | §7.1 |
| 11 | 先做推导还是先做分点审核？ | **先做推导**（本方案 T88–T92），分点审核顺延到 T93–T98 | §3.3、§10 |

---

## 12. 与既有 spec 的关系

- 本文**不改** `specs/03-documents/spec.md` 的任何条款（只**读**它的数据）；
- 本文**不改** `specs/04-baseline/spec.md` 的既有条款，但**兑现**了它 §2.2 里
  「文档推导…本期不做，留存追溯字段」留下的口子——追溯字段本期**有写入方**了；
- 本文**不改** `specs/05-incremental-analysis/spec*.md` 的判定逻辑与业务语义；
- 本文新增的 AC 编号从 **AC-122** 起（接 06 期的 AC-121）；
  分点审核方案的 AC 顺延到 **AC-132** 起。