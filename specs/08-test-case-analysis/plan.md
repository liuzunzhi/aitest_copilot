# 08 · 测试用例分析 · 技术方案

> 配套 [spec.md](./spec.md)（AC-159 ~ AC-180）与 [tasks.md](./tasks.md)（T105 ~ T110）。
> 定位：在 07「已评审测试点」之上补「测试用例」这一段，**不重写基础设施**。

## 1. 总体思路

```
approved 测试点（07）
      │
      ├─ context.build_case_context()   ← 模板正文 + 测试点段 + 章节段（可省略）
      │
      ├─ engine.analyze_point()         ← 逐测试点调 provider，纯函数校验 / 归一
      │
      ├─ service.run_analysis()         ← 事务：记录 + 用例 + 步骤；留痕；审计
      │
      └─ router / export                ← 评审、手工 CRUD、步骤覆盖、待复核派生、xlsx
```

三条与 07 不同的关键设计：

1. **循环单位是测试点，不是章节** —— 07 一个章节可能命中多个目标；08 的输入已经是点，
   逐点调用最简单，也天然支持「按测试点/章节/目标」三种筛选。
2. **模型不返回测试点 id** —— 服务端绑定当前点，从结构上消灭「越界 id」脏数据。
3. **待复核读时派生，不落库** —— 因为不能改 07，也就没有可靠的写入钩子；
   读时重算源测试点**内容指纹**与用例里的快照比对，永远与源数据一致
   （`updated_at` 在 MySQL 侧不会自动推进，不能用作判定基准）。

## 2. 目录与文件

```
app/test_cases/
├── __init__.py
├── context.py        # Prompt 分段渲染 + 截断
├── fingerprint.py    # 源测试点内容指纹（生成 / 读取 / ack 共用一份字段清单）
├── engine.py         # 单测试点调用 + 输出校验 / 归一（纯函数为主）
├── service.py        # 生成 / 列表 / 详情 / 删除 / 评审 / 手工 CRUD / 步骤 / 复核
├── exporter.py       # openpyxl 导出
├── schemas.py        # Pydantic 请求 / 响应模型
└── router.py         # 13 个路由

app/models/test_case.py            # TestCaseAnalysis / TestCase / TestCaseStep
migrations/versions/0023_test_cases.py
tests/test_cases/…                 # 见 §10
web/src/pages/ProjectTestCasesTab.tsx
web/src/components/TestCaseDrawer.tsx
web/src/components/TestCaseStepsEditor.tsx
web/src/components/testCaseMeta.tsx
tests/e2e/test_test_cases_ui.py
```

## 3. 数据层

### 3.1 模型

`app/models/test_case.py` 按 07 的写法：`Mapped[...]` + `mapped_column`，`__tablename__` 用
`test_case_analyses` / `test_cases` / `test_case_steps`，列类型照抄 07
（`BIGINT(unsigned=True)` / `DATETIME(fsp=3)` / `JSON` / `String(n)`，
`created_at` 用 `server_default=text("CURRENT_TIMESTAMP(3)")`）。
`test_cases.updated_at` **由服务层显式赋值**——MySQL 方言不会把 `server_onupdate` 渲染成
`ON UPDATE`（07 的 `updated_at` 实测就是插入后不变）。

- **三个类都要写 `__test__ = False`**：`TestCase*` 撞 pytest 的 `Test*` 收集规则，
  07 的 `TestPoint` 已有先例（`app/models/test_point.py#L48`）。
- `TestCase` 与 `TestCaseStep` 不建 ORM `relationship`（07 也不用 relationship），
  步骤一律显式查询 / 显式插入，避免 lazy load 在同步 session 里踩坑。
- `TestCaseStep.case_id` 的 FK 带 `ondelete="CASCADE"`（**数据库级**），
  删用例只 `session.delete(case)`，步骤由 MySQL 级联。
- `TestCase.test_point_id` 只有普通索引，**没有 ForeignKey**（见 spec §4.2 的理由）。

### 3.2 迁移 `0023`

`down_revision = "0022"`。升级顺序（按外键依赖）：

1. `create_table("test_case_analyses")`（FK → projects / prompt_templates / users；
   `test_point_analysis_id` **无 FK**，只是历史标签）
2. `create_table("test_cases")`（FK → projects / test_case_analyses / users，`test_point_id` 无 FK）
3. `create_table("test_case_steps")`（FK → test_cases，`ondelete='CASCADE'`）
4. `llm_run_logs` 的 CHECK：`drop_constraint` → `create_check_constraint`（加 `'test_case'`）
5. 播种 1 条 `task_type='test_case'` 的 `prompt_templates`

降级严格反向：

1. 删播种模板（按 `name` + `task_type` 精确删）
2. `llm_run_logs` 的 CHECK 还原 —— **先 `DELETE FROM llm_run_logs WHERE task_type='test_case'`**
   再重建（否则残留行会让 CHECK 重建报 3819；这是 06 期 e2e 降级踩过的坑）
3. `drop_table("test_case_steps")` → `test_cases` → `test_case_analyses`

> 播种内容写在迁移里（与 05 / 06 / 07 一致），不依赖代码里的常量；
> 模板 `system_prompt` 以 `[TEST_CASE_SYSTEM]` 开头，Mock 才认得出。

### 3.3 错误码

在 `app/common/errors.py` 末尾追加 9 个类（`ApiError` 子类，带 `status_code` / `code`），
并补进 `__all__`。命名与 07 的 `TestPoint*` 保持同一形态。

## 4. Prompt 组装（`context.py`）

```python
def build_case_context(template, point, chapter) -> tuple[str, str]:
    """返回 (system, user)；user 已按固定顺序拼好并在超预算时截断章节正文。"""
```

- `system` = `template.system_prompt`（原样，不加工）。
- `user` 分段顺序：模板 `user_prompt` → `## 测试点` → `## 来源章节：{title}`。
- 测试点段固定 6 行（名称 / 归属 / 优先级 / 前置条件 / 验证要点），缺失字段写 `（空）`，
  **不省略行**，保证结构稳定。
- 章节段：`chapter is None` 或 `chapter.content` 去空白后为空 → 整段不渲染。
  章节行由服务层用 `session.get(DocumentChapter, point.chapter_id)` 取
  （07 的 `_load_chapters` 是私有函数且绑定"一次生成的所有章节"语义，**不复用**）。
- 截断：`len(user) > get_settings().incremental_max_input_chars` 时，**只切章节正文尾部**；
  前缀超预算（极端情况）时不再二次截断，交由 provider 报错（与 07 同策略）。
  复用 07 已在用的 `incremental_max_input_chars`，**不新增配置项**。

## 5. 引擎（`engine.py`）

```python
@dataclass
class CaseDraft:
    title: str
    case_type: str
    priority: str
    precondition: str
    steps: list[tuple[str, str]]   # (action, expected)

def analyze_point(provider, system: str, user: str) -> list[CaseDraft]:
    req = LLMRequest(system=system, user=user)
    raw = provider.chat(req).content      # 只一次调用
    return normalize_cases(parse_llm_json(raw))

def normalize_cases(payload) -> list[CaseDraft]:
    """校验 + 归一；不合法整条丢弃，并返回丢弃原因（供 stats 汇总）。"""
```

- `parse_llm_json` 抛错 / `cases` 不是数组 → 冒泡成 `TestCaseInvalid`（整次失败）。
- 单条不合法 → 丢弃并累计 `discarded`（不中断整次生成）。
- 归一规则严格照 spec §5.3 表；**不做"猜字段名"的宽松映射**（避免又一次 06 期的示例污染）。
- 纯函数优先：`normalize_cases` 只吃 Python 结构，测试不用造 mock provider。

## 6. 服务层（`service.py`）

### 6.1 生成

```python
def run_analysis(session, actor, project, payload) -> dict:
    # 1 校验（顺序见 spec §6.2），失败即抛，不建行
    # 2 选点：显式 ids → 严格校验；否则按 chapter/target/analysis 过滤 approved
    # 3 建 analysis(status=pending) + commit
    # 4 status=running + started_at + commit
    # 5 逐测试点：
    #      build_case_context → analyze_point → 写 cases + steps
    #      每个测试点 commit 一次（逐点落库，失败可保留已产出）
    # 6 汇总 stats → status=succeeded + finished_at + commit
    # 7 record_run(task_type='test_case', calls=处理点数, ...) + 审计
```

- **异常**：任一测试点抛非预期异常 → `status='failed'` + `error_code` + `commit` 后**立即返回 / 抛出**，
  不再处理后续测试点（对齐 05 的硬约束）。
- **`TestCaseInvalid`**（JSON 结构坏）：同样整次失败，但**已写入的前序测试点用例保留**
  （逐点落库的副作用，与 05 的"章节级保留"同构）。
- `stats` 结构：

```json
{
  "point_count": 12, "processed_count": 12, "case_count": 18, "step_count": 47,
  "discarded_count": 3,
  "discarded": [{"test_point_id": 101, "test_point_name": "…", "title": "…", "code": "TEST_CASE_INVALID"}]
}
```

- `call_count` 用**跑前记基线、跑完相减**（07 的运行留痕教训），不读累计值；
  该计数在 `record_run(..., calls=...)` 之前算好。
- **`record_run` 只 add + flush，不 commit**（06 的既有语义）：必须在最后一次 `commit()`
  之前调用，让留痕与业务成败同事务；业务失败时留痕一起回滚（不留「业务没成但日志说成功」）。

### 6.2 查询

- `list_cases` 与 07 的 `list_points` 同构：一次全量取（按项目 + 可选 SQL 过滤）→
  Python 层算 `needs_review` → 按 `needs_review` / 关键词过滤 → 稳定排序 → 切片分页。
  排序：`id desc`（最新的在前），与 07 一致。
- `needs_review` 需要源测试点的当前行：**一次 `IN` 查询**批量取 `{id: TestPoint}`，
  在循环外逐个算指纹，不在循环里查库。
- 详情返回：元数据 + `steps`（按 `step_no` 升序）+ 追溯链
  （`test_point_name` / `target_name` / `chapter_title`）+ `needs_review` 三元组。

### 6.3 评审 / 手工 CRUD

- `review_case`：`status != 'pending'` → 409；写 `reviewed_by/at/comment`；审计带 `self_approved`。
- `create_case`：校验 `test_point_id` 存在且属于本项目（**不要求 approved**——手工用例允许挂
  pending 点，避免卡死人工补录），快照 `test_point_name` / `target_*` / `chapter_*` /
  `source_point_fingerprint`，`source_type='manual'`、`analysis_id=NULL`。
- `update_case`：白名单 4 字段；`extra='allow'` + 服务层拦截多余键 → 400（07 的既有约定）。
- `replace_steps`：先校验整组（1..100 步、`action` 非空）→ 全删 → 重插 → 一次 commit；
  失败回滚原样。
- `delete_case`：物理删 + 审计；步骤走级联。

### 6.4 待复核

**为什么不用 `updated_at`**：编译 `test_points` 的建表 DDL 可见，
`updated_at` 只有 `DEFAULT CURRENT_TIMESTAMP(3)`，没有 `ON UPDATE`；
应用代码也从不赋值。用它比对会让待复核**永远不触发**。
改用内容指纹：

```python
# app/test_cases/fingerprint.py —— 唯一字段清单出处
_FIELDS = ("name", "target_type", "target_id", "target_name", "priority",
           "precondition", "verification", "chapter_id", "chapter_title", "needs_review")

def point_fingerprint(point) -> str:
    payload = {f: getattr(point, f) for f in _FIELDS}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     default=str).encode()).hexdigest()

def derive_needs_review(case, point, current_fp) -> tuple[bool, str | None]:
    if point is None:
        return (case.source_point_fingerprint is not None, "source_point_deleted")
    if case.source_point_fingerprint is None or case.source_point_fingerprint != current_fp:
        return True, "source_point_changed"
    return False, None
```

`ack_case`：源存在 → 写 `current_fp`；源不存在 → 置 NULL；都记 `needs_review_ack_at`。

## 7. 接口层（`router.py`）

- 13 个路由，前缀 `/api/projects/{project_id}/test-cases`。
- **`/cases/export` 必须写在 `/cases/{case_id}` 之前**（FastAPI 按注册顺序匹配，
  否则 `export` 会被当成 id 解析成 422）。
- 每个写接口固定 4 步：`项目 404 → 归档 409 → 权限 403 → 业务校验`。
- `POST /analyses` 同步返回 `{analysis, cases}`（用例已带步骤），
  避免前端再串一次请求；返回体与 `GET /cases?analysis_id=` 字段一致。
- 导出走 `Response(content=bytes, media_type=…, headers={"Content-Disposition": ...})`，
  不落临时文件（`documents` 的 `FileResponse` 是磁盘文件，不适用）。
- 响应模型全部 `ConfigDict(extra='forbid')`（入参）/ 普通 dict（出参用 Pydantic 模型，便于前端类型）。

## 8. 导出（`exporter.py`）

- `openpyxl.Workbook(write_only=False)`（数据量小，需要首行加粗与列宽）。
- 一步一行；用例元数据重复；`步骤序号` 为空表示该用例无步骤。
- 列宽固定；首行冻结；`状态` / `用例类型` / `优先级` 输出中文（`pending`→`待评审` 等），
  用 `testCaseMeta.tsx` 同源的映射常量（后端单独放 `app/test_cases/labels.py`，前端手抄一份，
  两边都在测试里断言同一组中文，防止漂移）。
- 文件名 `test-cases-{project_id}-{yyyymmdd}.xlsx`。

## 9. 前端

- `ProjectDetailPage.tsx`：`items` 追加 `{key:'test-cases', label:'测试用例'}`。
- `ProjectTestCasesTab.tsx`：两段式（生成记录 + 用例表）；受控状态在页面内，
  与 `ProjectTestPointsTab.tsx` 保持同样的 loading / 空态 / 错误提示写法。
- `TestCaseDrawer.tsx`：详情 + 评审 + 待复核告警条（`Alert` + 「确认已复核」）。
- `TestCaseStepsEditor.tsx`：受控数组 + 增删行 + 上下移；保存时整体 `PUT /steps`。
- `web/src/api/index.ts` 追加 `testCases` 命名空间（13 个方法，类型齐全）。
- `web/src/api/client.ts` 追加 9 个错误码中文映射。
- 导出用 `responseType: 'blob'`（client 里若没有 blob 分支，补一个最小的，不动既有拦截逻辑）。
- 权限：`project.role === 'project_admin'` 才渲染写入口（与 07 的 `apply` 块同一判断源）。

## 10. 测试策略

| 层 | 文件 | 重点 |
|---|---|---|
| 模型 / 迁移 | `tests/test_cases/test_models.py` / `test_migration.py` | 三表存在；CHECK 接受 `test_case`、拒绝非法值；模板播种；`0023↔0022` 往返 |
| 上下文 | `test_context.py` | 段落顺序；空章节省略；截断只砍正文；前缀不变；模板正文来自库 |
| 引擎 | `test_engine.py` | 丢弃 / 归一全表；坏 JSON；重复 title；`step_no` 重排 |
| 生成 | `test_generate_flow.py` | approved 过滤；严格 ids；输入为空；逐点落库；失败即停；stats |
| 手工 + 评审 + 步骤 | `test_manual_and_review.py` | 新增快照；白名单 4 字段；删除级联；步骤覆盖事务；评审 409 |
| 待复核 | `test_needs_review.py` | 改点 / 删点 / ack / 再改；`_FIELDS` 逐字段；读时派生不改内容 |
| 权限 / 归档 | `test_permissions.py` | 矩阵；403 / 404 / 409 顺序 |
| 留痕 | `test_run_log.py` | `call_count` 相减；无 Prompt / Key |
| 导出 | `test_export.py` | 行数、列、中文状态、筛选 |
| Mock 前缀 | `test_mock_prefix.py` | `[TEST_CASE_SYSTEM]` 命中；既有前缀零漂移 |
| e2e | `tests/e2e/test_test_cases_ui.py` | `test_ac_178_*_ui`：生成 → 列表 → 评审 → 手工改步骤 → 待复核 → 导出 |

测试函数统一命名 `test_ac_<AC号>_<场景>`（验证约定 §4.2）。

Mock Provider 行为（`app/llm/mock.py` 加一个分支，**既有分支零改动**）：

- 命中 `[TEST_CASE_SYSTEM]` → 返回 `{"cases":[1 条带 2 步骤的用例]}`；
- e2e 因此**不需要预置用例**，点一次生成就有数据（这是 08 比 07 e2e 省事的地方：
  模型输出不含测试点 id，不存在"示例 id 与真实 id 不匹配"的坑）；
- 需要多结果 / 坏 JSON 的用例，走 `queue` 机制（06 已有），不新增机制。

## 11. 复用清单（不重写）

| 能力 | 出处 | 用法 |
|---|---|---|
| `get_provider` | `app/llm/provider.py` | 原样；无配置降级 Mock |
| `parse_llm_json` | `app/llm/json_utils.py` | 原样；处理围栏与 think 块 |
| `record_run` | `app/llm/run_log.py` | 原样；`task_type='test_case'` |
| `MockProvider` | `app/llm/mock.py` | **只加前缀分支** |
| `ensure_readable` / `ensure_writable_project` / `ensure_admin` / `ensure_member` / `ensure_project` | `app/common/permissions.py` | 原样；读走 `ensure_readable`，写走「writable → admin」两段 |
| `write_audit` | `app/common/audit.py` | 原样 |
| `DocumentChapter` | `app/models/document.py` | `session.get(DocumentChapter, point.chapter_id)` 取正文（07 的 `_load_chapters` 是私有且面向整批章节，不复用） |
| 测试点查询 / approved 口径 | `app/test_points/service.py` | **只读 SQL 复用**，不 import 业务函数（避免耦合），直接 `select(TestPoint)` |
| 分页 | 07 的 `_page` 写法 | 照抄形态 |
| 前端 Tab / 抽屉 / 空态 | `ProjectTestPointsTab.tsx` / `TestPointDrawer.tsx` | 同构实现 |

## 12. 风险与规避

| 风险 | 规避 |
|---|---|
| **外键阻塞 07 删测试点 / 删生成记录**（IntegrityError → 500） | `test_cases.test_point_id` 与 `test_case_analyses.test_point_analysis_id` **都不建 FK**；用快照 + 读时派生；AC-171 显式回归 07 的两个删除接口 |
| 读时派生拖慢列表 | 一次 `IN` 批量取测试点状态，Python 层比对；200 条量级无压力 |
| **降级时 CHECK 重建失败**（3819） | 0023 的 downgrade 先删 `llm_run_logs.task_type='test_case'` 行再重建；e2e 降级脚本同步 |
| e2e 数据残留 | `tests/e2e/support.py` 的清理列表按外键倒序加 `test_case_steps → test_cases → test_case_analyses` |
| `openpyxl` 未安装 | `pyproject.toml` 加运行时依赖；本机用镜像安装；导出测试直接断言工作簿内容 |
| 同步生成耗时长（逐点调模型） | 上限 200 点；Mock 场景毫秒级；真实场景由使用方控制筛选范围 |
| 模型输出字段漂移（06 期教训） | 契约里没有 id 可抄；只认 5 个字段；不合法丢弃并进 `stats.discarded`，日志里能看清原因 |
| **`TestCase*` 类被 pytest 当测试类收集** | 三个模型类显式 `__test__ = False`；错误类继承 `ApiError` 已免疫 |
| Mock `queue` 是**全局 FIFO** | 需要「每个测试点不同响应」的用例，必须按调用顺序 push N 条；只想断言落库条数的用例，直接给 `default_response` |
| **判定基准选错**：`test_points.updated_at` 实为「插入时间」，不会随修改推进 | 改用内容指纹（含 `needs_review` 位），读时重算；测试逐字段断言任一处改动都触发 |
| 指纹字段清单漏项 → 漏判 | 清单只在 `fingerprint.py::_FIELDS` 一处；测试遍历 `_FIELDS` 逐字段改值验证 |
| 前端 blob 下载拦截器不兼容 | 只在导出方法里走 `responseType:'blob'`，不改全局拦截器的错误分支 |
| 一次生成把已通过的用例冲掉 | **不覆盖**：生成永远新增行；重复生成同一测试点会产生新用例，由人工删旧（与 07 不覆盖测试点一致） |

## 13. 实施顺序

1. T105 迁移 + 模型 + 错误码 + 模板播种 + Mock 前缀 → 先让"表能建、绕得回"。
2. T106 上下文 + 引擎（纯函数，测试最快）。
3. T107 生成链路（服务 + 路由 + 留痕 + 审计）。
4. T108 评审 + 手工 CRUD + 步骤 + 待复核 + 导出。
5. T109 前端 + e2e。
6. T110 全量回归 + 迁移往返 + 文档回填。
