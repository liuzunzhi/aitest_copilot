# AI 辅助测试平台 · 项目地图

> **一句话**：这是一个基于 LLM 的自动化测试辅助平台，主打「文档 → 基线 → 增量 → 用例 → 执行」的闭环——把需求文档喂给大模型，自动长出功能基线、增量影响分析、测试点与测试用例，并接上自动化执行与报告。

- 后端：FastAPI + SQLAlchemy 2.0 + MySQL + Redis + Alembic
- 前端：React 18 + TypeScript + Vite + Ant Design 6
- 大模型：统一 Provider 抽象（OpenAI 兼容协议）+ Mock 实现，测试零真实网络
- 研发方法：Spec Coding（`specs/` 下 spec / plan / tasks 三件套 + 可执行验收标准）

---

## 1. 全局目录树

```
aitest_copilot/
├── app/                          # 后端应用
│   ├── main.py                   # 应用入口 + 全部路由注册
│   ├── common/                   # 通用基建
│   │   ├── config.py             # 配置（.env / 环境变量，必填项缺失即启动失败）
│   │   ├── db.py                 # SQLAlchemy 引擎与会话
│   │   ├── deps.py               # 鉴权依赖 current_user（令牌 → 未吊销 → 未过期 → active）
│   │   ├── permissions.py        # 项目级权限判定（成员 / 管理员 / 可读）
│   │   ├── errors.py             # 全局错误码与异常处理
│   │   ├── audit.py              # 审计写入
│   │   ├── security.py           # 密码哈希、令牌
│   │   ├── settings.py           # 系统配置（落库）
│   │   ├── clock.py / captcha.py / scoped_repo.py
│   ├── models/                   # ORM 模型（新增模型必须在此 import）
│   │   ├── user.py / token.py / project.py / application.py / system.py
│   │   ├── document.py / baseline.py / baseline_derive.py / baseline_review.py
│   │   ├── chapter_link.py / incremental.py / llm.py
│   │   ├── test_point.py / test_case.py / automation.py / process_baseline.py
│   ├── auth/                     # 01 登录、注册、改密、令牌
│   ├── users/                    # 01 用户管理（系统管理员）
│   ├── projects/                 # 02 项目、成员、概览、待办
│   ├── applications/             # 02 项目申请（申请人与项目管理员侧）
│   ├── admin/                    # 02 全局申请审批
│   ├── documents/                # 03 文档上传与解析（docx / pdf）、章节、版本
│   ├── baselines/                # 04 功能基线：模块/功能/功能点、标签、快照、审核、反推
│   ├── incremental/              # 05 增量分析：三阶段分析、二遍裁决、冲突、标签应用
│   │   ├── context.py / context2b.py / engine.py / second_pass.py
│   │   ├── links.py / links_router.py / apply.py
│   ├── llm/                      # 06 大模型底座：Provider、Mock、JSON 容错、加密、留痕
│   ├── llm_admin/                # 06 大模型配置与提示词模板管理（系统设置页）
│   ├── test_points/              # 07 测试点分析
│   ├── test_cases/               # 08 测试用例分析（含 Excel 导出）
│   ├── automation/               # 09 自动化执行：扫描、入库、执行器、报告
│   └── process_baselines/        # 10 流程基线（在建：数据层 + 场景 CRUD 已落地）
│
├── web/                          # 前端
│   └── src/
│       ├── main.tsx / App.tsx    # 路由表
│       ├── api/                  # client.ts（axios 封装 + 错误码中文）+ index.ts（接口与类型）
│       ├── auth/                 # AuthProvider / RequireAuth
│       ├── layout/AppLayout.tsx  # 侧边栏 + 顶栏 + 角色标签
│       └── pages/                # 页面与 Tab 组件
│           ├── ProjectDetailPage.tsx        # 项目详情：10 个顶层 Tab 的宿主
│           ├── ProjectDocumentsTab.tsx / ProjectBaselinesTab.tsx / ProjectBaselineTree.tsx
│           ├── ProjectIncrementalTab.tsx / ProjectTestPointsTab.tsx / ProjectTestCasesTab.tsx
│           ├── ProjectAutomationTab.tsx / ProjectTodoCard.tsx
│           └── settings/         # LlmProviderPanel / PromptTemplatePanel
│
├── migrations/                   # Alembic 迁移（当前 head = 0025）
│   ├── env.py
│   └── versions/0001_baseline.py … 0025_process_baselines.py
│
├── tests/                        # 后端测试 + Playwright 前台 e2e
├── specs/                        # 各期 spec / plan / tasks（与代码同库提交）
├── scripts/                      # dev_check.py / run_e2e.py / check_migration_roundtrip.py
├── pyproject.toml / alembic.ini
└── PROGRESS.md                   # 开发进展看板（每次开工前必读）
```

---

## 2. 核心模块指南（01 ~ 10 期）

> 快速定位：后端 Router（前缀）→ 核心 Service → 前端 Tab 入口。

| 期 | 模块 | 后端 Router | 核心 Service / 引擎 | 前端入口 |
|---|---|---|---|---|
| 01 | **Auth** 登录注册 | `app/auth/router.py`<br>`/api/auth` | `app/auth/service.py`、`app/auth/tokens.py` | `pages/LoginPage.tsx`<br>`auth/AuthProvider.tsx` |
| 02 | **Projects** 项目与申请 | `app/projects/router.py`（`/api/projects`）<br>`app/applications/router.py`（`/api/applications`）<br>`app/admin/applications_router.py`（`/api/admin`）<br>`app/users/router.py`（`/api/admin/users`） | `app/projects/service.py`、`query_service.py`、`apply_service.py` | `pages/ProjectListPage.tsx`<br>`AvailableProjectsPage.tsx`、`MyApplicationsPage.tsx`、`AdminApplicationsPage.tsx`、`AdminUsersPage.tsx` |
| 03 | **Documents** 文档解析 | `app/documents/router.py`（`/api/projects/{id}/documents`） | `app/documents/service.py`、`parser.py`、`pdf.py` | 项目详情 **「文档」Tab**<br>`ProjectDocumentsTab.tsx` |
| 04 | **Baseline** 功能基线 | `app/baselines/router.py`（`/api/projects/{id}/baselines/...`） | `app/baselines/service.py`（模块/功能/功能点、标签、快照、审核）、`derive.py`（反推引擎）、`approval.py`、`references.py`、`constants.py` | 项目详情 **「基线管理」Tab**<br>`ProjectBaselineTree.tsx`、`ProjectBaselineSnapshots.tsx`、`BaselineDeriveDrawer.tsx`、`BaselineReviewDrawer.tsx` |
| 05 | **Incremental** 增量分析 | `app/incremental/router.py`（`/api/projects/{id}/incremental`）<br>`app/incremental/links_router.py`（`.../documents/{id}/versions/{vid}/links`） | `app/incremental/service.py`、`engine.py`（章节循环）、`context.py` / `context2b.py`（上下文与 Prompt）、`second_pass.py`（二遍裁决）、`apply.py`（标签落库）、`links.py` | 项目详情 **「增量分析」Tab**<br>`ProjectIncrementalTab.tsx`、`IncrementalSecondPass.tsx`、`IncrementalApply.tsx`、`ChapterLinkDrawer.tsx` |
| 06 | **LLM** 大模型与模板 | `app/llm_admin/router.py`<br>`admin_router`（`/api/admin/llm-providers`、`/api/admin/prompt-templates`）<br>`templates_router`（`/api/prompt-templates`） | `app/llm_admin/provider_service.py`、`template_service.py`；底座 `app/llm/provider.py`、`mock.py`、`json_utils.py`、`crypto.py`、`run_log.py` | **「系统设置」页**<br>`pages/settings/LlmProviderPanel.tsx`、`PromptTemplatePanel.tsx` |
| 07 | **TestPoints** 测试点 | `app/test_points/router.py`（`/api/projects/{id}/test-points`） | `app/test_points/service.py`、`engine.py`（纯函数）、`context.py` | 项目详情 **「测试点」Tab**<br>`ProjectTestPointsTab.tsx`、`TestPointDrawer.tsx` |
| 08 | **TestCases** 测试用例 | `app/test_cases/router.py`（`/api/projects/{id}/test-cases`） | `app/test_cases/service.py`、`engine.py`、`context.py`、`fingerprint.py`（SHA-256 待复核判定）、`labels.py`、`exporter.py`（Excel 导出） | 项目详情 **「测试用例」Tab**<br>`ProjectTestCasesTab.tsx`、`TestCaseDrawer.tsx`、`TestCaseStepsEditor.tsx` |
| 09 | **Automation** 自动化执行 | `app/automation/router.py`（`/api/projects/{id}/automation`） | `app/automation/service.py`（扫描入库、执行编排、报告）、`scanner.py`（纯函数扫描）、`runner.py`（pytest 执行器） | 项目详情 **「自动化执行」Tab**<br>`ProjectAutomationTab.tsx`、`AutomationScanModal.tsx`、`AutomationReportDrawer.tsx` |
| 10 | **ProcessBaseline** 流程基线 | `app/process_baselines/router.py`（`/api/projects/{id}/process-baselines`） | `app/process_baselines/service.py`（场景 CRUD、步骤覆盖、关联）、`derive.py`（反推，待落地）、`schemas.py` | 计划挂在 **「基线管理」Tab** 内二级子菜单<br>（`ProjectBaselineManagementTab.tsx`，待落地） |

### 通用约定

- **权限判定顺序统一为**：`项目 404 → 归档 409 → 角色 403 → 业务校验 400`（见 `app/common/permissions.py`）。
- **路由统一前缀**：`/api/projects/{project_id}/...`；系统级为 `/api/admin/...`。
- **引擎层是纯函数**：签名里没有 `session`，不写库，便于不起 HTTP、不起数据库地逐条断言（`app/*/engine.py`、`app/automation/scanner.py`）。
- **错误码统一**：`app/common/errors.py` 集中定义，前端在 `web/src/api/client.ts` 里配中文文案。
- **前端 Tab 宿主**：项目详情页 `web/src/pages/ProjectDetailPage.tsx`（顶层 8 个 Tab：概览 / 文档 / 基线管理 / 增量分析 / 测试点 / 测试用例 / 自动化执行 / 成员——「成员」内含二级子菜单「成员列表」/「加入申请」；「版本快照」并入「文档」Tab 内的卡片）。

---

## 3. 测试体系

### 目录分布（`tests/`，共 1407 条）

| 目录 | 条数 | 覆盖 |
|---|---|---|
| `tests/llm/` | 174 | Provider 工厂、OpenAI 兼容、JSON 容错（thinking / code fence）、密钥加解密、模板与运行留痕 |
| `tests/projects/` | 160 | 项目 CRUD、成员与角色、项目隔离、申请与审批、概览、待办计数 |
| `tests/incremental/` | 154 | 一遍/二遍/产出段、冲突裁决、章节链接、标签应用、权限、状态机 |
| `tests/automation/` | 141 | 扫描路径安全、入库、资产 CRUD、执行器超时与死锁防护、报告追溯 |
| `tests/test_cases/` | 141 | 用例生成引擎、步骤覆盖、评审、待复核指纹、Excel 导出、权限 |
| `tests/baselines/` | 115 | 模块/功能/功能点 CRUD、标签、快照、审核、反推、保留策略 |
| `tests/test_points/` | 101 | 测试点生成引擎、评审、待复核、留痕、权限 |
| `tests/process_baselines/` | 90 | 流程基线数据层与迁移、场景 CRUD、步骤覆盖、关联（10 期在建） |
| `tests/common/` | 81 | 审计覆盖、权限、安全、配置、验证码 |
| `tests/documents/` | 77 | 上传、解析、章节、版本激活/作废、下载、概览计数 |
| `tests/auth/` | 58 | 注册、登录、登出、令牌、改密、密码重置、守卫 |
| `tests/users/` | 33 | 用户管理、角色 |
| `tests/integration/` | 3 | 审计链路贯通 |
| `tests/test_config.py` / `test_db.py` / `test_models.py` | 21 | 配置、连接、模型基线 |
| `tests/e2e/` | **58** | Playwright 前台用例（真实浏览器，独立执行） |

### 规模与执行方式

- **当前规模：后端 1349 条（`pytest` 全量）+ e2e 58 条 = 1407 条**，覆盖 01 ~ 10 期全部模块。
- 后端与 e2e **分开跑**：平台 `addopts` 含 `-m 'not e2e'`，全量 pytest 默认自动排除 e2e。

```powershell
# 后端全量（串行，禁止用 -n auto）
.\.venv\Scripts\python.exe -m pytest

# e2e 全量（自动起 8001/5174，指向 e2e 库）
.\.venv\Scripts\python.exe scripts\run_e2e.py

# 开跑前环境自检
.\.venv\Scripts\python.exe scripts\dev_check.py            # dev 库
.\.venv\Scripts\python.exe scripts\dev_check.py --expect-db e2e
```

- 命名约定：后端 `test_ac_<AC号>_<场景>`，e2e `test_ac_<AC号>_<场景>_ui`，与 `specs/` 的验收标准一一对应。
- **零真实 socket**：所有 LLM 相关测试一律走 `httpx.MockTransport` 或 Mock Provider。

---

## 4. 快速启动

### 4.1 后端

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 首次准备配置（复制后填 DB_DSN / LLM_SECRET_KEY）
Copy-Item .env.example .env

# 启动（开发模式）
uvicorn app.main:app --reload --port 8000
```

健康检查：

```powershell
curl http://localhost:8000/health
# {"status":"ok"}
```

接口文档：<http://localhost:8000/docs>

### 4.2 前端

```powershell
cd web
npm install
npm run dev            # http://localhost:5173，/api 自动代理到 127.0.0.1:8000
```

生产构建与代码检查：

```powershell
npm run build
npm run lint
```

### 4.3 数据库迁移（Alembic）

DSN 从 `.env` 读取（`alembic.ini` 里不写连接串）。当前 head = **0025**。

```powershell
# 应用到最新
alembic upgrade head

# 查看当前版本 / 历史
alembic current
alembic history

# 回退一版 / 回退到指定版本
alembic downgrade -1
alembic downgrade 0024
```

迁移往返检查（两库都跑，验证 downgrade 干净）：

```powershell
.\.venv\Scripts\python.exe scripts\check_migration_roundtrip.py
```

### 4.4 环境要求

- Python 3.11+、Node.js 20+
- MySQL 8.0（开发库 `aitest_copilot_v2` / e2e 库 `aitest_copilot_e2e`）
- Redis 7

---

## 5. 开发约定

- **时间一律 UTC**：数据库连接建立后强制 `SET time_zone = '+00:00'`。
- **规格先行**：任何新能力先在 `specs/<期号>-<名字>/` 落 spec / plan / tasks，再写代码。
- **一任务一提交**：提交信息写清「做了什么 / 为什么」；相关改动按逻辑范围拆多个提交。
- **红线不可越**：跨期改动只允许极窄例外（如 `app/llm/mock.py` 新增 Mock 前缀分支），需在 `specs/` 中显式声明。
- **`specs/` 随代码提交**；`doc/` 与 `.trae/` **不入版本控制**。
- 开工前先读 [PROGRESS.md](file:///d:/aitest_copilot/PROGRESS.md) 与 [specs/验证约定.md](file:///d:/aitest_copilot/specs/验证约定.md)。
