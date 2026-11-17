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
- [x] 03-documents (文档解析)
- [x] 04-baseline (基线管理、快照、标签) —— **已完成（含 T67 收尾）**
- [x] 05-increment-analysis (增量分析) —— **第一期完成（T68~T70）**
- [ ] 06 及后续模块 —— ****[TBD 待定，严禁 AI 擅自规划]****

## 3. 当前冲刺任务（⚠️ 务必先做这个）

**当前目标**：05 增量分析——第一期只做「第一遍 · 章节局部比对」。

> 04 遗留收尾已全部完成（见第 5 节），**现在可以开 05**。

### 范围（极简，不可扩大）

- 只做**第一遍 · 章节局部比对**：章节 → LLM 比对 → 局部结论落库。
- **零真实网络请求**：LLM 调用走 `LLMProvider` 抽象，本期只实现 `MockProvider`。
- 表结构**只建三张表**：`prompt_templates`、`incremental_analyses`、`incremental_conclusions`。

### 红线（违反即返工）

1. **不许写任何真实的网络请求代码**——不许引入 `openai` / `httpx` 调模型，不许写 `requests.post`。
   本期 `LLMProvider` 只有 `MockProvider` 一个实现。
2. **不许做模板管理 UI**——提示词模板只落库 + 被读取，不做增删改查页面。
3. **不许做全局裁决**（v2.2 §4.2 的 2b-1 / 2b-2 / 2b-3）——那是下一期的事。
4. **不许写第二遍**——第一遍产出直接落 `incremental_conclusions`。
5. 不许顺手修无关模块（例：03 的 PDF 解析、清除原因枚举对齐）——记到待办里，等用户点头。

### 三个 Task

| Task | 内容 | 关键产出 |
|---|---|---|
| **T68 · 建表与 Mock** | 三张表 + 迁移 `0013_incremental`；`app/llm/` 抽象与 `MockProvider`；`app/incremental/` 骨架 | `MockProvider` 能返回固定 JSON；表约束（唯一键 / 外键 / 默认值）有对应用例 |
| **T69 · 后端第一遍业务流** | `engine.py` 第一遍 + `service.py` + `router.py` + 错误码 + 审计 | **两个核心 AC 的用例**（见下） |
| **T70 · 前端最小展示** | 项目详情页第 7 个 Tab「增量分析」+ API 分节 + 错误码映射 | `npm run build` 通过；e2e 前台用例 |

### 两个核心 AC（必须覆盖，不可省略）

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

> AC-② 的可测性依赖 Mock 暴露「收到的请求」——`LLMResponse.raw` 或等价手段，
> 用例据此断言，而不是靠日志或 mock 打补丁。

## 4. 环境与验证现状

| 项 | 值 |
|---|---|
| 后端全量 pytest | **516 passed**（串行；T70 后） |
| e2e | 31 条（含增量分析 2 条），一条命令 `.\.venv\Scripts\python.exe scripts\run_e2e.py`（8001/5174 + `aitest_copilot_e2e`） |
| 前端构建 | `npm run build`（`web/` 目录，端口 5173，代理到 8000） |
| 开跑前自检 | `.\.venv\Scripts\python.exe scripts\dev_check.py`（跑 e2e 时加 `--expect-db e2e`） |
| 账号 | `admin` / `Admin12345` |
| 迁移 head | `0013`（05 增量分析三表） |
| 截图目录 | 仓库根 `.screenshots/`（`E2E_SCREENSHOT_DIR` 可覆盖） |

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

## 6. 待办（不属当前冲刺，等用户点头再做）

- 修 `tests/projects/` 的 xdist flaky（断言未按项目隔离）
- 03 的 PDF 解析（PRD 2.4.1 要求支持 pdf，当前只支持 md/docx/txt；需新增 `pypdf` 依赖，
  并改写 AC-50 已通过的前台用例）
- 前端「来源类型」筛选下拉值是 `'document'`，后端枚举是 `'document_derived'`——**真 bug**，
  选「文档解析」永远 0 条，且无测试覆盖
- 标签清除原因 6 类枚举与 PRD 2.4.2 不符（`priority_changed` / `duplicate_label`
  应为「基线已调整」/「回溯覆盖」）
- 基准集与评估脚本（v2.2 §10；05 的召回策略与切分阈值全靠它回填）
