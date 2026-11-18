# 05 · 增量分析（第一期 · 第一遍章节局部比对）· 规格

> 对齐需求：PRD 2.4.3 增量分析（记录留痕部分）、需求文档 v2.2 §4.2 第一遍·章节局部、§4.7 验收第 3 条。
> 上游依赖：03-documents 提供文档、生效版本、章节树；04-baseline 提供基线快照（`baseline_revisions.status='approved'`）与功能三级结构。
> 本期**只做第一遍**：章节 → LLM 比对 → 局部结论落库。
> 第二遍全局裁决（2b-1 / 2b-2 / 2b-3）、产出段写标签、模板管理 UI、真实模型调用**均不在本期**。

## 1. 背景与目标

PRD 主链路「上传文档 → 版本生效 → 文档解析 → 基线管理 → **增量分析** → 标签人工确认 → 测试点分析」中，
03 做完了「文档 → 章节树」，04 做完了「模块 → 功能 → 功能点 + 快照 + 两级标签」，
中间的**增量比对**是断的：章节内容与基线功能之间没有任何自动比对能力，
变更判定只能靠人一条条看。

本期目标：打通「章节 → 模型比对 → 局部结论落库」这一段，并把它做成**完全离线可跑、可断言**：

- LLM 调用走 `LLMProvider` 抽象，本期**只实现 `MockProvider`**，零真实网络请求；
- 提示词**从数据库模板读取**（`prompt_templates`），不硬编码在代码里；
- 第一遍结论逐条落 `incremental_conclusions`，越界与违规结论**丢弃并留痕**，不写脏数据。

做完之后，下一期做第二遍全局裁决时，只需消费 `incremental_conclusions`，不必再改本期的表与接口。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 提示词模板落库 | `prompt_templates` 单表，`task_type='incremental'` 的模板提供 `system_prompt` / `user_prompt`；只落库 + 被读取，**不做增删改查页面** |
| 分析记录 | 发起一次分析 → `incremental_analyses` 一行，记录模板、比对基准快照、对比文档版本、状态、统计 |
| 第一遍·章节局部比对 | 遍历生效文档版本的章节树，逐章节调 `LLMProvider.chat`，产出局部结论（`changed` / `affected` / `unchanged`） |
| 局部结论落库 | `incremental_conclusions` 逐条落库，带章节、目标、标签、置信度、理由 |
| 越界丢弃 | Mock 返回的目标不在「比对基准快照的基线」内 → **丢弃**，并把丢弃明细与错误标识记进 `analyses.stats` |
| 违规丢弃 | 第一遍返回 `label_type='new'` → **丢弃**（v2.2 §4.7-3：新增只能由第二遍按功能点索引写入） |
| 记录查询 | 分析记录列表 / 详情（含统计与丢弃明细）/ 结论列表 |
| 审计 | 发起分析写 `incremental.analysis.create` |

### 2.2 本期不做（红线，违反即返工）

| 不做 | 原因 |
|---|---|
| **任何真实网络请求** | 不许引入 `openai`、不许 `httpx`/`requests` 调模型、不许写 `requests.post`。`LLMProvider` 本期只有 `MockProvider` 一个实现 |
| **模板管理 UI / 模板 CRUD 接口** | 模板只落库 + 被读取；`prompt_templates` 由迁移播种，本期不给写接口 |
| **第二遍全局裁决**（2b-1 功能点索引 / 2b-2 按点分治 / 2b-3 图传播） | 下一期 |
| **产出段**（写 `baseline_labels`、生成新快照、冲突人工裁决队列） | 下一期；本期结论只进 `incremental_conclusions` |
| **章节引用图** | 2b-3 的前置，随第二遍一起做 |
| **密钥加密 / 模型供应商配置 / 运行日志表** | 本期无真实 provider，无密钥可存；日志走标准 logging |
| **「结论已全部撤销」标记** | 依赖产出段的标签清除回调 |
| **顺手修无关模块** | 例：03 的 PDF 解析、04 的 `source_type` 下拉值、清除原因枚举——记待办，等用户点头 |

### 2.3 与 04 的对接点（硬约束）

04 的 `app/baselines/references.py` 里，增量分析引用解析器**已就位**，探测到 `incremental_analyses` 表存在就生效。
它执行的是这条 SQL：

```sql
SELECT id, COALESCE(status, '') FROM incremental_analyses WHERE baseline_revision_id = :revision_id
```

因此本期建表必须**逐字满足**：

1. 表名必须是 `incremental_analyses`；
2. 必须有 `baseline_revision_id` 列（指向 `baseline_revisions.id`）；
3. 必须有 `status` 列。

满足之后，「快照被增量分析引用 → 禁止删除」在 05 落地当天自动生效，04 无需改动。
本期**不额外改动** `app/baselines/` 任何代码。

### 2.4 待确认（先按此实现，评审时可改）

1. `label_type` 本期只允许 `changed` / `affected` / `unchanged` 三种；`new` 被强制丢弃（见 AC-80）。
2. 丢弃的结论**不建第 4 张表**（红线：只建三张），统一记进 `incremental_analyses.stats.discarded` 数组与 `discarded_count` 计数。
3. 一次分析的全部章节处理完才算一次事务提交；单个章节调用失败 → 整个分析 `status='failed'`，已落库结论保留（便于排查），`stats` 记录失败章节。
4. 模板 `status='disabled'` 与模板不存在都**不产生分析记录**（先校验，后建行）。
5. 本期 `split_granularity` 只接受 `chapter`；传其他值 → 400 `INVALID_SPLIT_GRANULARITY`。

## 3. 角色与权限

| 操作 | guest | member | project_admin | system_admin |
|---|---|---|---|---|
| 分析记录列表 / 详情 / 结论列表 | 可 | 可 | 可 | 可（兜底） |
| 发起分析 | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |

- 非项目成员访问读接口 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404 `PROJECT_NOT_FOUND`。
- 归档项目内发起分析 → 409 `PROJECT_ARCHIVED`（**先判归档，再判角色**）。
- 发起分析限项目管理员：消耗模型资源且产物要落基线，依据 PRD 原则一「默认保守安全优先」。

## 4. 数据模型（3 张新表，迁移 0013）

迁移文件 `migrations/versions/0013_incremental.py`，`down_revision = "0012"`。
三张表按外键依赖顺序建：`prompt_templates` → `incremental_analyses` → `incremental_conclusions`；
`downgrade` 严格反序删表。

### 4.1 `prompt_templates`（提示词模板）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| name | VARCHAR(128) | 非空 |
| task_type | VARCHAR(32) | 非空，`document_parse` / `incremental` / `test_point` / `test_case`；本期只用 `incremental` |
| description | VARCHAR(500) | 可空 |
| system_prompt | MEDIUMTEXT | 非空 |
| user_prompt | MEDIUMTEXT | 非空 |
| version_no | INT | 非空，默认 1（版本化留给后续，本期不改） |
| status | VARCHAR(16) | 非空，默认 `active`，取值 `active` / `disabled` |
| created_at / updated_at | DATETIME(3) | 非空 |

唯一：`(task_type, name)`。
CheckConstraint：`task_type IN ('document_parse','incremental','test_point','test_case')`、`status IN ('active','disabled')`。

种子数据：迁移内播种 1 条 `task_type='incremental'`、`status='active'`、`name='增量分析·第一遍·章节局部'` 的模板，
保证 05 开箱可用、不依赖手工插数据。

### 4.2 `incremental_analyses`（分析记录）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| template_id | BIGINT | FK → prompt_templates.id，索引 |
| template_version | INT | 非空，发起时快照模板的 `version_no` |
| provider | VARCHAR(32) | 非空，默认 `mock` |
| baseline_revision_id | BIGINT | FK → baseline_revisions.id，索引（**04 引用解析器依赖此列**） |
| document_id | BIGINT | FK → documents.id，索引 |
| document_version_id | BIGINT | FK → document_versions.id，索引 |
| split_granularity | VARCHAR(16) | 非空，默认 `chapter`；本期只允许该值 |
| status | VARCHAR(16) | 非空，默认 `pending`，取值 `pending` / `running` / `succeeded` / `failed` |
| error_code | VARCHAR(64) | 可空 |
| error_message | VARCHAR(500) | 可空 |
| stats | JSON | 可空，见 §4.2.1 |
| started_at / finished_at | DATETIME(3) | 可空 |
| created_by / created_at | BIGINT / DATETIME(3) | 非空 |

CheckConstraint：`status IN ('pending','running','succeeded','failed')`、
`split_granularity IN ('chapter')`。

#### 4.2.1 `stats` 结构

```json
{
  "chapter_count": 3,
  "conclusion_count": 5,
  "discarded_count": 1,
  "dropped_new_count": 0,
  "discarded": [
    {
      "chapter_id": 12,
      "chapter_title": "登录",
      "target_type": "function",
      "target_id": 99,
      "label_type": "changed",
      "code": "INCREMENTAL_TARGET_OUT_OF_BASELINE"
    }
  ]
}
```

- `discarded` 是**被丢弃结论的明细**，不是业务数据：不进 `incremental_conclusions`，也不进任何标签表。
- `code` 取值：`INCREMENTAL_TARGET_OUT_OF_BASELINE`（目标不在比对基准基线内）、
  `INCREMENTAL_LABEL_NEW_DROPPED`（第一遍返回 `new`）。

### 4.3 `incremental_conclusions`（第一遍局部结论）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| analysis_id | BIGINT | FK → incremental_analyses.id（`ON DELETE CASCADE`），索引 |
| chapter_id | BIGINT | FK → document_chapters.id，索引 |
| chapter_title | VARCHAR(255) | 非空，落库时快照，章节改名不影响历史结论 |
| target_type | VARCHAR(16) | 非空，`function` / `feature_point` |
| target_id | BIGINT | 非空，指向功能或功能点（多态，不建 FK） |
| label_type | VARCHAR(16) | 非空，`changed` / `affected` / `unchanged`（**不含 `new`**） |
| confidence | DECIMAL(3,2) | 可空，模型给的置信度 |
| rationale | VARCHAR(1000) | 可空，模型给的理由摘要 |
| created_at | DATETIME(3) | 非空 |

唯一：`(analysis_id, chapter_id, target_type, target_id)`——同一次分析里，同一章节对同一目标的结论只留一条。
CheckConstraint：`target_type IN ('function','feature_point')`、
`label_type IN ('changed','affected','unchanged')`。

## 5. 接口

统一前缀 `/api/projects/{project_id}/incremental`，全部 JSON，在 `app/main.py` 注册 `incremental_router`。

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/analyses` | 分析记录列表（分页信封 `Page[AnalysisOut]`），按项目过滤，支持 `status` 筛选 | 项目成员 |
| POST | `/analyses` | 发起分析 | 项目管理员 |
| GET | `/analyses/{analysis_id}` | 分析详情（含 `stats` 与 `discarded` 明细） | 项目成员 |
| GET | `/analyses/{analysis_id}/conclusions` | 第一遍局部结论列表（分页信封），支持 `chapter_id` / `target_type` 筛选 | 项目成员 |

**`POST /analyses` 入参**

```json
{
  "template_id": 1,
  "baseline_revision_id": 3,
  "document_version_id": 7,
  "split_granularity": "chapter"
}
```

- `document_id` 由 `document_version_id` 反查得出，不接受前端传入（避免不一致）。
- 不传 `baseline_revision_id` → 400 `BASELINE_REVISION_REQUIRED`。
- 不传 / 传空 `split_granularity` → 默认 `chapter`；传其他值 → 400 `INVALID_SPLIT_GRANULARITY`。

**写接口校验顺序**（固定，便于用例逐条断言）
1. 项目存在（404 `PROJECT_NOT_FOUND`）
2. 归档检查（409 `PROJECT_ARCHIVED`）
3. 角色检查（403 `NOT_PROJECT_ADMIN`）
4. 模板存在且 `status='active'`（404 `TEMPLATE_NOT_FOUND` / 409 `TEMPLATE_DISABLED`）
5. 基线快照存在、属本项目、`status='approved'`（400 `BASELINE_REVISION_REQUIRED`）
6. 文档版本存在、属本项目、`status='active'`（400 `NO_ACTIVE_DOCUMENT_VERSION` / `DOCUMENT_VERSION_NOT_ANALYZABLE`）
7. **建 `incremental_analyses` 行 → 跑第一遍 → 回填统计与状态**

第 4–6 步失败时不产生任何分析记录（AC-78 第三条）。

## 6. 验收标准

### AC-77 章节局部结论正确落库（核心 AC-①）

- **Given** 项目有 `status='approved'` 的基线快照（含功能 F），文档有 `status='active'` 的版本（含章节 C），
  且 MockProvider 被编程为返回固定 JSON（结论指向 F、`label_type='changed'`）
- **When** 项目管理员 `POST /analyses`（带该快照 id + 该版本 id + `incremental` 模板）
- **Then** `incremental_analyses` 新增一行，`status='succeeded'`、`started_at` / `finished_at` 均有值
- **Then** `incremental_conclusions` 新增一行：`chapter_id=C`、`chapter_title=C.title`、`target_type='function'`、
  `target_id=F`、`label_type='changed'`、`analysis_id` 指向新记录
- **Then** `analyses.stats.conclusion_count` 等于结论条数，`stats.chapter_count` 等于本次遍历的章节数

### AC-78 Prompt 从数据库读取并传给 Mock（核心 AC-②）

- **Given** `prompt_templates` 里 `task_type='incremental'` 的模板，`system_prompt` 与 `user_prompt`
  是**可识别的固定字符串**（种子模板即满足）
- **When** 发起分析
- **Then** MockProvider **收到的 `system` 与模板的 `system_prompt` 完全相等**
- **Then** MockProvider **收到的 `user` 以模板的 `user_prompt` 开头**，且包含该章节的标题与正文
- **Then** 模板被删除 → 404 `TEMPLATE_NOT_FOUND`；模板 `status='disabled'` → 409 `TEMPLATE_DISABLED`；
  两种情况**都不产生分析记录**（`incremental_analyses` 行数为 0 增量）

> 可测性依赖「Mock 能拿到收到的请求」：`MockProvider` 保存 `calls: list[LLMRequest]`，
> `LLMResponse.raw` 同时回带该次 `LLMRequest`。用例断言 `calls`，不靠日志、不靠打补丁。

### AC-79 越界目标被丢弃并留痕

- **Given** Mock 返回的结论 `target_id` 指向一个**不在该基线快照内**的功能（例如属其他项目、或已删除）
- **When** 发起分析
- **Then** `incremental_conclusions` **不新增**该条
- **Then** `analyses.stats.discarded` 含一条明细，`code='INCREMENTAL_TARGET_OUT_OF_BASELINE'`，
  带 `chapter_id` / `target_type` / `target_id`
- **Then** `analyses.stats.discarded_count` 与 `discarded` 长度一致
- **Then** 分析整体仍 `status='succeeded'`（丢弃单条结论不使整次分析失败）

### AC-80 第一遍不得产出「新增」

- **Given** Mock 返回 `label_type='new'`
- **When** 发起分析
- **Then** 该条结论**不入库**（`label_type` 的 CheckConstraint 也只允许三值，双保险）
- **Then** `stats.dropped_new_count` 加 1，`discarded` 明细 `code='INCREMENTAL_LABEL_NEW_DROPPED'`
- **Then** 结论列表接口不返回任何 `label_type='new'` 的行

### AC-81 分析记录状态与失败留痕

- 发起前校验失败（模板 / 快照 / 文档版本任一不满足）→ 对应错误码，**不建分析记录**
- 分析正常跑完 → `status='succeeded'`
- 模型调用抛错或返回非 JSON → `status='failed'`，`error_code` / `error_message` 有值，
  `finished_at` 有值；已落库结论保留
- `GET /analyses` 支持 `status` 筛选，命中数与库内一致

### AC-82 权限矩阵

- 读接口：guest / member / project_admin / system_admin 均可读；非成员 → 403 `NOT_PROJECT_MEMBER`
- 发起分析：guest / member → 403 `NOT_PROJECT_ADMIN`；project_admin / system_admin 可
- 归档项目内发起分析 → 409 `PROJECT_ARCHIVED`（先于角色判定）
- 项目不存在 → 404 `PROJECT_NOT_FOUND`

### AC-83 审计

- 发起分析成功写 `incremental.analysis.create`
- 审计行含 `project_id` / `actor_id` / `target_type='incremental_analysis'` / `target_id=分析 ID`
- 校验失败的发起**不写审计**（与 04 的「失败操作不写审计」一致）
- `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补该 action

### AC-84 零真实网络请求（离线可跑）

- `LLMProvider` 只有 `MockProvider` 一个实现，代码中不存在 `httpx` / `requests` / `openai` 的调用
- 断网环境下全量 `pytest` 与 e2e 仍全绿
- `incremental_analyses.provider` 恒为 `mock`

### AC-85 快照引用自动生效（与 04 的联动，回归性质）

- 建好 `incremental_analyses` 后，若某快照被分析记录当作 `baseline_revision_id`，
  则 04 的 `DELETE /baselines/revisions/{id}` 返回 409 `SNAPSHOT_REFERENCED`，
  引用明细含 `source_type='incremental_analysis'`
- 本期不改 `app/baselines/` 代码；用例只验证「自动生效」

## 7. 错误码

| code | HTTP | 触发 |
|---|---|---|
| `INCREMENTAL_ANALYSIS_NOT_FOUND` | 404 | 分析记录不存在或不属于该项目 |
| `BASELINE_REVISION_REQUIRED` | 400 | 未传 `baseline_revision_id`，或该快照不存在 / 不属本项目 / 非 `approved` |
| `NO_ACTIVE_DOCUMENT_VERSION` | 400 | 文档无生效版本，或指定版本不属本项目 |
| `DOCUMENT_VERSION_NOT_ANALYZABLE` | 400 | 文档版本 `status` 不是 `active`（待确认 / 已作废） |
| `TEMPLATE_NOT_FOUND` | 404 | `task_type='incremental'` 的模板不存在 |
| `TEMPLATE_DISABLED` | 409 | 模板 `status='disabled'` |
| `INVALID_SPLIT_GRANULARITY` | 400 | 切分粒度不是 `chapter` |
| `LLM_CALL_FAILED` | 502 | Provider 调用抛错 |
| `LLM_OUTPUT_INVALID` | 502 | 模型输出不是合法 JSON，或缺少必需字段（`conclusions` 数组） |

**仅出现在 `stats.discarded`、不作 HTTP 响应**的两个标识：

| code | 触发 |
|---|---|
| `INCREMENTAL_TARGET_OUT_OF_BASELINE` | 结论目标不在比对基准基线内，被丢弃 |
| `INCREMENTAL_LABEL_NEW_DROPPED` | 第一遍返回 `new`，被丢弃 |

新增错误类进 `app/common/errors.py`，并同步 `__all__`。

## 8. 非功能

- 第一遍逐章节调用，每次调用**只带当前章节**的标题与正文 + 该章节召回的功能摘要；
  单次 `user` 字符数超 `INCREMENTAL_MAX_INPUT_CHARS`（模块常量，占位值）时截断章节正文并记 WARN
  （截断必须留痕，不静默）。
- 章节正文为空（`char_count=0`）的章节跳过，计入 `stats.chapter_count` 但不发调用。
- `stats` 用 JSON 列存，结论明细走 `incremental_conclusions` 表，不在 JSON 里塞结论正文。
- 列表接口统一分页信封：`page`（默认 1）/ `page_size`（默认 50，上限 200），
  返回 `{items,total,page,page_size}`，`total` 为过滤后条数。涉及 `/analyses`、`/analyses/{id}/conclusions`。
- **无新增第三方依赖**：`httpx` 已在 dev 依赖里，本期不引入；不引入 `openai`、`jsonschema`、`cryptography`。
- 阈值（召回策略、切分 token 上限、置信度门槛）本期**不实现**，全部留到第二期由基准集回填。

## 9. 依赖与影响

- **04-baseline**：`app/baselines/references.py` 的增量分析解析器本期**自动生效**（AC-85），不改 04 代码。
- **03-documents**：只读使用 `document_versions` / `document_chapters`，不改 03 代码。
- **概览**：本期不改 `get_overview` 计数。
- **审计清单**：`tests/common/test_audit_coverage.py` 增加 `incremental.analysis.create`。
- **迁移**：`0013_incremental`，`down_revision="0012"`；`downgrade` 反序删三张表。
- **验证约定**：每个任务按 `specs/验证约定.md` 第 2 节走「任务 pytest + 全量 pytest + 前台核对 + 截图」。
