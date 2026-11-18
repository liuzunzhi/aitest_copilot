# 05 · 增量分析（第一期）· 方案

> 规格 [spec.md](./spec.md) ｜ 任务 [tasks.md](./tasks.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)

## 1. 总体思路

03 把「文档 → 版本 → 章节」做完了，04 把「模块 → 功能 → 功能点 + 快照 + 两级标签」做完了，
缺的是中间那一步：**章节内容到底改了什么**。本期只补这一段的第一遍。

```
prompt_templates ──┐
                   ├─▶ incremental_analyses ──▶ incremental_conclusions
baseline_revisions ┤        （一次分析）              （逐条局部结论）
document_versions ─┘
        │
        └─▶ app/llm/  LLMProvider ── MockProvider（唯一实现）
```

关键取舍：

1. **只做第一遍，且只做章节粒度**。v2.2 §4.2 的第二遍（2b-1/2b-2/2b-3）规模远大于第一遍，
   混在一起做会让「流程能不能跑通」这个判断点被稀释。本期的验收边界是
   **「结论能不能正确落库」「Prompt 是不是真的从库里来」**，不是比对准不准。
2. **零真实网络请求**。`LLMProvider` 是 Protocol，本期只有 `MockProvider`。
   好处不只是省 token：全量 pytest 与 e2e 从此**完全离线可跑**，
   后续接真实模型时只加一个实现类，不动引擎。
3. **Prompt 必须来自数据库**。这是 PRD 2.3.6「全局提示词模板」的最小可用形态——
   模板改了不用改代码、不用发版。本期不做模板管理页，但**读取路径必须是真的**，
   否则第二期做页面时会发现底层还是硬编码。
4. **丢弃结论不建第 4 张表**。越界目标、`new` 标签都是「本该丢弃的坏数据」，
   给它单独建表等于给脏数据一个正式身份。统一记进 `analyses.stats.discarded` 数组，
   既留了痕，又不污染业务表。
5. **单表模板、不做版本表**。04 吃过「合表 vs 拆表」的教训：拆表要有明确收益。
   本期模板只被读，`version_no` 留个占位字段即可，真要做版本化再拆。

## 2. 数据层

### 2.1 迁移

`migrations/versions/0013_incremental.py`，`down_revision = "0012"`。

upgrade 顺序（外键依赖）：
`prompt_templates` → `incremental_analyses` → `incremental_conclusions`。

downgrade 反序：`incremental_conclusions` → `incremental_analyses` → `prompt_templates`。

沿用 `0012_baseline.py` 的写法：`mysql_default_charset="utf8mb4"`、
`mysql_collate="utf8mb4_0900_ai_ci"`、`mysql_engine="InnoDB"`，
所有 `CheckConstraint` 显式命名（`ck_<表缩写>_<字段>`），所有索引显式命名。

### 2.2 与 04 的硬约束

`app/baselines/references.py` 里已有这段（04 的 T67 落地）：

```python
INCREMENTAL_ANALYSIS_TABLE = "incremental_analyses"
...
SELECT id, COALESCE(status, '') FROM incremental_analyses WHERE baseline_revision_id = :revision_id
```

所以本期建表**必须**逐字满足三件事：表名 `incremental_analyses`、
列名 `baseline_revision_id`、列名 `status`。满足后 AC-85 自动成立，04 不动任何代码。

### 2.3 模型

`app/models/incremental.py`，3 个模型：`PromptTemplate` / `IncrementalAnalysis` / `IncrementalConclusion`。
注册到 `app/models/__init__.py` 的 import 与 `__all__`。

`stats` 用 `sa.JSON`（MySQL 下是 `JSON` 类型）。**不**为 `discarded` 建表。

### 2.4 种子模板

迁移 upgrade 里 `op.bulk_insert` 一条：

| name | task_type | status | system_prompt | user_prompt |
|---|---|---|---|---|
| 增量分析·第一遍·章节局部 | incremental | active | 固定文案，以 `[INCREMENTAL_SYSTEM]` 开头 | 固定文案，以 `[INCREMENTAL_USER]` 开头 |

前缀标记让 AC-78 的「可识别固定字符串」断言不依赖具体文案，改文案不破用例。

## 3. LLM 抽象层

新建包 `app/llm/`：

```
app/llm/
  __init__.py
  schemas.py     LLMRequest / LLMResponse / TokenUsage
  provider.py    LLMProvider（Protocol）+ get_provider()
  mock.py        MockProvider
```

### 3.1 接口

```python
class LLMRequest(BaseModel):
    system: str
    user: str
    temperature: float = 0.0
    max_tokens: int | None = None

class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class LLMResponse(BaseModel):
    content: str
    usage: TokenUsage
    model: str
    raw: dict            # 原样回带 LLMRequest，供用例断言 AC-78

class LLMProvider(Protocol):
    name: str
    def chat(self, req: LLMRequest) -> LLMResponse: ...
```

### 3.2 MockProvider

- `calls: list[LLMRequest]` —— 每次 `chat` 追加一条，用例据此断言 AC-78。
- `queue: list[str]` —— 预设返回队列；为空时返回 `default_response`。
- `chat()` 返回的 `raw` 里带 `{"request": req.model_dump(), "index": n}`。
- 默认返回 `{"conclusions": []}`（空结论），保证「不发预设也能跑通」。
- 测试通过 FastAPI 依赖覆盖拿到同一实例：
  `app.dependency_overrides[get_provider] = lambda: mock_instance`。

### 3.3 为什么不做 OpenAI 兼容实现

红线：本期不许写任何真实网络请求代码。留 `get_provider()` 一个函数做工厂，
第二期加 `OpenAICompatProvider` 时只在这里分支，引擎零改动。

## 4. 服务层

新建包 `app/incremental/`：

```
app/incremental/
  __init__.py
  schemas.py     请求 / 响应模型（含 Page 信封复用）
  context.py     Prompt 组装 + 基线索引（章节 ↔ 基线）
  engine.py      第一遍引擎（核心）
  service.py     记录生命周期、落库、丢弃判定
  router.py      路由
```

### 4.1 上下文组装（`context.py`）

**Prompt 组装**（严格按 AC-78）：

```python
system = template.system_prompt                      # 原样，不加工
user   = f"{template.user_prompt}\n\n## 章节：{chapter.title}\n{chapter.content}"
```

即 `user` 以 `template.user_prompt` 开头，其后是章节标题与正文。

**基线索引**：从 `baseline_revision_id` 对应的快照里取出该项目的
`baseline_functions` 与 `baseline_feature_points`（排除 `status='archived'` 的模块及其下属），
建成 `{("function"|"feature_point", id) → name}` 的字典。这份字典是 AC-79 的判定依据：
**目标不在字典里 = 越界**。

> 注意：这里取的是**当前**结构表，不是快照的 `structure_json`。
> 理由是本期结论的 `target_id` 必须能对上活数据（第二期写标签要用），
> `structure_json` 是冻结文本、不含可 join 的 id。两者的一致性由「快照未过期」保证（第二期做 apply 时校验）。

### 4.2 第一遍引擎（`engine.py`）

```
run_first_pass(session, analysis, provider, template) -> PassResult
  chapters = 生效版本的章节树（按 seq 升序，跳过 char_count == 0）
  for chapter in chapters:
      user = 组装 Prompt(template, chapter)
      截断：len(user) > INCREMENTAL_MAX_INPUT_CHARS → 截断正文，记 WARN
      resp = provider.chat(LLMRequest(system=..., user=...))
      payload = json.loads(resp.content)            # 失败 → LLM_OUTPUT_INVALID
      for item in payload["conclusions"]:           # 缺字段 → LLM_OUTPUT_INVALID
          分类：
            target 不在基线索引        → discarded(code=INCREMENTAL_TARGET_OUT_OF_BASELINE)
            label_type == "new"       → discarded(code=INCREMENTAL_LABEL_NEW_DROPPED)
            其余                      → 待落库
  返回 PassResult(chapters, conclusions, discarded, chapter_count)
```

引擎**只负责产出**，不写库；写库在 `service.py`。这样 AC-79 / AC-80 的丢弃逻辑
可以纯函数级测试，不必起 HTTP。

### 4.3 记录生命周期（`service.py`）

```
create_analysis(project_id, payload, actor):
  1. 项目 / 归档 / 角色（deps 已完成）
  2. 模板：不存在 → 404 TEMPLATE_NOT_FOUND；disabled → 409 TEMPLATE_DISABLED
  3. 快照：不存在/非本项目/非 approved → 400 BASELINE_REVISION_REQUIRED
  4. 文档版本：不存在/非本项目 → 400 NO_ACTIVE_DOCUMENT_VERSION；
               status != 'active'  → 400 DOCUMENT_VERSION_NOT_ANALYZABLE
  5. insert analysis(status='running', started_at=now) → flush
  6. write_audit("incremental.analysis.create", ...)
  7. commit
  8. run_first_pass(...)  ← 在同一请求内同步执行（本期无任务队列）
  9. 成功：bulk insert conclusions → 回填 stats/status='succeeded'/finished_at
     失败：status='failed' / error_code / error_message / finished_at
  10. commit
```

- 第 2–4 步失败**不建行**，因此没有「脏记录」（AC-78 第三条、AC-81）。
- 第 8 步失败时**保留**已落库结论：便于排查模型返回了什么；`status='failed'` 本身已表达不可用。
- 结论落库用「先删后插」不必要（一次分析只跑一次第一遍），直接 insert；
  唯一键 `(analysis_id, chapter_id, target_type, target_id)` 兜住模型重复输出。

### 4.4 审计

`write_audit` 的时序沿用 04 的教训：**改数据 → flush → write_audit → commit**，
`write_audit` 内部不 commit。

## 5. 接口层

路由挂在 `app/incremental/router.py`，前缀 `/api/projects/{project_id}/incremental`，
在 `app/main.py` 注册 `incremental_router`。

写接口统一：解析 `project_id`（404）→ 归档（409）→ 角色（403）→ 资源校验（404/400）。
读接口：项目成员 + system_admin 兜底；非成员 403 `NOT_PROJECT_MEMBER`。

分页信封直接复用 `app/baselines/schemas.py` 的 `Page[T]`，不另写一份。

响应模型避开内部主键裸奔：`AnalysisOut` 带 `baseline_revision_version`（如 `v1.2`）、
`document_version_no`、`template_name` 等业务标识，前端不需要自己再查一遍。

## 6. 前端

`web/src/pages/` 新增 `ProjectIncrementalTab.tsx`（控制在 400 行内）：

- 顶部：发起分析表单（选基线快照 / 文档版本 / 模板 / 切分粒度，后者固定 `chapter` 只读展示）
- 中部：分析记录列表（状态 Tag、时间、章节数 / 结论数 / 丢弃数）
- 点开记录 → 抽屉展示结论列表与丢弃明细（丢弃明细见 `stats.discarded`）

`ProjectDetailPage.tsx` 在「申请」Tab 之后插入第 7 个 Tab「增量分析」（`key: 'incremental'`）。

`web/src/api/index.ts` 增 `/* ---- 增量分析（05） ---- */` 分节 + 类型；
`web/src/api/client.ts` 补本期 9 个错误码的中文映射。

写入口（发起按钮）对非项目管理员隐藏；`data-testid` 用 `区域-动作-目标` 命名
（`incremental-create-btn`、`incremental-detail-btn-12`）。

## 7. 任务拆分

见 [tasks.md](./tasks.md)：T68 / T69 / T70。

依赖关系：

```
T68 建表与 Mock ──▶ T69 后端第一遍业务流 ──▶ T70 前端最小展示
```

T68 产出可测的底座（表约束、Mock 可编程），T69 才有东西可断言；
T70 只做展示，不改后端契约。

## 8. 风险与回退

| 风险 | 概率 | 应对 |
|---|---|---|
| 越界判定口径漂移（用 `structure_json` 还是活表） | 中 | spec §4.1 已定：用活表；`structure_json` 不含可 join 的 id。第二期做 apply 时再加「快照未过期」校验 |
| `stats.discarded` 越堆越大，撑爆 JSON 列 | 低 | 单次分析的丢弃条数量级 ≤ 章节数 × 每章结论数；超 200 条只记前 200 条 + `truncated: true` |
| Mock 让测试脱离真实行为 | 中 | Mock 的返回按契约构造（`{"conclusions":[...]}`），解析与校验走真实代码路径；只有「模型说了什么」是预设的 |
| 一次分析同步跑，章节多时请求很慢 | 中 | 本期章节数是个位数到十几；第二期接真实模型时再引入后台任务。前端对 `running` 状态轮询/手动刷新 |
| 迁移 `downgrade` 漏删外键 | 低 | 沿用 04 的写法：**直接删表**，不先删索引（MySQL 外键依赖，04 踩过） |
| 04 引用解析器因列名不符静默失效 | 低 | AC-85 是显式回归用例，列名写错会直接红 |
