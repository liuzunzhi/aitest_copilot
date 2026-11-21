# 08 · 测试用例分析 · 规格

> 对齐需求：PRD 2.4.5 测试用例分析、PRD 2.5 生成模式（只做直连模式）。
> 上游依赖：07-test-points（`test_points` / `test_point_analyses` / 评审口径）、
> 06-real-llm（`get_provider` / `parse_llm_json` / `record_run` / 提示词模板）、
> 04-baseline（标签 / 章节追溯）、05-incremental-analysis（增量结论追溯）。
> 本期只做**直连模式**：平台内可管理的提示词模板 + 上下文组装，直接调用大模型。

## 1. 背景与目标

07 期把主链路推到「评审通过的测试点」，但**测试点还不是可执行资产**：
测试工程师拿到测试点后仍要手工写步骤与预期结果，08 期的存在意义就是补上这一段。

本期目标：**只消费 `status='approved'` 的测试点**，生成可评审、可追溯、可手工编辑的测试用例：

- 一条测试点**可拆多条用例**（正向 / 反向 / 边界），用例与测试点是 1:N；
- 步骤与预期结果**分步建模**（子表），支持单步增删改与排序，供后续 2.4.6 自动化执行复用；
- 生成后进入「待评审 → 评审通过 / 驳回」，**只有评审通过的用例才算数**；
- 源测试点被修改 / 删除时，已生成用例**不自动改内容**，由读取时派生的「待复核」提示；
- 支持导出 Excel（PRD 2.4.5），导入列入 Backlog。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 建表 | 3 张新表（迁移 `0023`）：`test_case_analyses`（生成记录）+ `test_cases`（用例）+ `test_case_steps`（步骤） |
| 输入口径 | **只吃 `test_points.status='approved'`**；pending / rejected 一律不进 Prompt（服务端强制过滤） |
| 生成范围 | 按项目全量 approved 测试点；可选 `test_point_ids` / `chapter_ids` / `target_type + target_id` 收窄 |
| 生成记录 | 模板版本、执行状态、统计、错误码；与 05 / 07 同构 |
| Prompt 组装 | `app/test_cases/context.py`：模板正文 + 测试点明细 + 来源章节正文；超长只截章节正文 |
| JSON 容错 | 复用 `parse_llm_json`（06 期），**不自己写解析** |
| Provider | 复用 `get_provider`：无配置降级 Mock，有配置走真实模型 |
| 运行留痕 | `llm_run_logs.task_type` 扩 `'test_case'`；只记调用次数 / 耗时 / 状态 / 错误码 |
| 评审流程 | 待评审 → 通过 / 驳回；评审通过才允许下游（2.4.6）引用 |
| 手工增删改 | 项目管理员可手工新增 / 编辑 / 删除用例，可整体覆盖步骤 |
| 待复核 | 源测试点被改 / 删后**读时派生** `needs_review`（不落库、不改 07 代码），可「确认已复核」清标记 |
| 导出 Excel | `GET /cases/export` 返回 `.xlsx`（一步一行）；导入不做（见 §2.2） |
| 审计 | `test_case.analysis.create` / `.delete` / `test_case.review` / `test_case.case.*` / `test_case.steps.update` |
| 前端 | 项目详情页新增第 9 个 Tab「测试用例」 |

### 2.2 本期不做（红线，违反即返工）

- **不做 Skill 模式**（PRD 2.5）：延续 06 / 07，只做直连模式；不做 Skill 包 / manifest / 回退开关。
- **不做自动化执行（2.4.6）与测试报告（2.4.7）**：不建「用例 ↔ 自动化资产」关联字段，
  不做脚本生成、资产扫描、执行结果回写。
- **不做 Excel 导入**：PRD 2.4.5 的「批量导入导出」本期只做**导出**，导入登记 Backlog
  （导入需要列契约、行级错误报告与全量回滚语义，与本期闭环无耦合）。
- **不做工作台待办 / 看板计数**（PRD 2.3.1 的「待评审的用例」）：与 07 的「待评审测试点」
  一并延后，统一「测试点 + 用例」口径后再接。
- **不改 04 / 05 / 07 的判定逻辑与错误码**：
  - 07 的 `approved` 口径只读复用（`test_points.status='approved'`），不新增「已评审」判定；
  - `test_cases.test_point_id` **不建外键**，因此 07 的删测试点 / 删生成记录**行为完全不变**；
  - 待复核靠**读取时派生**，不往 07 的写路径里加钩子。
- **不做用例版本历史 / 快照**：用例是可增删改的活文档（与 07 的测试点同一定位）。
- **不做用例编号流水（TC-001）**：本期用自增 id + 名称，编号规则等执行模块（2.4.6）再定。
- **不做 Token 计费 / 配额**。

### 2.3 与上游的兼容约束

1. **「已评审」口径只有一个出处**：`test_points.status == 'approved'`。
   不新增「是否允许被引用」的开关，也不复制 07 的评审状态机。
2. **测试点被删后用例不消失**：`test_point_id` 是**无外键的逻辑引用**，
   与 07 的 `target_id` 多态引用同一思路——删测试点/删生成记录后，
   用例仍保留快照名称，读取时标「源测试点已删除」。
3. **源测试点变更的判定基准是「内容指纹」，不是 `updated_at`**：
   实测 `test_points.updated_at` 在迁移里只有 `server_default`（`0022` 第 196 行），
   SQLAlchemy 的 `server_onupdate` 在 MySQL 方言下**不会生成 `ON UPDATE`**（编译 DDL 验证过），
   应用代码也从不赋值 → 该列插入后基本不变，**不能拿来判断"点被改过"**。
   08 改为存一列 SHA-256 指纹（覆盖名称 / 目标 / 优先级 / 前置条件 / 验证要点 /
   章节 / `needs_review` 标志），读取时重算比对。这既不改 07 的表，也不需要写钩子。
4. **零真实 socket**：任何测试都不允许产生真实网络请求，一律 `httpx.MockTransport` 或 Mock Provider。
5. **章节正文是可选上下文**：测试点没有关联章节或章节为空时，Prompt 省略该段，**不跳过该测试点**
   （与 07 跳过空章节不同——08 的锚点是测试点，不是章节）。

## 3. 角色与权限

角色沿用 `project_members.role` 的三档（guest / member / project_admin）+ 系统管理员兜底：

| 操作 | 访客 guest | 成员 member | 项目管理员 | 系统管理员 |
|---|---|---|---|---|
| 用例列表 / 详情 / 步骤 / 导出 | 可 | 可 | 可 | 可（兜底） |
| 生成记录列表 / 详情 | 可 | 可 | 可 | 可 |
| 发起生成 | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |
| 评审（通过 / 驳回） | 403 | 403 | 可 | 可 |
| 手工增删改 / 步骤覆盖 / 确认复核 | 403 | 403 | 可 | 可 |
| 删除生成记录 | 403 | 403 | 可 | 可 |

- 非项目成员（不在 `project_members` 里）访问读接口 → 403 `NOT_PROJECT_MEMBER`；
  项目不存在 → 404 `PROJECT_NOT_FOUND`。
- 归档项目内读接口正常，写接口 → 409 `PROJECT_ARCHIVED`（**先判归档，再判角色**）。
- **复用 `app/common/permissions.py` 的既有 5 个函数**，不新写权限判定：
  - 读：`ensure_readable(session, project_id=..., actor=...)`
  - 写：`ensure_writable_project(...)` → `ensure_admin(..., action="发起测试用例生成")`
- 评审**不设「提交者不能自审」**（与 07 一致）：单人管理员是常态；
  审计 `after_data.self_approved=true` 留痕。

## 4. 数据模型（3 张新表，迁移 `0023`）

列类型与 07 的 `app/models/test_point.py` 保持同一写法：
`BIGINT(unsigned=True)` / `DATETIME(fsp=3)` / `JSON` / `String(n)`，
时间列 `server_default=text("CURRENT_TIMESTAMP(3)")`。

> `server_onupdate` 在 MySQL 方言下**不会生成 `ON UPDATE`**（实测 07 的 `updated_at` 就停在插入时间），
> 因此 08 的 `test_cases.updated_at` **由服务层在写操作里显式赋值**，
> 不依赖数据库自动推进；也不要把它当「变更检测」的依据。

> **三个模型类都必须写 `__test__ = False`**：`TestCase*` 以 `Test` 开头，
> pytest 会把它们当测试类收集（07 的 `TestPoint` 已踩过这个坑，
> `app/models/test_point.py` 第 48 / 115 行有先例）。
> 错误类不用管——`ApiError` 基类已设 `__test__ = False`，子类自动免疫。

### 4.1 `test_case_analyses`（生成记录）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| template_id | BIGINT | FK → prompt_templates.id，索引 |
| template_version | INT | 非空，模板版本快照 |
| provider | VARCHAR(64) | 非空，默认 `mock` |
| test_point_analysis_id | BIGINT | **无外键**（逻辑引用），索引，可空；07 删生成记录时不会被外键挡住 |
| chapter_ids | JSON | 可空，本次筛选的章节范围快照 |
| status | VARCHAR(16) | 非空，默认 `pending`，取值 `pending` / `running` / `succeeded` / `failed` |
| error_code | VARCHAR(64) | 可空 |
| error_message | VARCHAR(500) | 可空 |
| stats | JSON | 可空 |
| started_at / finished_at | DATETIME(3) | 可空 |
| created_by | BIGINT | FK → users.id，非空 |
| created_at | DATETIME(3) | 非空 |

索引：`idx_tcanalyses_project` / `_template` / `_point_analysis`。
CheckConstraint：`ck_tcanalyses_status`。

### 4.2 `test_cases`（用例）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| analysis_id | BIGINT | FK → test_case_analyses.id，索引；**手工新增为 NULL** |
| test_point_id | BIGINT | **无外键**（逻辑引用），索引；手工新增也必填 |
| test_point_name | VARCHAR(255) | 非空，测试点名称快照 |
| title | VARCHAR(255) | 非空，用例名称 |
| case_type | VARCHAR(16) | 非空，默认 `functional`，取值 `functional` / `api` / `ui` |
| priority | VARCHAR(16) | 非空，默认 `medium`，取值 `high` / `medium` / `low` |
| precondition | VARCHAR(1000) | 可空 |
| target_type | VARCHAR(16) | 非空，`function` / `feature_point`（由测试点快照） |
| target_id | BIGINT | 非空，多态不建 FK（由测试点快照） |
| target_name | VARCHAR(255) | 非空，目标名称快照 |
| chapter_id | BIGINT | 可空，来源章节（由测试点快照） |
| chapter_title | VARCHAR(255) | 可空，章节标题快照 |
| status | VARCHAR(16) | 非空，默认 `pending`，取值 `pending` / `approved` / `rejected` |
| reviewed_by | BIGINT | FK → users.id，可空 |
| reviewed_at | DATETIME(3) | 可空 |
| review_comment | VARCHAR(500) | 可空 |
| source_type | VARCHAR(16) | 非空，默认 `llm`，取值 `llm` / `manual` |
| source_point_fingerprint | CHAR(64) | 可空 —— 生成/复核时对源测试点内容算的 SHA-256；NULL 表示「已确认源已删除」 |
| needs_review_ack_at | DATETIME(3) | 可空 —— 人工「确认已复核」时间 |
| created_by | BIGINT | FK → users.id，非空 |
| created_at / updated_at | DATETIME(3) | 非空 |

索引：`idx_tcases_project` / `_analysis` / `_test_point` / `_target(target_type,target_id)` /
`_status(project_id,status)`。
CheckConstraint：`ck_tcases_case_type` / `ck_tcases_priority` / `ck_tcases_status` / `ck_tcases_source_type`。

> **`test_point_id` 为什么不建外键**：07 的 `delete_point` 是**物理删除**（不判状态），
> 建外键会让 07 的既有行为变成 500（IntegrityError），等于逼我们改 07 的错误码（红线）。
> 逻辑引用 + 快照名称 + 读时派生，既保住 07 的行为，又保住了追溯。
> （07 的 `delete_analysis` 本身已有「存在 approved 测试点 → 409」的保护，
> 因此批次删除不会带走已评审点；悬空引用只可能来自单点删除。）
>
> **`test_point_analysis_id` 同理不建外键**：07 的 `delete_analysis` 会物理删除
> `test_point_analyses` 行，建 FK 同样会把 07 的删除变成 500。
> 08 只把它当「本次选了哪个测试点批次」的**历史标签**，悬空即视为批次已删除。

> **`needs_review` 为什么不落库**：07 有 04 的 `clear_label()` 这个唯一清除入口可以做钩子，
> 08 没有——测试点的编辑 / 删除都在 07，而红线不允许改 07。
> 读时派生永远与源数据一致，不会出现「标记没同步」的脏状态。

### 4.3 `test_case_steps`（步骤）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| case_id | BIGINT | FK → test_cases.id **ON DELETE CASCADE**，索引 |
| step_no | INT | 非空，从 1 开始 |
| action | VARCHAR(1000) | 非空，操作步骤 |
| expected | VARCHAR(1000) | 非空，默认 `''`，预期结果 |
| created_at | DATETIME(3) | 非空 |

唯一键：`uk_tcsteps_case_no(case_id, step_no)`。
CheckConstraint：`ck_tcsteps_no_positive(step_no >= 1)`。

> 删用例时步骤由数据库级 `ON DELETE CASCADE` 一并清理；ORM 只删 `test_cases` 行，
> 不逐个删步骤（避免 N 次 DELETE 与顺序问题）。

### 4.4 `llm_run_logs` 的 CHECK 扩展

现为 `('incremental_first','incremental_second','provider_test','test_point')`，
迁移 `0023` 增加 `'test_case'`。MySQL 不允许直接改 CHECK：
先 `drop_constraint('ck_llmlogs_task_type')` 再 `create_check_constraint(...)`；`downgrade` 反向。

> `prompt_templates.task_type` 的枚举 `0013` 已包含 `'test_case'`，**不需要改枚举**。

### 4.5 播种：测试用例提示词模板

迁移 `0023` 播种 1 条 `task_type='test_case'` 的模板：

- `name` = `测试用例生成·基于已评审测试点`
- `system_prompt` 以 `[TEST_CASE_SYSTEM]` 开头（对齐 `MockProvider` 的前缀机制）
- `user_prompt` 以 `[TEST_CASE_USER]` 开头
- **示例里不出现任何"可照抄的 id"**：输出契约里没有测试点 id（见 §5.3），
  从结构上杜绝 06 期 L2 的「模型照抄示例 id」问题。

## 5. Prompt 与输出契约

### 5.1 循环单位是**测试点**（不是章节）

07 按章节调模型（一个章节可能命中多个目标）；08 的输入是测试点，
**逐测试点同步调用**（`provider.chat(LLMRequest(system=system, user=user))`），
一个测试点一次调用，产出 0..N 条用例。

排序固定：按 `test_point.id` 升序 → Prompt 可复现。

### 5.2 上下文组装（段落顺序固定）

```
{template.user_prompt}

## 测试点
- 名称：扫码登录连续失败 5 次后锁定
- 归属：功能#10096 用户扫码登录
- 优先级：high
- 前置条件：账号已存在且未锁定
- 验证要点：连续输错密码 5 次，提示锁定且扫码登录同样受阻

## 来源章节：4.2 登录失败次数限制
{chapter.content}
```

- 第 2 段必出（测试点是唯一输入）。
- 第 3 段**可整段省略**：`chapter_id` 为空、章节行不存在、`char_count == 0` 时都不渲染该段，
  但测试点照常生成。
- 截断：总预算复用 `get_settings().incremental_max_input_chars`，
  **只截章节正文**，前缀（模板正文 + 测试点段 + 章节标题）保持不变。

### 5.3 模型输出契约

```json
{
  "cases": [
    {
      "title": "连续输错密码 5 次后账号锁定",
      "case_type": "functional",
      "priority": "high",
      "precondition": "账号已存在、未锁定，登录页可访问",
      "steps": [
        {"action": "输入正确用户名与错误密码", "expected": "提示用户名或密码错误"},
        {"action": "连续重复 4 次", "expected": "每次提示用户名或密码错误"},
        {"action": "第 5 次提交", "expected": "提示账号已锁定 30 分钟"},
        {"action": "锁定期间尝试扫码登录", "expected": "提示账号已锁定"}
      ]
    }
  ]
}
```

**服务端校验（丢弃或归一，不猜、不修）**：

| 字段 | 不合法时 | 处理 |
|---|---|---|
| `cases` | 不是数组 / 缺失 | **整次失败**（`TEST_CASE_INVALID`），不落任何用例 |
| `title` | 缺失 / 空 | **整条丢弃**（`TEST_CASE_INVALID`） |
| `steps` | 缺失 / 空数组 / 不是数组 | **整条丢弃**（`TEST_CASE_INVALID`） |
| `steps[].action` | 缺失 / 空 | **整条丢弃**（`TEST_CASE_INVALID`） |
| `steps[].expected` | 缺失 / 空 | **存空串**（不丢——先保留用例，评审时补） |
| `case_type` | 不在枚举 | **归一到 `functional`** |
| `priority` | 不在枚举 | **归一到 `medium`** |
| `precondition` | 缺失 | **存空串** |
| 同测试点内 `title` 重复 | 第二次起 | **丢弃**（保留第一条，顺序确定） |

**用例绑定规则**：输出里**没有** `test_point_id`——服务端把该条用例绑定到
**当前正在处理的测试点**。模型无从选择别的测试点，因此不存在「越界 id」这一类脏数据。

### 5.4 步骤归一

- `step_no` 由服务端按数组顺序重排为 `1..n`（模型给的序号一律不信）；
- 单步 `action` / `expected` 去首尾空白；超长按列宽截断（1000），**不因超长丢弃整条**；
- `title` 截断到 255、`precondition` 截断到 1000；
- 落库时先写 `test_cases` 再 `flush` 拿 id，再批量写 `test_case_steps`。

## 6. 接口

路由前缀：`/api/projects/{project_id}/test-cases`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/analyses` | 成员 | 生成记录列表（分页） |
| POST | `/analyses` | 项目管理员 | 发起生成（**同步执行**，返回记录 + 用例） |
| GET | `/analyses/{id}` | 成员 | 生成记录详情（含统计与产出用例） |
| DELETE | `/analyses/{id}` | 项目管理员 | 删除生成记录（连带删用例，需无已通过用例） |
| GET | `/cases` | 成员 | 用例列表（状态 / 测试点 / 目标 / 批次 / 待复核 筛选） |
| POST | `/cases` | 项目管理员 | 手工新增用例（含步骤） |
| GET | `/cases/{id}` | 成员 | 用例详情（含步骤与来源追溯） |
| PATCH | `/cases/{id}` | 项目管理员 | 改元数据（名称 / 类型 / 优先级 / 前置条件） |
| DELETE | `/cases/{id}` | 项目管理员 | 删用例（步骤级联删除） |
| PUT | `/cases/{id}/steps` | 项目管理员 | **整体覆盖**步骤（数组，`step_no` 由服务端重排） |
| POST | `/cases/{id}/review` | 项目管理员 | 评审：通过 / 驳回 |
| POST | `/cases/{id}/ack` | 项目管理员 | 确认已复核（刷新源测试点快照时间） |
| GET | `/cases/export` | 成员 | 导出 `.xlsx`（一步一行） |

### 6.1 发起生成的请求体

```json
{
  "template_id": 5,
  "test_point_ids": [101, 102],
  "chapter_ids": [12, 13],
  "target_type": "function",
  "target_id": 10096,
  "test_point_analysis_id": 3
}
```

- `template_id` 必填 → `task_type='test_case'` 且 `status='active'`。
- `test_point_ids` 给了 → 只用这些；**必须全部存在、属于本项目、且 `status='approved'`**，
  任一不满足 → 400 `TEST_CASE_POINT_NOT_FOUND`（严格，不静默过滤）。
- 不给 `test_point_ids` → 按 `chapter_ids` / `target_type+target_id` / `test_point_analysis_id`
  筛 `status='approved'` 的测试点；都不给 = 全项目 approved。
- 筛选后 0 条 → 400 `TEST_CASE_INPUT_EMPTY`，**不建生成记录**。

> 手工新增（`POST /cases`）的挂靠口径与生成不同：允许挂**任意已存在的测试点**
> （含 pending / rejected），只要它属于本项目——人工补录不应被评审状态卡死。
> 生成链路则严格只吃 approved。

> 路由注册顺序：静态行为 `/cases/export` 必须注册在 `/cases/{case_id}` **之前**，
> 否则会被路径参数吞掉（FastAPI 按注册顺序匹配）。

### 6.2 校验顺序（固定）

```
项目 404 → 归档 409 → 角色 403 → 模板 400 → 批次 404 →
测试点 400 → 输入为空 400 → 跑模型
```

**任何一步失败都不产生生成记录**（校验在建行之前，与 07 一致）。

### 6.3 错误码（新增 9 个）

| 类名 | code | HTTP | 场景 |
|---|---|---|---|
| `TestCaseAnalysisNotFound` | `TEST_CASE_ANALYSIS_NOT_FOUND` | 404 | 生成记录不存在 / 不属于该项目 |
| `TestCaseNotFound` | `TEST_CASE_NOT_FOUND` | 404 | 用例不存在 / 不属于该项目 |
| `TestCaseTemplateInvalid` | `TEST_CASE_TEMPLATE_INVALID` | 400 | 模板不存在 / 类型不对 / 已停用 |
| `TestCaseInputEmpty` | `TEST_CASE_INPUT_EMPTY` | 400 | 筛选后没有可用的已评审测试点 |
| `TestCasePointNotFound` | `TEST_CASE_POINT_NOT_FOUND` | 400 | 指定测试点不存在 / 不属于项目 / 未评审通过 |
| `TestCaseInvalid` | `TEST_CASE_INVALID` | 400 | 模型输出结构不合法（整次失败）或请求带不可改字段 |
| `TestCaseStepInvalid` | `TEST_CASE_STEP_INVALID` | 400 | 步骤数组不合法（空 / action 空 / 超过 100 步） |
| `TestCaseReviewStateInvalid` | `TEST_CASE_REVIEW_STATE_INVALID` | 409 | 已评审过的用例重复评审 |
| `TestCaseAnalysisHasApproved` | `TEST_CASE_ANALYSIS_HAS_APPROVED` | 409 | 删除生成记录但已有评审通过的用例 |

全部加进 `app/common/errors.py` 的 `__all__`。

### 6.4 审计

| 场景 | action |
|---|---|
| 发起生成 | `test_case.analysis.create` |
| 删除生成记录 | `test_case.analysis.delete` |
| 评审通过 / 驳回 | `test_case.review` |
| 手工增 / 改 / 删 | `test_case.case.create` / `test_case.case.update` / `test_case.case.delete` |
| 步骤整体覆盖 | `test_case.steps.update` |
| 确认已复核 | `test_case.case.ack` |

审计条目含 `project_id` / `actor_id` / `target_type` / `target_id`；**失败操作不写审计**。

### 6.5 待复核派生（读时计算，不落库）

对每条用例（`needs_review` 为**响应字段**，不落库）：

1. 取源测试点当前行（一次批量 `IN` 查询）；逐行算当前指纹
   `F = sha256(json({name, target_type, target_id, target_name, priority,
   precondition, verification, chapter_id, chapter_title, needs_review}))`；
2. 源测试点不存在：
   - `source_point_fingerprint IS NOT NULL` → `needs_review=true`，`reason='source_point_deleted'`
   - `source_point_fingerprint IS NULL` → 已人工确认删除，`needs_review=false`
3. 源测试点存在：
   - 快照为 NULL，或 `F != source_point_fingerprint` → `needs_review=true`，
     `reason='source_point_changed'`
   - 否则 `needs_review=false`

`POST /cases/{id}/ack`：源存在 → `source_point_fingerprint = F`；
源不存在 → 置 NULL；两者都写 `needs_review_ack_at`。

> **标签清除也会被覆盖到**：07 因标签清除给测试点置 `needs_review=1` 会改变指纹，
> 08 的派生同样标「源测试点已变更」。08 不 import 04 / 05 的任何模块。
>
> **指纹字段清单只有一个出处**：`app/test_cases/fingerprint.py` 里一个 `_FIELDS` 常量，
> 生成 / 读取 / ack 三处共用；测试逐字段断言「任一处改动都触发待复核」，防漏项。

响应额外带 `needs_review` / `needs_review_reason` / `needs_review_ack_at`。

> 派生只在**查询时**发生：不改 07 的数据、不写 08 的标记列、不需要同步任务。
> 列表接口的 `needs_review=true` 筛选在 Python 层完成（现有列表本来就是全量取再分页）。

### 6.6 导出

`GET /cases/export` 复用列表筛选参数，返回 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`：

- 文件名：`test-cases-{project_id}-{yyyymmdd}.xlsx`；
- 列：`用例ID / 用例名称 / 用例类型 / 优先级 / 所属测试点ID / 所属测试点 / 功能或功能点 / 前置条件 / 步骤序号 / 操作步骤 / 预期结果 / 状态 / 来源 / 创建时间`；
- **一个步骤一行**；用例元数据在每行重复（便于筛选与透视）；
- 无步骤的用例（理论不存在）给一行空步骤；
- 导出不加审计（读操作）。

## 7. 前端

- 项目详情页新增第 9 个 Tab「测试用例」（插在「测试点」之后）。
- Tab 内容：
  - 上半区：生成记录表（模板 / 状态 / 统计 / 耗时 / 发起时间）+「发起生成」按钮 +「导出」按钮；
  - 下半区：用例表（名称、所属测试点、类型、优先级、步骤数、状态、来源、待复核标记）
    + 行操作（详情 / 评审 / 编辑 / 删除 / 确认复核）。
- 发起生成弹窗：模板下拉（`GET /api/prompt-templates?task_type=test_case`）+
  测试点多选（**只列 approved**，带目标与章节）+ 可选的章节 / 目标筛选。
- 详情抽屉：用例元数据 + 步骤表（序号 / 操作 / 预期）+ 来源追溯
  （测试点 → 目标 → 章节）+ 评审操作；待复核时展示告警条与「确认已复核」。
- 编辑弹窗：名称 / 类型 / 优先级 / 前置条件 + 步骤编辑器（增删行、上移下移，保存走 `PUT /steps`）。
- 访客只读：两张表可见，生成 / 编辑 / 评审 / 复核 / 导出入口不可用（导出按钮保留给成员）。
- 错误码中文映射加进 `web/src/api/client.ts`。

`data-testid` 命名沿用 `区域-动作-目标`：

```
testcase-tab / testcase-create-btn / testcase-export-btn
testcase-table / testcase-row-{id} / testcase-analysis-table
testcase-form-template / testcase-form-points
testcase-detail-drawer / testcase-steps-table
testcase-review-approve / testcase-review-reject
testcase-manual-create / testcase-steps-editor / testcase-ack-btn
testcase-needs-review-tag
```

## 8. 验收标准

验证口径遵循 [specs/验证约定.md](../验证约定.md)：后端用例命名 `test_ac_<AC号>_<场景>`，
e2e 命名 `test_ac_<AC号>_<场景>_ui`，前台截图落 `.screenshots/<任务号>/` 且文件名含 AC 编号。
每条 AC **至少**一条自动化用例；纯后台项（审计、留痕）在用例内断言。

### AC-159 表结构与迁移 `0023`
- **Given** 迁移 head 为 `0022`
- **When** `alembic upgrade head`
- **Then** 新增 `test_case_analyses` / `test_cases` / `test_case_steps` 三张表，
  索引与 CHECK 与 §4 一致
- **Then** `llm_run_logs.task_type` 的 CHECK 含 `'test_case'`：
  实插 `test_case` 成功、实插 `bogus_task` 被拒（3819）
- **Then** `prompt_templates` 里 `task_type='test_case'` 有且仅有 1 条 active
- **Then** 两库 `0023 → 0022 → 0023` 往返干净

### AC-160 只消费已评审测试点
- **Given** 项目有 1 条 `approved`、1 条 `pending`、1 条 `rejected` 测试点
- **When** 发起生成（不指定 `test_point_ids`）
- **Then** Mock 收到的调用次数为 **1**（只有 approved 那条）
- **Then** Prompt 里**不出现** pending / rejected 的名称与验证要点
- **Then** 服务端强制过滤（不依赖前端）

### AC-161 无可用测试点 → 拒绝发起
- **Given** 项目只有 pending / rejected 测试点
- **When** 发起生成
- **Then** 400 `TEST_CASE_INPUT_EMPTY`
- **Then** **不产生**生成记录

### AC-162 一条测试点可产多条用例
- **Given** Mock 对一条测试点返回 3 条用例（正向 / 反向 / 边界）
- **When** 发起生成
- **Then** `test_cases` 新增 3 行，`test_point_id` 均指向该测试点
- **Then** `test_case_steps` 行数与各用例的 `steps` 长度一致
- **Then** `stats.case_count=3`、`stats.step_count` 等于步骤总数

### AC-163 步骤子表顺序与约束
- **Given** 模型返回的步骤顺序确定
- **When** 落库
- **Then** `step_no` 从 1 连续递增，与数组顺序一致（不信模型给的序号）
- **Then** `(case_id, step_no)` 唯一；`step_no >= 1`
- **Then** 删除用例时步骤被级联删除（不留孤儿行）

### AC-164 模型输出校验与归一
- **Given** Mock 返回：1 条缺 `title`、1 条 `steps` 为空、1 条 `priority='urgent'` 且 `case_type='perf'`、
  1 条 `steps[].expected` 缺失
- **When** 发起生成
- **Then** 前两条**整条丢弃**并记入 `stats.discarded`（`TEST_CASE_INVALID`）
- **Then** 第三条落库，`priority` 归一为 `medium`、`case_type` 归一为 `functional`
- **Then** 第四条落库，缺失的 `expected` 存空串
- **Then** 同测试点内重复 `title` 只保留第一条

### AC-165 坏 JSON → 整次失败
- **Given** Mock 返回非法 JSON 或 `cases` 不是数组
- **When** 发起生成
- **Then** 生成记录 `status='failed'`、`error_code='TEST_CASE_INVALID'`
- **Then** **不产生**任何用例行

### AC-166 JSON 容错复用 parse_llm_json
- **Given** Mock 返回带 Markdown 围栏（或 `<think>` 块）的 JSON
- **When** 发起生成
- **Then** 用例照常落库（证明走 `parse_llm_json` 而非裸 `json.loads`）

### AC-167 评审流程
- **Given** 生成的用例 `status='pending'`
- **When** 评审通过
- **Then** `status='approved'`，记 `reviewed_by` / `reviewed_at`
- **When** 再评审一次
- **Then** 409 `TEST_CASE_REVIEW_STATE_INVALID`
- **Then** 审计 `test_case.review` 含 `self_approved`

### AC-168 手工增删改
- **Given** 项目管理员
- **When** 手工新增用例（挂一条已存在的测试点 + 2 个步骤）
- **Then** `source_type='manual'`、`analysis_id=NULL`、`test_point_name` 取快照
- **When** 改名称 / 类型 / 优先级 / 前置条件
- **Then** 只这 4 个字段可改；传 `status` / `test_point_id` → 400 `TEST_CASE_INVALID`
- **When** 删除
- **Then** 行被物理删除，步骤级联删除

### AC-169 步骤整体覆盖
- **Given** 用例已有 3 个步骤
- **When** `PUT /cases/{id}/steps` 传 2 个步骤
- **Then** 旧 3 行被删、新 2 行 `step_no` 为 1 / 2
- **When** 传空数组 / `action` 为空 / 超过 100 步
- **Then** 400 `TEST_CASE_STEP_INVALID`，**原步骤不变**（整体事务）
- **Then** 审计 `test_case.steps.update` 记 `before_count` / `after_count`

### AC-170 删除生成记录
- **Given** 某次生成产出的用例全部为 `pending` / `rejected`
- **When** 删除生成记录
- **Then** 记录与它产出的用例（连带步骤）一起删除
- **Given** 其中有 `approved` 的用例
- **When** 删除生成记录
- **Then** 409 `TEST_CASE_ANALYSIS_HAS_APPROVED`

### AC-171 测试点变更 / 删除 → 待复核（读时派生）
- **Given** 一条已生成的用例，源测试点被编辑（名称 / 前置条件 / 验证要点等任一字段变化）
- **When** 查询用例
- **Then** 用例**内容完全不变**
- **Then** `needs_review=true`、`needs_review_reason='source_point_changed'`
- **Given** 源测试点被 07 物理删除（或删生成记录连带删除）
- **When** 查询用例
- **Then** 用例仍存在，`test_point_name` 保留快照
- **Then** `needs_review_reason='source_point_deleted'`
- **Then** 07 的单点删除与删生成记录**行为与错误码不变**（无外键冲突、无 500）
- **Given** 07 因标签清除把测试点置 `needs_review=1`
- **When** 查询该测试点下的用例
- **Then** 同样得到 `needs_review=true`（指纹包含 `needs_review` 位，无需 08 感知标签）
- **Then** 仅改 `updated_at`（若有人手写 SQL）**不**触发待复核——判定基准是内容指纹

### AC-172 确认已复核
- **Given** 用例处于待复核
- **When** 调 `POST /cases/{id}/ack`
- **Then** `needs_review` 变为 false，`needs_review_ack_at` 有值
- **Then** `source_point_fingerprint` 被刷成当前测试点的指纹
- **When** 测试点再次被改
- **Then** 待复核重新出现
- **Given** 源测试点已删除且用例处于待复核
- **When** 确认已复核
- **Then** `source_point_fingerprint` 置 NULL，`needs_review` 变 false，之后不再提示

### AC-173 权限矩阵
- **Given** member / guest
- **When** 读接口（列表 / 详情 / 导出）
- **Then** 200
- **When** 发起生成 / 评审 / 手工改 / 步骤覆盖 / 确认复核
- **Then** 403 `NOT_PROJECT_ADMIN`
- **Given** 非项目成员
- **When** 读接口
- **Then** 403 `NOT_PROJECT_MEMBER`

### AC-174 归档项目
- **Given** 项目已归档
- **When** 发起生成
- **Then** 409 `PROJECT_ARCHIVED`
- **When** 读接口
- **Then** 200

### AC-175 运行留痕
- **Given** 发起一次生成（成功与失败各一次）
- **When** 跑完
- **Then** `llm_run_logs` 新增 `task_type='test_case'` 记录，`call_count` 等于**本次**调用测试点条数
  （连跑两次，两次的 `call_count` 都是 1，不累计）
- **Then** 失败时 `status='failed'` + `error_code`
- **Then** 表中**不出现** Prompt 正文与 API Key

### AC-176 提示词模板来自数据库
- **Given** `task_type='test_case'` 的模板正文是可识别的固定字符串
- **When** 发起生成
- **Then** Mock 收到的 `system` 等于该模板的 `system_prompt`
- **Then** Mock 收到的 `user` 以该模板的 `user_prompt` 开头，且包含测试点名称与验证要点
- **Then** 模板被停用 → 400 `TEST_CASE_TEMPLATE_INVALID`，**不产生生成记录**

### AC-177 导出 Excel
- **Given** 用例含 3 个步骤
- **When** `GET /cases/export`
- **Then** 返回 `.xlsx`，Content-Type 与文件名符合 §6.6
- **Then** 该用例占 3 行，`步骤序号` 为 1 / 2 / 3，元数据列在每行重复
- **Then** 筛选参数（状态 / 测试点 / 批次）对导出生效
- **Then** member 可导出，非成员 403

### AC-178 前端可用
- 项目详情页「测试用例」Tab 可见（第 9 个，位于「测试点」之后）
- 发起生成 → 用例出现在列表 → 打开详情 → 评审通过 → 状态变「已通过」
- 手工新增 → 编辑步骤 → 保存 → 步骤表更新；删除 → 行消失
- 待复核用例显示告警条，点「确认已复核」后消失
- 导出按钮可下载文件
- e2e 用例命名 `test_ac_178_*_ui`；截图 `.screenshots/T109/`，文件名含 AC 编号；
  前台核对点同步登记到 `specs/验证约定.md` §5.10

### AC-179 断网与模式红线
- **Given** 全量测试套件
- **When** 跑全量
- **Then** **零真实 socket**：真实 Provider 的用例一律 `httpx.MockTransport`；
  测试目录不出现 `requests` / `urlopen` / `aiohttp` / `socket.socket`
- **Then** 代码里**没有** Skill 模式分支（无 manifest / 无回退开关）

### AC-180 01–07 零回归
- **Given** 01–07 的既有行为
- **When** 跑全量 pytest 与 e2e
- **Then** 966 条既有测试**一条不删、不改期望值**
- **Then** 04 / 05 / 06 / 07 定向回归零失败
- **Then** 迁移 head 两库均为 `0023`，`0023 → 0022 → 0023` 往返干净

## 9. 非功能

- **零真实网络请求**（测试与开发环境均如此）。
- **同步执行**：逐测试点同步调模型，与 05 / 07 一致，不引入异步队列。
- **Prompt 可复现**：测试点按 id 排序、段落顺序固定、模板正文从库里取。
- **大模型不可用时降级 Mock**：`llm_providers` 空表 → Mock → 记录 `succeeded`，
  Mock 默认响应会产出一条带 2 个步骤的用例（e2e 可直接跑通，无需补写数据）。
- **API Key 不明文**：沿用 06 期口径，任何响应 / 审计 / 日志 / 异常都不带 Key。
- **单次生成规模上限**：一次最多处理 200 条测试点（超出 → 400 `TEST_CASE_INVALID`），
  避免一次同步请求跑太久。

## 10. 依赖与影响

| 依赖 | 状态 |
|---|---|
| 07 `test_points` / `test_point_analyses` | ✅ 已上线（`0022`） |
| 06 `get_provider` / `parse_llm_json` / `record_run` | ✅ 已上线 |
| 06 `prompt_templates.task_type='test_case'` | ✅ 枚举 `0013` 已预留，**本期播种模板** |
| 06 `llm_run_logs` | ✅ 已上线，本期扩 `task_type` 枚举 |
| `openpyxl` | ❌ **新增运行时依赖**（`openpyxl>=3.1`，仅导出用） |
| 04 章节 / 标签 | ✅ 只读引用 |

**对既有模块的影响**：

| 模块 | 影响 |
|---|---|
| `app/models/__init__.py` | 加 3 个模型的 import 与 `__all__` |
| `app/common/errors.py` | 加 9 个错误类 + `__all__` |
| `app/main.py` | 注册 1 个路由 |
| `app/llm/mock.py` | **加一个前缀分支**（`[TEST_CASE_SYSTEM]`），既有分支不动 |
| `pyproject.toml` | 加 `openpyxl>=3.1` |
| `app/test_points/` | **零改动** |
| `app/baselines/` / `app/incremental/` | **零改动** |
| `app/llm/` 其余文件 | **零改动** |

## 11. 后续期（明确不在本期）

| 期 | 内容 |
|---|---|
| 2.4.6 | 自动化执行：用例 ↔ 自动化资产关联、脚本生成、扫描导入 |
| — | 用例 Excel **导入**（含列契约、行级错误报告、全量回滚） |
| — | 工作台「待评审的用例」计数与看板（与 07 的待评审测试点统一口径） |
| — | 用例版本历史 / 快照、用例编号流水 |
| — | Skill 模式（PRD 2.5） |
