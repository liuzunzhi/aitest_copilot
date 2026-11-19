# 07 · 测试点分析 · 任务清单

> 规格 [spec.md](./spec.md) ｜ 方案 [plan.md](./plan.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)

## 执行约定

1. 每个任务开跑前先 `.\.venv\Scripts\python.exe scripts\dev_check.py`，有 `[FAIL]` 先修环境。
2. 定向用例跑 `-k ac_14X`，通过后再跑全量（**串行**，避免 `tests/projects/` 的既有 xdist flaky）。
   全量基线 **966 passed**，数量只增不减。
3. 改了前端就 `cd web; npm run build`；有前台交互就补 e2e 用例并截图到 `.screenshots/T10x/`。
4. **每个任务一个提交**，提交信息写清「做了什么 / 为什么」。
5. 测试名带 AC 编号（`test_ac_141_analysis_and_points_persisted`）。
6. **断网红线**：任何一条测试都**不允许产生真实 socket**。真实 Provider 的测试一律 `httpx.MockTransport`。

## 前置条件

| 项 | 状态 |
|---|---|
| 01–06 模块 | T01–T98 已验收（06 到 T87，04 到 T98） |
| 后端基线 | **966 passed**（2026-11-19，07 期收官；e2e 默认 `-m "not e2e"`） |
| e2e 基线 | **42 passed** |
| 前端 | `D:\aitest_copilot\web`；项目详情页含「概览 / 成员 / 文档 / 版本快照 / 基线管理 / 申请 / 增量分析 / 测试点」8 个 Tab |
| 数据库迁移 head | `0022`（07 建 `0022`） |
| 可复用资产 | 06 的 `LLMProvider` / `get_provider` / `parse_llm_json` / `record_run`；04 的 `approved_entities()` / `clear_label()`；`prompt_templates.task_type='test_point'` 枚举已预留（`0013`） |

## 本期红线（违反即返工）

- **不做 Skill 模式**（PRD 2.5 的 Skill 包 / manifest / schema 校验 / 回退开关）。
- **不做测试用例分析**（08 期）、不做自动化执行、不做测试报告。
- **不做「无基线直接对文档分析」**：输入（增量结论 / 生效标签）为空 → 400 `TEST_POINT_INPUT_EMPTY`。
- **不做工作台待办接入**、不做流程基线、不做 Token 计费。
- **不改 04 / 05 的判定逻辑**——只允许两处例外，且逐条列明：
  1. `app/baselines/service.py` 的 `clear_label()` 成功后补一行「标记下游测试点待复核」
     （表探测保护，07 迁移前后 04 都能跑）；
  2. 05 的 5 个权限函数**纯搬迁**到 `app/common/permissions.py`（函数体不改，05 保留别名导出）。
- **不改 `app/llm/` 的 Provider / 解析 / 留痕**——只允许 `app/llm/mock.py` 加一个前缀分支。
- **测试不允许产生真实 socket**。

## 任务

- [x] **T99 · 建表与迁移（`0022`）**（2026-11-19 完成）
  - 内容：
    - `app/models/test_point.py`（新增）：`TestPointAnalysis`（表 `test_point_analyses`）+
      `TestPoint`（表 `test_points`），字段 / 索引 / CheckConstraint 严格对齐 spec §4；
      注册到 `app/models/__init__.py` 的 import 与 `__all__`。
    - `migrations/versions/0022_test_points.py`（新增）：`down_revision="0021"`；
      两表按外键顺序建（`test_point_analyses` → `test_points`）、
      `downgrade` 反序直接删表（不逐个 `drop_index`，避免 MySQL 1553）。
    - **扩 `llm_run_logs` 的 CHECK**：`ck_llmlogs_task_type` 加 `'test_point'`。
      MySQL 不允许直接改 CHECK → **先 `drop_constraint` 再 `create_check_constraint`**；
      `downgrade` 反向。
    - **播种模板**：`prompt_templates` 插 1 条 `task_type='test_point'`，
      `system_prompt` 以 `[TEST_POINT_SYSTEM]` 开头、`user_prompt` 以 `[TEST_POINT_USER]` 开头；
      **JSON 示例里的 `target_id` 必须写 `123`**（真实模型会照抄示例值）；
      `downgrade` 里 `DELETE ... WHERE name = :name`。
    - `app/common/errors.py`：新增 9 个错误类（spec §6.3），同步 `__all__`。
  - 产出：AC-141（表结构部分）/ AC-154（枚举）/ AC-156（模板播种）可断言。
  - 验证：
    - `tests/test_points/test_models.py`——表约束（CK / 索引 / 枚举）；
    - `alembic downgrade 0021 → upgrade head` **往返**（两个库都跑）；
    - **确认 `llm_run_logs.task_type` 枚举扩充无误**：
      查 `information_schema.CHECK_CONSTRAINTS` 看新约束文本，
      并实际插入一条 `task_type='test_point'` 的留痕（应成功）、一条 `task_type='bogus'`（应被拒）。
    - 模板播种断言：`prompt_templates` 里 `task_type='test_point'` 有且仅有 1 条 active。
  - 前台：本期无页面。

- [x] **T100 · 上下文组装 + 引擎**（2026-11-19 完成）
  - 内容：
    - `app/test_points/context.py`：`build_system_prompt` / `render_target_brief` /
      `render_label_brief` / `render_conclusion_brief` / `build_user_prompt` /
      `active_label_context` / `conclusion_context` / `analysis_fully_revoked`。
      **取数口径**：标签一律 `status='active'`；结构实体用 04 的 `approved_entities()` 过滤。
    - `app/test_points/engine.py`：`run_generate()`（纯函数 + `on_chapter` 回调）+
      `_parse_point()`（逐条校验与归一）。
      **JSON 解析必须走 `parse_llm_json`**，不许裸 `json.loads`。
    - `app/llm/mock.py`：加 `TEST_POINT_SYSTEM_PREFIX` + `TEST_POINT_DEFAULT_RESPONSE`
      + `chat()` 里一条新分支（**既有分支行为不变**）。
  - 产出：AC-142 / AC-143 / AC-144 / AC-145 / AC-146 / AC-156（Prompt 部分）可断言。
  - 验证：
    - `tests/test_points/test_context.py`——Prompt 段落顺序 / 清单排序 / 截断只截正文；
    - `tests/test_points/test_engine.py`——坏 JSON 整次失败 / 越界丢弃 / 优先级归一 /
      缺字段不丢 / Mock 前缀命中；
    - `tests/test_points/test_mock_prefix.py`——既有分支零影响。
  - 前台：本期无页面。

- [x] **T101 · 服务层 + 接口 + 留痕 + 权限搬迁**（2026-11-19 完成）
  - 内容：
    - `app/common/permissions.py`（新增）：从 05 搬 5 个权限函数
      （`_ensure_project` / `_ensure_writable_project` / `_ensure_admin` /
      `_ensure_member` / `ensure_readable`），**函数体不改**；
      05 的 `service.py` 改成 import 别名，既有测试不受影响。
    - `app/test_points/service.py`：`create_analysis` / `list_analyses` / `get_analysis` /
      `list_analysis_points` / `delete_analysis` / `list_points` / `get_point` /
      `create_manual_point` / `update_point` / `delete_point` / `review_point`。
    - `app/test_points/schemas.py`：请求与响应模型（枚举字段用 `str` 不用 `Literal`）。
    - `app/test_points/router.py`：11 个路由，前缀
      `/api/projects/{project_id}/test-points`；`app/main.py` 注册。
    - 运行留痕：`run_log.record_run(task_type='test_point')`，
      **`calls` 跑前记基线、跑完相减**。
    - 审计：`test_point.analysis.create` / `test_point.analysis.delete` /
      `test_point.review` / `test_point.point.*`。
  - 产出：AC-141 / AC-152 / AC-153 / AC-154 / AC-156 可断言。
  - 验证：
    - `tests/test_points/test_generate_flow.py`——发起生成全链路；
    - `tests/test_points/test_permissions.py`——权限矩阵 + 归档项目；
    - `tests/test_points/test_run_log.py`——留痕（成功 / 失败两条路径）；
    - `tests/test_points/test_manual_and_review.py`——评审 + 手工增删改；
    - `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补 1 条：
      `test_point.analysis.create`。
  - 前台：本期无页面。

- [x] **T102 · 引用保护 + 04 待复核标记**（2026-11-19 完成）
  - 评审与手工增删改的**服务层与接口已在 T101 落地**（便于 T101 一次交付完整闭环）；
  - 本期内容：
    - `app/baselines/references.py`：加 `_test_point_references` 解析器 + 注册
      （**`_table_exists` 探测保护**）。
    - **`app/baselines/service.py` 的 `clear_label()`**：清除成功后把引用它的测试点
      标 `needs_review=1` + `needs_review_reason` + `needs_review_at`
      （**表探测**：表不存在就跳过）。
  - 产出：AC-149 / AC-150 / AC-151 可断言。
  - 验证：
    - `tests/test_points/test_needs_review.py`——标签清除 → 待复核（**内容不变**）；
    - `tests/baselines/` 全量 **115 passed**（04 的 `clear_label` 改了，零回归）；
    - 04 引用检查 + 清除标签定向 **13 passed**。
  - 前台：本期无页面。

- [x] **T103 · 前端「测试点」Tab**（2026-11-19 完成）
  - 内容：
    - `web/src/pages/ProjectTestPointsTab.tsx`（生成记录表 + 测试点表 + 发起弹窗）；
    - `web/src/pages/TestPointDrawer.tsx`（详情 + 来源追溯 + 评审操作）；
    - `web/src/pages/testPointMeta.tsx`（优先级 / 状态选项与文案）；
    - `web/src/api/index.ts`：07 分节（类型 + 11 个函数）；
    - `web/src/api/client.ts`：8 个错误码中文；
    - `web/src/pages/ProjectDetailPage.tsx`：加「测试点」Tab（插在「增量分析」之后）。
  - 产出：AC-157 可断言。
  - 验证：
    - `npm run build` 通过；
    - `tests/e2e/test_test_points_ui.py`（`@pytest.mark.task("T103")`）：
      发起生成 → 测试点出现在列表 → 评审通过 → 状态变「已通过」；
      手工新增 → 编辑 → 删除；截图 `.screenshots/T103/`。
  - 前台：项目详情页「测试点」Tab。

- [x] **T104 · 收尾**（2026-11-19 完成）
  - 内容：
    - 全量 `pytest`（串行）+ 全量 e2e + `npm run build` + `dev_check.py`；
    - `alembic downgrade 0021 → upgrade head` 往返（两个库）；
    - 文档回填：`PROGRESS.md`（当前冲刺、迁移 head、计数、待办）、
      `specs/验证约定.md`（第七期前台核对点 + 变更记录）、本文件验证记录。
  - 产出：AC-151 / AC-155 / AC-158 可断言。
  - 验证：
    - 后端全量 **≥ 864 passed**（串行，exit 0）；
    - e2e 全量 **≥ 40 passed**；
    - `run_e2e.py` 内联的 `dev_check --expect-db e2e` 通过；
    - 两个库迁移 head 均在 `0022`；
    - 断网复核：清空 `llm_providers` 后全量 pytest 与 e2e 仍全绿。

## 验证记录

| 任务 | 后端定向 | 后端全量 | 前端构建 | e2e | 截图 |
|---|---|---|---|---|---|
| T99 | **12 passed**（新增） | **876 passed**（串行，exit 0） | 通过 | **40 passed**（零回归） | —（本期无页面） |
| T100 | **43 passed**（新增） | **919 passed**（串行，exit 0） | 通过 | **40 passed**（零回归） | —（本期无页面） |
| T101 | **39 passed**（新增） | **958 passed**（串行，exit 0） | 通过 | **40 passed**（零回归） | —（本期无页面） |
| T102 | **8 passed**（新增） | **966 passed**（串行，exit 0） | 通过 | **40 passed**（零回归） | —（本期无页面） |
| T103 | —（无后端改动） | **966 passed**（未动后端） | 通过 | **42 passed**（新增 2 + 原 40 零回归） | `.screenshots/T103/` |
| T104 | 04: **115 passed** / 05: **154 passed** / 06: **174 passed** | **966 passed**（串行，exit 0） | 通过 | **42 passed**（exit 0） | 复用 T103 截图 |

## T99 实现要点（2026-11-19）

**做完了什么**：两张新表 + 迁移 `0022` + 播种模板 + 留痕枚举扩充 + 9 个错误码。
**零业务逻辑**——本期只落结构，不碰任何判定。

### 关键决策

- **测试点不建唯一键**：同名测试点是合法的（不同功能的同名测试点，
  比如两个功能都要验「连续失败 5 次锁定」）。只靠 `idx_tpoints_target` 检索。
- **测试点与生成记录分两张表**：生成任务是一次性的、可能失败；测试点是产出物，
  有独立的评审生命周期（待评审 → 通过 / 驳回），会被手工增删改，
  还可能被下游（08 期用例生成）引用。结构与 05 的 `analyses` / `conclusions` 一致。
- **`target_name` / `chapter_title` 落库快照**：目标或章节后来改名、被删，
  历史测试点仍然对得上原文。
- **`analysis_id` 可空**：手工新增的测试点没有来源任务（`source_type='manual'`）。

### 踩到的坑

- **MySQL 的 CHECK 违约抛 3819（`OperationalError`），不是 1062（`IntegrityError`）**。
  唯一索引才是 1062。断言要分开写：
  `pytest.raises(OperationalError)` + `exc.value.orig.args[0] == 3819`。
- **`Test*` 开头的 ORM 类会被 pytest 当成测试类收集**：
  `PytestCollectionWarning: cannot collect test class 'TestPoint'`。
  模型类上写 `__test__ = False` 关掉。
- **模板示例里的 `target_id` 必须写成 `"target_id": 123,`（带逗号）**：
  断言 `'"target_id": 123' in prompt` 会因为原文是 `"target_id": 123,`
  而**恰好也匹配**——但 `'"target_id": 123'` 单独断言时，
  若模板写的是 `"target_id":123`（无空格）就匹配不上。
  统一按 `0019` 的写法：`"target_id": 123,`（冒号后有空格）。
  **这正是 06 期 L2 踩过的坑**：模板示例写死 `"target_id": 1`，
  真实模型照抄，真实的 10096 / 10097 全被当越界丢弃。
- **`user_prompt` 也要带前缀**：第一版只给 `system_prompt` 加了
  `[TEST_POINT_SYSTEM]`，`user_prompt` 漏了 `[TEST_POINT_USER]`，
  被 `test_ac_156_seed_template_exists` 当场抓出来。

### `llm_run_logs.task_type` 枚举扩充的验证方式

MySQL **不允许**直接改 CHECK 约束，必须**先删后加**：

```python
op.drop_constraint("ck_llmlogs_task_type", "llm_run_logs", type_="check")
op.create_check_constraint("ck_llmlogs_task_type", "llm_run_logs", "task_type IN (...)")
```

`downgrade()` 反向（先删新 CHECK、再建旧 CHECK）。

**验证不只看「迁移跑通了」**，三层确认：
1. `information_schema.CHECK_CONSTRAINTS` 里能看到新约束文本含 `'test_point'`；
2. 实插一条 `task_type='test_point'` → **成功**；
3. 实插一条 `task_type='bogus_task'` → **被拒**（3819）——
   证明是「扩了枚举」而不是「放开了口子」。

### 迁移往返

两个库（开发库 `aitest_copilot_v2` 与 e2e 库 `aitest_copilot_e2e`）都跑了
`0022 → 0021 → 0022` 往返，干净无残留：
- 两库 `alembic_version` 均在 `0022`；
- 两库 `test_point_analyses` / `test_points` 均已建；
- 两库 `prompt_templates` 各有 1 条 `task_type='test_point'` 的 active 模板；
- 降级时模板随 `DELETE ... WHERE name = :name` 一并清掉，升级时重新播种
  （**不重复**——`uk_ptemplates_type_name` 唯一键兜底）。

## T100 实现要点（2026-11-19）

**做完了什么**：上下文组装（`context.py`）+ 纯引擎（`engine.py`）+ Mock 前缀分支。
**引擎不写库**——丢弃判定因此可以纯函数级测试，不必起 HTTP、不必起数据库。

### Prompt 的分段契约

```
{template.user_prompt}

## 可对照的基线目标
- 功能#10096 用户扫码登录

## 标签依据
- [变更] 用户扫码登录（function#10096），确认人 admin，确认于 2026-11-18 10:00:00

## 增量结论
- 4.2 登录失败次数限制 → 用户扫码登录：变更（0.8） 正文有改动

## 章节：4.2 登录失败次数限制
{章节正文}
```

- **顺序固定**：模板正文 → 清单 → 依据 → 结论 → 章节正文。
- **空段落整段省略**（不留空标题），但相对顺序永不改变。
- **截断只砍章节正文**，前缀保持不变 → 「user 以模板 user_prompt 开头」
  在超长场景下依然成立。

### 三处排序全部确定性（防 Prompt 漂移）

| 段 | 排序键 |
|---|---|
| 基线目标清单 | `(target_type, target_id)` |
| 标签依据 | `(target_type, target_id, label_type)` |
| 增量结论 | `(chapter_id, target_type, target_id)` |

**排序键是元组，按字典序**——所以 `"feature_point" < "function"`，
功能点排在功能前面（与 05 的 `render_baseline_brief` 完全一致）。
写测试时我一开始按「功能在前」写期望值，被当场打回——**代码是对的，期望值错了**。

### 逐条校验口径

| 字段 | 不合法时 | 码 |
|---|---|---|
| `name` 缺失 / 空 | **整条丢弃** | `TEST_POINT_INVALID` |
| `target_type` 不在枚举 | **整条丢弃** | `TEST_POINT_INVALID` |
| `target_id` 不在清单 | **整条丢弃** | `TEST_POINT_TARGET_OUT_OF_BASELINE` |
| `priority` 不在枚举 | **归一到 `medium`** | — |
| `precondition` / `verification` 缺失 | **存空串** | — |
| `target_id` 是数字字符串 | **归一成整数** | — |

**为什么 `target_id` 是字符串要归一而不是丢**：真实模型经常给 `"10096"`（带引号）。
这是格式噪声，还原成整数就是原文——与「补引号」那种猜测性修复不同，
这里只是把同一个数字换种写法。

**为什么 `priority` 不合法不丢**：优先级是展示属性，
丢掉整条测试点（可能包含有价值的验证要点）代价太大。

### 测试的关键约束

**所有用例显式给 `MockProvider(queue=[...])`**。
Mock 默认响应的 `target_id=123` 不在真实清单里 → 全被当越界丢弃。
`helpers.point_response(target_id=...)` 接收**真实 id**，生成命中清单的响应。
这是 06 期「Mock 通过 ≠ 真实模型能跑」的同一个坑，必须在测试层堵死。

`tests/test_points/test_mock_prefix.py` 额外钉死「既有分支零影响」——
第一遍 / 第二遍 / 文档推导三个前缀的默认返回一个字节没变。

### 顺手修的 pytest 坑

`AppError` 基类上加 `__test__ = False`——否则 `TestPointInvalid`
这类 `Test*` 开头的**错误类**也会被 pytest 当成测试类收集
（`PytestCollectionWarning`）。基类上一处，全期免疫。

## T101 实现要点（2026-11-19）

**做完了什么**：权限函数搬迁（05 → `app/common/permissions.py`）+ 服务层 +
11 个接口 + 审计 + 运行留痕。

**验证结果**：后端全量 **958 passed**（串行，exit 0）；e2e 全量 **40 passed**（零回归）；
`npm run build` 通过；05 / 06 定向回归全绿（权限搬迁零影响）。

### 权限函数搬迁：05 的别名必须继续生效

05 的 `service.py` 里保留**同名同签名的别名**：

```python
def _ensure_project(session, project_id) -> Project:
    return permissions.ensure_project(session, project_id)

def _ensure_writable_project(session, project_id) -> Project:
    return permissions.ensure_writable_project(session, project_id, action=_ACTION)
```

**唯一的行为变化是错误文案**：搬迁前 05 硬编码「不可发起增量分析」，
现在由 `action` 参数传入——05 传「发起增量分析」，文案**逐字节一致**
（e2e 有断言盯着「只有项目管理员可以发起增量分析」这句）。

搬迁后 05 里 5 个 import 变成未使用（`NotProjectAdmin` / `NotProjectMember` /
`ProjectArchived` / `ProjectNotFound` / `SYSTEM_ADMIN` / `ProjectMember`），
已清理。

### 校验顺序有专门的用例盯着

| 场景 | 期望 | 钉住了什么 |
|---|---|---|
| 项目不存在 + 非成员 | 404 | 项目不存在优先 |
| 归档项目 + member | **409** | 归档优先于角色 |
| member + 停用模板 | **403** | 角色优先于模板 |

### 写接口与读接口的越权错误码**不一样**

- 读接口非成员 → `NOT_PROJECT_MEMBER`
- 写接口非成员 → `NOT_PROJECT_ADMIN`

**这是刻意的**：区分「非成员」与「角色不符」会泄露项目是否存在
（05 的 `ensure_admin` 注释里明写了这条）。我第一版测试按读接口的直觉
写成了 `NOT_PROJECT_MEMBER`，被 05 的既有用例打回——**代码是对的，
期望值错了**。

### 留痕的 calls 必须「跑前记基线、跑完相减」

`provider.calls` 是**累计**的。直接取 `len(calls)` 会把历史调用算进来。
`test_ac_154_call_count_is_per_task_not_cumulative` 连续跑两次生成，
断言两条留痕的 `call_count` 都是 **1**（而不是 1 和 2）。

### 踩到的坑：pydantic 会把多余字段**悄悄丢掉**

`PointUpdate` 只声明 4 个字段，但 pydantic 默认 `extra='ignore'`——
传 `{"status": "approved"}` 会在**校验阶段**就被丢掉，
接口返回 200，用户以为改了状态，其实什么都没改。

**修法**：`model_config = ConfigDict(extra="allow")` 让多余字段**活到服务层**，
服务层用 `payload.model_extra` 抓出来判 400。

> 不用 `extra='forbid'`：那会变成 **422**（pydantic 的默认行为），
> 而 spec 要求的是 400 `TEST_POINT_INVALID`（与 01–05 的既有口径一致）。

### 审计覆盖清单补了 1 条

`tests/common/test_audit_coverage.py` 的 `SCENARIOS` 加
`test_point.analysis.create`——新增写操作而忘了写审计时，这份清单会缺项。

> 造数时踩了个坑：手写 JSON 字面量**漏了闭合的 `}`**，
> 被 `TEST_POINT_INVALID` 当场抓出。改用 `json.dumps` 生成，一劳永逸。

## T102 实现要点（2026-11-19）

**做完了什么**：04 侧的引用保护（快照被测试点引用 → 禁止删除）+
标签清除 → 测试点待复核标记。

**验证结果**：后端全量 **966 passed**（串行，exit 0）；e2e 全量 **40 passed**（零回归）；
**04 全部 115 条零回归**（引用检查 + 清除标签定向 13 条也全绿）。

### 04 的红线：两处都做了表探测保护

**① `references.py` 的新解析器**——严格照 05 的 `_analysis_record_references` 写：

```python
if not _table_exists(session, TEST_POINT_ANALYSIS_TABLE):
    return []
```

表不存在 → 返回空列表，**不报错、不误判**。
`_table_exists` 用 SQLAlchemy 的 inspector 探测（不查 information_schema），
对 MySQL 与 SQLite 都成立。

**② `clear_label()` 的待复核标记**——同样先探测：

```python
if not _table_exists(session, "test_points"):
    return 0
```

07 期迁移没跑时表不存在 → 直接跳过，04 的老库 / 老测试都不受影响。

### `clear_label()` 的改动只有一处调用

```python
label.status = "cleared"
...
session.flush()

_mark_dependent_test_points_needs_review(   # ← 只多了这一处
    session, project_id=project_id, label_id=label.id, clear_reason=clear_reason
)

write_audit(...)   # 审计逻辑一行没动
```

**清除逻辑本身、错误码、审计全部原样**——这是本期对 04 的唯一改动点。

### 标记只碰三列，用 ORM 的 update 语句

```python
update(TestPoint)
.where(
    TestPoint.project_id == project_id,
    TestPoint.source_label_id == label_id,
    TestPoint.needs_review == 0,       # 已标记的不重复处理
)
.values(
    needs_review=1,
    needs_review_reason=f"所依赖的基线标签已被清除（原因：{clear_reason}）",
    needs_review_at=_now(),
)
```

**不加载实体**——从物理上杜绝「误改别的字段」的可能。
测试点的名称、目标、优先级、前置条件、验证要点、章节、来源、评审状态
**一个字都不动**。

**也不改评审状态**：已评审通过（`status='approved'`）的测试点
**仍保持 approved**——清除标签不自动降级下游的评审结论
（PRD 2.4.4「已生成测试点不自动删改，仅提示复核」）。

### 踩到的坑：引擎在同一章节内会对同一目标去重

第一版测试想造「两条引用同一标签的测试点」，用 `extra` 在**同一章**里塞两条——
结果只落了 1 条：引擎的 `seen` 集合会按 `(target_type, target_id)` 去重
（只留第一条），这是 T100 就定下的口径。

**改用两个章节**：每章各产出一条，都指向同一个目标（因而同一个标签）。
顺带确认了「手工新增的测试点 `source_label_id` 为 NULL」——
所以它天然不受标签清除影响（AC-150 的另一半）。

### 引用保护的接线方式

`_test_point_references` 直接加进 `_BUILTIN_RESOLVERS`，
**不 import-time 改全局注册表**——与 05 的 `_analysis_record_references`
完全同构：04 不 import 05 / 07 的任何模块，各自的表自己探测。

## T103 实现要点（2026-11-19）

**做完了什么**：项目详情页新增第 8 个 Tab「测试点」——生成记录表 + 测试点表 +
发起生成弹窗 + 详情/评审抽屉 + 手工增删改。

**验证结果**：`npm run build` 通过；e2e 全量 **42 passed**（新增 2 条，原 40 条零回归）；
后端未改动（仍 966 passed）。

### 文件划分

| 文件 | 职责 |
|---|---|
| `web/src/pages/ProjectTestPointsTab.tsx` | 生成记录 + 测试点两张表、筛选、发起弹窗、手工增删改弹窗 |
| `web/src/pages/TestPointDrawer.tsx` | 详情 + 来源追溯 + 待复核提示 + 通过/驳回 |
| `web/src/pages/testPointMeta.tsx` | 优先级 / 状态 / 目标类型 / 来源 / 丢弃标识的文案与 Tag |

`web/src/api/index.ts` 加 07 分节（6 个类型 + 11 个函数）；
`web/src/api/client.ts` 加 8 个 HTTP 错误码中文
（`TEST_POINT_TARGET_OUT_OF_BASELINE` 只在 `stats.discarded` 里出现，不算错误码）。

### 冲突提示的落地方式

PRD 2.4.4 要求「同章节已有评审通过的测试点时，再次生成前提示将覆盖」，
且**由前端二次确认、服务端不静默覆盖**。实现：

1. 打开弹窗时并行拉一份 `status='approved'` 的测试点做快照；
2. 提交前用所选 `chapter_ids` 与快照里的 `chapter_id` 求交集；
3. 有交集 → `modal.confirm('将覆盖已有评审结果')`，确认后才发请求。

未选章节（全文档）时不做冲突判定——前端拿不到「全文档」的章节全集，
这一档留给服务端行为（新增而非删除已有测试点）。

### e2e 为什么需要种子数据

MockProvider 对 `[TEST_POINT_SYSTEM]` 返回的占位 `target_id=123` 一定不在依据清单内，
引擎按「越界丢弃」处理 → 发起生成只会得到 `succeeded` + 0 条测试点。
所以 `tests/e2e/support.py` 新增 `seed_test_points()`：
按真实表结构补写测试点，**评审 / 增删改仍走真实接口**，只造数、不绕过被验证的路径。
同时在 `cleanup_e2e_data()` 的最前面补了 `test_points` / `test_point_analyses` 的清理。

### 踩到的坑

- `InputNumber` 的 `data-testid` 落在 rc-input-number 外层，`fill()` 找不到 `input`；
  e2e 改用 `.ant-form-item`（标签「目标 ID」）下的 `input` 定位。
- 弹窗里「模板」是否已自动选中取决于模板接口返回时序；
  e2e 不依赖自动选中，显式再选一次模板，避免 flaky。

## T104 实现要点（2026-11-19）

**做完了什么**：07 期总收尾——迁移往返、全量回归、文档回填、欠账入 Backlog。

### 验证结果

| 项 | 结果 |
|---|---|
| 迁移往返（开发库 `aitest_copilot_v2`） | `0022 → 0021 → 0022` 干净，head `0022` |
| 迁移往返（e2e 库 `aitest_copilot_e2e`） | `0022 → 0021 → 0022` 干净，head `0022` |
| `dev_check.py` | 全部 `[ OK ]`，两库 head 均 `0022`、04 基线表齐 |
| 后端全量（串行） | **966 passed, 42 deselected**（exit 0） |
| 04 定向 | **115 passed** |
| 05 定向 | **154 passed** |
| 06 定向 | **174 passed** |
| e2e 全量 | **42 passed**（exit 0，含 `dev_check --expect-db e2e`） |
| 前端构建 | 通过 |

### 迁移往返时暴露并修掉的一个真实问题

第一次在 e2e 库跑 `downgrade 0021` 时，**降级在「重建旧 CHECK」这步失败**：
`llm_run_logs` 里还有 T103 e2e 留下的 `task_type='test_point'` 留痕，
旧 CHECK 不含该值 → `CheckConstraint` 违约。此时 `alembic_version` 仍停在 `0022`，
但模板已删、新 CHECK 已删、旧 CHECK 未建，库处于**半成品状态**。

- **根因**：`cleanup_e2e_data()` 没清 `llm_run_logs`（该表有 `project_id`，按项目就能清）。
- **修复**：清理清单补一行 `DELETE FROM llm_run_logs WHERE project_id IN (...)`。
- **修复现场**：先删 `task_type='test_point'` 留痕、删两张 07 表、补回旧 CHECK，
  `alembic stamp 0021` 把版本对齐后，再跑两轮 `upgrade → downgrade → upgrade` 确认干净。
- **为什么值得记**：这是「e2e 数据残留挡住迁移降级」的典型形态，
  只跑 `upgrade` 永远发现不了；**收尾必须做真实往返**。

### 断网复核的口径

开发库有 1 条真实大模型配置（L2 联调用），e2e 库 0 条。
不在收尾时清空开发库配置——`tests/conftest.py` 的 autouse 夹具在每条用例里
都会把 `llm_providers` 置空，全量 966 passed 本身就是「无真实 Provider」下的结果；
e2e 库本就 0 条，42 passed 即断网口径。**不为了形式上的「清空再跑」破坏 L2 配置。**

### 本期欠账（已记入 `PROGRESS.md` §6 Backlog）

- **无基线直接对文档分析**（PRD 2.4.4 输入②）：本期只有「增量结论 + 生效标签」一条输入路径。
- 工作台「待评审的测试点」计数：与 08 期用例评审合并口径后再接。
- 测试点版本历史 / 快照：本期定位为可增删改的活文档。
- Skill 模式（PRD 2.5）：06 / 07 均只做直连模式。
- Token 计费 / 配额。


