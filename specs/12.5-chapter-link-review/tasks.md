# 12.5 · 章节引用图 UX 补丁 · 任务清单

> 配套 [spec.md](./spec.md)（AC-229 ~ AC-239）与 [plan.md](./plan.md)。
> 执行口径一律以 [specs/验证约定.md](../验证约定.md) 为准，本文件不重复展开。
> 每个任务 = 一个提交，提交信息写清「做了什么 / 为什么」。
> **未明确要求不推送、不打 tag。**
> **细颗粒度交付红线**：每个任务改动文件数 **≤ 5**；
> 纯后端接口 / 纯前端组件 / 表结构不混在一个 Task。

## 0. 前置条件与基线（2026-11-26 核实）

| 项 | 基线 |
|---|---|
| 12 收官 | T129–T136 完成，两库 head `0027` |
| 后端全量 | **1533 passed**（串行，e2e 默认 `-m "not e2e"`） |
| e2e 全量 | **70 passed**（`scripts\run_e2e.py`） |
| 前端 | `npm run build` 通过；项目详情 **8 个 Tab** |
| 迁移 head | 两库均 `0027` |
| 用户拍板 | ① 待评审状态（AI 边先入待评审区，人工勾选确认 / 批量采纳后才生效）② 状态提示语状态驱动 ③ AI 分析期间锁抽屉 ④ 删前端「按规则重抽」入口（后端 `extract_links` 保留）⑤ 补表单引导文案 ⑥ 加「详情」按钮展示 rationale + confidence |
| AC 编号 | **AC-229 ~ AC-239**（12 期最后一号是 AC-228，必须连续） |
| 任务号 | **T137 ~ T144**（12 期收尾是 T136） |
| 迁移号 | **`0028`**（`down_revision = "0027"`） |

## 1. 执行约定

1. **开跑前自检**：`.\.venv\Scripts\python.exe scripts\dev_check.py`，任一 `[FAIL]` 先修环境。
2. **定向 → 全量 → e2e → 构建**：
   - 定向：`.\.venv\Scripts\python.exe -m pytest tests\incremental -k <关键字> -q`
   - 全量：`.\.venv\Scripts\python.exe -m pytest -m "not e2e"`（**不能用 `-o addopts=`**）
   - e2e：`.\.venv\Scripts\python.exe scripts\run_e2e.py`
   - 构建：`cd web; npm run build; npm run lint`
3. **用例命名**：后端 `test_ac_<AC号>_<场景>`，e2e `test_ac_<AC号>_<场景>_ui`。
4. **零真实 socket**：测试不得出现 `requests` / `urlopen` / `socket.socket`。
5. **不改既有期望值**：既有 1533 条 + 70 条 e2e 一条不删、不改断言，
   **例外只有 [spec.md §8.1](./spec.md) 列出的 3 处**（本期 spec 明确改变了契约，
   已逐条说明原因，**需用户 review 时一并裁决**）。
6. **不改 05 / 12 的判定逻辑**：`extract_links` / `_collect` / 正则 /
   `link_analyze.py` 引擎 / `app/llm/mock.py` 一个字节不动。
7. **迁移成对**：downgrade 可执行，两库都做真实往返，
   并**实跑核对**存量行回填值（不是只看 alembic 版本号）。
8. **前台必须真点**：前端任务结束在浏览器走一遍，截图落 `.screenshots/<任务号>/`，文件名含 AC 编号。
9. **审计注册表**：新增写操作必须在 `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 里加一项。
10. **强制节点汇报**：多文件 / 多表任务分步汇报（先报「已完成模型与迁移」，
    等确认再报「已完成接口编写」），不要一次性甩全套代码。

---

## 2. 任务拆分

### T137 数据层：`status` + `rationale` 两列 + 迁移 `0028`

**前置**：`dev_check.py` 全 `[ OK ]`；两库 head `0027`。

**产出**（4 个文件）

- `app/models/chapter_link.py`：`CHAPTER_LINK_STATUSES` + `status` 列 + `rationale` 列 + `ck_chlinks_status`
- `migrations/versions/0028_chapter_link_review_status.py`（新建）：
  upgrade 四步（加可空列 → 加 rationale → 加 CHECK → 收紧非空）；
  downgrade 三步（**先删 pending 行** → 删 CHECK → 删两列）
- `tests/incremental/test_chapter_link_review_migration.py`（新建）：
  列集合 = 12 列 / CHECK 扩枚举 / 存量回填 `'approved'` / head = `0028`
- `tests/incremental/test_chapter_link_migration.py`（改）：§8.1 第 1、2 条

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\incremental\test_chapter_link_review_migration.py tests\incremental\test_chapter_link_migration.py -q
.\.venv\Scripts\alembic.exe upgrade head    # current = 0028
.\.venv\Scripts\alembic.exe downgrade -1     # 0027
.\.venv\Scripts\alembic.exe upgrade head    # 0028
```

**实跑核对**（不是只看版本号）：

```sql
-- 升级后存量行的 status 全是 'approved'（造存量数据后跑）
SELECT status, COUNT(*) FROM document_chapter_links GROUP BY status;
-- 降级后列集合回到 10 列，且没有 status IS NULL 的孤儿行
```

---

### T138 图传播只读生效边（AC-231）

**前置**：T137 完成。

**产出**（2 个文件）

- `app/incremental/second_pass.py`：`build_point_index` 的链接查询**加一个条件**
  `DocumentChapterLink.status == "approved"`
- `tests/incremental/test_chapter_link_review_propagation.py`（新建）：
  `pending` 边**不产生** `possible_impact`；改成 `approved` 后**产生**

> **本任务只做这一件事**：让「待评审」在语义上真的成立。
> 漏了这一条，「待评审」就只是前端的一个分区标签。

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\incremental\test_chapter_link_review_propagation.py tests\incremental\test_second_pass_propagation.py -q
```

---

### T139 AI 分析落待评审 + 采纳服务层

**前置**：T137 完成。

**产出**（2 个文件）

- `app/incremental/links.py`：
  - `_persist_ai_links`：只删 `status='pending'` 的旧行；插入时写 `status='pending'` +
    `rationale`；跳过「已存在的同一条边」（不论来源/状态）
  - `create_link`：`status='approved'`
  - 新增 `approve_link()`（幂等）与 `approve_links_batch()`（整批原子）
- `tests/incremental/test_chapter_link_review.py`（新建）：
  分析落 `pending` / 采纳幂等 / 批量原子 / 批量含不存在的 id → 整批 404 /
  重新分析不冲掉已采纳的边 / 人工边与规则边默认 `approved`

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\incremental\test_chapter_link_review.py -q
```

---

### T140 采纳接口 + 列表扩字段 + 审计

**前置**：T139 完成。

**产出**（4 个文件）

- `app/incremental/links_router.py`：
  `POST /{link_id}/approve`（200 `ChapterLinkOut`）、
  `POST /approve-batch`（200 `{"approved_count": N}`）
- `app/incremental/schemas.py`：`ChapterLinkOut` 扩 `status` / `rationale`；
  新增 `ChapterLinkApproveBatchIn` / `ChapterLinkApproveBatchOut`
- `tests/incremental/test_chapter_link_review_api.py`（新建）：
  权限矩阵 / 审计 / 列表带 status / 跨版本 id → 404 / 空数组 → 400
- `tests/common/test_audit_coverage.py`：`SCENARIOS` 加 `"document.chapter_link.approve"`

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\incremental\test_chapter_link_review_api.py tests\common\test_audit_coverage.py -q
```

---

### T141 前端 API 客户端 + 状态标签

**前置**：T140 完成。

**产出**（2 个文件）

- `web/src/api/index.ts`：`ChapterLink` 扩 `status` / `rationale`；
  新增 `approveChapterLink()` / `approveChapterLinksBatch()`
- `web/src/pages/incrementalMeta.tsx`：`LINK_STATUS_META` + `linkStatusTag()`

> **`web/src/api/client.ts` 本期零改动**（本期零新增错误码，无新文案要配）。
> 这是**刻意不改**，不是漏改——T141 完成后用 `git diff --stat` 核对。

**验证**

```powershell
cd web; npm run build
```

---

### T142 前端抽屉三区 + 状态提示 + 锁屏 + 删重抽 + 表单引导

**前置**：T141 完成。

**产出**（3 个文件）

- `web/src/pages/ChapterLinkDrawer.tsx`：
  - 三区布局（待评审区 / 已生效区 / 补链表单）
  - 状态驱动的提示语（`chapter-link-hint`）
  - `ConfigProvider componentDisabled={analyzing}` 锁抽屉 + 补链按钮显式 disabled
  - 删「按规则重抽」按钮 + `extracting` state + `reExtract()`
  - 三个 `Form.Item` 加 `extra` 说明；类型下拉两行式 `optionRender`
  - 批量采纳（全选复选框 + 按钮）
- `web/src/pages/ChapterLinkTable.tsx`（新建）：表格组件（两个区共用列定义）
- `web/src/pages/ChapterLinkDetailModal.tsx`（新建）：详情弹窗

> **`web/src/api/index.ts` 本任务不动**（T141 已改完）。
> 本期前端**不引入新依赖**，`web/package.json` 不动。

**验证**

```powershell
cd web; npm run build; npm run lint
```

---

### T143 e2e 前台核对 + 既有 e2e testid 更新

**前置**：T142 完成。

**产出**（4 个文件）

- `tests/e2e/test_chapter_link_review_ui.py`（新建）：
  AC-233（状态提示语三态）/ AC-234（分析期间锁抽屉）/ AC-235（无重抽按钮）/
  AC-236（表单引导）/ AC-237（详情弹窗）/ AC-238（权限）
- `tests/e2e/test_chapter_link_ai_ui.py`（改）：§8.1 第 3 条——
  `chapter-link-ai-hint` → `chapter-link-hint`，**文案断言不动**
- `tests/e2e/support.py`（改）：`seed_chapter_links` 支持 `status` / `rationale`
- `tests/process_baselines/test_migration.py`（改）：§8.1 第 2 条——head = `0028`

> **T142 实测发现：12 期 e2e 有 3 类改动绕不过去**（都属于 WIP 重构的直接后果，
> 不是「为了让代码通过而改断言」）：
>
> 1. **`_open_link_drawer` 返回的 `chapter-link-table` 已不存在**——
>    表格拆成 `chapter-link-pending-table` / `chapter-link-effective-table` 两张。
>    改法：返回抽屉容器 `.ant-drawer-body`，或在各用例里按需定位具体那张表。
> 2. **`chapter-link-ai-hint` → `chapter-link-hint`**（提示语不再「AI 专用」）。
> 3. **`test_ac_220` 的文案断言需要先造「已生效」的边**——
>    新逻辑下「空数据」显示的是「当前版本还没有引用关系……」，
>    「系统已通过 AI 自动识别……」只在「无待评审 + 有已生效边」时出现。
>    **文案本身一字不改**，只是从「永远显示」变成「条件显示」，
>    所以用例要先 `seed_chapter_links(..., status="approved")` 再断言。
**验证**

```powershell
.\.venv\Scripts\python.exe scripts\run_e2e.py -k chapter_link
```

---

### T144 收尾：文档回填 + 全量回归

**前置**：T143 完成。

**产出**（3 个文件）

- `specs/验证约定.md`：§1 现状 + §5.16 前台核对点
- `PROGRESS.md`：§2 进度看板 + §3 当前冲刺任务
- `README.md`：测试条数、迁移 head 更新

**验证**

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not e2e"     # 全量，只增不减
.\.venv\Scripts\python.exe scripts\run_e2e.py          # e2e 全量
.\.venv\Scripts\python.exe scripts\check_migration_roundtrip.py   # 两库往返
cd web; npm run build; npm run lint
```

---

## 3. 任务依赖

```
T137 ─┬─→ T138（传播过滤）
      ├─→ T139（服务层）→ T140（接口）→ T141（前端 API）→ T142（抽屉 UI）→ T143（e2e）→ T144（收尾）
      └─→ （T138 与 T139/T140 可并行）
```

---

## 4. 红线自检清单（每任务完成时逐条核对）

| # | 红线 | 怎么验 |
|---|---|---|
| 1 | `extract_links` / `_collect` / 正则**一个字节不动** | `git diff --stat app/incremental/links.py` 只应看到 `_persist_ai_links` 与 `create_link` 的改动 |
| 2 | `link_analyze.py` 引擎**零改动** | `git diff --stat app/incremental/link_analyze.py` 为空 |
| 3 | `app/llm/mock.py` **零改动** | `git diff --stat app/llm/mock.py` 为空 |
| 4 | `app/common/errors.py` **零改动** | 本期零新增错误码 |
| 5 | `app/incremental/service.py` **零改动** | `_ensure_rule_links` 口径不变 |
| 6 | 05 期第二遍**判定逻辑与错误码**不变 | `second_pass.py` 只加了**一个** where 条件 |
| 7 | 存量行迁移后**全是 `approved`** | 造存量数据实跑 `SELECT status, COUNT(*) ...` |
| 8 | 唯一键**未改** | `uk_chlinks_to_chapter` / `uk_chlinks_entity` 定义不动 |
| 9 | 既有测试**只改 spec §8.1 列的 3 处** | `git diff tests/` 逐个核对 |
| 10 | **零真实 socket** | 全量 pytest 无网络访问 |

---

## 5. 验证记录

| 任务 | 验证命令 | 结果 |
|---|---|---|
| T137 | `pytest tests\incremental\test_chapter_link_review_migration.py tests\incremental\test_chapter_link_migration.py -q` | **16 passed**；两库 `0028 → 0027 → 0028` 往返干净；存量 19 行全回填 `approved`（无 NULL） |
| T138 | `pytest tests\incremental\test_chapter_link_review_propagation.py -q` | **5 passed**；`test_second_pass_*` 23 条零回归；后端全量 **1545 passed** |
| T139 | `pytest tests\incremental\test_chapter_link_review.py -q` | **14 passed**；`tests\incremental` 263 条全绿；后端全量 **1559 passed** |
| T140 | `pytest tests\incremental\test_chapter_link_review_api.py tests\common\test_audit_coverage.py -q` | **14 + 69 passed**；后端全量 **1574 passed** |
| T141 | `cd web; npm run build; npm run lint` | 构建通过；lint **0 errors**（36 warnings 为既有 React hooks 提示） |
| T142 | `cd web; npm run build; npm run lint` | 构建通过；lint **0 errors**（36 warnings，与 12 期同数，**零新增**） |
| T143 | `scripts\run_e2e.py -k chapter_link` → 全量 | **14 passed**（chapter_link 子集）；e2e 全量 **77 passed**；截图 7 张落 `.screenshots/T143/` |
| T144 | 全量 pytest + `run_e2e.py` + `check_migration_roundtrip.py` | 后端 **1574 passed**；e2e **77 passed**；两库往返干净；build/lint 通过 |

---

## 6. 实施中调整的地方（与原计划有出入，以本节为准）

| # | 原计划 | 实际做法 | 原因 |
|---|---|---|---|
| 1 | `op.alter_column` 不写 `existing_type` | **显式写 `existing_type=sa.String(16)`** | MySQL 的 CHANGE/MODIFY COLUMN 要求带上已有类型，alembic 不自动推断；不写会报 `All MySQL CHANGE/MODIFY COLUMN operations require the existing type`，且 DDL 非事务导致前 3 步已执行、版本号没升的半成品状态（已手工清理后重跑） |
| 2 | `test_ac_197_migration_head_is_0027` 放在 **T143** 改 | **提前到 T138 改**（T137 升 head 后立刻改） | head 断言是 T137 的**直接后果**，放到 T143 会让 T137/T138 的全量验证一直红，等于「明知过期却不修」 |
| 3 | 未提及开发库脏数据 | **清理了 1 条历史残留**（`project_applications.id=16660`，admin 对测试项目「流程基线项目-29d14e」的 pending 加入申请，2026-11-26 遗留） | 它不属于任何业务，却让 02 期 `test_ac_43` / `test_ac_44` / `test_ac_18` 三条既有用例永久红。**记录备查：删的是 pending 申请行，非业务数据** |
| 4 | T143 只计划改 3 个 e2e 相关文件 | **实际改了 4 个**：多出 `tests/e2e/test_incremental_second_pass_ui.py` | 05 期第二期的 `test_ac_86_chapter_link_ui` 也在用 `chapter-link-table` 定位，同样被表格拆分打破（实跑才发现） |
| 5 | AC-238 写「访客看不到详情按钮」，但 T142 实现里详情按钮无条件渲染 | **T143 补了 `canWrite` 限制**（改 `ChapterLinkTable.tsx`） | 让实现回归 spec 契约；访客无操作列内容，与 12 期「访客只有只读列表」一致 |
