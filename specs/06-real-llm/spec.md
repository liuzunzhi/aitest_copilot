# 06 · 真实大模型接入与提示词模板管理 · 规格

> 对齐需求：PRD 2.4.3「支持直连 / Skill 两种模式」的**直连模式**部分、PRD 2.3.6 全局提示词模板、PRD 3.1「密钥全局统一管控」、PRD 3.2「运行日志」。
> 上游依赖：05-incremental 第一/二/三期（T68–T83）已完成——`prompt_templates` 表已存在、`LLMProvider` 抽象已就位、05 三段链路已跑通。
> 本期**只做直连模式的真实模型落地**：配置落库 + 加密 + 动态 Provider + 模板管理 UI。
> **不做 Skill 双轨制、不做 Token 计费、不碰自动化执行。**

## 1. 背景与目标

05 把「章节 → 模型比对 → 全局裁决 → 人工确认 → 落标签」整条链路做完了，
但模型侧只有一个 `MockProvider`——它的默认响应是 `{"conclusions": []}`（第一遍）与
`{"decision": "unchanged"}`（第二遍）。**结论是：线上跑 05 等于什么都分析不出来。**

本期把模型侧补成真的：

```
llm_providers（Base URL / 加密 API Key / 模型 / 超时）
        │
        └─▶ get_provider(session) ──┬─▶ 无配置 → MockProvider（降级，行为与今天完全一致）
                                     │
                                     └─▶ 有默认配置 → OpenAICompatProvider
                                            │
                                            ├─▶ app/llm/crypto.py  解密 API Key
                                            └─▶ POST {base_url}/chat/completions
                                                   │
                                                   └─▶ llm_run_logs（耗时 / 次数 / 错误）
```

同时补上 PRD 2.3.6 要求的**提示词模板管理**：今天模板是迁移播种的只读数据，
前端写死 `DEFAULT_TEMPLATE_ID = 1`，管理员改不动、用户也选不了别的。

本期目标：

1. 大模型配置**落库**，API Key **密文存储**，任何响应 / 审计 / 日志 / 异常里都不出现明文；
2. `get_provider()` **优先读数据库**，没有配置**自动降级 Mock**——保证现有 626 条用例与 e2e 在断网下依然全绿；
3. 真实网络请求**有超时**，任何失败统一收敛到既有的 `LLM_CALL_FAILED`（502）；
4. 系统设置页能配大模型、测连通性；能列出并编辑提示词模板的 System / User Prompt；
5. 05 前端的模板下拉改成**动态拉取**，形成闭环。

做完之后，下一期（07）可以做测试点分析，且模型侧不再是拦路虎。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 大模型配置表 | `llm_providers`：名称、Base URL、**加密后的** API Key、模型名、超时、状态、是否默认 |
| 密钥加密 | `app/llm/crypto.py`：Fernet 对称加密，主密钥来自环境变量 `LLM_SECRET_KEY`（**必填**） |
| 动态 Provider | `OpenAICompatProvider`：OpenAI 兼容 `/chat/completions`，兼容 DeepSeek / 通义千问等 |
| 降级机制 | 数据库无默认配置（或默认配置被停用）→ 自动降级 `MockProvider`，**行为与今天完全一致** |
| 运行留痕 | `llm_run_logs`：任务类型、调用次数、耗时、状态、错误码与错误摘要；**不记 token 金额、不记 Prompt 正文** |
| 连通性测试 | 系统设置页一键测配置：固定 ping prompt，回填 `last_test_*`，不写业务表 |
| 配置管理 API | 系统管理员可增改查配置；Key 只返回掩码；更新时 Key 留空表示不改 |
| 模板管理 API | 系统管理员可列出 / 查看 / 编辑 `prompt_templates` 的 System / User Prompt（**不新建、不删除**） |
| 只读模板列表 API | 登录用户可查某任务类型的可用模板（`id / name / version_no / description`），供 05 下拉使用 |
| 前端 · 系统设置 | 新增「系统设置」页，两个 Tab：大模型配置 / 提示词模板 |
| 前端 · 05 联动 | 05 项目页模板下拉改为动态拉取；无可用模板时禁用发起按钮并提示 |
| 审计 | `llm.provider.create` / `llm.provider.update` / `prompt_template.update` |
| 配置 | `Settings.llm_secret_key` 必填环境变量；同步 `.env.example` 与 `PROGRESS.md` |
| **PDF 解析（前置任务 T84-PDF）** | 03 模块支持 `.pdf` 上传：`pdfplumber` 纯文本提取 + 字号规则切章节 + 表格还原 + 扫描件整文降级 |

### 2.2 本期不做（红线，违反即返工）

| 不做 | 原因 |
|---|---|
| **Skill 双轨制**（Skill 包、manifest、schema 校验、失败回退开关） | 用户明确划为红线；属 PRD 2.5 的后续期 |
| **Token 计费 / 配额 / 每日次数上限** | 用户明确划为红线；`llm_run_logs` 只记次数与耗时 |
| **碰自动化执行模块** | 用户明确划为红线；PRD 2.4.6 尚未排期 |
| **新建 / 删除提示词模板** | 用户明确只做「列表 + 编辑已有模板」；新建/删除会牵出版本链与引用校验 |
| **模板版本历史表** | 历史分析已用 `template_id + template_version` 快照追溯；正文变更靠审计 `before/after` 留痕 |
| **项目级供应商绑定 / 多供应商路由** | 本期全局唯一默认配置；项目级覆盖留待后续 |
| **改 05 的引擎 / 两遍 / 产出段逻辑** | 05 三期代码零改动，只换 `get_provider` 的取数来源 |
| **把 API Key 存进 `system_settings` 或日志表** | 密钥只允许落在 `llm_providers.api_key_ciphertext` 一处 |
| **顺手修无关模块**（04 的来源类型下拉、清除原因枚举、xdist flaky） | 记待办，等用户点头 |

> **红线精确化（2026-11-17 用户裁决）**：上面那条「不改 05 的引擎 / 两遍 / 产出段逻辑」
> 的准确含义是——**不改 05 的判定逻辑与业务语义**。
> **允许对 05 的 JSON 解析入口做容错加固**（见 §6.4）：
> 真实模型会返回带 Markdown 围栏的 JSON，不容错则整次分析直接 502。
> 除解析入口外，`app/incremental/` 下仍需零逻辑改动。
>
> **03 的 PDF 解析已由用户点头，从待办移入本期**，作为**前置任务 T84-PDF** 单独立项
> （见 §2.4），不与 06 的模型侧改动混在一个提交里。

### 2.3 与 05 的兼容约束

1. `app/llm/provider.py` 的 `get_provider` 保持**函数依赖**形态，签名从
   `get_provider() -> LLMProvider` 改为 `get_provider(session: Session = Depends(get_db)) -> LLMProvider`。
   现有测试的 `dependency_overrides[get_provider] = lambda: mock` **不受影响**（覆盖后不再走原函数体）。
2. `LLMProvider` 协议、`LLMRequest` / `LLMResponse` / `TokenUsage` 数据结构**不变**；
   05 的 `engine.py` / `second_pass.py` **零改动**。
3. `MockProvider` 的行为**一字不改**：默认响应、`queue`、`calls`、`raw` 契约全部保留。
4. `prompt_templates` 表结构**不迁移、不加列**：列表与编辑只用现有字段
   （`name / task_type / description / system_prompt / user_prompt / version_no / status / updated_at`）。
5. `incremental_analyses.provider` 字段继续记供应商名：无配置时为 `mock`，
   有配置时为 `openai_compat`——历史记录口径不变。

### 2.4 前置任务 T84-PDF · 03 模块支持 PDF 解析

**为什么必须在本期做**：T87 的验收要求「真实 `.pdf` 与 `.docx` 走完整端到端链路」。
PDF 不支持，这条验收做不了；而 PDF 是最基础的需求来源，不能一直挂着。

**为什么单独立项**：03 的改动（解析器、上传接口、前端 `accept`、**3 处既有测试的期望值**）
与 06 的模型侧改动（加密、Provider、迁移 `0017`）依赖不同、验收边界不同，
混在一个提交里既违反「不顺手修无关模块」的自我约束，也让出问题时不好二分定位。

#### 2.4.1 依赖选择：`pdfplumber`（实测结论）

实测本机样本 PDF（`Matrix系统说明书_基础需求文档.pdf`，8 页、2508 字、**文本型**）：

| 候选 | 提取字符数 | 能否拿到字号 | 表格还原 | 结论 |
|---|---|---|---|---|
| `pdfplumber` | 2508 | ✅ `extract_words(extra_attrs=['size'])` | ✅ `find_tables()` | **采用** |
| `pypdf` | 2746（多为空格/换行噪声） | ❌ | ❌ | 不用 |

**决定性因素是字号**：拿到字号才能用规则切章节，从而**不必**为 PDF 付出 LLM 拆解成本。
`pypdf` 拿不到字号，PDF 就只能走「整文输入 + LLM 拆解」，成本与复杂度都上一个台阶。

#### 2.4.2 章节切分规则

1. **提取**：逐页 `extract_words(extra_attrs=['size'])`，按 `top` **±2pt 容差**聚成行，
   行内按 `x0` 排序拼回文本，行字号取**行内最大字号**。
2. **分档**：统计全文字号分布，**众数 = 正文字号**；大于「众数 + 0.6pt」的字号即为标题档，
   按字号**降序**依次映射 level 1..N。
3. **判标题**：字号 ∈ 标题档 **且** 命中编号正则（`第X章/篇/部` 或 `\d+(\.\d+)+`）
   **且** 去空白后长度 ≤ 40 → 判为标题；否则是普通正文行。
4. **表格**：`find_tables()` 还原成 `a | b` 管道行（与 docx 的表格处理同构）。
5. **降级**：**提取不到任何文字**（扫描件 / 无字体层）→ 整文单章「全文」，
   **不报错**（对齐 03 的「txt 无标题整文单章」口径）。
6. **落库**：复用现有 `_insert_chapters`，章节树结构与 md / docx **完全一致**，
   05 的分析链路**零改动**。

#### 2.4.3 样本 PDF 的实测切分效果

用上述规则跑样本 PDF，得到 6 章 / 20 节 / 6 小节，**无错切、无漏章**：

```
L1 第一章引言          L2 1.1编写目的   L3 2.4.2上传功能
L1 第二章主要系统设计   L2 2.4功能描述   L3 2.4.3下载功能
L1 第三章UML设计类图   L2 3.1类图      ...
L1 第四章接口设计      L2 5.1ER分析
L1 第五章：ER分析和表结构设计
L1 第六章:系统安全和权限设计
```

#### 2.4.4 错误码与既有测试的改动

| 场景 | 响应 |
|---|---|
| 正常 PDF | 201，章节按规则落库 |
| 损坏 / 非 PDF 内容 | 400 `DOCUMENT_PARSE_FAILED` |
| 扫描件（无文字层） | 201，整文单章「全文」 |
| 扩展名不支持（如 `.xlsx`） | 400 `UNSUPPORTED_DOC_TYPE`（**保持不变**） |

「PDF 不支持」不再是一个错误码——`UNSUPPORTED_DOC_TYPE` 保留给真正的未知扩展名。
因此 **3 处既有测试的期望值必须改**（否则全量红）：

| 文件 | 现状 | 改为 |
|---|---|---|
| `tests/documents/test_parser.py` | `("需求.pdf", b"%PDF-1.4", UnsupportedDocType)` | 损坏 PDF → `DocumentParseFailed` |
| `tests/documents/test_upload.py` | 「PDF 暂不支持：400」 | PDF 上传成功 → 章节落库 |
| `tests/e2e/test_documents_ui.py` | 「传 .pdf → 提示只支持 md/docx/txt」 | 传 .pdf → 上传成功 |

## 3. 角色与权限

| 操作 | guest | member | project_admin | system_admin |
|---|---|---|---|---|
| 大模型配置列表 / 详情 | 403 | 403 | 403 | 可 |
| 大模型配置新建 / 更新 / 测试连通性 | 403 | 403 | 403 | 可 |
| 提示词模板列表 / 详情 / 编辑 | 403 | 403 | 403 | 可 |
| 只读模板列表（`GET /api/prompt-templates`） | 可 | 可 | 可 | 可 |

- 非系统管理员访问管理接口 → 403 `FORBIDDEN`（复用现有 `require_system_admin`）。
- 只读模板列表只需登录（`current_user`），因为 05 项目页要对所有项目成员开放模板下拉。
- 「系统设置」菜单入口**只对 `system_admin` 显示**，但接口层的权限校验才是真防线。

## 4. 数据模型（迁移 `0017`，2 张新表）

迁移文件 `migrations/versions/0017_llm_providers.py`，`down_revision = "0016"`。
两张表无外键依赖关系，upgrade 顺序 `llm_providers` → `llm_run_logs`；
downgrade 反序直接删表（沿用 04/05 的写法：**直接删表**，不先删索引，避开 MySQL 1553）。

### 4.1 `llm_providers`（大模型配置）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT UNSIGNED | PK 自增 |
| name | VARCHAR(64) | 非空，唯一 `uk_llmprov_name` |
| provider_type | VARCHAR(32) | 非空，默认 `openai_compat`；Check 只允许该值 |
| base_url | VARCHAR(255) | 非空，仅允许 `http://` / `https://`；入库前去掉尾部 `/` |
| api_key_ciphertext | TEXT | 非空，**Fernet 密文**，**绝不存明文** |
| api_key_last4 | VARCHAR(8) | 非空，仅末 4 位，用于 UI 掩码 |
| model | VARCHAR(128) | 非空 |
| timeout_seconds | INT UNSIGNED | 非空，默认 60；Check `1 <= timeout_seconds <= 300` |
| status | VARCHAR(16) | 非空，默认 `active`；Check `active` / `disabled` |
| is_default | TINYINT(1) | 非空，默认 0 |
| default_key | TINYINT | **STORED 生成列**：`CASE WHEN is_default = 1 THEN 1 ELSE NULL END` |
| last_test_status | VARCHAR(16) | 可空，`succeeded` / `failed` |
| last_test_at | DATETIME(3) | 可空 |
| last_test_error | VARCHAR(500) | 可空，**已脱敏**（不含 API Key） |
| created_by | BIGINT UNSIGNED | 非空 |
| updated_by | BIGINT UNSIGNED | 可空 |
| created_at / updated_at | DATETIME(3) | 非空 |

索引：
- `uk_llmprov_name` unique(`name`)
- `uk_llmprov_default` unique(`default_key`)——**保证全局只有一个默认**（MySQL 唯一索引允许多个 NULL，非默认行不受约束）
- `idx_llmprov_status` (`status`)

规则：

1. **不提供物理删除**：停用即 `status='disabled'`，历史与审计保留。
2. 把某行设为默认时，服务层**先把其余行 `is_default` 置 0**，再把目标行置 1（同一事务）。
3. 停用**默认行**时，服务层同时把该行 `is_default` 置 0——**结果可能是没有默认配置**，
   此时 `get_provider()` 降级 Mock（这是期望行为，不是故障）。
4. `provider_type` 本期只允许 `openai_compat`；建列是为了将来加供应商时不改表。

### 4.2 `llm_run_logs`（模型运行留痕）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT UNSIGNED | PK 自增 |
| task_type | VARCHAR(32) | 非空，`incremental_first` / `incremental_second` / `provider_test` |
| project_id | BIGINT UNSIGNED | 可空 |
| analysis_id | BIGINT UNSIGNED | 可空，**不建外键**（记录要能留存） |
| provider_id | BIGINT UNSIGNED | 可空，不建外键（配置停用后仍可追溯） |
| provider_name | VARCHAR(64) | 非空，快照 |
| model | VARCHAR(128) | 非空，快照 |
| template_id | BIGINT UNSIGNED | 可空，快照 |
| template_version | INT UNSIGNED | 可空，快照 |
| call_count | INT UNSIGNED | 非空，默认 0，本次任务的模型调用次数 |
| latency_ms | INT UNSIGNED | 非空，默认 0，任务墙钟耗时 |
| status | VARCHAR(16) | 非空，`succeeded` / `failed` |
| error_code | VARCHAR(64) | 可空 |
| error_message | VARCHAR(500) | 可空，**已脱敏** |
| created_at | DATETIME(3) | 非空 |

索引：`idx_llmlogs_analysis` (`analysis_id`)、`idx_llmlogs_created` (`created_at`)、
`idx_llmlogs_status` (`status`, `created_at`)。

规则：

1. **不存 Prompt 正文、不存模型原文、不存 token 金额**——只记次数、耗时、状态、错误。
2. 一条记录 = **一次任务**（一次分析的第一遍 / 第二遍 / 一次连通性测试），
   不是一次 HTTP 调用；`call_count` 记该任务内调用了几次。
3. 写日志**不写审计**（日志不是业务写操作）。

## 5. 加密与密钥处理

### 5.1 主密钥

- `Settings.llm_secret_key: str = Field(..., min_length=1)`，**必填**，来自环境变量 `LLM_SECRET_KEY`。
  缺失时构造 `Settings` 即失败——与 `db_dsn` 同一口径（不允许带空配置启动）。
- Fernet 密钥由主密钥派生：`base64.urlsafe_b64encode(sha256(secret_key.encode()).digest())`，
  这样任意长度的字符串都能当主密钥，不需要用户手工生成 32 字节。

### 5.2 加解密

`app/llm/crypto.py`：

| 函数 | 行为 |
|---|---|
| `encrypt(plain: str) -> str` | Fernet 加密，返回可安全落库的密文字符串 |
| `decrypt(cipher: str) -> str` | 解密；密文被篡改 / 主密钥不对 → 抛 `LLMConfigInvalid` |
| `mask(plain: str) -> str` | 掩码：`sk-****abcd`（长度 ≤ 4 时只给 `****`） |

- `decrypt` 失败时**只**抛 `LLMConfigInvalid("大模型配置无法解密，请检查 LLM_SECRET_KEY")`，
  错误消息**不含密文、不含明文**。
- 落库前写 `api_key_last4 = plain[-4:]`（明文末 4 位），供 UI 掩码展示。

### 5.3 明文边界（硬约束）

以下位置**一律不得出现 API Key 明文**：

- 数据库任何列（只存密文）；
- HTTP 响应体（只返回 `api_key_masked`）；
- 审计日志 `before_data` / `after_data`（只存 `api_key_last4`）；
- 应用日志（`logging` 的任何消息）；
- 异常消息与错误响应（`LLM_CALL_FAILED` 的 message 只描述「超时 / HTTP 401 / 连接失败」）；
- 运行日志 `llm_run_logs.error_message`。

## 6. 动态 Provider

### 6.1 解析顺序

```
get_provider(session) -> LLMProvider
  1. 查 llm_providers：status='active' AND is_default=1（最多一条，由唯一索引保证）
  2. 查不到 → 返回进程内 MockProvider 单例（与今天行为完全一致）
  3. 查到 → 解密 Key → OpenAICompatProvider(base_url, key, model, timeout)
```

- Mock 单例**保持进程级复用**（现有 `test_ac_84_get_provider_is_mock_singleton` 依赖这一点）。
- `get_provider` 每次调用都查库（配置改了立即生效，不做缓存）；
  查询成本极低（单表 + 唯一索引），不值得引入缓存一致性问题。
- 解密失败 → 抛 `LLMConfigInvalid`（500 `LLM_CONFIG_INVALID`），
  **不静默降级**——配置坏了要让人知道，否则线上会用 Mock 跑出一堆空结论却没人发现。

### 6.2 `OpenAICompatProvider`

- 端点：`POST {base_url}/chat/completions`（`base_url` 已去掉尾部 `/`）。
  DeepSeek：`https://api.deepseek.com/v1`；通义千问：`https://dashscope.aliyuncs.com/compatible-mode/v1`。
- 请求头：`Authorization: Bearer <api_key>`、`Content-Type: application/json`。
- 请求体：`{"model": ..., "messages": [{"role": "system", "content": ...}, {"role": "user", "content": ...}]}`。
  本期**不传** `temperature` / `max_tokens`（用供应商默认值，避免不同供应商行为不一致）。
- 超时：`httpx.Timeout(connect=5.0, read=timeout_seconds, write=timeout_seconds, pool=5.0)`。
- 解析：`choices[0].message.content`；结构不符（无 `choices` / 无 `message` / `content` 不是字符串）→ `LLMCallFailed`。
- `usage`：供应商返回了 `usage` 就透传 `prompt_tokens` / `completion_tokens` / `total_tokens`，
  **不落库、不计费**；没返回就留 0。
- 异常收敛（全部 → `LLMCallFailed`，HTTP 502 `LLM_CALL_FAILED`）：
  | 情况 | 消息（不含 Key） |
  |---|---|
  | `httpx.TimeoutException` | `调用大模型超时（超过 {timeout_seconds} 秒）` |
  | `httpx.ConnectError` | `无法连接大模型服务，请检查 Base URL 与网络` |
  | `httpx.HTTPError`（其他） | `调用大模型失败：{异常类型名}` |
  | HTTP 401 / 403 | `大模型鉴权失败（HTTP {status}），请检查 API Key` |
  | 其他非 2xx | `大模型返回 HTTP {status}` |
  | 响应结构不符 | `大模型返回结构不合法` |

- **模型内容不是合法 JSON 时不归本 Provider 管**：仍由 05 的引擎抛 `LLM_OUTPUT_INVALID`（502），
  职责不混（网络/协议问题 vs 业务格式问题）。

### 6.3 测试如何不碰真实网络

- Provider 构造时接受可选 `transport: httpx.BaseTransport` 参数；
  测试传 `httpx.MockTransport(handler)`，**不产生真实 socket**。
- `httpx` 从 dev 依赖**移到运行时依赖**（`pyproject.toml` 的 `dependencies`）。
- 新增运行时依赖 `cryptography>=43`（本期唯一新增依赖）。

### 6.4 JSON 解析容错（Markdown 围栏）

**问题**：真实模型（DeepSeek 等）极大概率返回带 Markdown 代码块的 JSON：

````
```json
{"conclusions": [...]}
```
````

裸 `json.loads` 会抛 `JSONDecodeError` → 整次分析直接 502 失败。
05 现状两处解析都是裸调：
`app/incremental/engine.py`（第一遍）与 `app/incremental/second_pass.py`（第二遍）。

**方案**：新增**纯函数** `app/llm/json_utils.py::parse_llm_json(content) -> dict`，
解析顺序：

1. `strip()` 去掉首尾空白；
2. 去掉 Markdown 围栏：匹配 ` ```json ... ``` ` 或 ` ``` ... ``` `
   （大小写不敏感，允许围栏内含换行）；
3. **再兜底一次**：若仍解析失败，取第一个 `{` 到最后一个 `}` 的**平衡括号区间**再试一次
   （应对「前面带一句说明文字」的情况）；
4. 仍失败 → 抛 `LLMOutputInvalid`，**错误消息不含原始响应正文**
   （避免把模型输出里可能夹带的敏感内容写进错误信息与审计）。

**落点与边界**：
- 只替换 05 两处 `json.loads` 的**解析入口**，**不动判定逻辑**：
  结论字段校验、标签分类、丢弃规则、错误码全部保持原样；
- 该函数是**纯函数、无 IO**，可脱离数据库单测；
- 兼容 `MockProvider` 的既有返回（本来就是裸 JSON，行为不变）。

## 7. 接口

### 7.1 大模型配置（`require_system_admin`）

前缀 `/api/admin/llm-providers`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 配置列表（不分页，数量极少）；只返回掩码 |
| POST | `/` | 新建配置（201） |
| PUT | `/{provider_id}` | 更新配置；`api_key` 不传或为 null → 保持原 Key 不变 |
| POST | `/{provider_id}/test` | 连通性测试 |

**POST 入参**

```json
{
  "name": "DeepSeek 生产",
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "sk-xxxx",
  "model": "deepseek-chat",
  "timeout_seconds": 60,
  "is_default": true
}
```

- `name` 非空 ≤ 64 字；重复 → 409 `LLM_PROVIDER_NAME_TAKEN`。
- `base_url` 必须以 `http://` 或 `https://` 开头；入库前去掉尾部 `/`；否则 400 `LLM_PROVIDER_INVALID`。
- `api_key` 非空；否则 400 `LLM_PROVIDER_INVALID`。
- `model` 非空 ≤ 128 字。
- `timeout_seconds` 取值 1~300；越界 → 400 `LLM_PROVIDER_INVALID`。
- `is_default=true` 时，其余配置行的 `is_default` 置 0（同一事务）。

**PUT 入参**（字段全可选，只传要改的）

```json
{
  "name": "DeepSeek 生产",
  "base_url": "https://api.deepseek.com/v1",
  "api_key": null,
  "model": "deepseek-chat",
  "timeout_seconds": 60,
  "status": "active",
  "is_default": true
}
```

- `api_key` 为 `null` 或不传 → **保持原密文与 `last4` 不变**；传非空字符串 → 重新加密并更新 `last4`。
- `status='disabled'` 且该行是默认行 → 服务层把 `is_default` 一并置 0（可能最终没有默认配置 → 降级 Mock）。
- 配置不存在 → 404 `LLM_PROVIDER_NOT_FOUND`。

**响应（GET / POST / PUT 共用）**

```json
{
  "id": 1,
  "name": "DeepSeek 生产",
  "provider_type": "openai_compat",
  "base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-chat",
  "api_key_masked": "sk-****abcd",
  "timeout_seconds": 60,
  "status": "active",
  "is_default": true,
  "last_test_status": "succeeded",
  "last_test_at": "2026-11-17T10:00:00",
  "last_test_error": null,
  "created_at": "2026-11-10T09:00:00",
  "updated_at": "2026-11-17T09:30:00"
}
```

**响应里没有 `api_key` 字段，也没有 `api_key_ciphertext` 字段。**

**连通性测试**

`POST /api/admin/llm-providers/{id}/test`

- 发一条固定 ping prompt（`system="ping"`、`user="ping"`），**不写任何业务表**；
- 成功 → HTTP 200 `{"ok": true, "latency_ms": 812, "model": "deepseek-chat", "message": "连通正常"}`，
  回填 `last_test_status='succeeded'` / `last_test_at`；
- 失败 → **仍返回 HTTP 200** `{"ok": false, "latency_ms": 0, "model": null, "message": "调用大模型超时（超过 1 秒）"}`，
  回填 `last_test_status='failed'` / `last_test_error`（已脱敏）。
  **不把连通性失败当业务异常**——它要让前端能在表单里内联展示错误。
- 无论成败都写一条 `llm_run_logs(task_type='provider_test')`；
- 配置不存在 → 404 `LLM_PROVIDER_NOT_FOUND`；
- 密文无法解密 → 500 `LLM_CONFIG_INVALID`。

### 7.2 提示词模板管理（`require_system_admin`）

前缀 `/api/admin/prompt-templates`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 分页列表，支持 `task_type` / `status` 筛选 |
| GET | `/{template_id}` | 详情（含完整 System / User Prompt） |
| PUT | `/{template_id}` | 编辑 |

**GET `/` 响应**（分页信封 `{items,total,page,page_size}`）

列表项**不返回 Prompt 正文**，只给元信息：

```json
{
  "id": 1,
  "name": "增量分析·第一遍·章节局部",
  "task_type": "incremental",
  "description": "第一遍：逐章节局部比对",
  "version_no": 1,
  "status": "active",
  "updated_at": "2026-11-17T10:00:00"
}
```

**GET `/{id}` 响应**：列表项 + `system_prompt` / `user_prompt` 全文。

**PUT 入参**

```json
{
  "name": "增量分析·第一遍·章节局部",
  "description": "第一遍：逐章节局部比对",
  "system_prompt": "……",
  "user_prompt": "……",
  "status": "active"
}
```

校验与行为：

1. 模板不存在 → 404 `PROMPT_TEMPLATE_NOT_FOUND`。
2. `name` 非空 ≤ 128 字；`system_prompt` / `user_prompt` 非空且各 ≤ 60000 字符；
   非法 → 400 `PROMPT_TEMPLATE_INVALID`。
3. `status` 只允许 `active` / `disabled`；非法 → 400 `PROMPT_TEMPLATE_INVALID`。
4. 同 `task_type` 下 `name` 重复 → 409 `PROMPT_TEMPLATE_NAME_TAKEN`。
5. **版本自增**：`system_prompt` 或 `user_prompt` 与原值不同 → `version_no += 1`；
   只改 `description` / `status` **不**升版本。
6. `task_type` **不可改**（改了等于换了个模板的身份，历史分析对不上）。
7. **不提供新建 / 删除接口**。

### 7.3 只读模板列表（登录用户）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/prompt-templates?task_type=incremental` | 可用模板列表（只给 `status='active'`） |

响应：

```json
{
  "items": [
    {"id": 1, "name": "增量分析·第一遍·章节局部", "task_type": "incremental",
     "version_no": 1, "description": "第一遍：逐章节局部比对"}
  ]
}
```

- 只返回 `id / name / task_type / version_no / description`——**不含 Prompt 正文**（普通成员没有管理权限）。
- `task_type` 可选；不传则返回全部 `active` 模板。

### 7.4 错误码

| code | HTTP | 触发 |
|---|---|---|
| `LLM_PROVIDER_NOT_FOUND` | 404 | 配置不存在 |
| `LLM_PROVIDER_NAME_TAKEN` | 409 | 配置名重复 |
| `LLM_PROVIDER_INVALID` | 400 | URL / Key / 模型 / 超时非法 |
| `LLM_CONFIG_INVALID` | 500 | 密文无法解密（主密钥不对或密文被改） |
| `PROMPT_TEMPLATE_NOT_FOUND` | 404 | 模板不存在 |
| `PROMPT_TEMPLATE_INVALID` | 400 | Prompt 为空 / 超长 / status 非法 |
| `PROMPT_TEMPLATE_NAME_TAKEN` | 409 | 同 task_type 下重名 |

复用：`LLM_CALL_FAILED`（502）、`LLM_OUTPUT_INVALID`（502）、`FORBIDDEN`（403）。

新增错误类进 `app/common/errors.py`，并同步 `__all__`。

### 7.5 审计

| action | target_type | target_id | before / after 记什么 |
|---|---|---|---|
| `llm.provider.create` | `llm_provider` | 配置 ID | after：名称 / base_url / 模型 / 超时 / 状态 / 是否默认 / `api_key_last4` |
| `llm.provider.update` | `llm_provider` | 配置 ID | before + after，同上字段集（**均不含密文与明文**） |
| `prompt_template.update` | `prompt_template` | 模板 ID | before + after：名称 / 描述 / 状态 / 版本号 / System / User Prompt |

- 校验失败的操作**不写审计**（与 01–05 的既有口径一致）。
- 连通性测试**不写审计**（只写运行日志）。
- `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补这 3 条。

## 8. 前端

### 8.1 系统设置页

新增路由 `/admin/settings`，页面 `web/src/pages/AdminSettingsPage.tsx`，两个 Tab。

**Tab 1 · 大模型配置**

- 表格列：名称 / Base URL / 模型 / API Key（掩码）/ 超时 / 状态 / 默认 / 最近测试 / 操作；
- 操作：新增、编辑、测试连通性、设为默认、停用；
- 表单字段：名称、Base URL、API Key（密码框）、模型、超时、是否默认；
  编辑态提示「API Key 留空表示不修改」；
- 测试结果**内联 Alert**：成功显示耗时，失败显示已脱敏原因（`data-testid="llm-test-result"`）；
- Key 列展示 `api_key_masked`。

**Tab 2 · 提示词模板**

- 表格列：名称 / 任务类型 / 版本 / 状态 / 更新时间 / 操作（编辑）；
- 编辑抽屉：名称、描述、状态、System Prompt（TextArea）、User Prompt（TextArea），带字符数；
- 保存后**版本号 +1** 的提示要能看到。

### 8.2 菜单与路由

- `AppLayout.tsx`：`system_admin` 分支追加「系统设置」菜单项；
- `App.tsx` 注册 `/admin/settings` 路由。

### 8.3 05 联动

- `ProjectIncrementalTab.tsx`：模板下拉的数据源从硬编码 `DEFAULT_TEMPLATE_ID = 1`
  改为调用 `GET /api/prompt-templates?task_type=incremental`；
- 下拉无可用模板 → 禁用「发起分析」按钮并提示「请先在系统设置中启用提示词模板」；
- `incrementalMeta.tsx` 的 `DEFAULT_TEMPLATE_ID` / `TEMPLATE_LABEL` 保留为**兜底常量**，
  但正常路径不再使用（接口返回空时也不回退到 1——因为 1 可能已被停用）。

## 9. 验收标准

### AC-105 API Key 绝不明文落库

- **Given** 系统管理员新建一条配置，`api_key='sk-supersecret-1234'`
- **When** 查询数据库 `llm_providers` 行
- **Then** `api_key_ciphertext` **不等于** `'sk-supersecret-1234'`，且 `api_key_last4 == '1234'`
- **Then** 全表 `SELECT` 任意列的拼接结果里**不含** `'sk-supersecret-1234'`
- **Then** 接口响应体、审计 `before_data` / `after_data`、`caplog` 文本中**均不含**该明文
- **Then** 响应只含 `api_key_masked`（形如 `sk-****1234`）

### AC-106 加解密往返与篡改检测

- `encrypt(x)` 再 `decrypt()` 得到 `x`
- 密文被改动一个字符 → `decrypt` 抛 `LLMConfigInvalid`，**消息不含密文也不含明文**
- 换一把主密钥解密旧密文 → 同样抛 `LLMConfigInvalid`
- `mask()` 对 4 位以内的 Key 只返回 `****`

### AC-107 无配置时降级 Mock（**断网全绿的关键**）

- **Given** `llm_providers` 表为空
- **When** 调用 `get_provider(session)`
- **Then** 返回 `MockProvider` 实例，`name == 'mock'`
- **Then** 现有 626 条后端用例与 36 条 e2e **全部通过**，且**零真实网络请求**
- **Then** 发起增量分析时 `incremental_analyses.provider == 'mock'`

### AC-108 有默认配置时使用真实 Provider

- **Given** 存在一条 `status='active'`、`is_default=1` 的配置
- **When** 调用 `get_provider(session)`
- **Then** 返回 `OpenAICompatProvider`，`name == 'openai_compat'`
- **Then** 发起分析时 `incremental_analyses.provider == 'openai_compat'`

### AC-109 默认唯一与降级

- 存在两条 `is_default=1` → **不可能**（唯一索引 `uk_llmprov_default` 拦截，直接报错）
- 把默认行设为 `disabled` → 该行 `is_default` 置 0 → `get_provider` 返回 `MockProvider`
- 把另一行设为默认 → 原默认行 `is_default` 置 0，**全局仍只有一个默认**

### AC-110 超时与异常统一收敛

- `httpx.MockTransport` 抛 `httpx.ReadTimeout` → `LLMCallFailed`（502 `LLM_CALL_FAILED`），消息含「超时」
- 返回 HTTP 401 → `LLMCallFailed`，消息含「鉴权失败」，**且不含 API Key**
- 返回 HTTP 500 → `LLMCallFailed`，消息含 `500`
- 返回体缺 `choices` → `LLMCallFailed`，消息含「结构不合法」
- **任何一种情况下，异常消息里都不出现 API Key**

### AC-111 OpenAI 兼容请求形状

- `OpenAICompatProvider.chat()` 发出的请求：
  - URL 恰为 `{base_url}/chat/completions`
  - Header `Authorization` 恰为 `Bearer <api_key>`
  - Body `model` 等于配置里的模型名
  - Body `messages` 恰为两条：`{"role":"system","content":system}`、`{"role":"user","content":user}`
- 返回体 `choices[0].message.content` 原样作为 `LLMResponse.content`

### AC-112 运行留痕

- 一次分析（第一遍）跑完 → `llm_run_logs` 新增一行：
  `task_type='incremental_first'`、`call_count` = 本次模型调用次数、`latency_ms > 0`、`status='succeeded'`、
  `provider_name` / `model` 与配置一致
- 第二遍跑完 → 新增一行 `task_type='incremental_second'`
- 连通性测试 → 新增一行 `task_type='provider_test'`
- 失败时 `status='failed'`、`error_code='LLM_CALL_FAILED'`、`error_message` 已脱敏
- **表里不出现 token 金额、不出现 Prompt 正文**

### AC-113 配置管理接口

- 列表 / 新建 / 更新按 §7.1 行为；
- 新建重名 → 409 `LLM_PROVIDER_NAME_TAKEN`
- `base_url` 为 `ftp://x` → 400 `LLM_PROVIDER_INVALID`
- `timeout_seconds=0` 或 `301` → 400 `LLM_PROVIDER_INVALID`
- 更新时 `api_key` 不传 → 原密文与 `last4` **不变**
- 更新时 `api_key` 传新值 → 密文变、`last4` 变
- 配置不存在 → 404 `LLM_PROVIDER_NOT_FOUND`
- 非系统管理员 → 403 `FORBIDDEN`
- 审计：`llm.provider.create` / `llm.provider.update` 各落一行，`before/after` 不含明文

### AC-114 连通性测试

- 成功 → HTTP 200 `ok=true`，`last_test_status='succeeded'`，`last_test_at` 有值
- 失败 → **HTTP 200** `ok=false`，`message` 可读且不含 Key，`last_test_status='failed'`，`last_test_error` 有值
- 两种情况都写一条 `llm_run_logs(task_type='provider_test')`
- 配置不存在 → 404 `LLM_PROVIDER_NOT_FOUND`

### AC-115 模板管理接口

- 列表分页、按 `task_type` / `status` 筛选，**列表项不含 Prompt 正文**
- 详情含完整 System / User Prompt
- 编辑 Prompt 正文 → `version_no` **+1**
- 只改 `description` / `status` → `version_no` **不变**
- Prompt 为空 / 超 60000 字 / `status` 非法 → 400 `PROMPT_TEMPLATE_INVALID`
- 同 `task_type` 下重名 → 409 `PROMPT_TEMPLATE_NAME_TAKEN`
- 模板不存在 → 404 `PROMPT_TEMPLATE_NOT_FOUND`
- **没有新建 / 删除接口**（路由不存在，404）
- 非系统管理员 → 403 `FORBIDDEN`
- 审计：`prompt_template.update` 落一行，`before/after` 含 Prompt 正文

### AC-116 只读模板列表与 05 联动

- `GET /api/prompt-templates?task_type=incremental` 只返回 `status='active'` 的模板元信息，不含正文
- 普通成员可访问（登录即可）
- 05 项目页模板下拉**动态渲染**：接口返回 2 条 → 下拉有 2 项
- 接口返回空 → 下拉为空 + 发起按钮禁用 + 提示「请先在系统设置中启用提示词模板」
- 停用某模板后 → 05 下拉不再出现该项

### AC-117 05 三段链路零回归

- 05 的第一遍 / 第二遍 / 产出段**代码零改动**（`git diff` 中 `app/incremental/` 下除 `provider` 依赖注入外无逻辑变更）
- 后端全量用例 **≥ 626 passed**（数量只增不减）
- e2e 全量 **≥ 36 passed**
- 断网环境下（无默认配置）后端全量与 e2e 全绿

### AC-118 配置与文档

- `Settings.llm_secret_key` **必填**：缺失时构造 `Settings` 抛 `ValidationError`（与 `db_dsn` 同口径）
- `.env.example` 增加 `LLM_SECRET_KEY` 说明
- `PROGRESS.md` 记录：迁移 head `0017`、依赖变更（新增 `cryptography`、`httpx` 移到运行时）、主密钥配置方式
- `pyproject.toml`：`cryptography>=43` 进 `dependencies`；`httpx>=0.28` 从 `dev` 移到 `dependencies`

### AC-119 PDF 解析（T84-PDF）

- **Given** 一个**文本型** PDF（含多级标题、正文、表格）
- **When** 上传该 PDF
- **Then** HTTP 201，文档与版本落库
- **Then** `document_chapters` 按 §2.4.2 规则落出章节树：
  标题层级正确（level 1/2/3）、正文归属最近的标题、表格还原成 `a | b` 行
- **Then** 章节树结构与 md / docx 的落库口径**完全一致**（复用 `_insert_chapters`）
- **Given** 一个**损坏 / 非 PDF** 内容（扩展名 `.pdf` 但内容不是 PDF）
- **When** 上传 → **Then** 400 `DOCUMENT_PARSE_FAILED`，不落盘、不落库、不写审计
- **Given** 一个**扫描件**（无文字层）→ **Then** 201，整文单章「全文」，**不报错**
- **Given** 未知扩展名（如 `.xlsx`）→ **Then** 400 `UNSUPPORTED_DOC_TYPE`（**保持不变**）
- 前端：上传控件 `accept` 含 `.pdf`；提示文案改为含 `.pdf`
- `.gitignore` 覆盖 `测试用的需求文档_不提交git/`（`git check-ignore` 实测命中）

### AC-120 JSON 解析容错（Markdown 围栏）

- `parse_llm_json('{"a":1}')` → `{'a': 1}`（**裸 JSON 行为不变**）
- `parse_llm_json('```json\n{"a":1}\n```')` → `{'a': 1}`
- `parse_llm_json('```\n{"a":1}\n```')` → `{'a': 1}`（无语言标记）
- `parse_llm_json('```JSON\n{"a":1}\n```')` → `{'a': 1}`（**大小写不敏感**）
- `parse_llm_json('好的，结果如下：\n{"a":1}')` → `{'a': 1}`（**平衡括号兜底**）
- `parse_llm_json('not a json')` → 抛 `LLMOutputInvalid`，
  **错误消息不含原始响应正文**
- 第一遍（`engine.py`）与第二遍（`second_pass.py`）的模型输出
  **带 Markdown 围栏时也能正常解析出结论 / 裁决**，不再 502
- **判定逻辑零改动**：字段校验、标签分类、丢弃规则、错误码全部保持原样

### AC-121 真实数据端到端联调（L1 / L2 分层）

**L1 · 自动化（进 CI，零真实 socket）**

- **Given** 真实 `.pdf` 与 `.docx` 文件（取自 `测试用的需求文档_不提交git/`）
- **When** 走完整链路：上传 → 解析 → 章节落库 → 建基线 → 发起分析 → 结论落库
- **Then** 章节数、章节标题与样本文件一致；结论落进 `incremental_conclusions`
- **Then** 模型侧用 `httpx.MockTransport` 返回**带 Markdown 围栏的 JSON**，
  链路照样跑通（一条用例同时覆盖 AC-119 / AC-120）
- **Then** 全量 pytest 与 e2e **零真实 socket**（断网红线不被破坏）
- 样本文件缺失 → 用例 **skip**，不影响没这套文档的机器跑全量

**L2 · 真实联调（人工触发，不计入 pytest）**

- **Given** 系统设置页已配好真实 DeepSeek（API Key 存进 `llm_providers` 表，**不写 `.env`**）
- **When** 用真实 `.pdf` 与 `.docx` 走完整链路
- **Then** 结论由真实模型产出并落库；`incremental_analyses.provider == 'openai_compat'`
- **Then** `llm_run_logs` 有对应留痕（次数 / 耗时 / 状态）
- 结果记入 `tasks.md` 的验证记录

## 10. 非功能

- **依赖**：新增 `cryptography>=43`；`httpx>=0.28` 从 dev 移到运行时；
  **T84-PDF 新增 `pdfplumber>=0.11`**（PDF 文本提取）。本期**不引入** `openai` SDK、
  `jsonschema`、异步队列框架、OCR 引擎。
- **超时**：连接 5 秒、读/写用配置里的 `timeout_seconds`（1~300，默认 60）。真实调用**必须有超时**，
  不允许出现无超时的 `httpx.post`。
- **同步执行**：本期仍是同步调用（与 05 一致），不引入后台任务队列。
- **连接复用**：每次 `chat` 新建一个 `httpx.Client`（本期调用量小，不做连接池复用；避免长连接泄漏）。
- **分页**：模板列表用分页信封 `{items,total,page,page_size}`，默认 20 / 上限 100；
  配置列表不分页（数量极少）。
- **可观测**：运行日志只记次数 / 耗时 / 状态 / 错误码，不记 Prompt 与 token 金额。
- **无新增外键**：`llm_run_logs` 的 `analysis_id` / `provider_id` 不建外键——记录必须能留存。

## 11. 依赖与影响

- **05-incremental**：`app/incremental/engine.py` / `second_pass.py` **只改 JSON 解析入口**
  （换成 `parse_llm_json`），判定逻辑零改动；
  `app/llm/provider.py` 的 `get_provider` 签名变化，`router.py` 的 `Depends(get_provider)` 无需改。
- **04-baseline**：零改动。
- **03-documents**（T84-PDF）：`parser.py` 支持 `.pdf`；章节落库口径不变；
  `pyproject.toml` 加 `pdfplumber`；前端 `accept` 与文案；3 处既有测试期望值调整。
- **01-auth**：`require_system_admin` 直接复用。
- **前端**：`AppLayout.tsx` / `App.tsx` 加入口与路由；`ProjectIncrementalTab.tsx` 改模板下拉；
  `api/index.ts` 加类型与 7 个函数；`api/client.ts` 加 7 个错误码中文。
- **迁移**：`0017_llm_providers`，`down_revision="0016"`；downgrade 反序删表。
- **依赖文件**：`pyproject.toml`（`cryptography` 进运行时、`httpx` 移出 dev、`pdfplumber` 进运行时）、
  `.env.example`（加 `LLM_SECRET_KEY`）、`PROGRESS.md`（计数与依赖变更）。
- **验证约定**：每个任务按 `specs/验证约定.md` 第 2 节走「任务 pytest + 全量 pytest + 前台核对 + 截图」。

## 12. 后续期（明确不在本期）

| 期 | 内容 |
|---|---|
| 07 | 测试点分析（PRD 2.4.4）：消费 05 的生效中标签与增量结论，产出测试点与评审流 |
| — | Skill 模式（PRD 2.5）：Skill 包、manifest、schema 校验、失败不回退 |
| — | 项目级供应商绑定、多个供应商路由、超时/重试策略 |
| — | Token 计费与配额、每日次数上限 |
| — | 提示词模板的新建 / 删除 / 版本历史表 / 试运行 |
| — | PDF 扫描件 OCR（本期只做「无文字层 → 整文单章」降级，不引入 OCR 引擎） |
| — | PDF 表格结构化落库（本期还原成 `a | b` 文本行，与 docx 同构） |
