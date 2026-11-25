# 12 · 章节引用图 AI 分析 · 任务清单

> 配套 [spec.md](./spec.md)（AC-220 ~ AC-228）与 [plan.md](./plan.md)。
> 执行口径一律以 [specs/验证约定.md](../验证约定.md) 为准，本文件不重复展开。
> 每个任务 = 一个提交，提交信息写清「做了什么 / 为什么」。
> **未明确要求不推送、不打 tag。**
> **细颗粒度交付红线**：每个任务改动文件数 **≤ 5**；纯后端接口 / 纯前端组件 / 表结构不混在一个 Task。

## 0. 前置条件与基线（2026-11-25 核实）

| 项 | 基线 |
|---|---|
| 11 收官 | T124–T128 完成，两库 head `0025` |
| 后端全量 | **1444 passed**（串行，e2e 默认 `-m "not e2e"`） |
| e2e 全量 | **64 passed**（`scripts\run_e2e.py`） |
| 前端 | `npm run build` 通过；项目详情 **8 个 Tab** |
| 迁移 head | 两库均 `0025` |
| 用户拍板 | ① 不新建表复用 `document_chapter_links` + `source` 区分来源 ② 分块映射法（≤30000 字整篇 / 超过两阶段） ③ 一并补齐删除能力 |
| AC 编号 | **AC-220 ~ AC-228**（11 期最后一号是 AC-219，必须连续） |
| 任务号 | **T129 ~ T136**（11 期收尾是 T128） |
| 迁移号 | **`0026`**（`down_revision = "0025"`） |

## 1. 执行约定

1. **开跑前自检**：`.\.venv\Scripts\python.exe scripts\dev_check.py`，任一 `[FAIL]` 先修环境。
2. **定向 → 全量 → e2e → 构建**：
   - 定向：`.\.venv\Scripts\python.exe -m pytest tests\incremental -k <关键字> -q`
   - 全量：`.\.venv\Scripts\python.exe -m pytest -m "not e2e"`（**不能用 `-o addopts=`**）
   - e2e：`.\.venv\Scripts\python.exe scripts\run_e2e.py`
   - 构建：`cd web; npm run build; npm run lint`
3. **用例命名**：后端 `test_ac_<AC号>_<场景>`，e2e `test_ac_<AC号>_<场景>_ui`。
4. **零真实 socket**：测试不得出现 `requests` / `urlopen` / `socket.socket`。
5. **不改既有期望值**：既有 1444 条 + 64 条 e2e 一条不删、不改断言。
6. **不回改 05 的判定逻辑**：`extract_links` / `create_link` / `list_links` 一个字节不动。
7. **迁移成对**：downgrade 可执行，两库都做真实往返。
8. **前台必须真点**：前端任务结束在浏览器走一遍，截图落 `.screenshots/<任务号>/`，文件名含 AC 编号。
9. **审计注册表**：新增写操作必须在 `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 里加一项。

## 2. 任务拆分

### T129 数据层：`source='ai'` + 3 个错误码 + 迁移 `0026`

**前置**：`dev_check.py` 全 `[ OK ]`；两库 head `0025`。

**产出**

- `app/models/chapter_link.py`：`CHAPTER_LINK_SOURCES` 加 `'ai'`；`ck_chlinks_source` 扩枚举
- `app/common/errors.py`：`ChapterLinkNotFound` / `ChapterLinkAnalyzeFailed` / `ChapterLinkAnalyzeEmpty` + `__all__`
- `migrations/versions/0026_chapter_link_ai.py`：扩 `ck_chlinks_source`（downgrade 先删 `source='ai'` 再重建旧 CHECK）
- `tests/incremental/test_chapter_link_models.py`（新增）：`source='ai'` 可插 / 非法被拒 3819 / `ck_chlinks_target` 二选一
- `tests/incremental/test_chapter_link_migration.py`（新增）：迁移 head=0026（只断言，往返由验证命令在两库实跑）

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\incremental\test_chapter_link_models.py tests\incremental\test_chapter_link_migration.py -q
.\.venv\Scripts\alembic.exe upgrade head   # current = 0026
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
```

---

### T130 Prompt 模板 + Mock 分支 + `task_type` 扩枚举

**前置**：T129 完成。

**产出**

- `app/models/incremental.py`：`TASK_TYPES` + `ck_ptemplates_task_type` 加 `'chapter_link_analyze'`
- `app/models/llm.py`：`RUN_LOG_TASK_TYPES` + `ck_llmlogs_task_type` 加 `'chapter_link_analyze'`（含补 `test_case` 的漏项）
- `migrations/versions/0026_chapter_link_ai.py`：同一迁移内追加扩 `ck_ptemplates_task_type` + `ck_llmlogs_task_type` + 播种模板
- `app/llm/mock.py`：`CHAPTER_LINK_SYSTEM_PREFIX` + `CHAPTER_LINK_DEFAULT_RESPONSE`（`{"references":[]}`）+ 分支
- `web/src/pages/settings/PromptTemplatePanel.tsx`：`TASK_TYPE_LABELS` 补 5 项（含 `chapter_link_analyze`）

> 合并进 0026 的理由：拆的是任务，不是迁移。若 0026 已发布则新开 0027。

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\llm tests\incremental\test_chapter_link_models.py -q
.\.venv\Scripts\alembic.exe upgrade head; .\.venv\Scripts\alembic.exe downgrade -1; .\.venv\Scripts\alembic.exe upgrade head
```

---

### T131 AI 分析引擎（纯函数 + 分块映射）

**前置**：T130 完成。

**产出**

- `app/incremental/link_analyze.py`（新增，约 320 行）：`analyze()` / `parse_references()` / `build_user_prompt()` / `flatten_chapters()`
- `tests/incremental/test_link_analyze.py`（新增）：越界 id / 自引用 / 非法类型丢弃；根结构错误抛 `LLMOutputInvalid`；阈值两条路径；阶段一块失败只跳过
- `tests/incremental/test_link_analyze_prompt.py`（新增）：Prompt 可复现；截断只砍正文
- `tests/incremental/test_link_analyze_mock.py`（新增）：小文档整篇路径；大文档两阶段 `provider.calls == 块数 + 1`

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\incremental\test_link_analyze.py tests\incremental\test_link_analyze_prompt.py tests\incremental\test_link_analyze_mock.py -q
```

---

### T132 AI 分析服务层 + 路由端点

**前置**：T131 完成。

**产出**

- `app/incremental/links.py`：`analyze_links()`（编排 + 落库幂等）+ `_ai_links_to_rows()`
- `app/incremental/links_router.py`：`POST /analyze`
- `app/incremental/schemas.py`：`ChapterLinkAnalyzeOut`
- `tests/incremental/test_link_analyze_api.py`（新增）：成功 / 幂等 / 人工边不受影响 / 冲突跳过 / 模板缺失 / 越界丢弃 / 权限 / 审计 / 留痕

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\incremental -k "link_analyze" -q
```

---

### T133 删除引用边（服务层 + 路由）

**前置**：T129 完成（可与 T131/T132 并行）。

**产出**

- `app/incremental/links.py`：`delete_link()`
- `app/incremental/links_router.py`：`DELETE /{link_id}` → 204
- `tests/incremental/test_chapter_link_delete.py`（新增）：删除 / 404 / 权限 / 审计
- `tests/common/test_audit_coverage.py`：`SCENARIOS` 加 `"document.chapter_link.delete"`

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\incremental\test_chapter_link_delete.py -q
.\.venv\Scripts\python.exe -m pytest tests\common\test_audit_coverage.py -q
```

---

### T134 前端 API 客户端 + 错误码文案

**前置**：T132 完成。

**产出**

- `web/src/api/index.ts`：`ChapterLink.source` 加 `'ai'`；`analyzeChapterLinks()`；`deleteChapterLink()`
- `web/src/api/client.ts`：`CODE_TEXT` 补 3 个错误码

**验证**

```powershell
cd web; npm run build
```

---

### T135 前端抽屉重构

**前置**：T134 完成。

**产出**

- `web/src/pages/ChapterLinkDrawer.tsx`：头部 AI 按钮 + 提示语 + 表单引导 + 缩进 + 来源列 + 删除列 + 拆 state
- `web/src/pages/incrementalMeta.tsx`：`LINK_SOURCE_META` + `linkSourceTag()`
- `web/src/pages/ProjectDocumentsTab.tsx`：引用图写权限改用 `canManage`
- `web/src/pages/ProjectDetailPage.tsx`：传 `canManage` 给 `ProjectDocumentsTab`

**验证**

```powershell
cd web; npm run build; npm run lint
```

---

### T136 e2e + 文档回填

**前置**：T135 完成。

**产出**

- `tests/e2e/test_chapter_link_ai_ui.py`（新增）：AC-220 ~ AC-227 前台核对
- `tests/e2e/support.py`：`seed_chapter_links` 支持 `source='ai'`
- `tests/e2e/conftest.py`（或 support 的清理清单）：加 `document_chapter_links`（`source='ai'`）+ `llm_run_logs`（`task_type='chapter_link_analyze'`）
- `specs/验证约定.md`：§1 现状 + §5.15 前台核对点
- `PROGRESS.md`：§3 当前状态 + 收官记录

**验证**

```powershell
.\.venv\Scripts\python.exe scripts\run_e2e.py -k chapter_link
.\.venv\Scripts\python.exe scripts\dev_check.py --expect-db e2e
```

## 3. 任务依赖

```
T129 ─┬─→ T130 → T131 → T132 → T134 → T135 → T136
      └─→ T133（可与 T131~T135 并行）
```
