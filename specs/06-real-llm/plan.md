# 06 · 真实大模型接入与提示词模板管理 · 方案

> 规格 [spec.md](./spec.md) ｜ 任务 [tasks.md](./tasks.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)

## 1. 总体思路

05 的链路是通的，唯一缺口在模型侧：`MockProvider` 的默认响应是空结论，
线上跑等于什么都分析不出来。本期只补这一段——**让模型侧从「假」变成「真」，但不改变任何业务语义**。

```
                      ┌─────────────── 无默认配置 ───────────────┐
llm_providers ──▶ get_provider(session) ──┤                            ├─▶ LLMProvider
                      └──── 有默认配置 ────┴──▶ OpenAICompatProvider ─┘        │
                                              ▲                               │
                              app/llm/crypto.py 解密 API Key                  │
                                              │                               │
                                              └─▶ llm_run_logs（次数/耗时/错误）
```

关键取舍：

1. **先降级、后接真**。`get_provider` 的第一分支是「查不到配置 → Mock」。
   这不是降级妥协，而是**安全阀**：没有配置、配置坏了、用户没配就发分析，
   平台仍然能跑（和今天一模一样），不会因为本期的新功能把 05 打挂。
   AC-107 是整个期的地基——它不通过，后面全都不算数。
2. **不做 Skill、不做计费、不碰执行**。这是用户划的红线。Skill 是 PRD 2.5 的完整一摊，
   放进来会让本期从「让 05 能用」变成「半套 Skill 平台」，两头不靠。
3. **加密必须用成熟库**。`bcrypt` 是单向的，存不了；自己写 AES 是自造漏洞。
   本期唯一新增依赖 `cryptography`，用 Fernet；主密钥来自必填环境变量 `LLM_SECRET_KEY`，
   由 `sha256` 派生，任意长度字符串都能用，不给用户添麻烦。
4. **配置读取不缓存**。每次 `get_provider` 都查一次库。单表 + 唯一索引，查询成本可忽略；
   换来的是「管理员改完配置立即生效」，不用处理缓存一致性和失效时机。
5. **失败收敛到一个错误码**。超时、连接失败、401、500、响应结构不对——
   对前端来说都是同一件事：「模型调不动」。统一 `LLM_CALL_FAILED`（既有错误码，502）。
   消息给可读原因（「超时」「鉴权失败」「HTTP 500」），但**永远不带 Key**。
6. **运行日志只记「慢不慢、错没错」**。不记 Prompt 正文、不记模型原文、不记 token 金额。
   用户要的是「模型变慢或报错」的可观测性，那就精确提供这三样，多一分都不记。
7. **PDF 解析单独立项（T84-PDF）**。它是 03 的改动、依赖 `pdfplumber`，
   与 06 的加密 / Provider / 迁移 `0017` 没有技术耦合，却**必须排在 T87 之前**
   （T87 的验收要用真实 `.pdf` 走端到端）。混进 T84 会同时破坏两条红线：
   06 的「不顺手修无关模块」与 T84 的「只做模型侧底座」。
8. **JSON 解析容错是「入口加固」不是「逻辑改动」**。真实模型返回 Markdown 围栏是**必然**，
   不是「可能」。容错只放宽「怎么把响应读成 JSON」，不放宽「什么算合法结论」——
   后者一个字节都不动（AC-120）。
9. **真实联调分 L1 / L2 两层**。L1 用真实文件 + `MockTransport` 进 CI（零 socket）；
   L2 用真实模型 + 真实文件人工跑一次、记进验证记录。
   这样「真实 PDF 端到端」既能被自动化断言，又不破坏断网红线。

## 2. 数据层

### 2.1 迁移

`migrations/versions/0017_llm_providers.py`，`down_revision = "0016"`。

upgrade 顺序：`llm_providers` → `llm_run_logs`。
downgrade 反序**直接删表**（沿用 04/05 的写法：不先删索引，避开 MySQL 1553 依赖错误）。

沿用既有写法：`mysql_default_charset="utf8mb4"`、`mysql_collate="utf8mb4_0900_ai_ci"`、
`mysql_engine="InnoDB"`，所有 `CheckConstraint` 与索引**显式命名**。

### 2.2 「全局唯一默认」怎么保证

两条路：

| 方案 | 做法 | 评价 |
|---|---|---|
| A. 唯一索引 + 生成列 | `default_key` STORED 生成列 `CASE WHEN is_default=1 THEN 1 ELSE NULL END`，唯一索引挂它 | ✅ 库层保证，绕不过去 |
| B. 服务层互斥 | 事务内先把其他行置 0 再置目标行 | ⚠️ 依赖服务层，漏一处就出双默认 |

**两个都做**：生成列 + 唯一索引是硬保证（AC-109 的「两条默认不可能」靠它），
服务层的互斥逻辑保证「不会出现两条默认」之外还不会撞唯一索引报错。

> 为什么用生成列而不是「部分唯一索引」：MySQL 不支持带 `WHERE` 的部分唯一索引。
> 生成列 + 普通唯一索引是 MySQL 5.7+ 的标准做法，04 的 `baseline_labels.active_key`
> 已经是同一套路（见 [app/models/baseline.py](file:///d:/aitest_copilot/app/models/baseline.py#L265-L269)），照抄即可。

### 2.3 模型

`app/models/llm.py` 两个模型：`LLMProviderConfig` / `LLMRunLog`。
注册到 `app/models/__init__.py` 的 import 与 `__all__`（**不改名**避免与 `app/llm/provider.py` 的
`LLMProvider` 混淆；表名与类名分别是 `llm_providers` / `LLMProviderConfig`）。

`llm_run_logs` **不建任何外键**：`analysis_id` / `provider_id` 只是快照引用，
配置被停用、记录被删都不该让日志丢失。

`prompt_templates` 表**不迁移、不加列**——列表与编辑只用现有字段。

### 2.4 种子

无种子数据。`llm_providers` 空表 = 平台出厂即 Mock 降级（AC-107 的天然前提）。

## 3. 加密层

`app/llm/crypto.py`：

```python
def _fernet() -> Fernet:
    raw = get_settings().llm_secret_key.encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))
```

三个公开函数：`encrypt` / `decrypt` / `mask`。

- `decrypt` 失败（`InvalidToken`）→ 抛 `LLMConfigInvalid`，
  消息固定为「大模型配置无法解密，请检查 LLM_SECRET_KEY」——
  **不含密文、不含明文、不含原始异常**（异常里可能有密文片段）。
- `mask`：`sk-****abcd`；长度 ≤ 4 → `****`。

主密钥必填（`Settings.llm_secret_key: str = Field(..., min_length=1)`），
缺失时构造 `Settings` 即失败——与 `db_dsn` 同一口径，不允许带空密钥启动。

> 为什么必填而不是给 dev 默认值：默认值等于「密钥是公开的」，
> 生产环境忘了配就会用一把全世界都知道的密钥去加密 API Key。宁可启动失败。

### 3.1 明文边界怎么测

「不出明文」不能靠人眼 review。测试策略：

1. **库层**：断言 `api_key_ciphertext != 明文`，且把整行所有列拼起来不含明文；
2. **响应层**：断言响应体不含 `api_key` / `api_key_ciphertext` 字段，且全文不含明文；
3. **审计层**：断言 `before_data` / `after_data` 序列化后不含明文；
4. **日志层**：用 `caplog` 捕获整个调用链的日志，断言不含明文；
5. **异常层**：造超时 / 401 / 500 三种失败，断言异常消息不含明文。

## 4. Provider 层

### 4.1 工厂改造

现状（[app/llm/provider.py](file:///d:/aitest_copilot/app/llm/provider.py)）：

```python
def get_provider() -> LLMProvider:   # 进程内 Mock 单例
```

改造后：

```python
def get_provider(session: Session = Depends(get_db)) -> LLMProvider:
    config = load_default_config(session)      # active + is_default=1
    if config is None:
        return _mock_singleton()                # 与今天完全一致
    return OpenAICompatProvider.from_config(config)
```

**兼容性关键**：`get_provider` 一直是 FastAPI 依赖，测试通过
`dependency_overrides[get_provider] = lambda: mock` 覆盖它。
覆盖后 FastAPI **不会执行原函数体**，所以签名变化对现有 626 条用例零影响。

唯一需要改的现有用例是 `test_ac_84_get_provider_is_mock_singleton`——
它直接调用 `get_provider()`，现在需要传 session。改成显式断言「无配置时返回 Mock 单例」，
**测试总数不变**（626 条里改 1 条断言方式，不删）。

### 4.2 `OpenAICompatProvider`

```python
class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, *, base_url, api_key, model, timeout_seconds,
                 transport: httpx.BaseTransport | None = None):
        ...

    def chat(self, req: LLMRequest) -> LLMResponse:
        # POST {base_url}/chat/completions
        # Header: Authorization: Bearer <api_key>
        # Body:   {"model": model, "messages": [
        #              {"role": "system", "content": req.system},
        #              {"role": "user",   "content": req.user}]}
        # 解析:   choices[0].message.content
```

异常收敛表见 spec §6.2。实现要点：

- **超时必填**：`httpx.Timeout(connect=5.0, read=timeout_seconds, write=timeout_seconds, pool=5.0)`，
  构造 `httpx.Client(timeout=..., transport=transport)`；
- **不传 temperature / max_tokens**：不同供应商默认值差异大，传固定值反而制造行为不一致；
- **`usage` 透传但不落库**：解析 `payload.get("usage")`，没有就留 0；
- **`raw` 回带请求**：沿用 `MockProvider` 的约定（`{"request": req.model_dump(), "index": n}`），
  这样 05 的既有断言「Prompt 确实从库里来」在真实 Provider 下同样成立；
- **每次 `chat` 新建 Client**：本期调用量小，不做连接池复用，避免长连接泄漏与跨线程问题。

### 4.3 为什么用 `httpx` 而不是 `openai` SDK

- `openai` SDK 会带来自己的重试、重试间隔、代理、异步体系，
  我们只要「一次 POST + 一次 JSON 解析」，SDK 太重；
- `httpx` 已是项目 dev 依赖，只需从 dev 移到运行时；
- `httpx.MockTransport` 让测试**不产生真实 socket**，这是断网全绿的前提。

### 4.4 `MockProvider` 零改动

`app/llm/mock.py` **一个字都不改**：默认响应、`SECOND_PASS_SYSTEM_PREFIX`、
`queue`、`calls`、`raw` 全部保留。它既是「无配置时的降级目标」，
也是 05 全部既有用例的依赖。

### 4.5 JSON 解析容错（`app/llm/json_utils.py`）

真实模型返回带 Markdown 围栏是**必然**事件，不容错则 T87 一接真模型就跑不通。
但容错的位置必须在**最窄的地方**——只放宽「怎么读」，不放宽「什么算合法」。

```python
def parse_llm_json(content: str) -> Any:
    """把模型输出读成 JSON。容错 Markdown 围栏与前置说明文字。"""
```

解析顺序（**只做这四步，不做更多**）：

1. `content.strip()`；
2. 去围栏：正则 ```` ```(?:json)?\s*(.*?)\s*``` ````（`re.S`，`json` 大小写不敏感）；
3. 兜底：第一个 `{` 到最后一个 `}` 的平衡区间再试一次（应对「前面带一句说明」）；
4. 仍失败 → 抛 `LLMOutputInvalid("模型返回不是合法 JSON")`，
   **消息里不带原始响应正文**。

> **为什么不做「智能修复」**（补引号、截断补全、JSON5 容错）：那些会掩盖模型输出的真实问题，
> 让「模型返回了坏 JSON」变成「平台悄悄改对了」，排查时更难定位。
> 围栏与前置说明是**格式噪声**，去掉它是还原原文；补引号是**猜测**，不做。

**落点**：`app/incremental/engine.py`（第一遍）与 `app/incremental/second_pass.py`（第二遍）
的 `json.loads(response.content)` 两处，换成 `parse_llm_json(response.content)`。
两处的**后续判定逻辑一个字节都不动**——字段校验、标签分类、丢弃规则、错误码全部保持原样。

## 4.6 PDF 解析（T84-PDF）

### 4.6.1 为什么用 `pdfplumber`

实测样本 PDF（`Matrix系统说明书_基础需求文档.pdf`，8 页、2508 字、**文本型**）：

| 候选 | 提取字符数 | 拿到字号 | 表格 | 结论 |
|---|---|---|---|---|
| `pdfplumber` | 2508 | ✅ | ✅ | **采用** |
| `pypdf` | 2746（噪声多） | ❌ | ❌ | 不用 |

**字号是决定性因素**：拿到字号才能用规则切章节，从而 PDF **不必**为 LLM 拆解付出成本。
`pypdf` 拿不到字号，PDF 就只能走「整文输入 + LLM 拆解」——复杂度与成本都上一个台阶。

> 附带好处：`pdfplumber` 的依赖链里带 `cryptography`，正好是 T84 要用的加密库。

### 4.6.2 实现落点

```
app/documents/parser.py
  ├─ SUPPORTED_SUFFIXES 加 ".pdf"
  ├─ parse() 分派：suffix == ".pdf" → _parse_pdf(data)
  └─ _parse_pdf(data):
       1. pdfplumber.open(BytesIO(data))，异常 → DocumentParseFailed
       2. 逐页 collect_words(extra_attrs=['size'])
       3. 按 top ±2pt 容差聚成行，行字号 = 行内最大字号
       4. 全文字号分布：众数 = 正文字号；> 众数+0.6pt 的字号 = 标题档（降序 → level 1..N）
       5. 判标题：字号 ∈ 标题档 且 命中编号正则 且 长度 ≤ 40
       6. 用现成的 _TreeBuilder 建树（与 md/docx 完全同构）
       7. find_tables() 还原成 "a | b" 行
       8. 一字未提取到 → 整文单章「全文」（扫描件降级，不报错）
```

**关键点：复用 `_TreeBuilder`**。这样 PDF 的章节树与 md / docx **天然同构**，
落库继续走 `app/documents/service.py::_insert_chapters`（**零改动**），
05 的分析链路也**零改动**。

### 4.6.3 编号正则

```python
_HEADING_NUM = re.compile(r"^(第[一二三四五六七八九十百零〇\d]+[章篇部]|\d+(\.\d+)+)")
```

样本 PDF 实测切出 6 章 / 20 节 / 6 小节，**无错切、无漏章**。

> **为什么不只靠字号**：样本 PDF 里 14.6pt 的小节标题是 `2.4.2上传功能`，
> 而 17.1pt 的节标题是 `2.4功能描述`——纯字号能分出档位，
> 但**编号正则**才能排除「正文里恰好是大字号的情况」。两个条件都满足才判标题。

### 4.6.4 错误码归属

| 场景 | 错误码 |
|---|---|
| 扩展名未知（`.xlsx`） | `UNSUPPORTED_DOC_TYPE`（**保持不变**） |
| 扩展名 `.pdf` 但内容损坏 | `DOCUMENT_PARSE_FAILED`（复用既有码，不新增） |
| 扫描件（无文字层） | **不报错**，整文单章 |

> 「PDF 不支持」不再是一个错误码——`UNSUPPORTED_DOC_TYPE` 回归它本来的语义：
> **不支持的扩展名**。这正是 PRD 2.4.1 要的 docx/pdf/md/txt 四种都支持。

## 5. 服务层

新建包 `app/llm_admin/`：

```
app/llm_admin/
  __init__.py
  schemas.py    请求 / 响应模型
  crypto.py     → 放 app/llm/crypto.py（与 Provider 同层，见 §3）
  provider_service.py   配置 CRUD + 默认互斥 + 连通性测试
  template_service.py   模板列表 / 详情 / 编辑（版本自增）
  router.py     /api/admin/llm-providers + /api/admin/prompt-templates
```

### 5.1 配置 CRUD（`provider_service.py`）

```
create_provider(session, payload, actor):
  1. 校验 name / base_url / api_key / model / timeout_seconds → LLM_PROVIDER_INVALID
  2. name 重复 → LLM_PROVIDER_NAME_TAKEN
  3. api_key_ciphertext = encrypt(payload.api_key)
     api_key_last4 = payload.api_key[-4:]
  4. insert（is_default=1 时先清其他行的 is_default）
  5. write_audit("llm.provider.create", target_type='llm_provider', target_id=新ID,
                 after_data={...不含密文...})
  6. commit
```

```
update_provider(session, provider_id, payload, actor):
  1. 配置不存在 → LLM_PROVIDER_NOT_FOUND
  2. 逐字段校验（name 重复 → LLM_PROVIDER_NAME_TAKEN）
  3. api_key 为空/None → 密文与 last4 保持不变
     api_key 非空 → 重新 encrypt + 更新 last4
  4. status='disabled' 且是默认行 → is_default 置 0
  5. is_default=True → 清其他行的 is_default
  6. write_audit("llm.provider.update", before_data=..., after_data=...)
  7. commit
```

> **默认互斥的实现顺序**：`is_default=True` 时先 `UPDATE ... SET is_default=0 WHERE id != :id`，
> 再把目标行置 1。同一事务内完成，不会撞唯一索引。
> 若目标行原本就是默认且没传 `is_default`，不动它。

### 5.2 连通性测试（`provider_service.py`）

```
test_provider(session, provider_id, actor):
  1. 配置不存在 → LLM_PROVIDER_NOT_FOUND
  2. 解密失败 → LLM_CONFIG_INVALID
  3. provider = OpenAICompatProvider.from_config(config)
  4. t0 = now(); 尝试 provider.chat(ping)
     成功 → ok=True, latency_ms=(now-t0), message="连通正常"
     失败 → ok=False, latency_ms=(now-t0), message=脱敏后的原因
  5. 回填 last_test_status / last_test_at / last_test_error
  6. 写一条 llm_run_logs(task_type='provider_test')
  7. return {ok, latency_ms, model, message}   ← 永远 HTTP 200
```

**为什么失败也返回 200**：连通性测试是「表单里的一个按钮」，
用户要看到的是「连不上，因为超时」而不是一个 502 错误页。
业务错误（配置不存在）仍然走 404。

### 5.3 模板编辑（`template_service.py`）

```
update_template(session, template_id, payload, actor):
  1. 模板不存在 → PROMPT_TEMPLATE_NOT_FOUND
  2. 校验 name / system_prompt / user_prompt / status → PROMPT_TEMPLATE_INVALID
  3. 同 task_type 下 name 重复（排除自己）→ PROMPT_TEMPLATE_NAME_TAKEN
  4. 正文变化判定：
       system_prompt != 旧值 或 user_prompt != 旧值 → version_no += 1
       只改 description / status → version_no 不变
  5. task_type 不可改（payload 里根本没有这个字段）
  6. write_audit("prompt_template.update", before_data=..., after_data=...)
  7. commit
```

**版本自增的意义**：05 的分析记录快照了 `template_version`，
正文改了要能看出「这次分析用的是第几版文案」。不建版本表，靠版本号 + 审计留痕。

### 5.4 05 的运行留痕接入

`incremental/service.py` 的 `create_analysis` 与 `run_second_pass`：
在跑第一遍 / 第二遍前后记录 `t0`，跑完写一条 `llm_run_logs`：

- `task_type`：`incremental_first` / `incremental_second`；
- `call_count`：Provider 的调用次数（`OpenAICompatProvider` 与 `MockProvider` 都维护 `calls` 计数，
  跑完取 `len(provider.calls) - 跑前基线`）；
- `latency_ms`：墙钟耗时；
- `status` / `error_code` / `error_message`：跟随本次任务的成败；
- `provider_name` / `model`：`provider.name` 与配置里的模型名。

> `call_count` 的取法：跑之前记 `len(provider.calls)`，跑完相减。
> `MockProvider` 已有 `calls`，`OpenAICompatProvider` 同样维护 `calls` 列表（与 Mock 同契约）。

## 6. 接口层

`app/llm_admin/router.py` 两个 router，都挂 `require_system_admin`：

```
router_providers   prefix="/api/admin/llm-providers"
router_templates   prefix="/api/admin/prompt-templates"
```

另加一个**只读** router（`app/llm_admin/templates_router.py` 或同一文件另一个 router）：

```
router_templates_read  prefix="/api/prompt-templates"   → current_user
```

注册进 `app/main.py`。

### 6.1 响应模型要点

- `LLMProviderOut` **没有** `api_key` / `api_key_ciphertext` 字段，
  只有 `api_key_masked`（由服务端 `mask()` 算好）；
- `PromptTemplateBriefOut`（列表项）**没有** `system_prompt` / `user_prompt`；
- `PromptTemplateDetailOut`（详情）才有正文。

> 「响应模型里根本不定义敏感字段」比「定义了但置空」更安全——
> 以后有人加字段也不会顺手把密文带出去。

### 6.2 分页

模板列表复用 `app/baselines/schemas.py` 的 `Page[T]`（05 已这么做，不另写一份）。
配置列表**不分页**（数量极少），直接返回 `list[LLMProviderOut]`。

## 7. 前端

```
web/src/pages/AdminSettingsPage.tsx      主页面（两个 Tab）
web/src/pages/settings/LlmProviderPanel.tsx   Tab1：大模型配置
web/src/pages/settings/PromptTemplatePanel.tsx  Tab2：提示词模板
```

按 05 的经验（`ProjectIncrementalTab` 拆成 Tab / Drawer / meta 三个文件才控住行数），
主页面只做 Tab 骨架，两个 Panel 各自独立。

- `AppLayout.tsx`：`system_admin` 分支追加 `{ key: '/admin/settings', label: '系统设置' }`；
- `App.tsx`：注册 `/admin/settings` 路由；
- `api/index.ts`：加 `/* ---- 真实大模型与模板（06） ---- */` 分节，7 个函数 + 类型；
- `api/client.ts`：加 7 个错误码中文；
- `ProjectIncrementalTab.tsx`：模板下拉改动态拉取。

`data-testid` 命名沿用 05 的「区域-动作-目标」：
`llm-provider-create-btn`、`llm-provider-test-btn-{id}`、`llm-test-result`、
`prompt-template-edit-btn-{id}`、`prompt-template-save-btn`、`incremental-template-select`。

## 8. 任务拆分

见 [tasks.md](./tasks.md)：T84-PDF / T84 / T85 / T86 / T87。

```
T84-PDF 03 支持 PDF 解析 ──▶ T84 配置落库 + 加密 + Provider ──▶ T85 配置管理接口 + 模板管理接口
   （03 的改动，独立提交）             │                                      │
                                     └──────────────▶ T86 05 接入（运行留痕 + 动态模板下拉）
                                                            │
                                                            └──────────────▶ T87 前端系统设置页 + 收尾
                                                                                  │
                                                              L1 自动化端到端 ─────┘
```

依赖理由：

- **T84-PDF** 必须**排在最前**：T87 的验收要拿真实 `.pdf` 走端到端，
  PDF 不支持这条验收做不了；它又是 03 的改动，独立提交不污染 06 的模型侧边界；
- **T84** 产出可测的底座（表约束、加解密、Provider 请求形状），
  T85 才有东西可断言；
- **T85** 只做接口，不碰 05 的业务流，出问题不会连累 05；
- **T86** 把新能力接进 05（运行留痕 + 模板下拉），此时接口已稳定；
- **T87** 前端 + 全量收尾，把「文档 / 依赖 / 迁移 head」一次对齐，
  并补 L1 自动化端到端与 L2 真实联调记录。

## 8.1 真实联调的分层（L1 / L2）

「断网红线：任何一条测试都不允许产生真实 socket」与
「T87 验收必须用真实 .pdf/.docx 走完整链路」这两条要求，
靠**分层**同时满足，而不是二选一。

| 层 | 文件来源 | 模型侧 | 网络 | 是否进 pytest |
|---|---|---|---|---|
| **L1 自动化** | **真实** `.pdf` / `.docx` | `httpx.MockTransport` 返回**带 Markdown 围栏的 JSON** | ❌ 零 socket | ✅ 进 |
| **L2 人工联调** | **真实** `.pdf` / `.docx` | **真实** DeepSeek（Key 存 `llm_providers` 表） | ✅ 真网络 | ❌ 不进 |

**L1 的设计要点**：

- 真实文件从 `测试用的需求文档_不提交git/` 读（已 gitignore）；
- 文件缺失 → `pytest.skip`，**不影响**没这套文档的机器跑全量；
- MockTransport 返回带围栏的 JSON → **一条用例同时覆盖 AC-119（PDF）与 AC-120（容错）**；
- 断言「章节数 / 章节标题与样本一致」+「结论落进 `incremental_conclusions`」。

**L2 的设计要点**：

- API Key **走系统设置页存进 `llm_providers` 表**（密文），**不写进 `.env`**——
  `.env` 虽已 gitignore，但仍可能被备份 / 粘贴到工单 / 误传；
  只有「平台自己的主密钥 `LLM_SECRET_KEY`」才进 `.env`（它不是供应商凭据）；
- 人工跑一次，结果记入 `tasks.md` 的验证记录表。

## 9. 风险与回退

| 风险 | 概率 | 应对 |
|---|---|---|
| 引入真实网络调用后，测试偷偷联网导致断网全红 | 中 | Provider 构造参数带 `transport`，测试一律传 `httpx.MockTransport`；`AC-107` 显式断言无配置时降级 Mock |
| `LLM_SECRET_KEY` 必填导致老环境启动失败 | 中 | 同步 `.env` / `.env.example` / `PROGRESS.md`；`dev_check.py` 增加一项检查（缺失则 `[FAIL]` 提示） |
| 密文被改 / 主密钥不对时静默降级 Mock | 低 | **不降级**，抛 `LLM_CONFIG_INVALID`（500）——配置坏了必须让人知道 |
| 默认互斥漏处理导致唯一索引冲突 | 低 | 生成列 + 唯一索引双保险；服务层先清后置 |
| `httpx` 移到运行时依赖后打包遗漏 | 低 | `pyproject.toml` 同步改；`dev_check.py` 可加一条导入检查 |
| 05 的既有用例因 `get_provider` 签名变化而红 | 低 | 依赖覆盖机制天然规避；只需改 1 条直接调用 `get_provider()` 的用例 |
| 前端把 API Key 打到 console / 错误提示里 | 低 | Key 用密码框；前端不回显明文；后端响应无 `api_key` 字段 |
| 真实模型返回慢导致请求超时 | 中 | 超时可配（1~300 秒，默认 60）；失败统一 `LLM_CALL_FAILED`；运行日志记 `latency_ms` 便于定位 |
| 06 顺手改了 05 的业务逻辑 | 低 | 本期红线明确写「05 判定逻辑零改动」；收尾用 `git diff` 核对 `app/incremental/` |
| **真实模型返回 Markdown 围栏导致整次分析 502** | **高** | **T84 加 `parse_llm_json` 容错**（§4.5）；L1 用带围栏的 MockTransport 响应覆盖 |
| **PDF 是扫描件（无文字层）→ 章节全丢** | 中 | 降级成整文单章「全文」**不报错**；OCR 明确留到后续期（spec §12） |
| PDF 标题字号不统一导致切分乱 | 中 | 字号分档 + 编号正则**双条件**；切不出标题时整文单章，不硬猜 |
| `pdfplumber` 依赖较重（带 pdfminer.six / Pillow） | 低 | 实测 8 页 0.13s，远低于上传限制；PDF 已是核心需求来源，值得 |

## 10. 不做什么（再次确认，避免范围蔓延）

- 不做 Skill 双轨制（manifest / schema / 回退开关）；
- 不做 Token 计费、配额、每日次数上限；
- 不碰自动化执行；
- 不做模板新建 / 删除 / 版本历史表 / 试运行；
- 不做项目级供应商绑定与多供应商路由；
- 不把 API Key 写到 `system_settings`、日志、审计或任何响应里；
- **不改 05 的判定逻辑与业务语义**（只放宽 JSON 解析入口，见 §4.5）；
- 不做 PDF 扫描件 OCR、不做 PDF 表格结构化落库（本期还原成文本行）；
- 不顺手修 04 的来源类型下拉、清除原因枚举、xdist flaky。
