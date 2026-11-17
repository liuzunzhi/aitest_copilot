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
- [ ] 06-real-llm (真实大模型接入与提示词模板管理) —— **进行中：T84-PDF 已完成，下一个 T84**

## 3. 当前冲刺任务（⚠️ 务必先做这个）

**当前目标**：06 真实大模型接入 —— **T84-PDF 已完成（排头兵）**，下一步 T84
（配置落库 + 密钥加密 + 动态 Provider + JSON 容错解析）。

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
| 后端全量 pytest | **636 passed**（串行；T84-PDF 收尾复核，基线 626 + 新增 10 条） |
| e2e | **37 passed**（含增量分析第一期 2 条 + 第二期 3 条 + 第三期 2 条 + PDF 1 条），一条命令 `.\.venv\Scripts\python.exe scripts\run_e2e.py`（8001/5174 + `aitest_copilot_e2e`） |
| 前端构建 | `npm run build`（`web/` 目录，端口 5173，代理到 8000） |
| 开跑前自检 | `.\.venv\Scripts\python.exe scripts\dev_check.py`（跑 e2e 时加 `--expect-db e2e`） |
| 账号 | `admin` / `Admin12345` |
| 迁移 head | `0016`（06 期 T84 建 `0017`） |
| 截图目录 | 仓库根 `.screenshots/`（`E2E_SCREENSHOT_DIR` 可覆盖） |
| 运行时依赖 | `pdfplumber>=0.11`（T84-PDF 新增）；`httpx` / `cryptography` 在 T84 移入运行时 |
| 环境变量 | `LLM_SECRET_KEY` 已写入本地 `.env`（随机生成，不入库）；`.env.example` 有说明 |

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

## 6. 待办（不属当前冲刺，等用户点头再做）

- 06 期其余任务：T84（配置落库 + 加密 + Provider + JSON 容错）→
  T85（配置与模板管理接口）→ T86（05 运行留痕 + 动态模板下拉）→
  T87（前端系统设置页 + L1/L2 联调收尾）
- PDF 扫描件 OCR（本期只做「无文字层 → 整文单章」降级）
- PDF 表格结构化落库（本期还原成 `a | b` 文本行，与 docx 同构）
- 05 第五期：模板管理 UI 与阈值回填（依赖基准集）
- 修 `tests/projects/` 的 xdist flaky（断言未按项目隔离）
- 前端「来源类型」筛选下拉值是 `'document'`，后端枚举是 `'document_derived'`——**真 bug**，
  选「文档解析」永远 0 条，且无测试覆盖
- 标签清除原因 6 类枚举与 PRD 2.4.2 不符（`priority_changed` / `duplicate_label`
  应为「基线已调整」/「回溯覆盖」）
- 基准集与评估脚本（v2.2 §10；05 的召回策略与切分阈值全靠它回填）
