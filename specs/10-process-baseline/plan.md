# 10 · 流程基线 · 技术方案

> 配套 [spec.md](./spec.md)（AC-197 ~ AC-214）与 [tasks.md](./tasks.md)（T117 ~ T123）。
> 定位：在 04「功能基线」旁边补上 PRD 2.4.2 的另一个子菜单「流程基线」，
> **独立建表、不重写基础设施**。

## 1. 总体思路

```
PRD 流程基线（场景 / 前置条件 / 操作步骤 / 关联功能基线）
      │
      ├─ service.list/create/update/delete_scenario   ← 场景 CRUD（批量新建）
      ├─ service.replace_steps                        ← 步骤整体覆盖（照抄 08）
      ├─ service.replace_links                        ← 关联整体覆盖（M:N、无 FK、名称快照）
      │
      ├─ derive.run_derive()                          ← 文档反推（纯函数，签名里没有 session）
      │
      └─ router / review                              ← 提交冻结 / 通过转正 / 驳回
```

四条关键设计：

1. **独立建表，对 04 零改动** —— 两套基线是两套并列资产，
   共用表会污染 04 的三处 CHECK 与版本号序列（spec §3.1）。
2. **反推引擎是纯函数** —— `run_derive()` 的签名里**没有 `session`**，
   「反推只出草案不写表」从「靠自觉」变成「结构上做不到」。
3. **提交即冻结 + 审核期锁定** —— 审核人看到的与最终冻结的**逐字节相同**
   （`structure_json` 直接由 `draft_snapshot` 转正）。
4. **关联无外键 + 名称快照** —— 04 物理删功能后链接行仍在、名称可读、
   04 的删除接口**仍返回 204**。

## 2. 目录与文件

```
app/process_baselines/
├── __init__.py
├── derive.py       # 文档反推引擎（纯函数，无 session）
├── service.py      # 场景 CRUD / 步骤 / 关联 / 反推编排 / 审核与快照
├── schemas.py      # Pydantic 请求 / 响应模型
└── router.py       # 13 个路由

app/models/process_baseline.py             # ProcessBaseline / Step / Link / Revision
migrations/versions/0025_process_baselines.py   # 4 表 + CHECK 扩枚举 + 播种模板
tests/process_baselines/…                  # 见 §10
web/src/pages/ProjectBaselineManagementTab.tsx
web/src/pages/ProjectProcessBaselineTab.tsx
web/src/pages/processBaselineColumns.tsx
web/src/pages/ProcessBaselineDrawer.tsx
web/src/pages/ProcessBaselineStepsEditor.tsx
web/src/pages/ProcessBaselineDeriveModal.tsx
web/src/pages/ProcessBaselineReviewDrawer.tsx
web/src/pages/processBaselineMeta.ts
tests/e2e/test_process_baseline_ui.py
```

`app/common/errors.py` 加 8 个错误类；
`app/models/__init__.py` 加 4 个模型的注册；
`app/models/incremental.py` 的 `TASK_TYPES` 与 `ck_ptemplates_task_type` 各加一个枚举值；
`app/llm/mock.py` 加一个前缀分支；`app/main.py` 注册 1 个路由。

## 3. 数据层

### 3.1 模型

`app/models/process_baseline.py` 照 04 / 07 / 08 / 09 的写法：`Mapped[...]` +
`mapped_column`，列类型照抄 08（`BIGINT(unsigned=True)` / `DATETIME(fsp=3)` /
`String(n)`，`created_at` 用 `server_default=text("CURRENT_TIMESTAMP(3)")`），
表选项 `_TABLE_OPTS` 与 04 同一份字典。

- **四个类都写 `__test__ = False`**（`ProcessBaseline*` 不撞 pytest 规则，
  但统一加上更省心——08 的 `TestCase*` 已有先例）。
- **不建 ORM `relationship`**（04 / 07 / 08 / 09 都不用），一律显式查询。
- `ProcessBaselineStep.baseline_id` / `ProcessBaselineLink.baseline_id` 的 FK
  带 `ondelete="CASCADE"`（数据库级）。
- **`ProcessBaselineLink.target_id` 绝不建 FK**：04 的删功能是物理删除，
  建 FK 会把 04 的既有行为变成 500（与 08 的 `test_point_id`、
  09 的 `linked_case_id` 同一教训）。

**四个模型类的关键列**：

```python
class ProcessBaseline(Base):
    """业务场景。`version_no` 是场景自身的修订次数，不是快照版本号。"""
    __tablename__ = "process_baselines"
    __test__ = False
    # CHECK: source_type IN ('manual','document_derived')
    #        status   IN ('active','archived')
    # UNIQUE: uk_pbaselines_project_name(project_id, name)


class ProcessBaselineStep(Base):
    """操作步骤。`step_no` 由服务端按数组顺序重排为 1..n。"""
    __tablename__ = "process_baseline_steps"
    __test__ = False
    # FK baseline_id → process_baselines.id  ON DELETE CASCADE
    # UNIQUE uk_pbsteps_baseline_no(baseline_id, step_no)
    # CHECK ck_pbsteps_no_positive (step_no >= 1)


class ProcessBaselineLink(Base):
    """关联功能基线。`target_id` 不建外键，`target_name` 是名称快照。"""
    __tablename__ = "process_baseline_links"
    __test__ = False
    # FK baseline_id → process_baselines.id  ON DELETE CASCADE
    # CHECK ck_pblinks_target_type (target_type IN ('function','feature_point'))
    # UNIQUE uk_pblinks_baseline_target(baseline_id, target_type, target_id)


class ProcessBaselineRevision(Base):
    """审核记录 / 版本快照，一体表。"""
    __tablename__ = "process_baseline_revisions"
    __test__ = False
    # CHECK ck_pbrevisions_status (status IN ('submitted','approved','rejected'))
    # UNIQUE uk_pbrevisions_project_no(project_id, version_no)
```

### 3.2 迁移 `0025`

`down_revision = "0024"`。upgrade 顺序（**有外键依赖，顺序不能乱**）：

1. `drop_constraint("ck_ptemplates_task_type", "prompt_templates", type_="check")`
   → `create_check_constraint` 含 `'process_baseline'`
2. 播种模板 `流程基线推导·场景抽取`（`task_type='process_baseline'`，
   `system_prompt` 以 `[PROCESS_BASELINE_SYSTEM]` 开头）
3. `create_table("process_baselines")`
4. `create_table("process_baseline_steps")`
5. `create_table("process_baseline_links")`
6. `create_table("process_baseline_revisions")`

downgrade 严格反序：

1. `drop_table("process_baseline_revisions")`
2. `drop_table("process_baseline_links")`
3. `drop_table("process_baseline_steps")`
4. `drop_table("process_baselines")`
5. `DELETE FROM prompt_templates WHERE task_type='process_baseline'`
6. `drop_constraint` → `create_check_constraint` 恢复旧的四值 CHECK

> **第 1 步与第 5 步的顺序不能反**：MySQL 不允许直接改 CHECK，必须先删后加
> （08 期在 `llm_run_logs` 上踩过同一件事，`migrations/versions/0023_test_cases.py:279-285`）。
>
> **第 5 步必须在第 6 步之前**：`task_type='process_baseline'` 的残留行会让旧 CHECK
> 重建失败（3819）。08 期在 `llm_run_logs` 上踩过同一个坑
> （`migrations/versions/0023_test_cases.py:321-322` 的注释写明了原因）。
>
> **第 1 步必须在第 2 步之前**：先扩 CHECK 再播种，反了的话插入会被旧 CHECK 拒（3819）。

### 3.3 错误码

`app/common/errors.py` 末尾追加 8 个类（`AppError` 子类），补进 `__all__`。
命名与 04 / 07 / 08 / 09 保持同一形态：统一 `ProcessBaseline*` 前缀。

| 类名 | code | HTTP |
|---|---|---|
| `ProcessBaselineNotFound` | `PROCESS_BASELINE_NOT_FOUND` | 404 |
| `ProcessBaselineInvalid` | `PROCESS_BASELINE_INVALID` | 400 |
| `ProcessBaselineDuplicateName` | `PROCESS_BASELINE_DUPLICATE_NAME` | 409 |
| `ProcessBaselineStepInvalid` | `PROCESS_BASELINE_STEP_INVALID` | 400 |
| `ProcessBaselineLinkInvalid` | `PROCESS_BASELINE_LINK_INVALID` | 400 |
| `ProcessBaselineRevisionNotFound` | `PROCESS_BASELINE_REVISION_NOT_FOUND` | 404 |
| `ProcessBaselineReviewStatusInvalid` | `PROCESS_BASELINE_REVIEW_STATUS_INVALID` | 409 |
| `ProcessBaselineInReview` | `PROCESS_BASELINE_IN_REVIEW` | 409 |

**另复用 1 个既有的错误类**（不改 04 的判定逻辑，只复用类本身）：
`ReviewCommentRequired`（`REVIEW_COMMENT_REQUIRED`，400）——驳回意见必填。

## 4. 反推引擎（`derive.py`）

### 4.1 与 04 期 `app/baselines/derive.py` 的四点差异

| 维度 | 04 期 | 本期 | 差异的原因 |
|---|---|---|---|
| **输出根结构** | `{"modules": [...]}` —— 三级树 | `{"scenarios": [...]}` —— **平铺列表** | 流程基线是场景列表，**没有层级**。若沿用树结构，模型要多输出一层无意义的包装 |
| **「已有清单」段内容** | **已有功能基线结构**（模块 → 功能） | **① 已有流程基线场景名清单** + **② 可关联的功能基线清单**（模块 → 功能 → 功能点，**带 id**） | ①防重复抽取（04 的 `render_existing_brief` 的存在理由）；②**模型要产出关联就必须知道有哪些功能可选、id 是多少**——06 期 L2 联调翻车就是因为没给清单，模型自己编 `target_id=1` |
| **合并策略** | 同名模块 / 功能 / 功能点按名字合并，子树补空缺（`_MergedTree`） | 同名场景按名字合并；**步骤保留首次出现**（不追加）、`source_chapter_id` 取第一次出现 | 步骤是**有序列表**，追加会重复；04 的功能点也是列表但它挂在一棵树下、合并粒度在父节点 |
| **落库方式** | 写 `baseline_derives` + 候选表 → 人工采纳（**两套表**） | 引擎**纯函数**，响应直接返回候选；用户勾选后走 `POST /scenarios` 批量采纳 | 与 09 期「扫描 → 人工确认入库」同一交互范式；**不再造候选表**（候选只是临时草稿，04 的候选表是历史包袱） |

### 4.2 引擎签名与契约

```python
@dataclass
class CandidateScenario:
    """候选场景（尚未落库）。"""
    name: str
    description: str | None = None
    precondition: str | None = None
    confidence: Decimal | None = None
    rationale: str | None = None
    source_chapter_id: int | None = None
    source_chapter_title: str | None = None
    steps: list[tuple[str, str]] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)


@dataclass
class DeriveResult:
    chapter_count: int
    processed_count: int
    skipped_chapters: list[dict]
    scenarios: list[CandidateScenario]


def run_derive(
    *,
    provider: LLMProvider,
    template: PromptTemplate,
    document_name: str,
    version_no: int,
    chapters: list[dict],
    existing_scenarios: list[str],
    linkable_targets: list[dict],
    max_chars: int | None = None,
) -> DeriveResult:
    """逐章节调用模型并合并候选。

    **签名里没有 `session`**——「反推只出草案不写表」结构上做不到。
    """
```

| 规则 | 实现 |
|---|---|
| 空章节不调模型 | `char_count == 0` 或正文空白 → 记 `empty_content`，`continue` |
| 空结果不算失败 | `{"scenarios": []}` → 记 `no_structured_content` |
| 坏 JSON / 根结构不对 → 整次失败 | `parse_llm_json` 解析失败或根不是 `{"scenarios": [...]}` → `LLMOutputInvalid` |
| 单候选名字为空 / 超长 → **只丢该候选** | `_normalize_scenario` 返回 `None` |
| 越界 `target_id` → **只丢该条关联** | `target_id` 不在 `linkable_targets` 里 → 跳过该条 link，候选与其步骤保留 |
| 步骤的 `action` 为空 → **只丢该步骤** | 步骤是候选的一部分，整条丢弃代价太大 |
| 跨章节合并 | `_MergedScenarioMerger`：同名场景按名字合并，步骤**保留首次出现** |
| 长度上限 | 场景名 128 / 描述 500 / 理由 1000 / `action` 与 `expected` 各 1000 |

### 4.3 Prompt 组装（四段，与 04 同构但内容不同）

```
user = f"{template.user_prompt}

         ## 文档信息
         - 文档名：{document_name}
         - 版本：v{version_no}

         ## 已有流程基线场景（避免重复抽取）
         {existing_scenarios}

         ## 可关联的功能基线目标（target_id 取自这里）
         {linkable_targets}

         ## 章节：{chapter_title}
         {chapter_content}"
```

> **「可关联的功能基线目标」这一段不能省** —— 06 期的教训：
> 模型看不到清单就会瞎猜 id，结论全被当成越界丢弃。
>
> 两份清单都**只给名称（+ 关联那一份额外给 id）**，排序稳定，保证同一份 Prompt 可复现。
> 超长时按 `BASELINE_BRIEF_MAX_RATIO`（`app/incremental/context.py:37`，0.4）截断，
> **只砍清单段尾部**，模板正文与章节正文不动。

## 5. 服务层（`service.py`）

### 5.1 函数职责表

| 函数 | 职责 | 权限 |
|---|---|---|
| `ensure_readable(session, *, project_id, actor)` | 读接口权限入口（转发 `permissions.ensure_readable`） | 成员 |
| `_ensure_admin(session, *, project_id, actor, action)` | 写接口权限入口（归档先判、角色后判） | 项目管理员 |
| `list_scenarios(session, project_id, *, keyword, source_type, status, page, page_size)` | 场景列表 + 分页 | 成员 |
| `create_scenarios(session, *, project_id, actor, items)` | **批量**新建（手工 / 反推采纳）；**整批拒** | 项目管理员 |
| `get_scenario(session, *, project_id, scenario_id)` | 详情（步骤 + 关联 + `target_deleted`） | 成员 |
| `update_scenario(session, *, project_id, actor, scenario_id, ...)` | 改元数据；内容变更 `version_no += 1` | 项目管理员 |
| `delete_scenario(session, *, project_id, actor, scenario_id)` | 物理删除（级联步骤与关联） | 项目管理员 |
| `replace_steps(session, *, project_id, actor, scenario_id, steps)` | 步骤整体覆盖 | 项目管理员 |
| `replace_links(session, *, project_id, actor, scenario_id, links)` | 关联整体覆盖 | 项目管理员 |
| `run_derive(session, *, project_id, actor, document_id, document_version_id, template_id, provider)` | 发起反推（**不写表**） | 项目管理员 |
| `submit_review(session, *, project_id, actor, comment)` | 提交审核（冻结 `draft_snapshot`） | 项目管理员 |
| `approve_review(session, *, project_id, actor, revision_id, comment)` | 通过（转正 + 分配版本号） | 项目管理员 |
| `reject_review(session, *, project_id, actor, revision_id, comment)` | 驳回（意见必填） | 项目管理员 |
| `list_revisions(session, project_id, *, page, page_size)` | 快照列表 | 成员 |
| `get_revision(session, *, project_id, revision_id)` | 快照详情 | 成员 |
| `_collect_snapshot(session, project_id)` | 收集全部 active 场景 → 快照 JSON + 计数 | — |
| `_freeze_draft(session, project_id)` | 冻结 `draft_snapshot` | — |
| `_next_version_no(session, project_id)` | 项目内下一个快照版本号（**只查本表**） | — |
| `_ensure_not_in_review(session, project_id)` | 审核期锁定检查 | — |

### 5.2 步骤校验规则（照抄 08）

```python
MAX_STEPS = 100

def _validate_steps(steps: list[dict]) -> list[tuple[str, str]]:
    """校验整组步骤。**不合法就整组拒**（不留半截状态）。"""
    if not steps:
        raise ProcessBaselineStepInvalid("步骤不能为空")
    if len(steps) > MAX_STEPS:
        raise ProcessBaselineStepInvalid(f"步骤不能超过 {MAX_STEPS} 步")
    cleaned = []
    for row in steps:
        action = (row.get("action") or "").strip()
        if not action:
            raise ProcessBaselineStepInvalid("步骤的操作不能为空")
        expected = (row.get("expected") or "").strip()
        cleaned.append((action[:1000], expected[:1000]))
    return cleaned
```

**覆盖方式**（与 08 的 `replace_steps` 同一顺序）：**先校验整组** → 删旧 →
按数组顺序 `enumerate(steps, start=1)` 插新 → `flush` → 审计 → commit。

> **整组拒的理由**（与 08 一致）：半截状态比「什么都没改」更糟——
> 用户以为改成功了，库里却是一份拼接物。

### 5.3 关联校验规则

| 顺序 | 校验 | 失败 |
|---|---|---|
| 1 | `target_type` ∈ {`function`, `feature_point`} | 400 `PROCESS_BASELINE_LINK_INVALID` |
| 2 | 目标存在、`project_id` 匹配、`status='active'` | 400 `PROCESS_BASELINE_LINK_INVALID` |
| 3 | 同一次提交里 `(target_type, target_id)` 不重复 | 400 `PROCESS_BASELINE_LINK_INVALID` |
| 4 | 单场景关联数 ≤ 50 | 400 `PROCESS_BASELINE_LINK_INVALID` |

**名称快照由服务端重查写入**（`target_name` 不采信客户端传值）——
与 09 的「入库时服务端重扫重算」同一思路。

**空数组允许**（清空关联）；**步骤的空数组不允许**——两者语义不同（spec §5.3）。

### 5.4 审核与快照的流程

```python
def submit_review(session, *, project_id, actor, comment=None) -> ProcessBaselineRevision:
    # 1 校验：项目 404 → 归档 409 → 角色 403
    # 2 已有 status='submitted' 的快照 → 409 PROCESS_BASELINE_IN_REVIEW
    # 3 当前无 active 场景 → 400 PROCESS_BASELINE_INVALID
    # 4 冻结：_freeze_draft(session, project_id) → draft_snapshot JSON + 三个计数
    # 5 建 ProcessBaselineRevision(status='submitted', draft_snapshot=…)
    # 6 审计 process_baseline.review.submit → commit
```

```python
def approve_review(session, *, project_id, actor, revision_id, comment=None):
    # 1 校验：项目 404 → 归档 409 → 角色 403
    # 2 快照不存在 → 404 PROCESS_BASELINE_REVISION_NOT_FOUND
    # 3 status != 'submitted' → 409 PROCESS_BASELINE_REVIEW_STATUS_INVALID
    # 4 自审：读系统设置 allow_baseline_self_approval
    #    提交者 == 审核者 且开关关闭 → 403 SelfApprovalForbidden（复用 04 的类）
    # 5 revision.structure_json = revision.draft_snapshot   ← **原样转正，逐字节相同**
    # 6 revision.version_no = _next_version_no(session, project_id)   ← 只查本表
    # 7 status='approved' + reviewed_by / reviewed_at → 审计 → commit
```

```python
def reject_review(session, *, project_id, actor, revision_id, comment):
    # 1 同上的前 3 步
    # 2 意见必填 → 复用 ReviewCommentRequired（400）
    # 3 status='rejected'；**不分配 version_no、不写 structure_json**
    #    （draft_snapshot 保留供追溯）
    # 4 审计 process_baseline.review.reject → commit
```

**审核期锁定**：`_ensure_not_in_review(session, project_id)` 在
`update_scenario` / `delete_scenario` / `replace_steps` / `replace_links` 里调用，
命中则抛 `ProcessBaselineInReview`（409）。

**冻结内容**（`_collect_snapshot`）：

```python
{
  "scenarios": [
    {
      "id": 1, "name": "...", "description": "...", "precondition": "...",
      "source_type": "document_derived", "status": "active", "version_no": 2,
      "steps": [{"step_no": 1, "action": "...", "expected": "..."}],
      "links": [{"target_type": "function", "target_id": 10096, "target_name": "用户扫码登录"}]
    }
  ],
  "counts": {"scenarios": 1, "steps": 2, "links": 1}
}
```

**归档场景不参与快照**（与 04 的 `_collect_structure` 过滤 `status='active'` 一致），
归档场景的步骤与关联也不计入计数。

**一次性批量查询**：收集快照时先取全部 active 场景的 id，
再用**一次 `IN`** 查步骤与关联，在 Python 层建映射——**不做 N+1**
（与 09 的 `_cases_by_ids` 同一思路）。

## 6. 路由层（`router.py`）

- 13 个路由，前缀 `/api/projects/{project_id}/process-baselines`。
- 每个写接口固定 4 步：`项目 404 → 归档 409 → 权限 403 → 业务校验 400`。
- 响应模型：入参 `ConfigDict(extra="allow")`（让多余字段活到服务层判 400，
  而不是被 pydantic 静默丢弃），出参用 Pydantic 模型。
- `POST /derive` 与 `POST /reviews/submit` 是**同步**接口，前端要有 loading
  与足够长的超时（与 04 推导的同步执行同一策略）。

## 7. 接口一览（13 个）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/scenarios` | 成员 | 场景列表（keyword / source_type / status 筛选，分页） |
| POST | `/scenarios` | 项目管理员 | 批量新建（手工 / 反推采纳） |
| GET | `/scenarios/{id}` | 成员 | 详情（步骤 + 关联 + `target_deleted`） |
| PATCH | `/scenarios/{id}` | 项目管理员 | 改元数据 |
| DELETE | `/scenarios/{id}` | 项目管理员 | 删场景（级联） |
| PUT | `/scenarios/{id}/steps` | 项目管理员 | 整体覆盖步骤 |
| PUT | `/scenarios/{id}/links` | 项目管理员 | 整体覆盖关联 |
| POST | `/derive` | 项目管理员 | 文档反推（不写表） |
| POST | `/reviews/submit` | 项目管理员 | 提交审核（冻结） |
| POST | `/reviews/{id}/approve` | 项目管理员 | 审核通过（转正） |
| POST | `/reviews/{id}/reject` | 项目管理员 | 审核驳回 |
| GET | `/revisions` | 成员 | 快照列表 |
| GET | `/revisions/{id}` | 成员 | 快照详情 |

请求 / 响应示例见 spec §7.1 ~ §7.4。

## 8. 审计

| 场景 | action | after_data |
|---|---|---|
| 批量新建场景 | `process_baseline.scenario.create` | `created` 计数 + 场景名列表（截断） |
| 改场景 | `process_baseline.scenario.update` | `scenario_id` / 变更字段 / 变更前后 `version_no` |
| 删场景 | `process_baseline.scenario.delete` | `scenario_id` / 场景名 / 级联清理的步骤数与关联数 |
| 覆盖步骤 | `process_baseline.steps.update` | `before_count` / `after_count` |
| 覆盖关联 | `process_baseline.links.update` | `before_count` / `after_count` |
| 发起反推 | `process_baseline.derive.run` | `document_id` / `document_version_id` / `template_id` / `provider` / 统计 |
| 提交审核 | `process_baseline.review.submit` | `revision_id` / 三个计数 / `comment` |
| 审核通过 | `process_baseline.review.approve` | `revision_id` / `version_no` / 三个计数 / `self_approved` |
| 审核驳回 | `process_baseline.review.reject` | `revision_id` / `comment` |

全部走 `app/common/audit.py` 的 `write_audit`（只 add + flush，不 commit）。
**失败操作不写审计**（校验在建行之前）。

`tests/common/test_audit_coverage.py` 的 `SCENARIOS` 字典要补这 9 个场景
（该文件是**写操作审计覆盖**的清单——新增写操作而忘了写审计时，这份清单会缺项）。

## 9. 前端

### 9.1 组件拆分（单文件 < 400 行，验证约定 §4.3）

| 文件 | 预估行数 | 职责 |
|---|---|---|
| `web/src/pages/ProjectBaselineManagementTab.tsx` | ~90 | 二级 Tabs 外壳（状态与事件编排） |
| `web/src/pages/ProjectProcessBaselineTab.tsx` | ~280 | 场景列表 + 工具条 + 编辑 / 删除 / 刷新（编排） |
| `web/src/pages/processBaselineColumns.tsx` | ~180 | 列表列定义（纯渲染） |
| `web/src/pages/ProcessBaselineDrawer.tsx` | ~330 | 详情抽屉（元数据 + 步骤 + 关联） |
| `web/src/pages/ProcessBaselineStepsEditor.tsx` | ~180 | 步骤编辑器 |
| `web/src/pages/ProcessBaselineDeriveModal.tsx` | ~230 | 反推弹窗（选文档 / 版本 / 模板 → 候选勾选 → 采纳） |
| `web/src/pages/ProcessBaselineReviewDrawer.tsx` | ~250 | 快照列表 + 提交 / 通过 / 驳回 + 快照内容 |
| `web/src/pages/processBaselineMeta.ts` | ~80 | 状态 / 来源 / 目标类型的中文文案与颜色 |

`ProjectDetailPage.tsx`（当前 379 行）只做**减法**——把基线管理的内容换成
`<ProjectBaselineManagementTab />`，**行数不增**。

> **为什么必须外提**：验证约定 §4.3 的阈值是「单页组件超过约 400 行要拆」。
> 379 行 + 基线管理的内容 = 超阈值。外提后主文件只少不少。

### 9.2 交互要点

- **步骤编辑**：受控数组 + 「上移 / 下移 / 删除」按钮 + 「新增步骤」。
  **不用拖拽**（antd Table 里要额外引依赖，且无障碍性差——08 期已定这个取舍，
  见 `web/src/pages/TestCaseStepsEditor.tsx:30-35` 的注释）。
  保存走 `PUT .../steps` **整体覆盖**；**前端不发 `step_no`**（服务端重排）。
- **关联编辑**：多选下拉（可关联的功能基线清单）+ 已选列表（可删）。
  保存走 `PUT .../links` 整体覆盖。
- **反推弹窗**：选文档 → 选生效版本 → 选模板 → 「开始反推」→ 候选表（勾选）→
  「采纳为场景」。**候选默认全不勾**（PRD 1.4 原则二：高风险行为人工确认）。
- **权限渲染**：`canManage` 才渲染写入口；成员与访客**一个都不渲染**，
  只显示一句只读提示（与 09 期 `ProjectAutomationTab.tsx` 同一口径）。
- **审核中**：列表上的写入口**禁用** + 提示「审核中，暂不可编辑」。

### 9.3 `data-testid` 清单（统一前缀 `process-baseline-`）

```
process-baseline-subtab / process-baseline-subtab-function / process-baseline-subtab-process
process-baseline-table / process-baseline-row-{id} / process-baseline-refresh-btn
process-baseline-create-btn / process-baseline-derive-btn
process-baseline-detail-btn-{id} / process-baseline-edit-btn-{id} / process-baseline-delete-btn-{id}
process-baseline-drawer / process-baseline-meta-form / process-baseline-save-btn
process-baseline-steps-editor / process-baseline-step-add-btn
process-baseline-step-action-input-{i} / process-baseline-step-expected-input-{i}
process-baseline-step-up-{i} / process-baseline-step-down-{i} / process-baseline-step-remove-{i}
process-baseline-links-table / process-baseline-link-select / process-baseline-link-confirm-btn
process-baseline-link-row-{i} / process-baseline-link-remove-{i}
process-baseline-derive-modal / process-baseline-derive-doc-select
process-baseline-derive-version-select / process-baseline-derive-template-select
process-baseline-derive-run-btn / process-baseline-derive-table
process-baseline-derive-check-{i} / process-baseline-derive-confirm-btn
process-baseline-review-table / process-baseline-review-submit-btn
process-baseline-review-approve-btn-{id} / process-baseline-review-reject-btn-{id}
process-baseline-review-comment-input / process-baseline-snapshot-drawer
process-baseline-snapshot-content / process-baseline-snapshot-scenario-{i}
```

**antd 的两个坑**（09 期踩过，见 tasks.md T115 补充记录）：
① 行的锚点要用 `onRow` 返回 `data-testid`，`rowClassName` 只能给 class；
② **disabled 的按钮不派发鼠标事件**，Tooltip 必须挂在外层 `<span>` 上。

## 10. 测试策略

| 层 | 文件 | 重点 |
|---|---|---|
| 模型 / 迁移 | `tests/process_baselines/test_models.py` / `test_migration.py` | 四表存在；CHECK 接受合法值、拒绝非法值（3819）；唯一键生效；`0025↔0024` 往返；模板播种；**两套版本号互不干扰** |
| 场景 CRUD | `tests/process_baselines/test_scenarios.py` | 批量建 / 改名 / 同名 409 / 删除级联 / 归档不参与快照 / 整批拒 |
| 步骤 | `tests/process_baselines/test_steps.py` | 空数组 400 / 101 步 400 / 空 action 400 / **整组拒（旧步骤原样保留）** / 序号重排 / 忽略客户端 `step_no` / 截断 1000 |
| 关联 | `tests/process_baselines/test_links.py` | M:N；**无 FK**；服务端重查名称；跨项目 400；归档目标 400；重复 400；**04 物理删功能后链接仍在 + `target_deleted=true` + 04 删除仍 204** |
| 反推 | `tests/process_baselines/test_derive.py` | 纯函数（签名无 session）；**反推不写表**；根结构 `scenarios`；坏 JSON 整次失败；单候选丢弃；**越界 `target_id` 只丢该条关联**；空章节不调模型；Prompt 含两份清单 |
| 审核快照 | `tests/process_baselines/test_review.py` | 提交冻结；**审核期锁定 409**；通过转正**逐字节相同**；版本号 v1.0 / v1.1；驳回不占版本号且保留 `draft_snapshot`；归档场景不入快照 |
| 权限 / 归档 | `tests/process_baselines/test_permissions.py` | 矩阵；403 / 404 / 409 顺序（**归档先于角色判**） |
| 欠账断言 | `tests/process_baselines/test_deferred_features.py` | **无标签表 / 无标签接口 / 无保留策略接口 / 无快照删除接口 / `projects` 表无新增列** |
| e2e | `tests/e2e/test_process_baseline_ui.py` | `test_ac_212_*_ui`（二级子菜单 + 顶层仍 10 个 Tab）；`test_ac_213_*_ui`（场景全链路） |

测试函数统一命名 `test_ac_<AC号>_<场景>`（验证约定 §4.2）；
e2e 命名 `test_ac_<AC号>_<场景>_ui`。

### 10.1 必须有的断言（5 条，最能防回归）

| # | 断言 | 防的是 |
|---|---|---|
| 1 | **反推后 `process_baselines` / `process_baseline_steps` / `process_baseline_links` 三张表行数全部不变** | 「反推只出草案不写表」被写成「直接落库」 |
| 2 | **同项目里功能基线发 `v1.0` 后，流程基线仍发 `v1.0`**（两表 `version_no` 序列独立） | 两套基线抢版本号（共用表方案的核心缺陷） |
| 3 | **步骤校验失败后旧步骤行数与内容逐字节不变** | 「先删旧再校验」导致半截状态 |
| 4 | **04 物理删除功能后：链接行仍在 + `target_deleted=true` + 04 的删除接口仍返回 204** | 建 FK 让 04 的既有删除变成 500 |
| 5 | **通过后 `structure_json` 与 `draft_snapshot` 逐字节相同** | 「通过时重新冻结」导致审核人看的与冻结的不是同一份 |

> 第 5 条是本期「提交即冻结」这条裁决的**唯一硬证据**——
> 没有它，冻结时机的设计随时可能被改回去。

### 10.2 测试口径

- **零真实 socket**：测试目录不出现 `requests` / `urlopen` / `aiohttp` / `socket.socket`。
- **不执行平台自身的 `tests/` 目录**。
- **既有 1259 条一条不删、不改期望值**。
- e2e 造数：走真实 API（`tests/e2e/support.py` 里补 4 张新表的清理语句，
  按外键倒序：`process_baseline_revisions` → `process_baseline_links` /
  `process_baseline_steps` → `process_baselines`）。

## 11. 复用清单（不重写）

| 能力 | 出处 | 用法 |
|---|---|---|
| 步骤编辑器的交互骨架 | `web/src/pages/TestCaseStepsEditor.tsx:36-193` | **照抄改** → `ProcessBaselineStepsEditor.tsx`（受控数组 + 上移/下移/删除/新增；不用拖拽；不发 `step_no`） |
| `formatSnapshotVersion` | `web/src/pages/baselineShared.ts:7-9` | **直接调用**（显示 `v1.{n}`） |
| `isValidationError` | `web/src/pages/baselineShared.ts:16-23` | **直接调用**（表单校验失败时不当成请求失败） |
| `SOURCE_TYPE_OPTIONS` | `web/src/pages/baselineMeta.ts:43-46` | **直接复用**（`manual` / `document_derived` 口径完全一致） |
| `STATUS_FILTER_OPTIONS` | `web/src/pages/baselineMeta.ts:49-54` | **直接复用**（`active` / `archived` / `all`） |
| 快照与审核的交互骨架 | `web/src/pages/ProjectBaselineSnapshots.tsx`（提交 / 通过 / 驳回 / 快照弹窗） | **照抄改** → `ProcessBaselineReviewDrawer.tsx`（绑定的 `BaselineRevision` 字段要换成本期的） |
| `Page[T]` 分页信封 | `app/baselines/schemas.py:39-45`（后端）/ `web/src/api/index.ts:47-52`（前端） | **照抄形态** |
| `ensure_readable` / `ensure_writable_project` / `ensure_admin` | `app/common/permissions.py:38-85` | **直接调用**（顺序只有这一处出处） |
| `write_audit` | `app/common/audit.py:17-50` | **直接调用**（只 add + flush，不 commit） |
| `get_setting`（自审开关） | `app/common/settings.py:25` | **直接调用**（不新增系统设置项） |
| `parse_llm_json` | `app/llm/json_utils.py` | **直接调用**（容错解析，不补引号不截断补全） |
| `run_log.record_run` | `app/llm/run_log.py:53-92` | **不用**——04 的推导不写留痕，本期同构（省一处上游 CHECK 改动） |
| `BaselineFunction` / `BaselineFeaturePoint` 只读查询 | `app/models/baseline.py:74-167` | `select(...)`——**只读，不 import 04 的业务函数** |
| `documents_service.list_chapters` | `app/documents/service.py` | **直接调用**（取章节正文） |
| 错误码中文映射 | `web/src/api/client.ts` | **追加 8 条** |
| **功能基线树** `ProjectBaselineTree`（579 行）+ `baselineTreeNodes`（261 行） | `web/src/pages/` | **不可复用**——绑死 04 的「模块 → 功能 → 功能点」三级树；流程基线是**平铺列表**，没有层级可渲染 |
| **分点审核节点** `baselineReviewNodes`（109 行） | `web/src/pages/baselineReviewNodes.tsx:21-25` | **不可复用**——`TYPE_META` 写死三个层级名（module / function / feature_point）；本期不做分点审核（spec §3.7） |
| **推导候选树** `baselineDeriveNodes`（122 行） | `web/src/pages/baselineDeriveNodes.tsx` | **不可复用**——是树；本期的反推候选是**列表** |
| **推导记录表** `baseline_derives` / `baseline_derive_candidates` | `app/models/baseline_derive.py` | **不新建候选表**——本期的候选只在响应里，用勾选 + `POST /scenarios` 采纳（spec §4.1） |
| **`baseline_labels` / `baseline_review_items` / `baseline_revisions`** | `app/models/baseline.py` / `baseline_review.py` | **不可复用**——三处 CHECK 写死了层级名 / 版本号唯一键共用（spec §3.1） |

## 12. 风险与规避

| 风险 | 规避 |
|---|---|
| **两套基线抢版本号** | 分表存储；AC-197 断言两套序列独立 |
| **审核期间内容漂移** | 提交即冻结 + 审核期锁定；AC-205 断言 `structure_json` 与 `draft_snapshot` 逐字节相同 |
| **04 物理删功能导致 500** | `target_id` 不建 FK + 名称快照 + `target_deleted`；AC-200 断言 04 删除仍 204 |
| **关联表达不了多对多** | 关联表；AC-200 断言一个场景可关联多个目标 |
| **模型瞎猜 `target_id`** | Prompt 给带 id 的功能基线清单；越界 id 只丢该条关联；AC-202 断言 |
| **反推重复抽取** | Prompt 给已有场景清单；同名合并 |
| **反推写出脏数据** | 引擎签名里没有 `session`；采纳走独立批量接口；AC-202 断言三表行数不变 |
| **批量采纳半批落库** | 整批拒；AC-203 断言行数不变 |
| **步骤半截状态** | 先校验整组再动手；AC-199 断言旧步骤原样保留 |
| **e2e 的 Tab 计数失效** | antd 非活动面板懒渲染 → 计数时内层未挂载；AC-212 断言计数仍为 10，且既有 e2e 文件**一个字节都不改** |
| **组件超 400 行** | 基线管理内容外提；`ProjectDetailPage.tsx` 只做减法 |
| **降级时模板残留撞 3819** | `downgrade` 先删模板行再重建旧 CHECK；迁移往返**两库**都跑 |
| **欠账被当成漏做** | AC-210 / AC-211 显式断言「不存在」；spec §13 登记去向 |
| **上游 schema 改动越界** | 只有 spec §11 声明的两处；`git diff --stat` 实测并在 AC-214 断言 |
| **既有测试被改动** | 既有 1259 条零期望值改动；新增测试只能增 |

## 13. 实施顺序

1. **T117** 数据层：迁移 `0025`（4 表 + CHECK 扩枚举 + 播种模板）+ 4 个模型 +
   8 个错误类 + Mock 前缀分支。
2. **T118** 场景 CRUD + 步骤整体覆盖 + 关联功能基线（13 个接口里的前 7 个）。
3. **T119** 反推引擎（纯函数）+ `POST /derive` + 候选采纳链路。
4. **T120** 审核与快照（提交冻结 / 通过转正 / 驳回）+ 审核期锁定。
5. **T121** 权限与归档收口 + 审计覆盖 + 欠账断言。
6. **T122** 前端二级子菜单 + 场景管理 + e2e。
7. **T123** 全量回归 + 迁移往返 + 文档回填 + 收官总结。
