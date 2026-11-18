# 06 · 真实大模型接入与提示词模板管理 · 任务清单

> 规格 [spec.md](./spec.md) ｜ 方案 [plan.md](./plan.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)

## 执行约定

1. 每个任务开跑前先 `.\.venv\Scripts\python.exe scripts\dev_check.py`，有 `[FAIL]` 先修环境。
2. 定向用例跑 `-k ac_XX`，通过后再跑全量（**串行**，避免 `tests/projects/` 的既有 xdist flaky）。
   全量基线 **626 passed**，数量只增不减。
3. 改了前端就 `cd web; npm run build`；有前台交互就补 e2e 用例并截图到 `.screenshots/T8x/`。
4. 每个任务一个提交，提交信息写清「做了什么 / 为什么」。
5. **本期红线**（违反即返工）：
   - **不做 Skill 双轨制**（无 Skill 包 / manifest / schema 校验 / 回退开关）；
   - **不做 Token 计费 / 配额 / 每日次数上限**；
   - **绝不碰自动化执行模块**；
   - **API Key 绝不明文落库**，且不出现在响应 / 审计 / 日志 / 异常 / 运行日志里；
   - **不做模板新建 / 删除**（只做列表 + 编辑）；
   - **不改 05 的判定逻辑与业务语义**——`app/incremental/` 下除「JSON 解析入口换成
     `parse_llm_json`」与依赖注入外，零逻辑改动；
   - **不引入无超时的网络调用**；
   - 不顺手修无关模块（04 的来源类型下拉、清除原因枚举、xdist flaky）。
6. **断网红线**：任何一条测试都**不允许产生真实 socket**。
   真实 Provider 的测试一律用 `httpx.MockTransport`。
7. 测试名带 AC 编号（`test_ac_105_api_key_never_plaintext`）。
8. **每个任务一个提交**，提交信息写清「做了什么 / 为什么」。

> **红线澄清（2026-11-17 用户裁决）**：
> 第 5 条的「不改 05」指的是**判定逻辑与业务语义**不变。
> 真实模型必然返回带 Markdown 围栏的 JSON，不容错则整次分析直接 502——
> 因此**允许且必须**把 05 两处 `json.loads` 换成容错解析入口（`parse_llm_json`）。
> 除解析入口外，05 的字段校验、标签分类、丢弃规则、错误码全部保持原样（AC-120）。

## 前置条件

| 项 | 状态 |
|---|---|
| 01–05 模块 | T01–T83 已验收 |
| 后端基线 | **626 passed**（2026-11-17，T83 后；e2e 默认 `-m "not e2e"`） |
| e2e 基线 | **36 passed** |
| 前端 | `D:\aitest_copilot\web`；侧边栏有「我的项目 / 可申请项目 / 我的申请 / 全局申请 / 用户管理」 |
| 数据库迁移 head | `0016`（06 建 `0017`；**T84-PDF 不动迁移**） |
| 现有依赖 | `httpx` 在 dev 组（本期移到运行时）、`cryptography` 本期新增、**`pdfplumber` 在 T84-PDF 新增** |
| 环境变量 | **新增必填 `LLM_SECRET_KEY`**（`.env` / `.env.example` 同步） |
| 测试样本 | `测试用的需求文档_不提交git/`（.pdf + .docx + .md），**已被 `.gitignore` 覆盖** |

## 任务

- [x] **T84-PDF · 03 模块支持 PDF 解析（本期排头兵）**
  - 为什么排最前：T87 的验收要拿真实 `.pdf` 走完整端到端，PDF 不支持就做不了。
  - 为什么单独立项：03 的改动与 06 的模型侧无技术耦合，混进 T84 会同时破坏
    「不顺手修无关模块」与「T84 只做模型侧底座」两条红线（见 plan §8）。
  - 内容：
    - `pyproject.toml`：`pdfplumber>=0.11` 进 `dependencies`。
    - `app/documents/parser.py`：`SUPPORTED_SUFFIXES` 加 `.pdf`；
      新增 `_parse_pdf(data)`（提取 → 字号分档 → 编号正则判标题 → 表格还原 →
      复用 `_TreeBuilder` 建树 → 扫描件整文降级）；
      损坏 PDF → `DocumentParseFailed`。
    - `app/documents/service.py` **零改动**（复用 `_insert_chapters`，章节树天然同构）。
    - `app/common/errors.py` **零改动**（`UNSUPPORTED_DOC_TYPE` 回归「未知扩展名」语义）。
    - 前端 `web/src/pages/ProjectDocumentsTab.tsx`：`accept` 加 `.pdf`、提示文案改；
      `web/src/api/client.ts`：`UNSUPPORTED_DOC_TYPE` 文案改。
    - `tests/documents/test_parser.py`：**改** 1 处既有期望
      （`("需求.pdf", b"%PDF-1.4", UnsupportedDocType)` → 损坏 PDF 抛 `DocumentParseFailed`）。
    - `tests/documents/test_upload.py`：**改** 1 处既有用例（PDF 不再是 400，改成上传成功）。
    - `tests/e2e/test_documents_ui.py`：**改** 1 处既有用例（PDF 从「被拒」改成「上传成功」）。
  - 产出：AC-119 可断言。
  - 验证：
    - `tests/documents/test_parser.py`——新增 PDF 用例：多级标题切树 / 正文归属 /
      表格还原 / 扫描件降级 / 损坏 PDF 报错；
    - `tests/documents/test_upload.py`——PDF 上传成功 → 章节落库；
    - `tests/e2e/test_documents_ui.py`——前台传 `.pdf` → 文档出现在列表；
    - 后端全量 **≥ 626 passed**（串行）；e2e 全量 **≥ 36 passed**；`npm run build` 通过。
  - 前台：文档 Tab 传 `.pdf` → 列表出现文档、版本数 +1；截图 `.screenshots/T84PDF/`。

- [x] **T84 · 配置落库 + 密钥加密 + 动态 Provider + JSON 容错**（2026-11-18 完成）
  - 内容：
    - `pyproject.toml`：`cryptography>=43` 进 `dependencies`；`httpx>=0.28` 从 `dev` 移到 `dependencies`。
    - `app/common/config.py`：`Settings.llm_secret_key: str = Field(..., min_length=1)`（**必填**）。
    - `.env.example` 增加 `LLM_SECRET_KEY` 说明；`.env` 同步补上（本地开发用，随机生成）。
    - `app/llm/json_utils.py`：**纯函数** `parse_llm_json(content)`——
      剥 Markdown 围栏（` ```json ` / ` ``` `，大小写不敏感）+ 平衡括号兜底；
      失败抛 `LLMOutputInvalid` 且**消息不含原始响应正文**。
    - `app/incremental/engine.py` 与 `app/incremental/second_pass.py`：
      两处 `json.loads(response.content)` 换成 `parse_llm_json(response.content)`，
      **判定逻辑零改动**。
    - `app/models/llm.py`：`LLMProviderConfig`（`llm_providers`）与 `LLMRunLog`（`llm_run_logs`），
      字段 / 索引 / CheckConstraint 严格对齐 spec §4；
      `default_key` STORED 生成列 + `uk_llmprov_default` 唯一索引；
      注册到 `app/models/__init__.py` 的 import 与 `__all__`。
    - `migrations/versions/0017_llm_providers.py`，`down_revision="0016"`；
      两表按顺序建、`downgrade` 反序直接删表；**无种子数据**。
    - `app/llm/crypto.py`：`encrypt` / `decrypt` / `mask`；
      Fernet 密钥由 `sha256(llm_secret_key)` 派生；解密失败抛 `LLMConfigInvalid`（消息不含密文与明文）。
    - `app/llm/openai_compat.py`：`OpenAICompatProvider`
      （`name='openai_compat'`、`calls` 列表、`transport` 可注入、`httpx.Timeout`、
      异常统一收敛 `LLMCallFailed`、`raw` 回带请求）。
    - `app/llm/provider.py`：`get_provider(session: Session = Depends(get_db))` 改造——
      查库取默认配置；无配置 → 进程内 Mock 单例；有配置 → `OpenAICompatProvider`；
      解密失败 → `LLMConfigInvalid`（**不降级**）。
    - `app/common/errors.py`：新增 `LLMProviderNotFound` / `LLMProviderNameTaken` /
      `LLMProviderInvalid` / `LLMConfigInvalid` / `PromptTemplateNotFound` /
      `PromptTemplateInvalid` / `PromptTemplateNameTaken`，同步 `__all__`。
  - 产出：AC-106 / AC-107 / AC-108 / AC-109 / AC-110 / AC-111 / **AC-120** 在底层可断言。
  - 验证：
    - `tests/llm/test_crypto.py`——AC-106 往返 / 篡改检测 / 换密钥 / 掩码规则；
    - `tests/llm/test_openai_compat.py`——AC-111 请求形状（URL / Header / Body / 解析）、
      AC-110 异常收敛（超时 / 401 / 500 / 结构非法）；
    - `tests/llm/test_provider_factory.py`——AC-107 无配置降级 Mock、
      AC-108 有配置走真实 Provider、AC-109 默认唯一与停用降级；
    - `tests/llm/test_models.py`——表约束（生成列 / 唯一索引 / CheckConstraint）；
    - `tests/llm/test_json_utils.py`——**AC-120** 围栏 / 大小写 / 前置说明 / 失败消息不含原文；
    - `tests/incremental/test_llm_json_fallback.py`——**AC-120** 第一遍与第二遍
      喂带围栏的响应，结论 / 裁决照样落库；
    - `alembic downgrade 0016 → upgrade head` 往返。
  - 前台：本期无页面，随 T87 一并核对。

- [x] **T85 · 配置管理接口 + 模板管理接口**（2026-11-18 完成）
  - 内容：
    - `app/llm_admin/` 包：`__init__.py` / `schemas.py` / `provider_service.py` /
      `template_service.py` / `router.py`。
    - `provider_service.py`：配置 CRUD、**默认互斥**（先清后置，同一事务）、
      停用默认行时 `is_default` 一并置 0、连通性测试（失败也返回 HTTP 200 + `ok=false`）、
      写 `llm_run_logs(task_type='provider_test')`。
    - `template_service.py`：模板列表（分页 + `task_type` / `status` 筛选，**列表项不含正文**）、
      详情（含正文）、编辑（**正文变化才 `version_no += 1`**、`task_type` 不可改）。
    - `router.py`：三个 router——`/api/admin/llm-providers`（`require_system_admin`）、
      `/api/admin/prompt-templates`（`require_system_admin`）、
      `/api/prompt-templates`（只读，`current_user`）。
    - `app/main.py` 注册路由。
    - `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补 3 条：
      `llm.provider.create` / `llm.provider.update` / `prompt_template.update`。
  - 产出：AC-113 / AC-114 / AC-115 / AC-116（接口部分）可断言。
  - 验证：
    - `tests/llm/test_provider_api.py`——AC-113 CRUD / 校验 / 权限 / 审计；
      AC-114 连通性成功与失败两条路径（失败仍 200）；
      AC-105（接口层）响应不含明文与密文字段；
    - `tests/llm/test_template_api.py`——AC-115 列表 / 详情 / 编辑 / 版本自增 / 校验 / 无新建删除路由；
    - `tests/llm/test_readonly_templates.py`——AC-116 只读列表只返回 active 且不含正文；
    - `-k "ac_105 or ac_113 or ac_114 or ac_115 or ac_116"`
  - 前台：本期无页面，随 T87 一并核对。

- [x] **T86 · 05 接入（运行留痕 + 动态模板下拉）**（2026-11-18 完成，后端部分）
  - 内容：
    - `app/incremental/service.py`：`create_analysis` 与 `run_second_pass`
      在跑模型前后记录 `t0` 与调用次数，跑完写一条 `llm_run_logs`
      （`task_type='incremental_first'` / `'incremental_second'`，
      `call_count` / `latency_ms` / `status` / `error_code` / `error_message`）。
      **只改加日志这一处，不动任何判定逻辑**。
    - `app/llm/mock.py` 与 `app/llm/openai_compat.py` 的 `calls` 计数口径对齐
      （跑前记基线，跑完相减）。
    - `tests/incremental/test_llm_provider.py`：改 `test_ac_84_get_provider_is_mock_singleton`
      为「无配置时返回 Mock 单例」（传 session），**测试总数不变**。
    - `app/llm/__init__.py`：导出新增的 `OpenAICompatProvider` 与 crypto 函数。
  - 产出：AC-112 / AC-117 可断言；05 三段逻辑零改动。
  - 验证：
    - `tests/llm/test_run_logs.py`——AC-112 第一遍 / 第二遍 / 连通性三条留痕；
      失败时 `status='failed'` + `error_code='LLM_CALL_FAILED'`；
      表中**不出现** token 金额与 Prompt 正文；
    - `git diff --stat` 核对 `app/incremental/` 只改了日志接入处；
    - 后端全量 **≥ 626 passed**（串行，exit 0）。
  - 前台：本期无新增交互（**05 模板下拉动态化在 T87**，本任务只做后端留痕）。

- [x] **T87 · 前端系统设置页 + 收尾**（2026-11-18 完成；**L2 真实联调待人工执行**）
  - 内容：
    - `web/src/pages/AdminSettingsPage.tsx`（Tab 骨架）+ `web/src/pages/settings/LlmProviderPanel.tsx`
      + `web/src/pages/settings/PromptTemplatePanel.tsx`。
    - `web/src/App.tsx` 注册 `/admin/settings` 路由；
      `web/src/layout/AppLayout.tsx` 在 `system_admin` 分支加「系统设置」菜单。
    - `web/src/api/index.ts`：加 06 分节、类型与 7 个函数；
      `web/src/api/client.ts` 加 7 个错误码中文。
    - `web/src/pages/ProjectIncrementalTab.tsx`：模板下拉改为动态拉取
      `GET /api/prompt-templates?task_type=incremental`；无可用模板 → 禁用发起按钮 +
      提示「请先在系统设置中启用提示词模板」。
    - `scripts/dev_check.py`：新增一项检查——`LLM_SECRET_KEY` 缺失时 `[FAIL]` 并提示。
    - **L1 自动化端到端**（AC-121）：
      `tests/llm/test_real_docs_e2e.py`——取真实 `.pdf` / `.docx`
      （`测试用的需求文档_不提交git/`，缺失则 skip），
      走「上传 → 解析 → 章节落库 → 建基线 → 发起分析 → 结论落库」全链路；
      模型侧用 `httpx.MockTransport` 返回**带 Markdown 围栏的 JSON**，
      **一条用例同时覆盖 AC-119 与 AC-120**；零真实 socket。
    - **L2 真实联调**（AC-121，人工触发，不计入 pytest）：
      用真实 DeepSeek 配置（Key 存 `llm_providers` 表，**不写 `.env`**）
      + 真实 `.pdf` / `.docx` 跑完整链路，结果记入本文件验证记录。
    - 文档回填：`PROGRESS.md`（迁移 head `0017`、依赖变更、主密钥配置方式、计数）、
      `specs/验证约定.md`（§5.8 第六期前台核对点 + 变更记录）、本文件验证记录。
  - 产出：AC-116（前端部分）/ AC-117 / AC-118 / **AC-121** 可断言。
  - 验证：
    - `npm run build` 通过；
    - `tests/e2e/test_llm_settings_ui.py`（`@pytest.mark.task("T87")`）：
      管理员新建配置（`base_url=http://127.0.0.1:9`、超时 1 秒）→ Key 只显示掩码 →
      点测试连通性显示失败原因 → 编辑提示词模板 → 版本号 +1 →
      05 项目页模板下拉出现该模板；普通成员看不到「系统设置」菜单；
      截图 `.screenshots/T87/`；
    - 后端全量 **≥ 626 passed**（串行）；e2e 全量 **≥ 36 passed**；
    - `run_e2e.py` 内联的 `dev_check --expect-db e2e` 通过；
    - 两个库迁移 head 均在 `0017`；
    - 断网复核：清空 `llm_providers` 后全量 pytest 与 e2e 仍全绿（AC-107 / AC-117）。
  - **实现说明**（2026-11-18）：
    - **L1 只断言「实际调用次数」**：引擎只把**有正文**的章节送模型，父章节只做归组，
      因此 `conclusion_count` 不等于章节总数。以 `provider.calls` 为口径，
      同时校验 `stats.conclusion_count == len(provider.calls)` 与留痕 `call_count` 一致。
    - **05 模板下拉要滤掉第二遍模板**：第二遍与第一遍同属 `task_type='incremental'`，
      靠名字前缀区分。不滤会把「第二遍·全局裁决」模板选给第一遍，Prompt 格式不兼容。
    - **连通性失败在前端是「warning」不是「error」**：后端返回 200 + `ok=false`，
      页面按业务结果展示失败原因；只有真异常（权限、配置不存在）才走 `message.error`。
    - **e2e 里 antd Select 首点可能被重渲染吞掉**：切 Tab 后立即点下拉，第一次点击
      只拿到焦点。用例改成「点一次 → 等 600ms → 没展开再点一次」，避免偶发失败。
    - **e2e 造数清理**：大模型配置按 `e2e-llm-` 前缀直删（连带 `llm_run_logs`）；
      模板正文在 `finally` 里还原，避免 e2e 库越跑越脏（版本号会再 +1，内容不变）。

## L2 真实联调发现（2026-11-18，真实 MiniMax-M3）

L2 用真实模型（`https://api.minimax.cn/v1`，模型 `MiniMax-M3`）+ 真实文档
（`需求变更_V3.3_Matrix系统.md`，12 章）+ 真实基线（模块「登录模块」下
功能「用户扫码登录」「账号密码登录」）跑通。**首轮 502，两处真因**：

### 真因一：推理模型的 `<think>` 思考块

带推理能力的模型（MiniMax-M3 / DeepSeek-R1 / Qwen3）会在 `content` 里
先给一段 `<think>…</think>` 推理过程，再给答案。

**坑在推理过程里出现 JSON 片段**——模型会自问自答「输出 `{"conclusions":[]}`
行不行」。而 `parse_llm_json` 的兜底是「取第一个 `{` 到最后一个 `}`」，
于是从**思考块内部**的花括号起算，截出一堆垃圾 → `LLM_OUTPUT_INVALID`。

**修法**：`app/llm/json_utils.py` 加 `strip_think_block()`，在围栏剥离**之前**
执行。思考块与围栏一样是格式噪声，剥掉它就是还原原文——**不做智能修复**的
边界不变（不补引号、不补全、不猜）。

> 为什么不能靠「取最后一个 `}`」解决：模型可能先给答案再补推理，
> 纯靠括号位置无法可靠区分「答案的括号」和「推理里的括号」。

### 真因二：Prompt 里从来没给过基线清单

模型原话：*"user didn't include baseline explicitly... Need target ids based
on baseline unavailable"*。

第一遍模板文案自己就写着「并与比对基准基线中的功能 / 功能点对照」——
**基线本来就该给，只是从未实现**。Mock 时代测试用例直接硬编码了正确的
`target_id`，这个洞一直隐形：**Mock 通过 ≠ 真实模型能跑**。

**修法**（改了 05 的 Prompt 组装，但**判定逻辑零改动**）：

| 位置 | 改动 |
|---|---|
| `app/incremental/context.py` | 新增 `render_baseline_brief()`；`build_user_prompt()` 接受 `baseline_brief` 参数，多拼一段 `## 可对照的基线目标` |
| `app/incremental/engine.py` | `run_first_pass` 渲染一次清单，整次分析共用 |
| 迁移 `0019` | 修正第一遍模板的 system prompt：示例 `"target_id": 1` 改成 `123`，并加一句「target_id 必须取自清单中的编号」；模板正文变了 → `version_no` +1 |

**清单渲染规则**：每行 `- 功能#10096 用户扫码登录`；按 `(target_type, target_id)`
排序（Prompt 必须可复现）；最多占输入预算的 40%（`BASELINE_BRIEF_MAX_RATIO`），
剩下的留给章节正文；截断时注明「其余 N 项已省略」——让模型知道「还有没列出来的」。

> **模板示例写死 `"target_id": 1` 是真的有害**：真实模型**照抄了示例值**。
> 而项目里真实的基线目标 id 是 10096 / 10097，抄来的 `1` 全部被 AC-79
> 判成越界丢弃。示例值必须是「看起来像占位符」的值。

### 判定逻辑未变（红线复核）

字段校验、标签分类、丢弃规则、错误码**全部原样**——
只改了「喂给模型什么」，没改「怎么判定模型说得对不对」。
AC-79 的越界判定、AC-80 的 `new` 丢弃、`LLM_OUTPUT_INVALID` 错误码都没动。

### L2 实测结果（修复后）

| 项 | 结果 |
|---|---|
| HTTP | **201**（首轮 502） |
| 耗时 | 60.8s（12 章，逐章同步调用） |
| 分析状态 | `succeeded` |
| 章节数 | 12 |
| **结论数** | **15**（`discarded_count=0`，`dropped_new_count=0`） |
| 留痕 | `llm_run_logs` 一条 `incremental_first`，`call_count=12` |

结论质量抽样（人工核对，合理）：

| 章节 | 目标 | 判定 | 理由摘要 |
|---|---|---|---|
| 4.2 登录失败次数限制 | 账号密码登录 | `changed`（0.98） | 新增失败 5 次锁定 30 分钟 |
| 4.2 登录失败次数限制 | 用户扫码登录 | `affected`（0.76） | 锁定期内扫码登录也会受阻 |
| 5.1 数据库账号与口令策略 | 账号密码登录 | `affected`（0.82） | 口令策略影响登录安全但未改交互 |
| 3. 文件下载 | 两者 | `unchanged`（0.98） | 与登录无关 |

### 顺带修的测试脆弱点

`tests/llm/test_run_logs.py` 的留痕断言查的是**全表**，L2 实测留下的真实行
把它们算进去了（`provider_name == 'minax'`）。改成按 `project_id` 过滤——
与之前修的审计断言同类问题。

## 收尾（随 T87 完成）

| 项 | 期望 | 实际 |
|---|---|---|
| 后端全量 pytest | ≥ 626 passed（新增约 25–35 条，另加 T84-PDF 的用例） | **829 passed**（串行，exit 0） |
| 前端 `npm run build` | 通过 | 通过 |
| e2e 全量 | 36 + 新增 2~3 条，全绿 | **39 passed**（零回归） |
| `scripts/dev_check.py --expect-db e2e` | 通过 | 通过 |
| 断网可跑 | 无默认配置时全量 pytest 与 e2e 均绿 | 通过（`llm_providers` 空表，两库均 0 行） |
| 迁移 | `0016 → 0017 → 0016` 往返，两个库 head 在 `0017` | 通过（往返干净）；L2 后 head 为 `0019` |
| **L1 端到端** | 真实 `.pdf` / `.docx` 走完整链路，零 socket | **通过**（2 条：pdf / docx） |
| **L2 真实联调** | 真实模型 + 真实文档，结论落库 | **通过**（真实 MiniMax-M3：12 章 → 15 条结论，`discarded=0`） |
| 红线 | 未做 Skill、未做计费、未碰执行、Key 无明文、未新建/删除模板、未改 05 判定逻辑 | 全部遵守 |

## 验证记录

| 任务 | 后端定向 | 后端全量 | 前端构建 | e2e | 截图 |
|---|---|---|---|---|---|
| T84-PDF | **10 passed** | **636 passed**（串行，exit 0） | 通过 | **37 passed**（新增 1 条） | `.screenshots/T84PDF/` |
| T84 | **96 passed**（新增） | **732 passed**（串行，exit 0） | 通过 | **37 passed**（零回归） | —（本期无页面） |
| T85 | **66 passed**（新增） | **798 passed**（串行，exit 0） | 通过 | **37 passed**（零回归） | —（本期无页面） |
| T86 | **11 passed**（新增） | **812 passed**（串行，exit 0） | 通过 | **37 passed**（零回归） | —（本期无页面） |
| T87 | （待填） | （待填） | 通过 | （待填） | `.screenshots/T87/` |

## 实现要点（待补）

- **T84-PDF**（已完成）：
  - `app/documents/pdf.py` 新增：`extract_lines`（逐页取**字符** → top ±2pt 聚行 →
    横向间隙切列 → 行字号取行内最大 + 加粗标记）、
    `heading_levels`（非加粗行众数 = 正文字号，> 众数+0.6pt 的字号为标题档，降序映射 level）、
    `is_heading`（字号更大 **且** 命中编号正则，**或** 加粗 **且** 命中多级编号）、
    `heading_level`（字号定档；只有加粗小标题时按编号深度定层级，至少为 2）。
  - `app/documents/parser.py`：`SUPPORTED_SUFFIXES` 加 `.pdf`；新增 `_parse_pdf`
    **复用 `_TreeBuilder`**（章节树与 md/docx 天然同构，落库口径零变化）；
    标题文本用 `_clean_heading` 压掉排版空格（正文里的空格保留，标题里的不需要）。
  - **为什么用 `pdfplumber` 而不是 `pypdf`**：实测样本 PDF（8 页、2508 字、文本型），
    `pdfplumber` 能拿到**字号**并还原表格；`pypdf` 拿不到字号，
    PDF 就只能走「整文输入 + LLM 拆解」，复杂度与成本都上一个台阶。
  - **为什么用字符而不是 `extract_words`**：`extract_words` 按空格切词，
    会**丢掉 PDF 里真实的空格字符**——`APP Application` 会粘成 `APPApplication`。
    改用 `page.chars` 逐字符重建。
  - **编号正则刻意不匹配单级编号**（`1` / `2`）：`1. ` 是列表项的写法，点后不是数字；
    `\d+(\.\d+)+` 只匹配 `1.1` / `2.4.2`。结尾用 `(?!\d)` 而不是 `\b`——
    `6.1WEB` 的数字与字母之间没有词边界，用 `\b` 会漏掉这种标题。
  - **正文字号取非加粗行的众数**：标题行可能比正文行还多（目录页、短文档），
    全量众数会被标题字号占据，导致「没有标题档」。
  - **表格不单独识别**：单独跑 `find_tables()` 会与正文流**重复**（表格内容出现两次）。
    改为行内按横向间隙切列（正文间隙 ≤ 6pt，表格列间隙 ≥ 20pt，取 10pt）。
  - **扫描件降级**：提取不到任何文字 → 整文单章「全文」，**不报错**。
  - **错误码归属**：`.pdf` 内容损坏 → `DOCUMENT_PARSE_FAILED`（复用既有码）；
    `UNSUPPORTED_DOC_TYPE` 回归「未知扩展名」语义（`.xlsx` 等）。
  - 验证：新增 `tests/documents/test_pdf_parser.py`（8 条）+ 上传侧 2 条；
    改 3 处既有测试期望值（`test_parser.py` / `test_upload.py` / `test_documents_ui.py`）；
    后端全量 **636 passed**、e2e **37 passed**、`npm run build` 通过；
    迁移 head 仍在 `0016`（本期不动迁移）。
- **T84**（已完成，2026-11-18）：
  - **加密层**：`Fernet` 密钥由 `sha256(llm_secret_key)` 派生
    （`base64.urlsafe_b64encode(sha256(secret).digest())`）——
    任意长度的字符串都能当主密钥，用户不必手工生成 32 字节。
    `decrypt` 的错误消息**固定**：Fernet 原始异常里可能带密文片段，
    直接透出去等于把密文写进日志。
  - **Provider 请求形状**：`POST {base_url}/chat/completions`；
    Header `Authorization: Bearer <key>` + `Content-Type: application/json`；
    Body 只带 `model` 与**恰好两条** `messages`。
    **不传** `temperature` / `max_tokens`（不同供应商默认值差异大）。
    超时 `httpx.Timeout(connect=5.0, read=ts, write=ts, pool=5.0)`，
    `httpx.Timeout` 是必填的——**绝不允许无超时的网络调用**。
    `raw` 回带 `{"request": ..., "index": n}`，与 `MockProvider` 同契约，
    05 的「Prompt 确实从库里来」断言在真 Provider 下同样成立。
  - **降级分支的取舍**：`get_provider` **每次都查库**（单表 + 唯一索引，
    查询成本可忽略），换来「管理员改完配置立即生效」，不引入缓存一致性问题。
    **解密失败不降级**，抛 `LLMConfigInvalid`（500）——配置坏了必须让人知道，
    否则线上会用 Mock 跑出一堆空结论却没人发现。
  - **容错解析的顺序**：`strip()` → 剥围栏（` ```json ` / ` ``` `，
    大小写不敏感，`re.S`）→ 取 `{` 到 `}` 区间兜底 → 失败抛
    `LLMOutputInvalid`（**消息不含原始响应正文**）。
    **只做这三步，不做「智能修复」**（补引号 / 截断补全 / JSON5 容错）：
    那些会掩盖模型输出的真实问题，让「模型返回了坏 JSON」变成
    「平台悄悄改对了」，排查时更难定位。围栏与前置说明是**格式噪声**，
    去掉它是还原原文；补引号是**猜测**。
  - **⚠️ 给 T85 的坑：切换默认必须「先清后置」**。
    `default_key` 是**即时计算**的生成列：把新行 `is_default` 置 1 的那一刻，
    它的 `default_key` 立刻落成 1；而老默认行还没清、`default_key` 还是 1
    → 唯一索引**当场报错**。反过来做（先置后清）必炸。
    T85 的 `provider_service` 要按「先清后置」写（同一事务内两次 UPDATE）。
  - **`test_ac_84_no_real_network_code` 改写而非删除**（用户 2026-11-18 裁决）：
    06 期引入了真实供应商，「`app/llm` 下不出现 httpx 字样」的前提已不成立。
    改成两条可执行断言——① `OpenAICompatProvider` 必须支持 `transport` 注入
    且真实调用点走的就是它；② `app/` 下除它之外零真实网络客户端。
    另加 `test_ac_84_tests_never_use_real_socket`：测试目录里不许出现
    `requests` / `urlopen` / `aiohttp` / `socket.socket`。
    **守卫意图（断网可跑）保住了，用例一条没删。**
  - **05 的改动只有 2 处解析入口**：`git diff app/incremental/` 实测
    只动了 `engine.py` 与 `second_pass.py` 的 `json.loads` →
    `parse_llm_json`（外加删掉不再用的 `import json`）。
    判定逻辑零改动——字段校验 / 标签分类 / 丢弃规则 / 错误码全部原样，
    `test_llm_json_fallback.py` 里的坏 JSON / 非法 `decision` 用例
    断言的仍是 `LLM_OUTPUT_INVALID`。
  - **测试规模**：新增 **96 条**（`tests/llm/` 5 个文件 +
    `tests/incremental/test_llm_json_fallback.py`），
    全部用 `httpx.MockTransport`，**零真实 socket**。
- （待 T85 后补：默认互斥的实现顺序、连通性失败仍返 200 的理由）
- （待 T86 后补：运行留痕接入点、调用次数计数口径）
- **T85**（已完成，2026-11-18）：
  - **默认互斥严格「先清后置」**（T84 排的雷）：`_clear_other_defaults()`
    **逐行改** `is_default`（不用批量 `UPDATE`）——
    批量更新绕过 ORM 脏检查，内存里的对象留着旧 `is_default`，
    后面 flush 可能把刚清掉的老默认行又立回来；
    flush 之后再把目标行置 1。
  - **响应里只有掩码**：`api_key_masked` 形如 `sk-****1234`，
    **没有 `api_key`、没有 `api_key_ciphertext`**。
    掩码靠「解密 → `mask()`」还原前缀；主密钥换掉时退化成 `****{last4}`
    ——宁可少给几个字符，也不让整个列表挂掉。
  - **连通性失败仍返 200 的理由**：它不是业务异常，是
    「这个配置连不通」的正常反馈，前端要在**表单里内联展示**错误。
    抛 502 的话前端只能弹全局提示，用户填的表单内容会丢。
    成功与失败**都**写一条 `llm_run_logs(task_type='provider_test')`。
  - **失败消息只取 `LLMCallFailed.message`**：其它异常只取**类型名**，
    不取 `str(exc)`——原始异常里可能带 URL、请求头等敏感片段。
  - **校验一律在服务层做**：pydantic 校验失败会变成 422，
    而 spec 要求 400 `LLM_PROVIDER_INVALID` / `PROMPT_TEMPLATE_INVALID`
    （与 01–05 的既有口径一致）。
  - **模板版本自增只看正文**：`system_prompt` / `user_prompt` 变了才
    `version_no += 1`；只改 `description` / `status` **不**升版本
    （升了「模板版本」就失去「内容变了」的标记意义）。
    `task_type` **不在入参里**——改了等于换了个模板的身份，历史分析对不上。
  - **连通性测试的 transport 走依赖注入**（`provider_transport`）：
    生产是 `None`（真实网络），测试注入 `httpx.MockTransport`，
    **零真实 socket**。
- **T86**（已完成，2026-11-18，后端部分）：
  - **运行留痕接入点**：`app/incremental/service.py` 的
    `create_analysis` 与 `run_second_pass`，各在跑模型**前**记
    `t0` 与调用基线，跑完（或失败）写一条 `llm_run_logs`。
    **纯增量 +90 / -0，判定逻辑零改动**。
  - **调用次数计数口径**：`provider.calls` 是**累计**的
    （Mock 与真实 Provider 同契约），所以**跑前记基线、跑完相减**——
    直接取 `len(calls)` 会把历史调用也算进来。
    用例 `test_ac_112_call_count_is_per_task_not_cumulative` 固定这条。
  - **留痕记的是「配置身份」不是「供应商类型」**：
    `OpenAICompatProvider` 加了 `provider_name` / `provider_id` 快照，
    所以留痕里是「DeepSeek 生产」而不是「openai_compat」。
  - **留痕表里根本没有 Prompt / token 列**——不是靠代码自觉，是表结构保证。
  - **写日志不写审计**（日志不是业务写操作）。
- （待 T87 后补：前台核对暴露的真实缺陷、L1/L2 联调实测结果）
