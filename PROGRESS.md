# AI 辅助测试平台 - 当前开发进展看板

> **给 AI 的强制指令**：每次新任务开始前，必须先阅读本文件，并严格遵循当前冲刺任务，严禁越界写代码。

## 1. 项目路径映射

- **代码路径**：`D:\aitest_copilot`
- **需求/Spec 路径**：仓库内 `specs/`（与代码同一代码库）
  - 模块目录：`01-auth` / `02-projects` / `03-documents` / `04-baseline` / `05-incremental-analysis`
  - **验证约定**：`specs/验证约定.md`

## 2. 项目整体进度

- [x] 01-auth (登录)
- [x] 02-projects (项目与申请)
- [x] 03-documents (文档解析) —— **已完成（含 T84-PDF：PDF 解析支持）**
- [x] 04-baseline (基线管理、快照、标签) —— **已完成（含 T67 收尾）**
- [x] 05-increment-analysis (增量分析) —— **第一期（T68~T70）+ 第二期（T71~T78）+ 第三期 T79~T83 全部完成**
- [ ] 06-real-llm (真实大模型接入与提示词模板管理) —— **进行中：T84-PDF + T84 + T85 + T86 已完成，下一个 T87**

## 3. 当前冲刺任务（⚠️ 务必先做这个）

**当前目标**：06 真实大模型接入 —— **T84-PDF + T84 + T85 + T86 已完成**，下一步 **T87**
（前端系统设置页 + 05 动态模板下拉 + L1/L2 联调收尾）。

> **06 期红线（用户 2026-11-17 裁决）**：
> - 不做 Skill 双轨制 / Token 计费 / 不碰自动化执行；
> - API Key 绝不明文落库，不出现在响应 / 审计 / 日志 / 异常 / 运行日志；
> - **不改 05 的判定逻辑与业务语义**——但**允许且必须**把 05 两处
>   `json.loads` 换成容错解析入口 `parse_llm_json`（真实模型必然返回
>   Markdown 围栏的 JSON，不容错则整次分析直接 502）；
> - 不做模板新建 / 删除（只做列表 + 编辑）；
> - 不引入无超时的网络调用；**任何测试不允许产生真实 socket**。
>
> **任务顺序**：`T84-PDF → T84 → T85 → T86 → T87`。
> T84-PDF 是 06 的**前置排头兵**（T87 验收要用真实 `.pdf` 走端到端）。
>
> **真实联调分两层**：
> - **L1 自动化**（进 CI，零 socket）：真实 `.pdf`/`.docx` + `httpx.MockTransport`
>   返回**带 Markdown 围栏的 JSON**，一条用例同时覆盖 PDF 与容错；
> - **L2 人工**（不计入 pytest）：真实 DeepSeek（API Key 走系统设置页存
>   `llm_providers` 表，**不写 `.env`**）+ 真实文档。

### T84-PDF 已完成（03 模块支持 PDF）

> 范围：`pdfplumber` 纯文本提取 + 字号/加粗/编号规则切章节 + 表格还原成
> `a | b` + 扫描件整文降级；**不改 `app/documents/service.py` 与
> `app/common/errors.py`**（章节落库口径不变，`UNSUPPORTED_DOC_TYPE`
> 回归「未知扩展名」语义）。

### T84 已完成（配置落库 + 密钥加密 + 动态 Provider + JSON 容错）

> 范围：两张新表（迁移 `0017`）+ Fernet 加密 + `OpenAICompatProvider` +
> 查库降级工厂 + `parse_llm_json` 容错解析入口。
> **05 的判定逻辑零改动**——`app/incremental/` 下只换了 2 处解析入口
> （`engine.py` / `second_pass.py`），字段校验 / 标签分类 / 丢弃规则 /
> 错误码全部原样。

### T85 + T86 已完成（配置管理接口 + 模板管理接口 + 运行留痕）

> 范围：`app/llm_admin/` 三个路由（配置管理 / 模板管理 / 只读模板列表）
> + 05 两段接入 `llm_run_logs` 运行留痕。
> **05 仍是纯增量改动**——`app/incremental/service.py` 只多了写日志的调用，
> 判定逻辑与业务语义一个字节没动（`git diff` 实测 +90 / -0）。

### 第二期范围（已完成，不可扩大）

- 只做**第二遍 · 全局裁决**：章节引用图 + 2b-1 功能点索引 / 2b-2 按点分治 / 2b-3 一跳图传播。
- **零真实网络请求**：仍只有 `MockProvider`（第二遍默认响应 `unchanged`）。
- 表结构只加三张：`document_chapter_links`（0014）、`incremental_decisions` / `incremental_conflicts`（0015）。

### 第二期红线（已遵守）

1. **不写 `baseline_labels`**——人工裁决只改冲突行，产出段是第三期的事。
2. **不做模板管理 UI / 模板 CRUD**——第二遍模板由迁移播种、只读。
3. **不自动裁决冲突**——冲突只能人工确认 / 驳回。
4. **不引入真实模型供应商**、不做密钥加密与运行日志表。
5. 不许顺手修无关模块——引用抽取代码放 05 包内，没改 03 的解析器。

### 第一期核心 AC（已覆盖，见下方历史任务）

**AC-① 章节局部结论能否正确落库**
- Given 项目有基线快照（含功能 F）+ 生效文档版本（含章节 C）+ Mock 返回固定 JSON（结论指向 F，`label_type='changed'`）
- When 发起分析
- Then `incremental_analyses` 新增一行 `status='succeeded'`
- Then `incremental_conclusions` 新增一行：`chapter_id=C`、`target_type='function'`、`target_id=F`、`label_type='changed'`
- Then 目标不在基线内的结论**被丢弃**并记错误码（不能静默写入脏数据）

**AC-② Prompt 是否从数据库读取并传给 Mock**
- Given `prompt_templates` 表里 `task_type='incremental'` 的模板，其 `system_prompt` / `user_prompt` 是**可识别的固定字符串**
- When 发起分析
- Then **Mock 收到的 `system` 等于该模板的 `system_prompt`**
- Then **Mock 收到的 `user` 以该模板的 `user_prompt` 开头**，且包含章节标题与章节正文
- Then 模板被删除 / `status='disabled'` → 发起分析返回对应错误码，**不产生分析记录**

## 4. 环境与验证现状

| 项 | 值 |
|---|---|
| 后端全量 pytest | **812 passed**（串行；T85+T86 收尾复核，基线 732 + 新增 80 条） |
| e2e | **37 passed**（含增量分析第一期 2 条 + 第二期 3 条 + 第三期 2 条 + PDF 1 条），一条命令 `.\.venv\Scripts\python.exe scripts\run_e2e.py`（8001/5174 + `aitest_copilot_e2e`） |
| 前端构建 | `npm run build`（`web/` 目录，端口 5173，代理到 8000） |
| 开跑前自检 | `.\.venv\Scripts\python.exe scripts\dev_check.py`（跑 e2e 时加 `--expect-db e2e`） |
| 账号 | `admin` / `Admin12345` |
| 迁移 head | **`0017`**（06 期 T84 建；T84-PDF 不动迁移） |
| 截图目录 | 仓库根 `.screenshots/`（`E2E_SCREENSHOT_DIR` 可覆盖） |
| 运行时依赖 | `pdfplumber>=0.11`（T84-PDF 新增）；**`cryptography>=43`（T84 新增）、`httpx>=0.28`（T84 从 dev 移入）** |
| 环境变量 | **新增必填 `LLM_SECRET_KEY`**（已写入本地 `.env`，随机生成，不入库；`.env.example` 有说明） |

### ⚠️ 两个已知的坑（别重复踩）

1. **`pytest -n 4` 下 `tests/projects/` 有既有 flaky**（与新改动无关）：
   `test_available_returns_all_unjoined_projects`、`test_ac_36_add_member`
   会偶发失败——根因是断言只按 `action` 过滤 AuditLog、未按项目隔离，并行 worker 撞车。
   **对照验证过**：回到改动前提交连跑 3 次同样失败；串行跑全绿、单跑这 2 条全绿。
   → **判定回归时用串行跑**，或先确认失败是否属于这 2 条。
2. **MySQL DDL 隐式提交**会破坏 pytest 夹具的外层事务。
   测试里造表必须用**独立引擎**（如内存 SQLite + `StaticPool` + `check_same_thread=False`），
   不能在夹具事务内 `CREATE TABLE`。

## 5. 04 收尾完成情况（2026-11-17）

- [x] 把 `D:\aitest_copilot` 下的 17 个未推送提交 push 到远端（`db0b09b..683cfed`）
- [x] 补齐 04 的"快照引用保护扩展"——引用检查拆成**来源解析器**架构
      （`app/baselines/references.py`），标签引用与增量分析引用各一个解析器；
      增量分析解析器探测表是否存在，05 落地后**自动生效，04 无需再改**
- [x] 跑通测试 `pytest -k ac_04_cleanup`（11 passed）

**验证结果**：`pytest -k ac_04_cleanup` 11 passed；全量 484 passed；e2e 29 passed；构建通过。

**提交**：`1539646` / `0f06583` / `4ab12fe` / `9d3a885`，已推送到 `origin/main`。

## 5.1 05 收尾完成情况（2026-11-17）

### 第一期（T68~T70）· 第一遍 · 章节局部比对

- [x] 三张表 + 迁移 `0013_incremental`；`app/llm/` 抽象与 `MockProvider`
- [x] `engine.py` 第一遍 + `service.py` + `router.py` + 错误码 + 审计
- [x] 项目详情页第 7 个 Tab「增量分析」+ API 分节 + 错误码映射

**验证结果**：后端全量 516 passed；e2e 31 passed（新增 2 条）；构建通过。

### 第二期（T71~T78）· 第二遍 · 全局裁决

- [x] T71 章节引用图：迁移 `0014` + `links.py` 规则抽取 + `links_router.py` 三接口
- [x] T72 第二遍表结构：迁移 `0015`（`incremental_decisions` / `incremental_conflicts`
      + `analyses` 第二遍列）+ 第二遍模板种子
- [x] T73 2b-1 功能点索引 + 2b-2 按点分治（含证据一致性判定与 Mock 第二遍默认响应）
- [x] T74 2b-3 一跳图传播（`possible_impact` 只进人工队列）
- [x] T75 第二遍服务与四个接口（触发 / 裁决列表 / 冲突列表）
- [x] T76 人工裁决接口（确认 / 驳回，**不写 `baseline_labels`**）
- [x] T77 前端：第二遍区块 + 引用图抽屉 + 3 条 e2e
- [x] T78 收尾：全量 pytest 串行 + e2e 全量 + `dev_check` + build + 文档回填

**验证结果**：后端全量 **589 passed**（T70 后 516 + 新增 73）；e2e **34 passed**
（新增 3 条）；`npm run build` 通过；两个库迁移 head 均在 `0015`；
截图 `.screenshots/T77/`（5 张）。

**提交**：`2dd6161` / `41a4cf4`（T71）、`c51d2e6`（T72）、`478f429`（T73）、
`c51d7d1`（T74）、`d015b7f`（T75）、`8b1cc3f`（T76）、`a7d93a5`（T77）。

### 第三期（T79~T83）· 产出段

- [x] T79 产出段模型与迁移：`0016`（`incremental_labels` 映射表 + `analyses` 的 `apply_*` 列，
      唯一键 `(analysis_id, baseline_label_id)`，标签类型只收 `changed` / `affected`）
- [x] T80 产出引擎：`app/incremental/apply.py`（收集规则 / 复用或新建 submitted 快照 /
      写标签 + 映射 / 重跑逻辑清除），标签行只置 `cleared`、绝不物理删除
- [x] T81 产出服务与接口：`run_apply`（固定校验顺序 + 逻辑清除 + 落标签 + 审计）、
      `list_applied_labels`（历史行可查 + `revoked` 派生）、两个路由与 3 个错误码；审计覆盖补 1 条
- [x] T82 前端：`IncrementalApply.tsx`（状态 / 触发 / 产出标签表 / 撤销提示）挂进分析详情抽屉，
      `api/index.ts` 补两接口与类型、`client.ts` 补 3 个错误码中文
- [x] T83 收尾：后端全量 **626 passed**、e2e **36 passed**、构建通过、自检通过；
      `验证约定.md` §5.6 与本文件计数回填，第三期收尾完成

**T79 验证结果**：定向 15 passed；后端全量 **604 passed**（串行）；
`alembic downgrade 0015 → upgrade head` 往返通过；两个库迁移 head 均在 `0016`。

**T80 验证结果**：`tests/incremental/test_apply_engine.py` 11 passed；
后端全量 **615 passed**（串行）。未改 `app/baselines/` 任何代码，未物理删除标签行。

**T81 验证结果**：`tests/incremental/test_apply_flow.py` 10 passed，
审计覆盖清单新增 `incremental.apply.run` 1 条；后端全量 **626 passed**（串行）。

**T82 验证结果**：`npm run build` 通过；e2e 全量 **36 passed**
（新增 `test_incremental_apply_ui.py` 2 条）；截图 `.screenshots/T82/`（3 张）。

**T83 验证结果**：后端全量 **626 passed**（串行，exit 0）；e2e 全量 **36 passed**；
`npm run build` 通过；`run_e2e.py` 内联的 `dev_check --expect-db e2e` 通过；
两个库迁移 head 均在 `0016`；AC-104 复核通过（全链路只有 `MockProvider`，零真实网络请求）。

## 5.2 06 期 · T84-PDF 完成情况（2026-11-17）

**做了什么**：03 模块支持 PDF 上传（`pdfplumber` 运行时依赖）。

- [x] `app/documents/pdf.py`（新增）：逐页取**字符** → 按 top ±2pt 聚行 →
      横向间隙切列（表格还原成 `a | b`）→ 字号分档 + 编号正则判标题。
- [x] `app/documents/parser.py`：`SUPPORTED_SUFFIXES` 加 `.pdf`，
      新增 `_parse_pdf`（复用 `_TreeBuilder`，章节树与 md/docx 同构）。
- [x] `pyproject.toml`：`pdfplumber>=0.11` 进运行时依赖。
- [x] 前端：`accept` 加 `.pdf`、提示文案加 `.pdf`、`UNSUPPORTED_DOC_TYPE` 文案改。
- [x] 3 处既有测试期望值改：`test_parser.py`（PDF 不再是不支持类型，
      改用 `.xlsx`）、`test_upload.py`（PDF 上传成功 + 损坏 PDF 报错）、
      `test_documents_ui.py`（PDF 从「被拒」改成「上传成功」）。
- [x] 新增 `tests/documents/test_pdf_parser.py`（8 条）+ 上传侧 2 条。
- [x] `.env` 补 `LLM_SECRET_KEY`（随机生成），`.env.example` 补说明；
      `.gitignore` 补注释并确认 `测试用的需求文档_不提交git/` 命中。

**验证结果**：后端全量 **636 passed**（串行，exit 0）；e2e 全量 **37 passed**；
`npm run build` 通过；迁移 head 仍在 `0016`（本期不动迁移）。

**实现要点**：

- **为什么用 `pdfplumber` 而不是 `pypdf`**：实测样本 PDF（8 页、2508 字、文本型），
  `pdfplumber` 能拿到**字号**（`extract_words(extra_attrs=['size'])`）并还原表格；
  `pypdf` 拿不到字号，PDF 就只能走「整文输入 + LLM 拆解」，复杂度与成本都上一个台阶。
- **用字符而不是 `extract_words`**：`extract_words` 按空格切词，会**丢掉 PDF 里真实的
  空格字符**——`APP Application` 会粘成 `APPApplication`，中英混排的需求文档里
  这明显降低可读性。改用 `page.chars` 逐字符重建。
- **标题判据是两条硬条件**：
  ① 字号 > 正文字号（+0.6pt 缓冲）**且**命中编号正则；
  ② 或 **加粗** **且**命中多级编号（有些文档的小节标题字号与正文相同，
  只靠加粗区分，样本 PDF 的 `6.1WEB攻击防御手段` 就是这种）。
  两条都要求命中编号正则——否则正文里的 `1. 防止SQL注入` 列表项会被误判成标题。
- **编号正则刻意不匹配单级编号**（`1` / `2`）：`1. ` 是列表项的写法，
  点后不是数字；`\d+(\.\d+)+` 只匹配 `1.1` / `2.4.2` 这类多级编号。
  结尾用 `(?!\d)` 而不是 `\b`——`6.1WEB` 的数字与字母之间没有词边界。
- **正文字号取非加粗行的众数**：标题行可能比正文行还多（目录页、短文档），
  那时全量众数会被标题字号占据，导致「没有标题档」。
- **表格不单独识别**：PDF 里表格的绝对坐标与正文行不在同一条「行」序列里，
  单独跑 `find_tables()` 会与正文流**重复**（表格内容出现在章节里两次）。
  改为在行内按横向间隙切列（正文实测间隙 ≤ 6pt，表格列间隙 ≥ 20pt，取 10pt）。
- **扫描件降级**：提取不到任何文字 → 整文单章「全文」，**不报错**
  （与「txt 无标题整文单章」同一口径）。OCR 明确留到后续期。

## 5.3 06 期 · T84 完成情况（2026-11-18）

**做了什么**：真实大模型接入的**模型侧底座**（不含接口、不含前端）。

- [x] `app/models/llm.py`（新增）：`LLMProviderConfig`（`llm_providers`）+
      `LLMRunLog`（`llm_run_logs`），字段 / 索引 / CheckConstraint 对齐 spec §4。
- [x] `migrations/versions/0017_llm_providers.py`（新增）：`down_revision="0016"`，
      两表按序建、downgrade 反序直接删表、**无种子数据**。
- [x] `app/llm/crypto.py`（新增）：`encrypt` / `decrypt` / `mask`，
      Fernet 密钥由 `sha256(llm_secret_key)` 派生。
- [x] `app/llm/openai_compat.py`（新增）：`OpenAICompatProvider`
      （`transport` 可注入 → 测试零真实 socket）。
- [x] `app/llm/json_utils.py`（新增）：`parse_llm_json` 容错解析。
- [x] `app/llm/provider.py`：工厂改造成查库降级（无配置 → Mock 单例）。
- [x] `app/incremental/engine.py` + `second_pass.py`：**两处** `json.loads`
      换成 `parse_llm_json`，判定逻辑零改动。
- [x] `app/common/config.py`：`Settings.llm_secret_key` **必填**；
      `.env` / `.env.example` 同步。
- [x] `app/common/errors.py`：新增 7 个错误码类。
- [x] `pyproject.toml`：`cryptography>=43` 进运行时；`httpx>=0.28` 从 dev 移入运行时。
- [x] `tests/llm/`（新增 5 个文件）+ `tests/incremental/test_llm_json_fallback.py`：
      新增 **96 条**用例，全部用 `httpx.MockTransport`，**零真实 socket**。

**验证结果**：后端全量 **732 passed**（串行，exit 0）；e2e 全量 **37 passed**；
`npm run build` 通过；`dev_check.py` 通过；两个库迁移 head 均在 `0017`；
`alembic downgrade 0016 → upgrade head` 往返通过；`llm_providers` 表为空时
（= 断网降级 Mock 场景）全量仍全绿。

**实现要点**：

- **为什么「先降级、后接真」不是妥协而是安全阀**：没有配置、用户没配就发分析，
  平台仍然能跑（和今天一模一样），不会因为新功能把 05 打挂。
  `get_provider` 每次都查库（单表 + 唯一索引，查询成本可忽略），
  换来「管理员改完配置立即生效」，不用处理缓存一致性。
- **解密失败不降级，抛 `LLMConfigInvalid`（500）**：配置坏了必须让人知道，
  否则线上会用 Mock 跑出一堆空结论却没人发现。
- **唯一默认用「生成列 + 唯一索引」在库层兜底**：
  `default_key` 是 `STORED` 生成列 `IF(is_default=1, 1, NULL)`，
  唯一索引 `uk_llmprov_default` 挂在它上面。
  MySQL 唯一索引允许多个 NULL，所以非默认行不占位。
- **⚠️ 切换默认必须「先清后置」**：生成列是**即时计算**的——
  把新行 `is_default` 置 1 的那一刻它的 `default_key` 立刻落成 1，
  而老默认行还没清、`default_key` 还是 1 → 唯一索引当场报错。
  **反过来做（先置后清）必炸**，T85 的服务层要按这个顺序写。
- **Fernet 密钥由 `sha256(llm_secret_key)` 派生**：
  `base64.urlsafe_b64encode(sha256(secret).digest())`，
  任意长度的字符串都能当主密钥，用户不必手工生成 32 字节。
  换掉主密钥 = 库里已存的密文全部解不开。
- **`decrypt` 的错误消息是固定的**：Fernet 的原始异常里可能带密文片段，
  直接透出去等于把密文写进了日志。
- **`parse_llm_json` 只做三件事，不做「智能修复」**：
  剥围栏 → 取 `{` 到 `}` 区间兜底 → 失败就报错。
  **补引号 / 截断补全 / JSON5 容错一律不做**——那些会掩盖模型输出的真实问题，
  让「模型返回了坏 JSON」变成「平台悄悄改对了」，排查时更难定位。
  围栏与前置说明是**格式噪声**，去掉它是还原原文；补引号是**猜测**。
- **异常收敛成 6 类**：超时 / 连接失败 / 其他 HTTPError / 401-403 / 其他非 2xx /
  响应结构不符，全部 → `LLMCallFailed`（502 `LLM_CALL_FAILED`），
  消息给可读原因但**永远不带 API Key**。
- **不传 `temperature` / `max_tokens`**：不同供应商默认值差异大，
  传固定值反而制造行为不一致。
- **`test_ac_84_no_real_network_code` 改写而非删除**（用户 2026-11-18 裁决）：
  06 期引入了真实供应商，「代码里不出现 httpx 字样」的前提已不成立。
  改成两条可执行断言——① `OpenAICompatProvider` 必须支持 `transport` 注入；
  ② `app/` 下除它之外零真实网络客户端。另加一条
  `test_ac_84_tests_never_use_real_socket`：测试目录里不许出现
  `requests` / `urlopen` / `aiohttp` / `socket.socket`。
  **守卫意图（断网可跑）保住了，用例一条没删。**

## 5.4 06 期 · T85 + T86 完成情况（2026-11-18）

**做了什么**：配置管理接口 + 模板管理接口 + 05 运行留痕。

- [x] `app/llm_admin/`（新增包）：`__init__.py` / `schemas.py` /
      `provider_service.py` / `template_service.py` / `router.py`。
- [x] 三个路由（`app/main.py` 注册）：
      `/api/admin/llm-providers`（`require_system_admin`）、
      `/api/admin/prompt-templates`（`require_system_admin`）、
      `/api/prompt-templates`（只读，`current_user`）。
- [x] `app/llm/run_log.py`（新增）：运行留痕的统一写入口。
- [x] `app/incremental/service.py`：第一遍与第二遍各接一处留痕
      （**纯增量 +90 / -0，判定逻辑零改动**）。
- [x] `app/llm/openai_compat.py`：加 `provider_name` / `provider_id`
      快照——留痕要记「用的哪条配置」，不是「用的哪个类型」。
- [x] `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补 3 条：
      `llm.provider.create` / `llm.provider.update` / `prompt_template.update`。
- [x] 新增 `tests/llm/test_provider_api.py`（31 条）/
      `test_template_api.py`（27 条）/ `test_readonly_templates.py`（8 条）/
      `test_run_logs.py`（11 条），共 **77 条**。

**验证结果**：后端全量 **812 passed**（基线 732 + 80）；
e2e 全量 **37 passed**（零回归）；`npm run build` 通过。

**实现要点**：

- **响应里只有掩码**：只有 `api_key_masked`（`sk-****1234`），
  **没有 `api_key`、没有 `api_key_ciphertext`**。
  掩码靠「解密 → `mask()`」还原前缀，所以主密钥换掉时退化成
  `****{last4}`——宁可少给几个字符，也不让整个列表挂掉。
- **默认互斥严格「先清后置」**（T84 排的雷）：
  `_clear_other_defaults()` 逐行改 `is_default`（**不用批量 UPDATE**——
  批量更新绕过 ORM 脏检查，内存里的对象会留着旧值，
  后面 flush 可能把刚清掉的老默认行又立起来），
  flush 之后再把目标行置 1。
- **连通性测试失败返回 200 + `ok=false`**，不抛 502——
  它不是业务异常，是「这个配置连不通」的正常反馈，
  前端要在表单里内联展示。成功与失败**都**写一条
  `llm_run_logs(task_type='provider_test')`。
- **失败消息只取 `LLMCallFailed.message`**：其它异常只取**类型名**，
  不取 `str(exc)`——原始异常里可能带 URL、请求头等敏感片段。
- **模板版本自增只看正文**：`system_prompt` / `user_prompt` 变了才
  `version_no += 1`；只改 `description` / `status` **不**升版本
  （升了「模板版本」就失去「内容变了」的标记意义）。
  `task_type` **不在入参里**——改了等于换了个模板的身份，历史分析对不上。
- **运行留痕的调用次数是「本次任务」的**：`provider.calls` 是累计的，
  所以**跑前记基线、跑完相减**。直接取 `len(calls)` 会把历史调用算进来。
- **留痕表里根本没有 Prompt / token 列**——不是靠代码自觉，是表结构保证。
- **连通性测试的 transport 走依赖注入**（`provider_transport`）：
  生产是 `None`（真实网络），测试注入 `httpx.MockTransport`，
  **零真实 socket**。
- **校验一律在服务层做**：pydantic 校验失败会变成 422，
  而 spec 要求 400 `LLM_PROVIDER_INVALID` / `PROMPT_TEMPLATE_INVALID`
  （与 01–05 的既有口径一致）。

## 6. 待办（不属当前冲刺，等用户点头再做）

- 06 期其余任务：T87（前端系统设置页 + 05 动态模板下拉 + L1/L2 联调收尾）
- PDF 扫描件 OCR（本期只做「无文字层 → 整文单章」降级）
- PDF 表格结构化落库（本期还原成 `a | b` 文本行，与 docx 同构）
- 05 第五期：模板管理 UI 与阈值回填（依赖基准集）
- 修 `tests/projects/` 的 xdist flaky（断言未按项目隔离）
- 前端「来源类型」筛选下拉值是 `'document'`，后端枚举是 `'document_derived'`——**真 bug**，
  选「文档解析」永远 0 条，且无测试覆盖
- 标签清除原因 6 类枚举与 PRD 2.4.2 不符（`priority_changed` / `duplicate_label`
  应为「基线已调整」/「回溯覆盖」）
- 基准集与评估脚本（v2.2 §10；05 的召回策略与切分阈值全靠它回填）
