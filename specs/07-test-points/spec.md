# 07 · 测试点分析 · 规格

> 对齐需求：PRD 2.4.4 测试点分析、PRD 2.5 生成模式（只做直连模式）。
> 上游依赖：04-baseline（功能基线结构 + 两级标签 + 审核快照）、05-incremental-analysis（增量结论 / 决策 / 冲突）、06-real-llm（`LLMProvider` / `parse_llm_json` / 提示词模板 / 运行留痕）。
> 本期只做**直连模式**：平台内可管理的提示词模板 + 上下文组装，直接调用大模型。

## 1. 背景与目标

主链路目前走到「增量分析」为止：文档 → 基线 → 增量结论 → 人工打标，
但**闭环没有出口**——打好的标签没有变成可执行的测试点，测试工程师还得手工重读文档写测试点。

本期目标：把「生效中的基线标签 + 增量分析结论」喂给大模型，产出**可追溯、可人工评审**的测试点：
- 输入只有一条路：**增量分析结果 + 基线**（PRD 2.4.4 的输入 ②「无基线直接对文档分析」本期不做，见 §2.2）；
- 输出落到新表，逐条带来源追溯（章节 / 功能 / 功能点 / 标签 / 增量结论）；
- 生成后进入「待评审 → 评审通过 / 驳回」流程，**只有评审通过的测试点才算数**；
- 标签被清除时，已生成测试点**不自动删改**，只挂「待复核」提示。

做完之后，08 期（测试用例分析）有了可靠的输入载体。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 建表 | 2 张新表（迁移 `0022`）：`test_point_analyses`（生成记录）+ `test_points`（测试点） |
| 生成记录 | 记录模板版本、执行状态、统计、错误码；与 05 同构（`status` / `stats` / `error_code` / `started_at` / `finished_at`） |
| 测试点字段 | 名称、所属功能/功能点、优先级、前置条件、验证要点、关联章节、来源标签与增量结论 |
| 输入口径 | **只吃「生效中」标签**（`baseline_labels.status='active'`）；已清除标签不进入 Prompt（服务端强制过滤） |
| 增量结论输入 | 只吃**未全部撤销**的增量分析记录；全部撤销的默认不可选 |
| Prompt 组装 | `app/test_points/context.py`：基线清单 + 标签依据 + 增量结论 + 章节正文；超长只截章节正文 |
| JSON 容错 | 复用 `parse_llm_json`（06 期），**不自己写解析** |
| Provider | 复用 `get_provider`（06 期）：无配置降级 Mock，有配置走真实模型 |
| 运行留痕 | `llm_run_logs` 增 `task_type='test_point'`；只记调用次数 / 耗时 / 状态 / 错误码 |
| 评审流程 | 待评审 → 评审通过 / 驳回；**评审通过**才允许下游（08 期用例生成）引用 |
| 手工增删改 | 项目管理员可手工增删改测试点（PRD 2.4.4「支持手工增删改」） |
| 冲突提示 | 同一章节已有评审通过的测试点时，再次生成前返回「将覆盖已有评审结果」的提示信息（**由前端二次确认**，服务端不静默覆盖） |
| 待复核标记 | 依赖标签被清除时，测试点标 `needs_review=true` 并在详情页给出清除时间与原因 |
| 审计 | `test_point.analysis.create` / `test_point.review` / `test_point.manual.*` |
| 前端 | 项目详情页新增「测试点」Tab：发起生成 + 列表 + 详情抽屉 + 评审操作 |
| 引用保护 | 快照被测试点引用时计入引用来源（`app/baselines/references.py` 挂解析器） |

### 2.2 本期不做（红线，违反即返工）

- **不做 Skill 模式**（PRD 2.5 的 Skill 包 / manifest / schema 校验 / 回退开关）。
  06 期已明确「不做 Skill 双轨制」，本期延续；PRD 2.5.2 的「回退直连重试」开关也一并不做。
- **不做测试用例分析**（PRD 2.4.5）、不做自动化执行（2.4.6）、不做测试报告（2.4.7）。
- **不做「无基线直接对文档分析」**（PRD 2.4.4 输入 ②）：本期输入**必须**含增量结论或生效标签，
  两者都没有 → 400 拒绝发起。没有输入就没有依据，生成出来的测试点无法追溯。
- **不做流程基线**（PRD 2.4.2 的场景/步骤/预期结果子菜单）。
- **不做测试点版本历史 / 快照**：测试点是可增删改的活文档，不是冻结快照。
- **不做工作台待办接入**（PRD 2.3.1 的「待评审的测试点」计数）：等 08 期用例评审一起做，
  届时「待评审」的口径要统一（测试点 + 用例）。
- **不改 04 / 05 的判定逻辑**：只在 04 的 `references.py` 挂一个引用解析器（04 已预留该接口），
  在 05 的 `llm_run_logs.task_type` 的 CHECK 约束里加一个枚举值（迁移层，不动 05 代码）。
- **不做 Token 计费 / 配额**。

### 2.3 与上游的兼容约束

1. **「生效中标签」口径必须与 04 一致**：一律 `baseline_labels.status='active'`。
   04 的 `_label_type_map()` 已封装该口径，07 直接复用，不另写一套。
2. **「已批准」结构口径必须与 04 一致**：用 `app/baselines/approval.py` 的 `approved_entities()`，
   不自己写「哪些节点算生效」的判断。
3. **标签清除后不自动改测试点**（PRD 2.4.4 明写）：测试点行一个字节都不动，
   只置 `needs_review=true` + 记 `needs_review_reason` / `needs_review_at`。
4. **增量结论已全部撤销的记录默认不可选**（PRD 2.4.4）：
   「全部撤销」= 该次分析产出的标签**全部**处于 `cleared` 状态。
   本期**只做服务端强制过滤**（发起时直接拒），不做「手动勾选并二次提示」的开关。
5. **不生成真实 socket**：任何测试都不允许产生真实网络请求，一律 `httpx.MockTransport` 或 Mock Provider。

## 3. 角色与权限

| 操作 | guest | member | project_admin | system_admin |
|---|---|---|---|---|
| 测试点列表 / 详情 | 可 | 可 | 可 | 可（兜底） |
| 发起生成 | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |
| 评审（通过 / 驳回） | 403 | 403 | 可 | 可 |
| 手工增删改 | 403 | 403 | 可 | 可 |
| 删除生成记录 | 403 | 403 | 可 | 可 |

- 非项目成员访问读接口 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404 `PROJECT_NOT_FOUND`。
- 归档项目内读接口正常，写接口 → 409 `PROJECT_ARCHIVED`（**先判归档，再判角色**，与 04 / 05 一致）。
- 评审**不设「提交者不能自审」**：测试点生成与评审是两个角色（分析师 vs 评审人），
  但单人管理员是常态（04 已用 `allow_baseline_self_approval` 开关解决同类问题）。
  本期**不引入新开关**，直接允许自审，审计 `after_data.self_approved=true` 留痕。

## 4. 数据模型（2 张新表，迁移 `0022`）

### 4.1 `test_point_analyses`（生成记录）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| template_id | BIGINT | FK → prompt_templates.id，索引 |
| template_version | INT | 非空，模板版本快照 |
| provider | VARCHAR(32) | 非空，默认 `mock` |
| document_id | BIGINT | FK → documents.id，索引，可空（按文档生成时非空） |
| document_version_id | BIGINT | FK → document_versions.id，索引，可空 |
| analysis_id | BIGINT | FK → incremental_analyses.id，索引，可空（无增量结论时为空） |
| baseline_revision_id | BIGINT | FK → baseline_revisions.id，索引，可空 |
| status | VARCHAR(16) | 非空，默认 `pending`，取值 `pending` / `running` / `succeeded` / `failed` |
| error_code | VARCHAR(64) | 可空 |
| error_message | VARCHAR(500) | 可空 |
| stats | JSON | 可空 |
| started_at / finished_at | DATETIME(3) | 可空 |
| created_by | BIGINT | FK → users.id，非空 |
| created_at | DATETIME(3) | 非空 |

索引：`idx_tpanalyses_project` / `_template` / `_analysis` / `_revision`。
CheckConstraint：`ck_tpanalyses_status`。

### 4.2 `test_points`（测试点）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| analysis_id | BIGINT | FK → test_point_analyses.id，索引；**手工新增的测试点为 NULL** |
| name | VARCHAR(255) | 非空 |
| target_type | VARCHAR(16) | 非空，`function` / `feature_point`（**可空？否——必须有归属对象**） |
| target_id | BIGINT | 非空，多态不建 FK |
| target_name | VARCHAR(255) | 非空，落库快照（目标改名不影响历史） |
| priority | VARCHAR(16) | 非空，默认 `medium`，取值 `high` / `medium` / `low` |
| precondition | VARCHAR(1000) | 可空 |
| verification | VARCHAR(2000) | 可空 |
| chapter_id | BIGINT | FK → document_chapters.id，可空（手工新增时为空） |
| chapter_title | VARCHAR(255) | 可空，章节标题快照 |
| source_label_id | BIGINT | FK → baseline_labels.id，可空（来源标签） |
| source_conclusion_id | BIGINT | FK → incremental_conclusions.id，可空（来源增量结论） |
| status | VARCHAR(16) | 非空，默认 `pending`，取值 `pending` / `approved` / `rejected` |
| reviewed_by | BIGINT | FK → users.id，可空 |
| reviewed_at | DATETIME(3) | 可空 |
| review_comment | VARCHAR(500) | 可空 |
| needs_review | TINYINT(1) | 非空，默认 0 —— 依赖标签被清除 |
| needs_review_reason | VARCHAR(255) | 可空 |
| needs_review_at | DATETIME(3) | 可空 |
| source_type | VARCHAR(16) | 非空，默认 `llm`，取值 `llm` / `manual` |
| created_by | BIGINT | FK → users.id，非空 |
| created_at / updated_at | DATETIME(3) | 非空 |

索引：`idx_tpoints_project` / `_analysis` / `_target(target_type,target_id)` / `_status(project_id,status)`。
CheckConstraint：`ck_tpoints_target_type` / `ck_tpoints_priority` / `ck_tpoints_status` / `ck_tpoints_source_type`。

> **不建唯一键**：测试点允许同名（不同章节 / 不同功能的同名测试点是合法的），
> 只靠 `idx_tpoints_target` 做检索。

### 4.3 `llm_run_logs` 的 CHECK 扩展

`llm_run_logs.task_type` 的 CheckConstraint 现为 `('incremental_first','incremental_second','provider_test')`，
迁移 `0022` 增加 `'test_point'`。
**MySQL 不允许直接改 CHECK 约束**，需 `DROP CHECK` → `ADD CONSTRAINT`（见 plan §2.3）。

### 4.4 播种：测试点提示词模板

迁移 `0022` 播种 1 条 `task_type='test_point'` 的模板（`prompt_templates` 的 `task_type` 枚举
`0013` 已预留该值，**不需要改枚举**）：

- `name` = `测试点生成·基于标签与增量结论`
- `system_prompt` 以 `[TEST_POINT_SYSTEM]` 开头（对齐 `MockProvider` 的前缀机制）
- `user_prompt` 以 `[TEST_POINT_USER]` 开头

## 5. Prompt 与上下文组装

### 5.1 上下文来源与顺序

`build_user_prompt()` 的段落顺序固定（**Prompt 必须可复现**）：

1. `template.user_prompt`（模板正文，原样取库）
2. `## 可对照的基线目标` —— 生效标签命中的功能 / 功能点清单
   （格式 `- 功能#10096 用户扫码登录`，按 `(target_type, target_id)` 排序）
3. `## 标签依据` —— 生效标签明细（`标签类型` / `目标` / `确认人` / `确认时间`）
4. `## 增量结论` —— 所选增量分析记录的结论明细（章节 / 目标 / 判定 / 理由）
5. `## 章节：{title}` + 章节正文

**没有第 2 段就等于「模型不知道能写什么」**——这是 06 期 L2 联调踩过的坑
（模型拿不到 `target_id`，只能瞎猜，结论全被丢弃）。07 必须在 Prompt 里给全清单。

### 5.2 截断规则

- 总预算 `get_settings().incremental_max_input_chars`（与 05 共用同一配置项）。
- **只截章节正文**，前缀（1–4 段）保持不变。
- 清单截断时追加「其余 N 项已省略」提示（照抄 `render_baseline_brief()` 的做法）。
- 截断比例上限 40%（`BASELINE_BRIEF_MAX_RATIO`），其余留给章节正文。

### 5.3 模型输出契约

模型必须返回 JSON：

```json
{
  "test_points": [
    {
      "name": "扫码登录连续失败 5 次后锁定",
      "target_type": "function",
      "target_id": 10096,
      "priority": "high",
      "precondition": "账号已存在且未锁定",
      "verification": "连续输错密码 5 次，提示锁定且扫码登录同样受阻"
    }
  ]
}
```

**服务端校验**（全部 400 / 丢弃，不猜、不修）：
- `test_points` 必须是数组。
- 每条必须有非空 `name`；缺 `name` → 整条丢弃，记入 `stats.discarded`（错误码 `TEST_POINT_INVALID`）。
- `target_type` 必须在 `('function','feature_point')` 内；不在 → 整条丢弃。
- `target_id` 必须在**本次输入的清单**内；不在 → 整条丢弃（错误码 `TEST_POINT_TARGET_OUT_OF_BASELINE`）。
  **口径与 05 的越界丢弃一致**：模型猜出来的目标一律丢，不静默写入脏数据。
- `priority` 不在 `('high','medium','low')` 内 → **归一到 `medium`**，不丢弃
  （优先级是展示属性，丢弃整条测试点代价太大）。
- `precondition` / `verification` 缺失 → 存空串，**不丢**。

> **为什么 `target_id` 越界要丢**：真实模型会照抄模板示例里的 id。
> 06 期 L2 联调实测——模板示例写死 `"target_id": 1`，模型照抄，
> 真实 id 是 10096/10097，抄来的 `1` 全部被丢弃。
> **模板示例里的 id 必须写成「看起来像占位符」的值**（如 `123`）。

## 6. 接口

路由前缀：`/api/projects/{project_id}/test-points`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/analyses` | 成员 | 生成记录列表（分页） |
| POST | `/analyses` | 项目管理员 | 发起生成（**同步执行**，返回生成记录 + 测试点） |
| GET | `/analyses/{id}` | 成员 | 生成记录详情（含统计） |
| GET | `/analyses/{id}/points` | 成员 | 该次生成的测试点列表 |
| DELETE | `/analyses/{id}` | 项目管理员 | 删除生成记录（**连带删除它产出的测试点**，需无已评审通过的） |
| GET | `/points` | 成员 | 测试点列表（按项目 / 状态 / 目标 / 章节筛选） |
| GET | `/points/{id}` | 成员 | 测试点详情 |
| PATCH | `/points/{id}` | 项目管理员 | 手工改测试点（仅名称 / 前置条件 / 验证要点 / 优先级） |
| DELETE | `/points/{id}` | 项目管理员 | 删测试点 |
| POST | `/points/{id}/review` | 项目管理员 | 评审：通过 / 驳回 |

### 6.1 发起生成的请求体

```json
{
  "template_id": 3,
  "document_id": 12,
  "document_version_id": 15,
  "analysis_id": 7,
  "baseline_revision_id": 4,
  "chapter_ids": [101, 102]
}
```

- `template_id` 必填 → 必须 `task_type='test_point'` 且 `status='active'`。
- `analysis_id` 与 `baseline_revision_id` **至少给一个**；两个都给则交集使用。
- `chapter_ids` 可空 → 空表示**全文档**；给了则只对这些章节生成。
- `document_version_id` 可空 → 空表示不限定文档，按基线 / 增量结论的章节推导。

### 6.2 校验顺序（固定，与 05 一致）

```
项目 404 → 归档 409 → 角色 403 → 模板 400 → 增量记录 404/409 →
快照 404/400 → 章节 400 → 输入为空 400 → 跑模型
```

**任何一步失败都不产生生成记录**（与 05 的「失败留痕」不同：
05 是在创建行之后失败才留痕，07 在校验阶段失败就不建行）。

### 6.3 错误码（新增）

| 类名 | code | HTTP | 场景 |
|---|---|---|---|
| `TestPointAnalysisNotFound` | `TEST_POINT_ANALYSIS_NOT_FOUND` | 404 | 生成记录不存在 |
| `TestPointNotFound` | `TEST_POINT_NOT_FOUND` | 404 | 测试点不存在 |
| `TestPointTemplateInvalid` | `TEST_POINT_TEMPLATE_INVALID` | 400 | 模板不存在 / 类型不对 / 已停用 |
| `TestPointInputEmpty` | `TEST_POINT_INPUT_EMPTY` | 400 | 增量结论与生效标签都没有 |
| `TestPointTargetNotFound` | `TEST_POINT_TARGET_NOT_FOUND` | 400 | 章节 / 目标不存在或不属于本项目 |
| `TestPointReviewStateInvalid` | `TEST_POINT_REVIEW_STATE_INVALID` | 409 | 已评审过的测试点重复评审 |
| `TestPointAnalysisHasApproved` | `TEST_POINT_ANALYSIS_HAS_APPROVED` | 409 | 删除生成记录但已有评审通过的测试点 |
| `TestPointInvalid` | `TEST_POINT_INVALID` | 400 | 模型输出结构不合法（整次失败） |
| `TestPointTargetOutOfBaseline` | `TEST_POINT_TARGET_OUT_OF_BASELINE` | — | **丢弃码**，不是 HTTP 错误 |

全部加进 `app/common/errors.py` 的 `__all__`。

### 6.4 审计

| 场景 | action |
|---|---|
| 发起生成 | `test_point.analysis.create` |
| 评审通过 / 驳回 | `test_point.review` |
| 手工增 / 改 / 删 | `test_point.point.create` / `test_point.point.update` / `test_point.point.delete` |

审计条目含 `project_id` / `actor_id` / `target_type` / `target_id`；
**失败操作不写审计**。

## 7. 前端

- 项目详情页新增「测试点」Tab（插在「增量分析」之后）。
- Tab 内容：
  - 上半区：**生成记录表**（模板、状态、结论数、耗时、发起时间）+「发起生成」按钮。
  - 下半区：**测试点表**（名称、目标、优先级、章节、状态、来源、待复核标记）+ 行操作（详情 / 评审 / 编辑 / 删除）。
- 发起生成弹窗：模板下拉（动态拉 `GET /api/prompt-templates?task_type=test_point`）、
  增量分析记录下拉、基线快照下拉、章节多选。
- 详情抽屉：测试点全文 + 来源追溯（目标 / 章节 / 标签 / 增量结论）+ 评审操作。
- **冲突二次确认**：所选章节已有评审通过的测试点 → 弹窗提示「将覆盖已有评审结果」，
  用户确认后才发起（**服务端不静默覆盖**）。
- **待复核提示**：详情页展示「所依赖基线标签已于 {时间} 被清除（原因：XX），请复核」。
- 错误码映射加进 `web/src/api/client.ts`。

## 8. 验收标准

### AC-141 生成记录与测试点落库
- **Given** 项目有生效标签 + 已成功的增量分析 + `test_point` 模板，Mock 返回固定 JSON（含 2 条测试点）
- **When** 发起生成
- **Then** `test_point_analyses` 新增一行 `status='succeeded'`
- **Then** `test_points` 新增 2 行，均带 `target_type` / `target_id` / `target_name` / `chapter_id` / `source_label_id` / `source_conclusion_id`
- **Then** 响应直接带回生成的测试点（前端不用再发一次 GET）

### AC-142 只引用生效标签
- **Given** 项目有一个 `status='active'` 标签和一个 `status='cleared'` 标签
- **When** 发起生成
- **Then** Prompt 里**只出现** active 标签对应的目标，cleared 标签的目标**完全不出现**
- **Then** 服务端强制过滤（不依赖前端）

### AC-143 增量结论已全部撤销 → 拒绝发起
- **Given** 所选增量分析记录产出的标签**全部**处于 `cleared`
- **When** 发起生成
- **Then** 400 `TEST_POINT_INPUT_EMPTY`（或明确指向该记录的错误码）
- **Then** **不产生**生成记录

### AC-144 目标越界 → 丢弃不落库
- **Given** Mock 返回的 `target_id` 不在本次输入清单内
- **When** 发起生成
- **Then** 该条**不落库**
- **Then** `stats.discarded` 记一条 `TEST_POINT_TARGET_OUT_OF_BASELINE`
- **Then** `stats.test_point_count` 只算落库的条数

### AC-145 模型输出坏 JSON → 整次失败
- **Given** Mock 返回非法 JSON
- **When** 发起生成
- **Then** 生成记录 `status='failed'`，`error_code='TEST_POINT_INVALID'`
- **Then** **不产生**任何测试点行

### AC-146 JSON 容错复用 parse_llm_json
- **Given** Mock 返回带 Markdown 围栏的 JSON
- **When** 发起生成
- **Then** 测试点**照常落库**（证明走的是 `parse_llm_json` 而不是裸 `json.loads`）

### AC-147 评审流程
- **Given** 生成的测试点 `status='pending'`
- **When** 评审通过
- **Then** `status='approved'`，记 `reviewed_by` / `reviewed_at`
- **When** 再评审一次
- **Then** 409 `TEST_POINT_REVIEW_STATE_INVALID`
- **Then** 评审写审计 `test_point.review`

### AC-148 手工增删改
- **Given** 项目管理员
- **When** 手工新增一条测试点（指定目标）
- **Then** `source_type='manual'`、`analysis_id` 为 NULL
- **When** 改名称 / 前置条件 / 验证要点 / 优先级
- **Then** 只这 4 个字段可改；传别的字段 → 400
- **When** 删除
- **Then** 行被物理删除（测试点是活文档，不是留痕记录）

### AC-149 标签清除后不自动改测试点
- **Given** 测试点引用了某个标签，该标签被清除
- **When** 查询测试点
- **Then** 测试点行**内容完全不变**（不删、不改字段值）
- **Then** `needs_review=true`，`needs_review_reason` 含清除原因
- **Then** 已评审通过（`status='approved'`）的测试点**仍保持 approved**（不被自动降级）

### AC-150 标签清除触发待复核标记
- **Given** 测试点引用了标签 L
- **When** L 被清除
- **Then** 引用 L 的所有测试点 `needs_review=true`
- **Then** 手工新增的测试点（不引用标签）不受影响

### AC-151 快照引用保护
- **Given** 快照被某次测试点生成记录引用
- **When** 查询快照引用来源
- **Then** 引用列表里出现 `source_type='test_point_analysis'` 条目
- **Then** 被引用的快照禁止删除（409 `SNAPSHOT_REFERENCED`）

### AC-152 权限矩阵
- **Given** member / guest 身份的成员
- **When** 读接口
- **Then** 200
- **When** 发起生成 / 评审 / 手工改
- **Then** 403 `NOT_PROJECT_ADMIN`
- **Given** 非项目成员
- **When** 读接口
- **Then** 403 `NOT_PROJECT_MEMBER`

### AC-153 归档项目写接口
- **Given** 项目已归档
- **When** 发起生成
- **Then** 409 `PROJECT_ARCHIVED`
- **When** 读接口
- **Then** 200

### AC-154 运行留痕
- **Given** 发起一次生成
- **When** 跑完
- **Then** `llm_run_logs` 新增一条 `task_type='test_point'`，含 `call_count` / `latency_ms` / `status`
- **Then** 失败时 `status='failed'` + `error_code`
- **Then** 表中**不出现** Prompt 正文与 API Key

### AC-155 无真实网络
- **Given** 测试套件
- **When** 跑全量
- **Then** **零真实 socket**：真实 Provider 的测试一律 `httpx.MockTransport`；测试目录里不出现 `requests` / `urlopen` / `aiohttp` / `socket.socket`

### AC-156 提示词模板来自数据库
- **Given** `task_type='test_point'` 的模板正文是可识别的固定字符串
- **When** 发起生成
- **Then** Mock 收到的 `system` 等于该模板的 `system_prompt`
- **Then** Mock 收到的 `user` 以该模板的 `user_prompt` 开头，且包含章节标题与正文
- **Then** 模板被停用 → 400 `TEST_POINT_TEMPLATE_INVALID`，**不产生生成记录**

### AC-157 前端可用
- 项目详情页「测试点」Tab 可见
- 发起生成 → 测试点出现在列表 → 评审通过 → 状态变「已通过」
- 手动新增测试点 → 列表出现 → 编辑 → 删除
- 截图 `.screenshots/T104/`

### AC-158 05 / 04 零回归
- **Given** 04 / 05 的既有行为
- **When** 跑全量 pytest
- **Then** 既有 864 条**一条不删、不改期望值**
- **Then** 04 的快照引用检查**只多一类来源**，既有引用条目的数量与内容不变

## 9. 非功能

- **零真实网络请求**（测试与开发环境均如此）。
- **同步执行**：与 05 第一遍一致，逐章同步调用模型。测试点生成不引入异步队列。
- **Prompt 可复现**：清单排序固定，模板正文从库里取，不做随机。
- **大模型不可用时降级 Mock**：与 06 期一致，`llm_providers` 空表 → Mock → 生成记录 `succeeded`、
  测试点数为 0（Mock 默认返回空数组）。**平台不因没配模型而挂**。
- **API Key 不明文**：沿用 06 期口径，任何响应 / 审计 / 日志 / 异常都不带 Key。

## 10. 依赖与影响

| 依赖 | 状态 |
|---|---|
| 04-baseline 结构与标签 | ✅ 已上线 |
| 04 `approved_entities()` | ✅ 已上线（`app/baselines/approval.py`） |
| 05 增量结论 / 决策 | ✅ 已上线 |
| 06 `LLMProvider` / `get_provider` / `parse_llm_json` | ✅ 已上线 |
| 06 `prompt_templates.task_type='test_point'` | ✅ 枚举已预留（`0013`），**本期播种模板** |
| 06 `llm_run_logs` | ✅ 已上线，本期扩 `task_type` 枚举 |

**对既有模块的影响**：

| 模块 | 影响 |
|---|---|
| `app/baselines/references.py` | **加一个引用解析器**（`register_resolver`），既有解析器不动 |
| `app/models/__init__.py` | 加 2 个模型的 import 与 `__all__` |
| `app/common/errors.py` | 加 9 个错误类 + `__all__` |
| `app/main.py` | 注册 1 个路由 |
| `app/llm/mock.py` | **加一个前缀分支**（`[TEST_POINT_SYSTEM]`）——为让 Mock 开箱可用 |
| `app/llm/run_log.py` | **不改**（`task_type` 是自由字符串，由 DB 的 CHECK 约束把关） |
| `app/incremental/` | **零改动** |
| `app/baselines/service.py` | **零改动** |
| `app/llm/` | 只改 `mock.py` 一处 |

## 11. 后续期（明确不在本期）

| 期 | 内容 |
|---|---|
| 08 | 测试用例分析（PRD 2.4.5）：消费**已评审**测试点生成用例 |
| — | Skill 模式（PRD 2.5）：Skill 包 / manifest / schema 校验 / 回退开关 |
| — | 测试点版本历史、测试点导入导出（Excel） |
| — | 「无基线直接对文档分析」模式 |
| — | 工作台待办接入（待评审的测试点 / 用例） |
| — | 流程基线（场景 / 步骤 / 预期结果） |
