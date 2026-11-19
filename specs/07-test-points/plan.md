# 07 · 测试点分析 · 方案

> 规格 [spec.md](./spec.md) ｜ 任务 [tasks.md](./tasks.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)

## 1. 总体思路

07 是**主链路的最后一环**：04 建基线 → 05 比对变更 → 06 接真模型 → **07 产出测试点**。

本期只做一件事：**把「生效中的基线标签 + 增量分析结论」喂给大模型，产出可评审、可追溯的测试点**。

四条硬约束贯穿全期：

| 约束 | 落点 |
|---|---|
| **只吃生效标签** | `baseline_labels.status='active'` —— 复用 04 的口径，不另写一套 |
| **复用 06 的模型层** | `get_provider` / `parse_llm_json` / `parse_llm_json` 前的围栏与思考块处理，一个字都不重写 |
| **同步执行** | 与 05 第一遍一致，逐章同步调模型。不引入异步队列 / 任务中心 |
| **零真实 socket** | 测试一律 `httpx.MockTransport` 或 Mock Provider |

### 1.1 为什么输入必须含标签或增量结论

PRD 2.4.4 的输入 ②「无基线直接对文档分析」本期不做（spec §2.2）。
理由不是"做不了"，而是**没有输入就没有依据**：
- 测试点必须挂到某个功能 / 功能点上（`target_type` + `target_id` 非空），
  否则它既不可追溯，也无法参与 08 期的用例生成；
- 06 期 L2 联调实测：模型拿不到 `target_id` 清单就会瞎猜，
  猜出来的 id 全部被当越界丢弃——**先有清单，模型才知道往哪写**。

所以本期「输入为空 → 400 拒绝发起」是**设计**，不是限制。

### 1.2 为什么不做 Skill 模式

06 期已定「不做 Skill 双轨制」（`specs/06-real-llm/spec.md` §2.2）。
PRD 2.5 的 Skill 包 / manifest / schema 校验 / 回退开关是**独立的一整套机制**，
塞进 07 会让这期的体量翻三倍，且没有第二个使用场景来验证它。
07 延续 06 的口径：**只做直连模式**。

## 2. 数据层

### 2.1 迁移

`migrations/versions/0022_test_points.py`

```
revision = "0022"
down_revision = "0021"
```

建表顺序（外键依赖）：`test_point_analyses` → `test_points`。
`downgrade()` **反序直接删表**，不逐个 `drop_index`（MySQL 1553，见 `0021` 的做法）。

`test_points` 有 4 个 FK：`project_id` / `analysis_id` / `chapter_id` / `source_label_id` / `source_conclusion_id` / `created_by` / `reviewed_by`。
`downgrade` 只需 drop_table（MySQL 会连带删 FK）。

### 2.2 模型

`app/models/test_point.py`（新增文件，2 个模型）：

- `TestPointAnalysis` → 表 `test_point_analyses`
- `TestPoint` → 表 `test_points`

注册到 `app/models/__init__.py` 的 import 与 `__all__`（**必须**，
`migrations/env.py` 靠 `app.models.target_metadata` 自动发现表结构）。

> **为什么单独建文件而不是塞进 `app/models/incremental.py`**：
> 测试点是**独立的业务实体**，有自己的评审生命周期。
> 混进 incremental 会让那个文件同时承载两个模块的枚举，迟早互相污染。

### 2.3 `llm_run_logs.task_type` 的 CHECK 扩展

MySQL **不允许** `ALTER TABLE ... DROP CHECK` 之外直接改 CheckConstraint，
必须先删后加：

```python
op.drop_constraint("ck_llmlogs_task_type", "llm_run_logs", type_="check")
op.create_check_constraint(
    "ck_llmlogs_task_type",
    "llm_run_logs",
    "task_type IN ('incremental_first','incremental_second','provider_test','test_point')",
)
```

`downgrade()` 反向：删掉新 CHECK → 重建旧 CHECK。
**注意顺序**：先 drop 新约束再建旧约束，中间不能有 NOT NULL 冲突。

> **为什么不动 `app/llm/run_log.py`**：`record_run()` 的 `task_type` 是自由字符串，
> 由 DB 的 CHECK 兜底。服务层加枚举值是**服务层的事**，留痕函数一行不用改。

### 2.4 播种模板

用 `op.bulk_insert`（照 `0013` / `0015` 的写法）播种 1 条 `task_type='test_point'` 的模板：

| 字段 | 值 |
|---|---|
| `name` | `测试点生成·基于标签与增量结论` |
| `system_prompt` | 以 `[TEST_POINT_SYSTEM]` 开头 |
| `user_prompt` | 以 `[TEST_POINT_USER]` 开头 |

**`system_prompt` 里给的 JSON 示例，`target_id` 必须写 `123`（看起来像占位符）**，
不能写 `1`——真实模型会照抄示例值（06 期 L2 实测）。

`downgrade()` 里 `DELETE FROM prompt_templates WHERE name = :name`（照 `0015` 的做法）。

## 3. 模型层复用（**本期的关键设计**）

### 3.1 Provider：直接用 `get_provider`

```python
from app.llm.provider import LLMProvider, get_provider

@router.post("/analyses")
def create_analysis(
    ...,
    provider: LLMProvider = Depends(get_provider),
) -> ...:
```

**不新建 Provider、不加配置项、不改 `app/llm/provider.py`**。
无配置 → 降级 Mock → 生成记录 `succeeded`、测试点数 0（Mock 默认返回空数组）。
**平台不因没配模型而挂**——这是 06 期定下的安全阀，07 必须继承。

### 3.2 JSON 解析：直接用 `parse_llm_json`

```python
from app.llm.json_utils import parse_llm_json

payload = parse_llm_json(response.content)   # 剥 think → 剥围栏 → 取括号
```

**不自己写解析**。06 期的 `parse_llm_json` 已经处理了三件事：
`strip_think_block()`（推理模型的思考块）→ `strip_code_fence()`（Markdown 围栏）→ `extract_json_block()`（括号兜底）。
失败抛 `LLMOutputInvalid`（消息不含原始响应正文）。

07 只需要把它包一层，翻译成 07 的错误码 `TEST_POINT_INVALID`。

### 3.3 Mock Provider：加一个前缀分支

`app/llm/mock.py` 加：

```python
TEST_POINT_SYSTEM_PREFIX = "[TEST_POINT_SYSTEM]"
TEST_POINT_DEFAULT_RESPONSE = json.dumps({
    "test_points": [
        {
            "name": "mock 测试点",
            "target_type": "function",
            "target_id": 123,       # 占位符：真实 id 靠 Prompt 清单给
            "priority": "medium",
            "precondition": "mock 前置条件",
            "verification": "mock 验证要点",
        }
    ]
})
```

并在 `chat()` 的 `elif` 链里加一条：
```python
elif req.system.startswith(TEST_POINT_SYSTEM_PREFIX):
    content = TEST_POINT_DEFAULT_RESPONSE
```

> **为什么允许改 `app/llm/mock.py`**：06 期 plan §4.4 说「MockProvider 零改动」，
> 那是**06 期内部**的约束（06 改 Mock 会影响 05 的既有断言）。
> 07 加的是**新分支**（前缀不同 → 既有分支的行为一个字节没变），
> 05 的 `test_llm_provider.py` 与 `test_real_docs_e2e.py` 的断言不受影响。
> 改完必须跑 05 / 06 的既有测试确认零回归。

### 3.4 运行留痕：直接用 `record_run`

```python
run_log.record_run(
    session,
    task_type="test_point",
    provider=provider,
    calls=run_log.call_count(provider) - calls_before,   # 跑前记基线，跑完相减
    started_at=started_at,
    status="succeeded",          # 或 "failed" + error_code / error_message
    project_id=project_id,
    analysis_id=analysis.id,
    template_id=template.id,
    template_version=template.version_no,
)
```

**`calls` 必须跑前记基线、跑完相减**——`provider.calls` 是累计的（06 期 T86 的教训）。

## 4. 上下文组装（`app/test_points/context.py`）

### 4.1 结构

```
app/test_points/
├── __init__.py
├── context.py      # Prompt 组装 + 清单渲染
├── engine.py       # 纯引擎：遍历章节 → 调模型 → 解析 → 校验 → 产出候选
├── service.py      # 事务 / 权限 / 审计 / 留痕 / 落库
├── schemas.py      # 请求与响应模型
├── router.py       # 11 个路由
└── models.py?      # 不需要——模型在 app/models/test_point.py
```

### 4.2 `context.py` 的三个函数

#### `build_system_prompt(template)` → 原样返回 `template.system_prompt`

与 `app/incremental/context.py` 同名同义，便于对照。

#### `render_target_brief(index, *, max_chars=None)` → 清单文本

**照抄 `app/incremental/context.py` 的 `render_baseline_brief()`**：
- 每行 `- 功能#10096 用户扫码登录`
- 排序按 `(target_type, target_id)` → Prompt 可复现
- 截断预算 `int(max_chars * 0.4)`，截断时追加「其余 N 项已省略」

> **为什么不直接 import 05 的 `render_baseline_brief`**：
> 它接收的 index 语义是「全部结构实体」，07 的 index 语义是
> 「**生效标签命中的**目标」——是 05 的**子集**。
> 复用它的**渲染逻辑**（复制 + 改注释），不复用它的**取数逻辑**。
> 两处都调用同一套截断口径（`BASELINE_BRIEF_MAX_RATIO = 0.4`），
> 避免两个模块各调各的。

#### `build_user_prompt(template, *, chapter, targets, labels, conclusions, max_chars=None)`

段落顺序固定（spec §5.1）：

```
{template.user_prompt}

## 可对照的基线目标
- 功能#10096 用户扫码登录

## 标签依据
- [变更] 用户扫码登录（功能#10096），确认人 admin，确认于 2026-11-18 10:00

## 增量结论
- 4.2 登录失败次数限制 → 用户扫码登录：受影响（0.76）锁定期内扫码登录也会受阻

## 章节：4.2 登录失败次数限制
{chapter.content}
```

**只截章节正文**，前缀（1–4 段）保持不变 → AC-156 的「user 以模板 user_prompt 开头」在截断场景下依然成立。

### 4.3 取数口径（`context.py` 里的两个取数函数）

#### `active_label_context(session, *, project_id, revision_id=None)`

返回三样东西：

```python
@dataclass
class LabelContext:
    index: dict[tuple[str, int], str]        # (target_type, target_id) → name
    labels: list[dict]                        # 标签明细（供 Prompt 渲染）
    label_ids: dict[tuple[str, int], int]     # (target_type, target_id) → label_id
```

取数：
```sql
SELECT id, revision_id, target_type, target_id, label_type, confirmed_by, confirmed_at
FROM baseline_labels
WHERE project_id = ? AND status = 'active'
  [AND revision_id = ?]
```

**`status='active'` 是硬口径**——已清除的标签连同它的目标**完全不出现**在 Prompt 里（AC-142）。
目标名称从 `baseline_functions` / `baseline_feature_points` 现查，
查不到（目标已删）的标签**跳过**（不把悬空目标喂给模型）。

#### `conclusion_context(session, *, analysis_id)`

从 `incremental_conclusions` 取该次分析的全部结论（章节 / 目标 / 判定 / 置信度 / 理由）。
**只取 `label_type IN ('changed','affected')`**——`unchanged` 的结论没有测试价值
（PRD 2.4.4 的输入是「增量分析结果」，重点是变更与受影响）。

### 4.4 「增量结论已全部撤销」的判定

```python
def analysis_fully_revoked(session, *, analysis_id) -> bool:
    """该次分析产出的标签是否全部被清除。"""
    labels = session.scalars(
        select(BaselineLabel.id).where(
            BaselineLabel.source_analysis_id == analysis_id
        )
    ).all()
    if not labels:
        return False          # 没有标签 → 不是「全部撤销」，是「没有标签」
    active = session.scalar(
        select(func.count(BaselineLabel.id)).where(
            BaselineLabel.source_analysis_id == analysis_id,
            BaselineLabel.status == "active",
        )
    )
    return (active or 0) == 0
```

> **为什么用 `source_analysis_id` 而不是 `analysis_id`**：
> 标签挂在**快照**上（`revision_id`），而分析记录是**另一次比对**。
> 二者的连接点就是 `baseline_labels.source_analysis_id`（04 早就预留了这列，05 在写标签时填它）。
> 这是唯一能把「增量记录 → 它产出的标签」对上的字段。

### 4.5 「标签清除 → 待复核」的触发点

04 的 `clear_label()` 是唯一的清除入口。07 **不改 04 的代码**，
而是**在 07 的查询侧派生** `needs_review`：

```sql
SELECT tp.id, bl.cleared_at, bl.clear_reason
FROM test_points tp
JOIN baseline_labels bl ON bl.id = tp.source_label_id
WHERE tp.source_label_id IS NOT NULL AND bl.status = 'cleared'
```

**但 `needs_review` 是落库的列**（spec §4.2），不能只靠查询派生。
两条路：

| 方案 | 做法 | 代价 |
|---|---|---|
| A | 改 04 的 `clear_label()`，清除后 UPDATE 引用它的测试点 | **要改 04**（红线） |
| B | 07 提供一个「同步待复核」的服务函数，在**清除后被调用** | 要 04 调用 07 → 循环依赖 |
| C | 07 在**查询时**派生（`needs_review` 列不落库） | 与 spec §4.2 冲突 |

**选 A 的变体**：07 在 `clear_label()` **之后**由 04 调一个**回调**——
但这违反红线。

**最终决策**：**改 04 的 `clear_label()`，加 3 行**。
理由：
- 「标签清除后下游提示复核」是 PRD 2.4.2 明写的行为（"清除后下游约束"），
  04 只是**没做下游**，现在 07 落地了，04 补上这一处是**补齐原承诺**，不是加新功能；
- 改动极小：`clear_label()` 成功后，`UPDATE test_points SET needs_review=1 ... WHERE source_label_id = :label_id`；
- **加表探测**（照 `references.py` 的 `_table_exists` 模式）：
  表不存在（07 还没迁移）就跳过 → **04 在 07 落地前后都能跑**，不破坏既有测试。

> **红线豁免**：本条是**唯一**一处改 `app/baselines/service.py`，
> 范围严格限定为「`clear_label()` 成功后的一行 UPDATE + 表探测」，
> **不改清除逻辑本身、不改错误码、不改审计**。
> 已在 spec §2.3 补充说明，实施时在 `tasks.md` 里单列一条验收。

## 5. 引擎（`app/test_points/engine.py`）

### 5.1 模式：纯函数 + 回调（照 05 的 `engine.py`）

```python
@dataclass
class PointResult:
    chapter: DocumentChapter
    points: list[dict]          # 已校验、可落库的测试点
    discarded: list[dict]       # 被丢弃的条目 + 原因


def run_generate(
    session: Session,
    *,
    analysis: TestPointAnalysis,
    provider: LLMProvider,
    template: PromptTemplate,
    targets: LabelContext,
    conclusions: list[dict],
    chapters: list[DocumentChapter],
    on_chapter: Callable[[PointResult], None] | None = None,
) -> PassResult:
```

**「只算不写库」**：引擎不碰 session 的写操作，落库由 service 的 `on_chapter` 回调做。
这样引擎可以脱离数据库单测（与 05 一致）。

### 5.2 单章流程

```
build_system_prompt(template)
  → build_user_prompt(...)
  → provider.chat(LLMRequest(system, user))
  → parse_llm_json(response.content)          # 复用 06
  → 校验 test_points 是数组                    # 不是 → 整次失败（TestPointInvalid）
  → 逐条 _parse_point(point, targets)          # 校验 + 归一
  → 产出 PointResult
```

### 5.3 逐条校验（spec §5.3）

| 字段 | 不合法时 | 错误码 |
|---|---|---|
| `name` 缺失 / 空 | **整条丢弃** | `TEST_POINT_INVALID` |
| `target_type` 不在枚举 | **整条丢弃** | `TEST_POINT_INVALID` |
| `target_id` 不在清单内 | **整条丢弃** | `TEST_POINT_TARGET_OUT_OF_BASELINE` |
| `priority` 不在枚举 | **归一到 `medium`** | — |
| `precondition` / `verification` 缺失 | **存空串** | — |

> **为什么 `target_id` 越界要丢**：模型会照抄模板示例里的 id（06 期 L2 实测）。
> 不丢 = 把脏数据写进库，后面没人知道它挂在哪个功能上。
>
> **为什么 `priority` 不合法不丢**：优先级是展示属性，
> 丢掉整条测试点（可能包含有价值的验证要点）代价太大，归一即可。

### 5.4 章节遍历

- `char_count == 0` 的章节**不调模型**（照 05 的口径），记 `skipped_empty`。
- 逐章同步；**任一章失败立即抛错**，不续跑后续章节（照 05 的引擎契约）。
- 失败时**已落库的章节保留**（service 层在事务里 commit 已成功的部分）。

## 6. 服务层（`app/test_points/service.py`）

### 6.1 权限函数

**直接复用 05 的**（`app/incremental/service.py` 的 `_ensure_project` / `_ensure_writable_project` / `_ensure_admin` / `_ensure_member` / `ensure_readable`）。

问题：它们是**私有**的（下划线前缀），05 也没导出。

**决策**：把 05 的这 5 个权限函数**提到 `app/common/permissions.py`**（新文件），
05 与 07 都从那里 import。
- 这是**纯搬迁**，函数体一个字节不改 → 05 零行为变更；
- 05 的 `service.py` 里保留 `from app.common.permissions import ...` 的别名，
  既有测试若 import 了它们也不受影响。

> **为什么不复制粘贴到 07**：两份权限判定逻辑必然漂移。
> 「归档先判、角色后判」的顺序只有一个出处——这是 04 的 `app/baselines/router.py` docstring 明写的约定。

### 6.2 `create_analysis()` 的骨架

```python
def create_analysis(
    session: Session,
    *,
    project_id: int,
    actor: User,
    payload: AnalysisCreate,
    provider: LLMProvider,
) -> TestPointAnalysis:
```

固定顺序（spec §6.2）：

```
1. _ensure_writable_project(session, project_id)      # 404 → 409
2. _ensure_admin(session, project_id=project_id, actor=actor)   # 403
3. _load_template(session, payload.template_id)        # 400 TEST_POINT_TEMPLATE_INVALID
4. _load_analysis(session, payload.analysis_id)        # 404；全部撤销 → 409
5. _load_revision(session, payload.baseline_revision_id)  # 404；非 approved → 400
6. _load_chapters(session, ...)                       # 400 TARGET_NOT_FOUND
7. 取输入上下文（标签 / 增量结论）
8. 输入为空 → 400 TEST_POINT_INPUT_EMPTY
9. 建行 status='running' → flush
10. write_audit('test_point.analysis.create') → flush
11. calls_before = run_log.call_count(provider); started_at = time.monotonic()
12. engine.run_generate(..., on_chapter=_persist)
13. 成功：status='succeeded' + stats；失败：status='failed' + error_code
14. run_log.record_run(task_type='test_point', ...)
15. commit
```

**任何一步失败都不产生生成记录**（校验阶段失败在建行之前）。

### 6.3 失败处理

| 阶段 | 处理 |
|---|---|
| 校验阶段（1–8） | 直接抛异常，**不建行**，**不写审计** |
| 引擎阶段（12） | `status='failed'` + `error_code` / `error_message`，**已落库的章节保留**（commit），写留痕 `status='failed'` |

### 6.4 评审

```python
def review_point(session, *, project_id, point_id, actor, action, comment) -> TestPoint:
```

- `action` ∈ `('approve','reject')`；非法 → 400。
- 已评审过（`status != 'pending'`）→ 409 `TEST_POINT_REVIEW_STATE_INVALID`。
- 通过 → `status='approved'`；驳回 → `status='rejected'`。
- 记 `reviewed_by` / `reviewed_at` / `review_comment`。
- 审计 `test_point.review`，`after_data` 含 `self_approved`（自审留痕，04 同款）。

### 6.5 手工增删改

```python
def create_manual_point(session, *, project_id, actor, payload) -> TestPoint
def update_point(session, *, project_id, point_id, actor, payload) -> TestPoint
def delete_point(session, *, project_id, point_id, actor) -> None
```

- `source_type='manual'`、`analysis_id=NULL`、`source_label_id=NULL`。
- `update_point` **只接受** `name` / `precondition` / `verification` / `priority`；
  传 `target_type` / `target_id` / `status` 等 → 400 `TEST_POINT_INVALID`。
- 删除是**物理删除**（测试点是活文档，不是留痕记录）。

### 6.6 删除生成记录

```python
def delete_analysis(session, *, project_id, analysis_id, actor) -> None
```

- 该次生成产出的测试点里有 `status='approved'` 的 → 409 `TEST_POINT_ANALYSIS_HAS_APPROVED`。
- 否则连带删掉它产出的测试点，再删生成记录。
- 审计 `test_point.analysis.delete`。

## 7. 接口层（`app/test_points/router.py`）

```python
router = APIRouter(prefix="/api/projects/{project_id}/test-points", tags=["test-points"])
```

11 个路由（spec §6）。依赖注入照 05 的写法：

```python
def create_analysis(
    project_id: int,
    payload: AnalysisCreate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
    provider: LLMProvider = Depends(get_provider),
) -> AnalysisDetailOut:
```

**枚举字段一律用 `str` 不用 `Literal`**（照 `app/incremental/schemas.py` 的约定）：
非法值走服务层 400，而不是 pydantic 的 422。

在 `app/main.py` 注册：

```python
from app.test_points.router import router as test_points_router
app.include_router(test_points_router)
```

## 8. 前端

### 8.1 文件

| 文件 | 内容 |
|---|---|
| `web/src/pages/ProjectTestPointsTab.tsx` | Tab 主体（生成记录表 + 测试点表 + 发起弹窗） |
| `web/src/pages/TestPointDrawer.tsx` | 详情抽屉（全文 + 来源追溯 + 评审操作） |
| `web/src/pages/testPointMeta.tsx` | 优先级 / 状态选项与文案 |
| `web/src/api/index.ts` | 加 07 分节：类型 + 11 个函数 |
| `web/src/api/client.ts` | 加 8 个错误码中文 |
| `web/src/pages/ProjectDetailPage.tsx` | 加「测试点」Tab（插在「增量分析」之后） |

### 8.2 关键交互

- **模板下拉动态化**：照 T87 的做法，拉 `GET /api/prompt-templates?task_type=test_point`；
  无可用模板 → 禁用发起按钮 + 提示「请先在系统设置中启用提示词模板」。
- **冲突二次确认**：所选章节已有 `status='approved'` 的测试点 → 弹窗提示
  「将覆盖已有评审结果」，用户确认后才发起。
  **服务端不静默覆盖**（这是 PRD 2.4.4 明写的行为）。
- **待复核提示**：详情抽屉展示
  「所依赖基线标签已于 {时间} 被清除（原因：XX），请复核」。

### 8.3 `data-testid` 命名

照既有约定（`区域-动作-目标`）：

```
testpoint-tab / testpoint-create-btn / testpoint-table / testpoint-row-{id}
testpoint-form-template / testpoint-form-analysis / testpoint-form-revision
testpoint-detail-drawer / testpoint-review-approve / testpoint-review-reject
testpoint-manual-create / testpoint-needs-review-tag
```

## 9. 引用保护（04 侧）

`app/baselines/references.py` 加一个解析器：

```python
def _test_point_references(session: Session, revision_id: int) -> list[dict]:
    if not _table_exists(session, TEST_POINT_ANALYSIS_TABLE):
        return []
    rows = session.execute(
        text("SELECT id FROM test_point_analyses WHERE baseline_revision_id = :rid"),
        {"rid": revision_id},
    ).all()
    return [
        {"source_type": "test_point_analysis",
         "target_id": row_id,
         "target_name": f"测试点生成 #{row_id}"}
        for (row_id,) in rows
    ]
```

并注册到 `_resolvers`（用 `register_resolver()`）。

**既有解析器不动** → AC-158 的「既有引用条目的数量与内容不变」成立。

## 10. 任务拆分（T99 – T104）

| 任务 | 内容 | 产出 |
|---|---|---|
| **T99** | 建表 + 模型 + 迁移 `0022` + 播种模板 + 扩 `llm_run_logs` CHECK + 错误码 | 表可 upgrade/downgrade；`test_point` 枚举可用 |
| **T100** | 上下文组装 + 引擎（纯函数）+ 标签 / 增量结论取数 + 越界丢弃 | Prompt 可复现；坏 JSON 整次失败 |
| **T101** | 服务层 + 路由 + 审计 + 运行留痕 + 权限函数搬迁（05 → `app/common/permissions.py`） | 11 个接口可断言 |
| **T102** | 评审 + 手工增删改 + 删除生成记录 + **04 `clear_label()` 补待复核标记** | 评审闭环 |
| **T103** | 前端：Tab + 列表 + 详情抽屉 + 评审 + 手工编辑 + 发起弹窗 | `npm run build` 通过 |
| **T104** | 收尾：全量 pytest + e2e + 迁移往返 + 文档回填（`PROGRESS.md` / 本文件 / `specs/验证约定.md`） | 零回归 |

**依赖**：T99 → T100 → T101 → T102 → T103 → T104。

### 10.1 任务与 AC 的对应

| 任务 | AC |
|---|---|
| T99 | AC-141（表结构部分）、AC-154（`task_type` 枚举）、AC-156（模板播种） |
| T100 | AC-142 / AC-143 / AC-144 / AC-145 / AC-146 / AC-156（Prompt 部分） |
| T101 | AC-141 / AC-152 / AC-153 / AC-154 / AC-156 |
| T102 | AC-147 / AC-148 / AC-149 / AC-150 |
| T103 | AC-157 |
| T104 | AC-151 / AC-155 / AC-158 |

### 10.2 验收基线

| 项 | 当前值 | 07 完成后 |
|---|---|---|
| 后端全量 pytest | **864 passed** | ≥ 864（只增不减） |
| e2e | **40 passed** | ≥ 40（新增若干条） |
| 前端构建 | 通过 | 通过 |
| 迁移 head | `0021` | `0022` |

## 11. 风险与回退

| 风险 | 概率 | 对策 |
|---|---|---|
| 真实模型返回的 `target_id` 全是猜的 | **高** | Prompt 必须给清单（§4.2）；越界即丢（§5.3）；模板示例 id 用 `123` |
| 模型输出结构不符（不是数组 / 字段缺失） | 中 | 整次失败 + `TEST_POINT_INVALID`；**不做智能修复**（06 期的边界） |
| 推理模型的 `<think>` 块破坏解析 | 中 | `parse_llm_json` 已处理（06 期实测） |
| 标签清除后测试点状态不一致 | 中 | 「不改内容 + 标待复核」（§4.5 决策）；评审状态不自动降级 |
| 04 的 `clear_label()` 改动影响既有测试 | 低 | 表探测 + 只加 3 行；既有测试全量回归 |
| 权限函数搬迁影响 05 | 低 | 纯搬迁 + 别名导出；05 全量回归 |
| Mock 返回的 `target_id=123` 不在清单 → 全被丢 | 中 | e2e 用例要**按清单给 Mock 队列**，不能靠默认值；见 §12 |

## 12. 测试要点

### 12.1 目录

```
tests/test_points/
├── __init__.py
├── conftest.py       # provider 夹具（照 tests/incremental/conftest.py）
├── helpers.py        # 造数：标签 / 增量结论 / 模板 / 章节
├── test_models.py            # 表约束
├── test_context.py           # Prompt 组装 / 清单渲染 / 截断
├── test_engine.py            # 引擎：坏 JSON / 越界 / 归一
├── test_generate_flow.py     # 发起生成全链路
├── test_review.py            # 评审流程
├── test_manual.py            # 手工增删改
├── test_needs_review.py      # 标签清除 → 待复核
└── test_permissions.py       # 权限矩阵
```

### 12.2 造数要点

- **标签**：`baseline_labels` 需要挂在**已 approved 的快照**上（`revision_id` 必填），
  照 `tests/incremental/helpers.py` 的 `make_revision()` 造。
- **清单里的 id 必须与 Mock 返回的 `target_id` 对上**：
  Mock 默认返回 `target_id=123`，而清单里是真实 id → **全被当越界丢弃**。
  用例必须用 `MockProvider(queue=[...])` 显式给一条**命中清单**的 JSON，
  或让 Mock 返回空数组只断言落库条数。
  **这是 06 期「Mock 通过 ≠ 真实模型能跑」的同一个坑。**

### 12.3 零 socket

- `tests/conftest.py` 已有 autouse 夹具摘掉 `llm_providers` 的默认配置行；
- 真实 Provider 的用例一律 `httpx.MockTransport`；
- 沿用 06 期的守卫用例（`test_ac_84_tests_never_use_real_socket`）。

## 13. 不做什么（再次确认）

- **不做 Skill 模式**（PRD 2.5）——06 期已定，07 延续。
- **不做测试用例分析**（08 期）。
- **不做「无基线直接分析」模式**——输入为空 → 400。
- **不做工作台待办接入**——等 08 期统一口径。
- **不做流程基线**。
- **不做 Token 计费 / 配额**。
- **不改 04 / 05 的判定逻辑**（只补 04 的 `clear_label()` 待复核标记 + 搬移权限函数）。
- **不改 `app/llm/` 的 Provider / 解析 / 留痕**（只加 Mock 的一个前缀分支）。
