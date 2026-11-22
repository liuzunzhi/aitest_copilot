# 10 · 流程基线 · 规格

> 对齐需求：PRD 2.4.2「流程基线」（与「功能基线」并列的子菜单）+ PRD 2.4.2「通用能力」中
> 与流程基线相关的部分。
> 上游依赖：04-baseline（功能基线结构与快照、来源追溯 6 列、审核范式）、
> 03-documents（章节追溯）、08-test-case-analysis（步骤整体覆盖范式）。
> 本期口径（用户 2026-11-22 拍板）：
> - **独立建表**，对 04 零改动（不复用 `baseline_labels` / `baseline_review_items` / `baseline_revisions`）；
> - **本期不做标签**（显式欠账，AC-210 断言）；
> - **本期不做快照保留策略 / 被引用即保护**（显式欠账，AC-211 断言）；
> - **「关联功能基线」单向、关联表、不建外键、存名称快照**；
> - **提交审核时即冻结**（`draft_snapshot` → 通过时转正 `structure_json`）；
> - 前端入口是**「基线管理」Tab 内的二级子菜单**，不加第 11 个顶层 Tab。
> 本文是待 review 的规格，未写任何业务代码。评审通过后才拆任务落地。

## 0. 一句话结论（先看这个）

| 问题 | 结论 |
|---|---|
| 本期做什么 | **流程基线的最小闭环**：场景 CRUD + 操作步骤 + 关联功能基线 → 文档反推草案 → 提交审核 → 冻结快照 |
| 数据落哪 | **4 张新表**（`process_baselines` / `process_baseline_steps` / `process_baseline_links` / `process_baseline_revisions`），迁移 `0025` |
| 场景怎么进库 | **手工添加**（`source_type='manual'`）与 **文档反推后采纳**（`source_type='document_derived'`）两条路；反推**只出候选不写表** |
| 步骤怎么存 | 独立的 `process_baseline_steps` 表（**照抄 08 的 `test_case_steps`**）：`action` / `expected` 各 1000 字，序号由**服务端按数组顺序**重排为 1..n |
| 关联怎么存 | 独立的 `process_baseline_links` **关联表**（多对多），**不建外键**，额外存 `target_name` **名称快照** |
| 跟功能基线什么关系 | **单向引用**：流程基线指向功能基线，**不回写 04**；04 的功能被删后链接行**保留**，读取时标「目标已删除」 |
| 版本快照 | 提交审核时冻结 `draft_snapshot`，通过时**原样转正**为 `structure_json` 并分配 `v1.{n}`；**与功能基线的版本号互不干扰** |
| 标签 | **本期不做**。PRD 明写有标签，但标签语义依赖「增量分析 → 打标」，而增量分析只认功能基线。**显式欠账，登记在 §13** |
| 保留策略 / 被引用即保护 | **本期不做**。流程基线快照当前**零下游引用**，「被引用即保护」的保护对象是空集。**显式欠账，登记在 §13** |

---

## 1. 背景与目标

09 期把主链路推到了「可执行的自动化资产与可追溯的执行报告」：

```
文档 → 基线 → 增量分析 → 测试点 → 测试用例 → 自动化资产 → 执行报告
```

但 PRD 2.4.2 的基线管理有**两个并列子菜单**——「功能基线」与「流程基线」——
09 期明确跳过了后者（`PROGRESS.md` §3「09 期红线：跳过流程基线」）。
至此 PRD 2.4.2 唯一未落地的子菜单就是「流程基线」。

PRD 2.4.2 对流程基线的原文（`doc/AI 辅助测试平台 产品需求文档.md:442-445`）：

> ##### 流程基线
>
> - 存放完整业务场景操作步骤：场景名称、前置条件、操作步骤列表、预期结果、关联功能基线、标签、版本号、状态。
> - 来源：文档反推 / 手工添加。

它与功能基线的本质差别是**形态**：功能基线是「模块 → 功能 → 功能点」的三级**树**，
流程基线是「一个个完整业务场景」的**平铺列表**——每个场景自带前置条件、有序操作步骤、
每步预期结果，并指向它覆盖的功能基线目标。

本期目标：

- 落地 PRD 2.4.2「流程基线」的**数据与主链路**：
  场景 CRUD、操作步骤整体覆盖、关联功能基线、文档反推、审核与版本快照；
- **独立建表**，对 04 的表结构、判定逻辑、错误码**零改动**；
- 把 PRD 2.4.2「通用能力」中**与流程基线语义相容**的部分（版本快照、审核流程、
  基线反推、来源追溯、审计）落地，**不相容 / 无对象**的部分（标签、保留策略、
  被引用即保护、清理候选、告警、删除留痕）**显式记为欠账**，不半吊子实现。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 场景 CRUD | 场景名称 / 描述 / 前置条件 / 状态；**批量新建**（手工或反推候选采纳）；改名 / 改描述 / 归档 / 删除 |
| 操作步骤 | 整体覆盖（`PUT .../steps`）：`action` + `expected`，最多 100 步，序号服务端重排 |
| 关联功能基线 | 整体覆盖（`PUT .../links`）：场景 ↔ 功能 / 功能点，**多对多**、存名称快照、不建外键 |
| 来源追溯 | 6 列来源追溯字段（与 04 同名同义）；文档推导的**只读**，手工添加不要求追溯 |
| 文档反推 | 从生效文档版本逐章节推导出**场景候选**（含步骤与关联建议），**只出草案不写表** |
| 审核与快照 | 提交审核即冻结 `draft_snapshot`；通过时转正 `structure_json` + 分配 `v1.{n}`；驳回不占版本号 |
| 审核期锁定 | 审核中时场景不可编辑（保证「所见即所冻」） |
| 检索 | 场景列表支持 **关键词 / 来源类型 / 状态** 三个筛选（分页） |
| 前端二级子菜单 | 「基线管理」Tab 内新增「功能基线」/「流程基线」两个子 Tab |
| 审计 | 9 个写操作全部留痕，带 `project_id` / `actor_id` / `target_type` / `target_id` |

### 2.2 本期不做（红线，违反即返工）

| 不做 | 为什么 |
|---|---|
| **不做标签** | PRD 明写流程基线有「标签」，但标签语义依赖「增量分析 → 打标」，而**增量分析目前只认功能基线**（05 的比对基准是功能基线快照，`baseline_labels.target_type` 的 CHECK 写死 `('function','feature_point')`）。要做就得改 04 的 CHECK + 05 的引擎目标类型——那是改上游判定逻辑，越红线。**AC-210 显式断言「不存在流程基线标签」**，欠账登记在 §13 |
| **不做快照保留策略** | 04 的保留策略是**项目级单列** `baseline_snapshot_max_count`（`app/models/project.py:35-39`）。两套基线共用一列会**混算**（流程基线的快照不该被功能基线的上限清理）；要独立就得新增项目列（那是整套功能，超出本期）。**AC-211 显式断言「`projects` 表无新增列」** |
| **不做「被引用即保护」/ 清理候选 / 告警 / 删除留痕** | 这四项都挂在保留策略之下。且流程基线快照**当前没有任何下游引用**（增量分析不认它、无标签、报告不追它）→「被引用即保护」的**保护对象是空集**。**AC-211 显式断言「无快照删除接口、快照永久保留」** |
| **不做分点（逐项）审核** | 04 的分点审核绑死 `baseline_review_items.entity_type` 的 CHECK（写死 `('module','function','feature_point')` 三个层级名）。流程基线只有「场景」一个层级、审核对象是「场景集合」整体，整体通过 / 驳回已够用。**AC-204 ~ AC-206 只覆盖整体审核** |
| **不做标签筛选 / 变更历史 / 关联增量分析记录展示** | 前者依赖标签；后两者依赖增量分析与变更记录表（本期无）。§13 登记 |
| **不做场景 ↔ 测试点 / 测试用例的关联** | PRD 未要求；08 的用例以**测试点**为锚，流程基线与它是两套并列资产，硬接要改 08 的表结构 |
| **不做流程基线的 Excel 导入导出** | PRD 未对流程基线提导出；08 的导出是「用例」专用 |
| **不做基线检索的完整组合** | PRD 2.4.2「基线检索」列了模块 / 来源类型 / 标签 / 关键词 / 版本五个维度。模块与标签维度**对流程基线不适用**（无层级、无标签）；版本维度本期只暴露在快照列表里，不做场景列表的版本筛选 |
| **不加第 11 个顶层 Tab** | PRD 2.4.2 明确流程基线是「基线管理」下的**并列子菜单**。加顶层 Tab 会打乱现有 10 个 Tab 的信息架构，也会让 e2e 的 `get_by_role("tab")` 计数断言全部失效 |
| **不改 04 / 05 / 07 / 08 / 09 的判定逻辑与错误码** | 本期对上游目录**零改动**。**唯一例外**：① `app/llm/mock.py` 加一个前缀分支（既有五个分支行为一个字节不变）；② `app/models/incremental.py` 的 `prompt_templates.task_type` CHECK 扩一个枚举值 `'process_baseline'`（详见 §11「上游 schema 改动声明」） |
| **不改既有测试的期望值** | 既有 1259 条一条不删、不改断言 |
| **不引入任何新前端依赖** | `web/package.json` 不动 |
| **不做 Skill 模式** | 延续 06 / 07 / 08 / 09，只做直连 |

### 2.3 与上游的兼容约束

1. **版本号互不干扰**：`process_baseline_revisions.version_no`（快照 `v1.{n}`）与
   `baseline_revisions.version_no`（功能基线快照 `v1.{n}`）**分表存储**。
   同一项目里两套基线各自从 `v1.0` 开始，互不影响、互不抢号。
2. **关联是单向的**：流程基线 → 功能基线。**不回写 04**（04 的表结构零改动，
   `baseline_functions` / `baseline_feature_points` 上不出现任何流程基线字段）。
3. **不建外键**：04 的删功能是**物理删除**（`app/baselines/service.py:678`
   `delete_function`）。建 FK 会把 04 的既有行为变成 500（`IntegrityError`）。
   沿用 08 的 `test_point_id`、09 的 `linked_case_id` 同一思路：逻辑引用 +
   名称快照 + 读取时判定「目标已删除」。
4. **04 的三张表零改动**：`baseline_labels`（标签）、`baseline_review_items`（分点审核）、
   `baseline_revisions`（功能基线快照）——本期**一个字节都不改**。
5. **上游 schema 改动仅一处**：`prompt_templates.task_type` 的 CHECK 扩
   `'process_baseline'`（详见 §11）。`llm_run_logs.task_type` **不动**——
   04 的文档推导不写运行留痕，本期的反推同构。
6. **零真实 socket**：本期不引入任何网络客户端。反推只调注入的 `LLMProvider`，
   测试用 `MockProvider`；其余全是本地文件与数据库操作。
7. **快照 JSON 与 04 的结构不同**：04 冻结的是三级树，本期冻结的是场景列表。
   两份 JSON **互不解析**，不存在「同一段代码解析两种结构」的问题。
8. **两套「版本号」不可混淆**（PRD 里同时出现）：
   - `process_baselines.version_no` = **场景自身的修订次数**（内容变更即 +1），
     对应 PRD 流程基线字段清单里的「版本号」；
   - `process_baseline_revisions.version_no` = **快照版本号**（项目内 `v1.{n}` 递增），
     对应 PRD「通用能力 → 版本快照」里的 `v1.0、v1.1…`。
   前者在场景行上，后者在快照行上，**两个字段名相同但含义不同**——接口响应里
   分别叫 `version_no` 与 `version_no`，靠外层对象区分（详见 §7.1）。

## 3. 业务语义裁决

### 3.1 流程基线独立建表，不复用功能基线的表

**裁决**：4 张新表 `process_baselines` / `process_baseline_steps` /
`process_baseline_links` / `process_baseline_revisions`，对 04 **零改动**。

**理由**：PRD 说两套基线是并列子菜单、共用「通用能力」，看起来应该同表。
但「共用表」在现有实现下有三处**硬约束**顶死：

| 硬约束 | 位置 | 复用会怎样 |
|---|---|---|
| `baseline_labels.target_type` 的 CHECK 写死 `('function','feature_point')` | `app/models/baseline.py:234-236` | 要挂流程基线的标签就必须扩 CHECK → 改 04 的表结构 → 04–09 的回归测试全受影响 |
| `baseline_review_items.entity_type` 的 CHECK 写死 `('module','function','feature_point')` | `app/models/baseline_review.py:107-110` | 同上 |
| `baseline_revisions` 唯一索引 `uk_brevisions_project_no(project_id, version_no)` | `app/models/baseline.py:184` | 两套基线**抢同一个版本号**：功能基线发了 `v1.0`，流程基线就发不出 `v1.0` |

还有一条语义上的：**04 的 `baseline_revisions.structure_json` 冻结的是一棵三级树**
（`app/baselines/service.py:1920-2035` 的 `_collect_structure` / `_freeze_structure`），
`module_count` / `function_count` / `feature_point_count` / `label_count` 四个计数列
描述的是树。流程基线的快照是**场景列表**，计数是场景数 / 步骤数 / 关联数——
塞进同一张表要么加列（改 04 的表结构），要么让计数列语义分裂。

**「为什么不能靠加枚举值复用」**：枚举值能表达「多了一种目标类型」，但**表达不了
「另一套基线有自己的版本号、自己的快照格式、自己的审核状态机」**。
强行复用的结果是一张表里同时住着两种结构，读取时靠 `if` 分支区分——
04 的 `structure_json` 解析、`label_count` 语义、`_next_version_no` 全要改，
而这些正是 04–09 的回归断言所在。

**代价**：两套基线各有一套表与一套快照实现，PRD「通用能力」要分两套写。
换来的是 04 目录**零改动**、既有 1259 条测试**零期望值改动**。

### 3.2 本期不做标签（显式欠账）

**裁决**：流程基线**没有任何标签能力**——不建标签表、不开放标签接口、
不动 `baseline_labels`。

**理由**：PRD 2.4.2 的标签定义是「新增 / 变更 / 受影响 / 无变化」，
且「清除即退出所有下游引用，测试点分析不再参考」——它的**产生源是增量分析**。
05 的增量分析以**功能基线快照**为比对基准，结论挂在
`(analysis_id, target_type, target_id)` 上，`target_type` 只能是
`function` / `feature_point`。要让增量分析能给流程基线打标，得改 05 的引擎目标类型
与 04 的标签表 CHECK——**改上游判定逻辑**，越红线。

**代价**：流程基线在本期**无法表达「这个场景受某次变更影响」**。
用户要判断影响面，只能回到功能基线上看标签，再人工对应场景。
**这是显式欠账，不是遗漏**——AC-210 会断言「不存在流程基线标签」，
§13 登记「增量分析支持流程基线打标」为后续期。

### 3.3 本期不做保留策略与被引用即保护（显式欠账）

**裁决**：流程基线快照**永久保留**；不新增项目列；不提供快照删除接口；
不做清理候选 / 告警 / 删除留痕。

**理由**：

1. 04 的保留策略是**项目级单列** `baseline_snapshot_max_count`
   （`app/models/project.py:35-39`，注释写明「基线快照保留上限，空 = 不启用（永久保留）」）。
   两套基线共用一列会**混算**——功能基线的上限会连坐删掉流程基线的快照，
   反之亦然。要独立就得新增 `process_snapshot_max_count` 项目列，
   那是一整套功能（配置界面 + 清理任务 + 人工确认 + 告警），超出本期。
2. 「被引用即保护」的保护对象是**引用方**。流程基线快照当前的引用方是**空集**：
   增量分析不认它（05 只比对功能基线快照）、标签不做、测试点 / 用例不引它、
   09 的执行报告不追它。**保护一个没人引的东西，是空转**。
3. PRD「通用能力」这一整组（保留策略 / 被引用即保护 / 清理候选 / 告警 / 删除留痕）
   本质是**一条链**：有保留上限 → 才有超限候选 → 才有引用检查 → 才有告警。
   砍掉第一环，后面四环全部失去对象。

**代价**：流程基线的快照会**一直堆积**。本期快照产生频率很低
（只有「提交审核 → 通过」才产生一份），实际增长可控。
**AC-211 显式断言「`projects` 表无新增列」「无快照删除接口」「快照永久保留」**，
§13 登记「流程基线快照保留策略」为后续期。

### 3.4 「关联功能基线」单向、多对多、不建外键、存名称快照

**裁决**：`process_baseline_links` 关联表，`target_type` ∈ {`function`, `feature_point`}，
`target_id` **不建外键**，额外存 `target_name` **名称快照**；读取时若目标已不存在，
返回 `target_deleted=true` 并仍返回快照名。

**理由**：

1. **单向**：PRD 只说流程基线「关联功能基线」，没说功能基线要反查场景。
   反向索引可以由流程基线侧聚合得到，不需要在 04 的表上加字段——
   **04 零改动的唯一办法就是单向**。
2. **多对多**：一个场景覆盖多个功能/功能点（PRD 的「完整业务场景」天然如此），
   一个功能也会被多个场景引用。**两个可空外键列表达不了 M:N**——
   `function_id` + `feature_point_id` 只能表达「至多一个功能 + 至多一个功能点」。
   关联表是唯一能表达 M:N 的结构，同时还能多存一列名称快照（外键列存不下）。
3. **不建外键**：04 的删功能是**物理删除**（`app/baselines/service.py:678`）。
   建 FK 会把 04 的既有行为变成 500。08 的 `test_point_id`、09 的 `linked_case_id`
   都是同一处理。
4. **名称快照**：目标被删后，链接行仍要能告诉用户「这个场景原本关联的是
   『用户扫码登录』」。与 08 的 `test_point_name`、09 的 `case_title` 同一思路。

**代价**：目标被删后链接行**仍在**（不级联清理），读取时要做一次
「批量查目标是否存活」的判定（一次 `IN` 查询，不做 N+1）。
前端要在链接上标「目标已删除」。

### 3.5 快照在**提交审核时**冻结，不在通过时冻结

**裁决**：提交审核时把当前全部 active 场景（含步骤与关联）冻结进
`process_baseline_revisions.draft_snapshot`；审核通过时**原样转正**为
`structure_json`（逐字节相同），并分配 `version_no`。

**理由**：04 是**通过时**才冻结（`approve_review` 里调 `_freeze_structure`）。
但 04 的结构表在审核期间**没有被锁**——提交审核后功能还能改，
于是「审核人看到的」与「最终冻结的」可能不是同一份。
流程基线的审核对象是「一组场景的整体」，这个偏差更刺眼：
审核人逐条看过、点了通过，冻结出来的却是另一批内容。

**提交即冻结 + 审核期锁定**把「所见即所冻」变成结构上的保证：
审核期间任何场景编辑 / 删除 / 改步骤 / 改关联都被 409 拒绝；
驳回则解锁，用户改了再提。

**代价**：审核期间场景**不能改**。解锁的路径有两条——
「驳回」（解锁）或「通过」（快照已成，随后可继续编辑场景，产生下一份快照）。
被驳回后重提会产生**两份** `draft_snapshot`（一份 rejected、一份 submitted），
历史保留供追溯。

### 3.6 前端入口是「基线管理」内的二级子菜单

**裁决**：`ProjectDetailPage.tsx` 的 `baseline-management` Tab 改为渲染新的
`ProjectBaselineManagementTab.tsx`（antd 二级 `Tabs`），
`items` = `[{key:'function', label:'功能基线'}, {key:'process', label:'流程基线'}]`，
`defaultActiveKey="function"`。

**理由**：PRD 2.4.2 的标题就是「**子菜单**：功能基线 / 流程基线」——
它们是同一菜单下的并列项，不是两个平级 Tab。当前 `baseline-management` 的实现
是纵向堆叠（`Card「功能基线结构」` + `ProjectBaselineSnapshots`），没有子 Tab 组件，
但**位置已经是 PRD 说的那个位置**，加二级 Tabs 是最小改动。

`defaultActiveKey="function"` 保证**现有用户路径完全不变**：进来还是先看到功能基线。

**代价**：① 要改 `ProjectDetailPage.tsx`；② 该文件当前 379 行，加内容会超
400 行阈值（验证约定 §4.3）→ **必须把基线管理内容外提到新文件**，
`ProjectDetailPage.tsx` 只做「减法」（把原来的两块换成新组件），行数不增；
③ e2e 里 `get_by_role("tab")` 的计数断言要回归验证（antd `Tabs` 的非活动面板
懒渲染，内层二级 Tabs 在计数时**尚未挂载**，顶层仍是 10 个 Tab——AC-212 断言这一点）。

### 3.7 审核只做整体通过 / 驳回，不做分点审核

**裁决**：不引入分点审核表。审核对象是「场景集合」整体。

**理由**：04 的分点审核由 `baseline_review_rounds` + `baseline_review_items`
两张表实现，其中 `baseline_review_items.entity_type` 的 CHECK **写死三个层级名**
（`app/models/baseline_review.py:107-110`）。流程基线只有「场景」一个层级，
且「整体通过还是整体驳回」是更符合「快照」语义的判断——
快照本身就是一份完整的场景集合，逐项批准再拼成集合没有额外价值。

**代价**：审核人无法「通过其中 3 个场景、驳回其中 1 个」。
**这是本期刻意接受的简化**——驳回后改完重提即可。

### 3.8 审核期间锁定场景编辑

**裁决**：项目内只要存在 `status='submitted'` 的流程基线快照，
所有场景写接口一律 409 `PROCESS_BASELINE_IN_REVIEW`。

**理由**：§3.5 的「提交即冻结」只有在「提交后不能改」时才成立。
若提交后还能改，冻结的 `draft_snapshot` 与库里当下的内容就会漂移，
「通过时原样转正」也就失去意义。

**代价**：审核中的项目里场景被冻结。解锁靠驳回。

### 3.9 场景删除是物理删除，级联清理步骤与关联

**裁决**：`DELETE /scenarios/{id}` 物理删除场景行，
`process_baseline_steps` / `process_baseline_links` 由**数据库级 `ON DELETE CASCADE`** 清理。

**理由**：与 08 的删用例一致（`test_case_steps.case_id` 带 `ondelete="CASCADE"`，
`app/models/test_case.py:182-187`）。场景是从属实体，没有独立存在的价值——
留着步骤残骸只会让列表里出现「有步骤但没有场景」的孤儿。
链接同理：链接的存在意义就是「这个场景关联了它」，场景没了链接也没有意义。

**代价**：删场景**不可恢复**（无软删除）。这与 08、09 的既有口径一致，
且场景删除是**低频、高风险**操作，前端用 `Popconfirm` 二次确认。

### 3.10 反推的「已有清单」段要给两样东西

**裁决**：反推的 Prompt 在「已有基线结构」那一段放**两份清单**：
① **已有流程基线场景名清单**（防重复抽取）；② **可关联的功能基线清单**
（模块 → 功能 → 功能点，**带 id**，供模型产出关联建议）。

**理由**：① 不给已有清单，模型每次把整份文档重抽一遍，多次推导产生大量重复候选
（04 期 `render_existing_brief` 的存在理由）。② **不给功能基线清单，模型只能瞎猜 id**——
06 期的 L2 联调就是这么翻车的：「baseline unavailable」，模型自己编 `target_id=1`，
结论全被当成越界丢弃。场景要产出「关联功能基线」，模型就必须知道有哪些功能可选、
它们的 id 是多少。

**代价**：Prompt 变长。可参照 04 的做法用
`BASELINE_BRIEF_MAX_RATIO`（`app/incremental/context.py:37`，0.4）做**比例截断**，
只砍清单段的尾部、不砍模板正文与章节正文。

## 4. 数据模型（4 张新表，迁移 `0025`）

列类型与 04 / 07 / 08 / 09 同口径：`BIGINT(unsigned=True)` / `DATETIME(fsp=3)` /
`JSON` / `String(n)`，时间列 `server_default=text("CURRENT_TIMESTAMP(3)")`，
表选项 `mysql_engine=InnoDB` / `utf8mb4` / `utf8mb4_0900_ai_ci`。

> **四个模型类都写 `__test__ = False`**：`ProcessBaseline*` 不撞 pytest 的 `Test*`
> 收集规则，但 `ProcessBaselineRevision` 之类的名字统一加上更省心
> （08 的 `TestCase*` 已踩过这个坑，`app/models/test_case.py:180` 有先例）。
> 错误类不用管——`AppError` 基类已设 `__test__ = False`（`app/common/errors.py:19`），子类自动免疫。

### 4.1 `process_baselines`（业务场景）

| 列名 | 类型 | 约束 | 注释 |
|---|---|---|---|
| id | BIGINT(unsigned) | PK 自增 | |
| project_id | BIGINT(unsigned) | 非空，FK → `projects.id`，索引 | 项目隔离边界 |
| name | VARCHAR(255) | 非空 | **场景名称** |
| description | VARCHAR(500) | 可空 | 场景说明 |
| precondition | VARCHAR(1000) | 可空 | **前置条件** |
| source_type | VARCHAR(16) | 非空，默认 `'manual'`，CHECK `('manual','document_derived')` | 来源 |
| status | VARCHAR(16) | 非空，默认 `'active'`，CHECK `('active','archived')` | 状态 |
| version_no | INT(unsigned) | 非空，默认 1 | **场景自身的修订次数**（内容变更即 +1），**不是快照版本号** |
| source_document_id | BIGINT(unsigned) | 可空 | 来源文档（04 同名列同义） |
| source_version_id | BIGINT(unsigned) | 可空 | 来源文档版本 |
| source_chapter_id | BIGINT(unsigned) | 可空 | 来源章节 |
| source_chapter_title | VARCHAR(255) | 可空 | 来源章节标题（**快照列**，章节改名不影响追溯） |
| source_method | VARCHAR(32) | 可空 | 生成方式：`baseline_reverse`（文档反推）/ `incremental_new`（后续期） |
| source_analysis_id | BIGINT(unsigned) | 可空 | 关联增量分析记录（本期恒为 NULL，见 §13） |
| created_by | BIGINT(unsigned) | 非空，FK → `users.id` | |
| created_at | DATETIME(3) | 非空，默认 `CURRENT_TIMESTAMP(3)` | |
| updated_at | DATETIME(3) | 非空，默认 `CURRENT_TIMESTAMP(3)` | |

- 唯一：`uk_pbaselines_project_name(project_id, name)`
- 索引：`idx_pbaselines_project(project_id)`、`idx_pbaselines_source(project_id, source_type)`、
  `idx_pbaselines_status(project_id, status)`

> **`version_no` 变更规则**：名称 / 描述 / 前置条件 / 步骤 / 关联，**任一变更即 +1**。
> 与 04 的 `baseline_functions.version_no`（只算名称 / 描述）不同——流程基线的
> 步骤与关联是场景的**组成部分**，改了步骤等于改了场景。

> **来源追溯 6 列与 04 同名同义**（`app/models/baseline.py:107-122` / `:158-163`），
> 这样前端的「来源区域」展示与 04 完全同构。手工添加时**六列全为 NULL**
> （PRD：「手工添加来源（不做追溯要求）：记录操作人与时间即可」）。

### 4.2 `process_baseline_steps`（操作步骤列表）

| 列名 | 类型 | 约束 | 注释 |
|---|---|---|---|
| id | BIGINT(unsigned) | PK 自增 | |
| baseline_id | BIGINT(unsigned) | 非空，FK → `process_baselines.id`，**`ondelete="CASCADE"`** | 所属场景 |
| step_no | INT(unsigned) | 非空 | 序号，**服务端按数组顺序重排为 1..n**，不信客户端 |
| action | VARCHAR(1000) | 非空 | 操作步骤 |
| expected | VARCHAR(1000) | 非空，默认 `''` | 预期结果 |
| created_at | DATETIME(3) | 非空，默认 `CURRENT_TIMESTAMP(3)` | |

- 唯一：`uk_pbsteps_baseline_no(baseline_id, step_no)`
- CHECK：`ck_pbsteps_no_positive` — `step_no >= 1`
- 索引：`idx_pbsteps_baseline(baseline_id)`

> **这张表是 08 的 `test_case_steps` 的照抄**（`app/models/test_case.py:172-203`）：
> 同样的 `ondelete="CASCADE"`、`UniqueConstraint(case_id, step_no)`、
> `CheckConstraint(step_no >= 1)`、`Index(case_id)`、同样的列宽 1000。
> **只换了表名与外键列名**，`step_no` 的「服务端重排」口径一字不改。

### 4.3 `process_baseline_links`（关联功能基线）

| 列名 | 类型 | 约束 | 注释 |
|---|---|---|---|
| id | BIGINT(unsigned) | PK 自增 | |
| baseline_id | BIGINT(unsigned) | 非空，FK → `process_baselines.id`，**`ondelete="CASCADE"`** | 所属场景 |
| target_type | VARCHAR(16) | 非空，CHECK `('function','feature_point')` | 目标层级 |
| target_id | BIGINT(unsigned) | 非空，**不建外键** | 逻辑引用 `baseline_functions.id` / `baseline_feature_points.id` |
| target_name | VARCHAR(255) | 非空 | **目标名称快照**（目标被删后仍可读） |
| created_at | DATETIME(3) | 非空，默认 `CURRENT_TIMESTAMP(3)` | |

- 唯一：`uk_pblinks_baseline_target(baseline_id, target_type, target_id)`
- 索引：`idx_pblinks_target(target_type, target_id)`

> **为什么用关联表而不是两个可空外键列**：
> ① **多对多表达不了**——PRD 的「完整业务场景」天然覆盖多个功能/功能点，
>    一个功能也会被多个场景引用。`process_baselines.function_id` +
>    `feature_point_id` 只能表达「至多一个功能 + 至多一个功能点」，
>    要表达 M:N 只能再开一张表。
> ② **名称快照存不下**——外键列只能存 id，「目标被删后仍要显示原名」需要额外一列。
> ③ **不建外键才敢存 id**——建了 FK，04 物理删功能时这条链接会让删除直接 500。
> 关联表同时满足这三条，两个可空外键列一条都满足不了。

### 4.4 `process_baseline_revisions`（审核记录 / 版本快照，一体表）

| 列名 | 类型 | 约束 | 注释 |
|---|---|---|---|
| id | BIGINT(unsigned) | PK 自增 | |
| project_id | BIGINT(unsigned) | 非空，FK → `projects.id`，索引 | |
| version_no | INT(unsigned) | **可空**，唯一键的一部分 | **通过时分配**，项目内 `v1.{n}` 递增；驳回 / 审核中为 NULL |
| status | VARCHAR(16) | 非空，CHECK `('submitted','approved','rejected')` | 审核状态 |
| draft_snapshot | MEDIUMTEXT | 可空 | **提交时冻结**的场景集合 JSON |
| structure_json | MEDIUMTEXT | 可空 | **通过时由 `draft_snapshot` 原样转正**的快照 JSON |
| scenario_count | INT(unsigned) | 非空，默认 0 | 快照里的场景数 |
| step_count | INT(unsigned) | 非空，默认 0 | 快照里的步骤总数 |
| link_count | INT(unsigned) | 非空，默认 0 | 快照里的关联总数 |
| submitted_by | BIGINT(unsigned) | 可空，FK → `users.id` | |
| submitted_at | DATETIME(3) | 可空 | |
| reviewed_by | BIGINT(unsigned) | 可空，FK → `users.id` | |
| reviewed_at | DATETIME(3) | 可空 | |
| review_comment | VARCHAR(500) | 可空 | 审核意见（驳回时必填） |
| created_at | DATETIME(3) | 非空，默认 `CURRENT_TIMESTAMP(3)` | |

- 唯一：`uk_pbrevisions_project_no(project_id, version_no)`
  （`version_no` 可空 → MySQL 唯一索引允许多个 NULL，**多份审核中 / 已驳回的记录不占版本号**）
- 索引：`idx_pbrevisions_project(project_id)`、
  `idx_pbrevisions_project_status(project_id, status)`

> **为什么 `draft_snapshot` 与 `structure_json` 是两列而不是一列**：
> 一列的话，「提交时的内容」与「通过时的内容」会互相覆盖，
> 驳回后就查不到当初提交的是什么。两列让**「审核人看到的」与「最终冻结的」逐字节相同**
> 成为可断言的事实（AC-205），同时驳回后仍保留 `draft_snapshot` 供追溯。

> **计数列的语义**：`scenario_count` / `step_count` / `link_count` 描述的是**快照内容**
> （与 `draft_snapshot` 一致），不是「当前库里有几个场景」——
> 与 04 的 `module_count` / `function_count` 同一思路（04 的计数也是快照的计数）。

### 4.5 迁移 `0025`

`down_revision = "0024"`。**upgrade 顺序**（有外键依赖，顺序不能乱）：

1. **扩 `prompt_templates` 的 CHECK**：
   `drop_constraint("ck_ptemplates_task_type", "prompt_templates", type_="check")`
   → `create_check_constraint` 含
   `'document_parse','incremental','test_point','test_case','process_baseline'`。
   > MySQL 不允许直接改 CHECK，必须**先删后加**（08 期在 `llm_run_logs` 上踩过同一件事，
   > `migrations/versions/0023_test_cases.py:279-285`）。
   > **必须先扩 CHECK 再播种模板**——顺序反了，插入 `task_type='process_baseline'`
   > 的行会被旧 CHECK 拒（3819）。
2. **播种模板**：`prompt_templates` 插一行
   `name='流程基线推导·场景抽取'`、`task_type='process_baseline'`、
   `status='active'`、`version_no=1`；`system_prompt` 以
   **`[PROCESS_BASELINE_SYSTEM]`** 开头（Mock 靠这个前缀分流）。
3. `create_table("process_baselines")`
4. `create_table("process_baseline_steps")`（FK → `process_baselines`，CASCADE）
5. `create_table("process_baseline_links")`（FK → `process_baselines`，CASCADE）
6. `create_table("process_baseline_revisions")`

**downgrade 严格反序**：

1. `drop_table("process_baseline_revisions")`
2. `drop_table("process_baseline_links")`
3. `drop_table("process_baseline_steps")`
4. `drop_table("process_baselines")`
5. **删模板行**：`DELETE FROM prompt_templates WHERE task_type='process_baseline'`
   > **必须在重建旧 CHECK 之前删**——否则 `task_type='process_baseline'` 的残留行
   > 会让旧 CHECK 重建失败（3819）。这正是 08 期在 `llm_run_logs` 上踩过的坑
   > （`migrations/versions/0023_test_cases.py:321-322` 的注释写明了原因）。
6. `drop_constraint` → `create_check_constraint` 恢复旧的四值 CHECK。

> **`llm_run_logs.task_type` 不动**：04 的文档推导**不写运行留痕**
> （`app/baselines/service.py:2387` `run_document_derive` 里没有 `run_log.record_run`），
> 本期的反推同构——不写留痕 → 不需要扩 `llm_run_logs` 的 CHECK → 少一处上游改动。

## 5. 业务语义

### 5.1 场景的两种来源

| 来源 | `source_type` | 追溯字段 | 入口 |
|---|---|---|---|
| 手工添加 | `manual` | 六列**全为 NULL** | `POST /scenarios` |
| 文档反推 | `document_derived` | 六列**必填且自洽** | `POST /derive` 出候选 → `POST /scenarios` 采纳 |

**自洽校验**（`source_type='document_derived'` 时，服务层逐条校验）：

1. `source_document_id` / `source_version_id` / `source_chapter_id` **三者必填**
   （PRD：「文档推导来源（强制追溯）」）；
2. 文档存在且**属于本项目**；
3. 文档版本存在且**属于该文档**；
4. 章节存在且**属于该文档版本**；
5. 任一条不满足 → **整批拒绝**，400 `PROCESS_BASELINE_INVALID`，**不半批落库**。

> **为什么整批拒**：批量采纳是「一次动作」——用户勾了 5 个场景，
> 若第 3 个的章节对不上，理想是「前 2 个成功 + 报第 3 个」。但那样用户不知道
> 库里到底是哪几个。整批拒 + 明确报错，用户改完重勾一次，语义最简单
> （与 08 的步骤「整组拒」同一思路：`app/test_cases/service.py:911-925`）。

### 5.2 步骤的整体覆盖语义

`PUT /scenarios/{id}/steps` 的语义与 08 的 `PUT /cases/{id}/steps` **完全一致**：

| 规则 | 值 | 出处 |
|---|---|---|
| 最少步数 | 1（空数组 → 400 `PROCESS_BASELINE_STEP_INVALID`） | 照抄 `app/test_cases/service.py:913-914` |
| 最多步数 | 100（超出 → 400） | 照抄 `:908`、`:915-916` |
| `action` 去空格后不能为空 | 否则 400 | 照抄 `:919-921` |
| `expected` 可为空 | 存 `''` | 照抄 `:922-923` |
| 长度截断 | `action` / `expected` 各截到 1000 | 照抄 `:924` |
| **整组拒** | 校验不过 → **旧步骤原样保留**，一步都不改 | 照抄 `:911` docstring |
| 覆盖方式 | 先删旧、再按数组顺序插新，`step_no` 重排为 1..n | 照抄 `replace_steps` `:928-990` |
| 客户端**不发** `step_no` | 服务端不信模型/客户端给的序号 | 照抄 `app/models/test_case.py:175-176` |

> **为什么整组拒**：半截状态（前三步是新写的、第四步是旧的）比「什么都没改」更糟——
> 用户以为改成功了，库里却是一份拼接物。

### 5.3 关联的整体覆盖语义

`PUT /scenarios/{id}/links` 与步骤同样走**整体覆盖**：

| 规则 | 值 |
|---|---|
| 校验顺序 | `target_type` 枚举 → 目标存在且属本项目 → 同目标不重复 |
| 目标存在性 | `target_type='function'` → `baseline_functions`；`'feature_point'` → `baseline_feature_points`；**必须 `status='active'`** 且 `project_id` 等于当前项目 |
| 名称快照 | 服务端**重查**目标名写入 `target_name`，**不采信客户端传值**（与 09 的「入库时服务端重扫重算」同一思路） |
| 重复关联 | 同一 `(target_type, target_id)` 在一次提交里出现两次 → 400 `PROCESS_BASELINE_LINK_INVALID` |
| 空数组 | **允许**（清空关联）——与步骤不同，场景没有关联是合法的 |
| 覆盖方式 | 先删旧、再插新；`baseline_id` 上 FK CASCADE 保证不残留 |

> **为什么空关联合法但空步骤非法**：一个没有步骤的场景**没有任何可执行内容**，
> 是个残缺实体；一个没有关联的场景仍然是一个完整可用的业务场景
> （只是暂时还没归到功能基线上）。两者语义不同，所以校验不同。

### 5.4 文档反推流程

```
POST /process-baselines/derive  { document_id, document_version_id, template_id }
    1 校验：项目 404 → 归档 409 → 角色 403
    2 文档 / 版本 / 章节校验（版本必须是 active 生效版本）
    3 模板校验：存在 + task_type='process_baseline' + status='active'
    4 取章节列表（复用 documents_service.list_chapters）
    5 组装两份清单：
         ① 已有流程基线场景名清单（防重复抽取）
         ② 可关联的功能基线清单（模块→功能→功能点，带 id）
    6 逐章节调模型 → 候选场景列表（含步骤 + 关联建议）
    7 返回候选 + 统计（**不写表**）
```

**引擎契约**（`app/process_baselines/derive.py`，与 04 的 `app/baselines/derive.py` 同构）：

| 规则 | 值 | 与 04 的关系 |
|---|---|---|
| **签名里没有 `session`** | `run_derive(provider, template, document_name, version_no, chapters, existing_scenarios, linkable_targets, max_chars)` | 照抄 04 的 `:349-410`——「反推只出草案不写表」从「靠自觉」变成「结构上做不到」 |
| 空章节不调模型 | `char_count == 0` 或正文空白 → 记 `empty_content`，**不调模型** | 照抄 04 的 `:371-376` |
| 空结果不算失败 | `{"scenarios": []}` → 记 `no_structured_content` | 照抄 04 的 `:394-398` |
| 坏 JSON / 根结构不对 → 整次失败 | `LLMOutputInvalid` | 照抄 04 的 `parse_modules` `:190-210` |
| 单候选名字为空 / 超长 → **只丢该候选** | 不失败 | 照抄 04 的 `_normalize_node` `:229-248` |
| 候选的 `target_id` 不在可关联清单里 → **只丢该条关联** | 不丢整个候选 | **本期新增**（04 没有关联概念） |
| 跨章节合并 | 同名场景按名字合并，**步骤保留首次出现**（不追加）、`source_chapter_id` 取第一次出现 | 照抄 04 的 `_MergedTree` `:271-346`，但步骤是列表，追加会重复 |
| JSON 容错 | 一律走 `parse_llm_json`（`app/llm/json_utils.py`），**不补引号、不截断补全** | 与 06 期一致 |
| 长度上限 | 场景名 128 / 描述 500 / 理由 1000 | 照抄 04 的 `:34-36` |

**输出契约**（模型要返回的 JSON）：

```json
{
  "scenarios": [
    {
      "name": "扫码登录连续失败 5 次后锁定",
      "description": "账号已存在且未锁定时，连续输错密码达阈值后账号被锁定",
      "precondition": "账号已注册且处于未锁定状态",
      "confidence": 0.9,
      "rationale": "章节 4.2 明确描述了失败次数阈值与锁定行为",
      "steps": [
        {"action": "打开登录页并选择「扫码登录」", "expected": "展示扫码二维码"},
        {"action": "连续 5 次输入错误密码", "expected": "提示账号已被锁定"}
      ],
      "links": [
        {"target_type": "function", "target_id": 10096, "target_name": "用户扫码登录"}
      ]
    }
  ]
}
```

> **`target_id` 是真实 id**，由 Prompt 里的「可关联的功能基线清单」给出
> （§3.10）。清单里没有的 id → **该条关联被丢弃**（不丢整个候选）。

**采纳**：`POST /process-baselines/scenarios` 批量建，条目形如：

```json
{
  "name": "扫码登录连续失败 5 次后锁定",
  "description": "...",
  "precondition": "...",
  "source_type": "document_derived",
  "source_document_id": 3,
  "source_version_id": 7,
  "source_chapter_id": 12,
  "source_chapter_title": "4.2 登录失败次数限制",
  "source_method": "baseline_reverse",
  "steps": [{"action": "...", "expected": "..."}],
  "links": [{"target_type": "function", "target_id": 10096}]
}
```

> 客户端**可以**传 `target_name`（回显用），但服务端**会重查覆盖**（§5.3）。

### 5.5 审核与快照流程

```
提交审核 POST /process-baselines/reviews/submit  { comment? }
    1 校验：项目 404 → 归档 409 → 角色 403
    2 项目内已有 status='submitted' 的快照 → 409 PROCESS_BASELINE_IN_REVIEW
    3 当前无 active 场景 → 400 PROCESS_BASELINE_INVALID
    4 冻结：收集全部 active 场景（含步骤 + 关联）→ draft_snapshot JSON
    5 建 process_baseline_revisions(status='submitted', draft_snapshot=…, 三个计数)
    6 审计 process_baseline.review.submit → commit

审核通过 POST /process-baselines/reviews/{revision_id}/approve  { comment? }
    1 校验：项目 404 → 归档 409 → 角色 403
    2 快照不存在 → 404 PROCESS_BASELINE_REVISION_NOT_FOUND
    3 status != 'submitted' → 409 PROCESS_BASELINE_REVIEW_STATUS_INVALID
    4 自审校验：读系统设置 allow_baseline_self_approval（app/common/settings.get_setting）
       —— 提交者 == 审核者 且开关关闭 → 403 SelfApprovalForbidden（复用 04 的错误类）
    5 structure_json = draft_snapshot（**原样转正，逐字节相同**）
    6 version_no = 项目内下一个 v1.{n}（**只查 process_baseline_revisions**）
    7 status='approved' + reviewed_by / reviewed_at → 审计 → commit

审核驳回 POST /process-baselines/reviews/{revision_id}/reject  { comment }
    1 同上的前 3 步
    2 意见必填（复用 04 的 ReviewCommentRequired）
    3 status='rejected' + reviewed_by / reviewed_at / review_comment
    4 **不分配 version_no、不写 structure_json**（draft_snapshot 保留供追溯）
    5 场景编辑解锁（不再有 submitted 记录）→ 审计 → commit
```

**快照 JSON 结构**（`draft_snapshot` 与 `structure_json` 同格式）：

```json
{
  "scenarios": [
    {
      "id": 1,
      "name": "扫码登录连续失败 5 次后锁定",
      "description": "...",
      "precondition": "...",
      "source_type": "document_derived",
      "status": "active",
      "version_no": 2,
      "steps": [{"step_no": 1, "action": "...", "expected": "..."}],
      "links": [{"target_type": "function", "target_id": 10096, "target_name": "用户扫码登录"}]
    }
  ],
  "counts": {"scenarios": 1, "steps": 2, "links": 1}
}
```

**归档场景不参与快照**（与 04「归档模块及其功能不参与新快照」一致：
`app/baselines/service.py:1920-2035` 的 `_collect_structure` 过滤 `status='active'`）；
**归档场景的步骤与关联也不计入计数**。

### 5.6 目标存活的判定

场景详情与列表的关联字段，读取时判定目标是否仍存在：

| 字段 | 含义 |
|---|---|
| `target_type` / `target_id` / `target_name` | 链接本身（`target_name` 是快照） |
| `target_deleted` | `true` = 目标已被 04 物理删除；`false` = 目标仍在 |

**判定方式**：一次 `IN` 批量查 `baseline_functions` / `baseline_feature_points`，
在 Python 层建映射，**不做 N+1**（与 09 的 `_cases_by_ids` 同一思路）。

**目标被删后的行为**：
- 链接行**保留**（不级联清理——链接上没有 FK，04 的删除不会碰它）；
- `target_deleted=true`，`target_name` 仍返回快照名；
- **04 的删功能接口仍返回 204**（不因流程基线的链接行而 500）。

## 6. 角色与权限

角色沿用 `project_members.role` 三档（`project_admin` / `member` / `guest`）+ 系统管理员兜底：

| 操作 | 访客 guest | 成员 member | 项目管理员 | 系统管理员 |
|---|---|---|---|---|
| 场景列表 / 详情 | 可 | 可 | 可 | 可（兜底） |
| 步骤 / 关联读取 | 可 | 可 | 可 | 可 |
| 快照列表 / 快照详情 | 可 | 可 | 可 | 可 |
| **新建场景**（手工 / 采纳） | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |
| **改场景 / 删场景** | 403 | 403 | 可 | 可 |
| **覆盖步骤 / 覆盖关联** | 403 | 403 | 可 | 可 |
| **发起反推** | 403 | 403 | 可 | 可 |
| **提交审核 / 通过 / 驳回** | 403 | 403 | 可 | 可 |

- 非项目成员访问读接口 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404 `PROJECT_NOT_FOUND`。
- 归档项目内读接口正常，写接口 → 409 `PROJECT_ARCHIVED`（**先判归档，再判角色**）。
- **复用 `app/common/permissions.py` 的既有 5 个函数**，不新写权限判定：
  - 读：`ensure_readable(session, project_id=..., actor=...)`
  - 写：`ensure_writable_project(...)` → `ensure_admin(..., action="…")`
- **自审**沿用 04 的口径：读系统设置 `allow_baseline_self_approval`
  （`app/common/settings.py:25` 的 `get_setting`，迁移 `0018` 播种，默认开启），
  关闭时提交者不能审核自己的提交（403 `SelfApprovalForbidden`）。
  **本期不新增系统设置项。**

## 7. 接口

前缀：`/api/projects/{project_id}/process-baselines`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/scenarios` | 成员 | 场景列表（`keyword` / `source_type` / `status` 筛选，分页） |
| POST | `/scenarios` | 项目管理员 | **批量**新建场景（手工添加 / 反推候选采纳），`items` 为数组 |
| GET | `/scenarios/{scenario_id}` | 成员 | 场景详情（步骤 + 关联 + 目标存活标记） |
| PATCH | `/scenarios/{scenario_id}` | 项目管理员 | 改名称 / 描述 / 前置条件 / 状态 |
| DELETE | `/scenarios/{scenario_id}` | 项目管理员 | 删场景（物理删除，级联步骤与关联） |
| PUT | `/scenarios/{scenario_id}/steps` | 项目管理员 | **整体覆盖**步骤 |
| PUT | `/scenarios/{scenario_id}/links` | 项目管理员 | **整体覆盖**关联 |
| POST | `/derive` | 项目管理员 | 从文档反推场景候选（**不写表**） |
| POST | `/reviews/submit` | 项目管理员 | 提交审核（冻结 `draft_snapshot`） |
| POST | `/reviews/{revision_id}/approve` | 项目管理员 | 审核通过（转正 + 分配版本号） |
| POST | `/reviews/{revision_id}/reject` | 项目管理员 | 审核驳回（意见必填，不占版本号） |
| GET | `/revisions` | 成员 | 快照列表（分页） |
| GET | `/revisions/{revision_id}` | 成员 | 快照详情（`draft_snapshot` / `structure_json` + 计数） |

**固定校验顺序**（与 04 / 05 / 07 / 08 / 09 一致）：

```
项目 404 → 归档 409 → 角色 403 → 资源 / 业务校验 400 → 执行
```

**任何一步失败都不产生写入**（校验在建行之前）；**失败操作不写审计**。

### 7.1 `POST /scenarios`（手工新增）

```json
// 请求
{
  "scenarios": [
    {
      "name": "扫码登录连续失败 5 次后锁定",
      "description": "账号已存在且未锁定时，连续输错密码达阈值后账号被锁定",
      "precondition": "账号已注册且处于未锁定状态",
      "source_type": "manual",
      "steps": [
        {"action": "打开登录页并选择「扫码登录」", "expected": "展示扫码二维码"},
        {"action": "连续 5 次输入错误密码", "expected": "提示账号已被锁定"}
      ],
      "links": [{"target_type": "function", "target_id": 10096}]
    }
  ]
}
```

```json
// 响应 201
{
  "created": 1,
  "items": [
    {
      "index": 0,
      "id": 12,
      "name": "扫码登录连续失败 5 次后锁定",
      "source_type": "manual",
      "version_no": 1,
      "step_count": 2,
      "link_count": 1
    }
  ]
}
```

> `source_type='manual'` 时，**六列追溯字段一个都不传**（服务端也不写）。
> 传了也不报错，但会被服务端**忽略并强制置 NULL**——手工来源按 PRD 不做追溯要求。

### 7.2 `POST /derive`（文档反推）

```json
// 请求
{
  "document_id": 3,
  "document_version_id": 7,
  "template_id": 2
}
```

```json
// 响应 200（**不写表**）
{
  "chapter_count": 12,
  "processed_count": 11,
  "skipped_chapters": [{"chapter_id": 15, "reason": "empty_content"}],
  "scenarios": [
    {
      "name": "扫码登录连续失败 5 次后锁定",
      "description": "...",
      "precondition": "...",
      "confidence": 0.9,
      "rationale": "章节 4.2 明确描述了失败次数阈值与锁定行为",
      "source_chapter_id": 12,
      "source_chapter_title": "4.2 登录失败次数限制",
      "steps": [{"action": "...", "expected": "..."}],
      "links": [{"target_type": "function", "target_id": 10096, "target_name": "用户扫码登录"}]
    }
  ]
}
```

> **响应里没有 `id`**——候选还没落库。用户勾选后走 `POST /scenarios`，
> 条目里带上 `source_document_id` / `source_version_id` / `source_chapter_id`
> 与 `source_chapter_title`，服务端做 §5.1 的自洽校验。

### 7.3 `PUT /scenarios/{id}/steps`（整体覆盖）

```json
// 请求
{ "steps": [{"action": "打开登录页", "expected": "展示登录页"}, {"action": "输入错误密码", "expected": "提示密码错误"}] }
```

```json
// 响应 200
{
  "id": 12,
  "step_count": 2,
  "steps": [
    {"step_no": 1, "action": "打开登录页", "expected": "展示登录页"},
    {"step_no": 2, "action": "输入错误密码", "expected": "提示密码错误"}
  ]
}
```

### 7.4 `GET /scenarios/{id}`（详情）

```json
{
  "id": 12,
  "name": "扫码登录连续失败 5 次后锁定",
  "description": "...",
  "precondition": "账号已注册且处于未锁定状态",
  "source_type": "document_derived",
  "status": "active",
  "version_no": 2,
  "source_document_id": 3,
  "source_version_id": 7,
  "source_chapter_id": 12,
  "source_chapter_title": "4.2 登录失败次数限制",
  "source_method": "baseline_reverse",
  "source_analysis_id": null,
  "created_by": 1,
  "created_at": "2026-11-22T10:00:00",
  "updated_at": "2026-11-22T11:00:00",
  "steps": [{"step_no": 1, "action": "...", "expected": "..."}],
  "links": [
    {
      "target_type": "function",
      "target_id": 10096,
      "target_name": "用户扫码登录",
      "target_deleted": false
    }
  ]
}
```

> **`target_deleted`**：目标被 04 物理删除后为 `true`，但 `target_name` 仍返回快照名。

### 7.5 错误码（新增 8 个）

| 类名 | code | HTTP | 场景 |
|---|---|---|---|
| `ProcessBaselineNotFound` | `PROCESS_BASELINE_NOT_FOUND` | 404 | 场景不存在 / 不属于该项目 |
| `ProcessBaselineInvalid` | `PROCESS_BASELINE_INVALID` | 400 | 名称为空或超长 / 非法 `status` / 非法 `source_type` / 没有可提交审核的场景 / 文档推导来源三元组不自洽 / 溯源字段缺失 |
| `ProcessBaselineDuplicateName` | `PROCESS_BASELINE_DUPLICATE_NAME` | 409 | 同项目已有同名场景 |
| `ProcessBaselineStepInvalid` | `PROCESS_BASELINE_STEP_INVALID` | 400 | 步骤数组不合法（空 / `action` 为空 / 超过 100 步） |
| `ProcessBaselineLinkInvalid` | `PROCESS_BASELINE_LINK_INVALID` | 400 | `target_type` 非法 / 目标不存在或不属于本项目 / 目标已归档 / 同一次提交里重复关联同一目标 |
| `ProcessBaselineRevisionNotFound` | `PROCESS_BASELINE_REVISION_NOT_FOUND` | 404 | 快照不存在 / 不属于该项目 |
| `ProcessBaselineReviewStatusInvalid` | `PROCESS_BASELINE_REVIEW_STATUS_INVALID` | 409 | 快照状态不允许（对已通过 / 已驳回的快照再审核） |
| `ProcessBaselineInReview` | `PROCESS_BASELINE_IN_REVIEW` | 409 | 项目内已有审核中的快照（重复提交审核 / 审核期间编辑场景被锁定） |

全部加进 `app/common/errors.py` 的 `__all__`（`app/common/errors.py:959` 起）。

**另复用 1 个既有的错误类**（不改 04 的判定逻辑，只复用类本身）：

| 类名 | code | HTTP | 场景 |
|---|---|---|---|
| `ReviewCommentRequired`（**已存在**，04 的驳回意见必填） | `REVIEW_COMMENT_REQUIRED` | 400 | 本期的驳回同样要求意见必填 |

> 为什么复用而不新造：语义完全一致（"审核驳回必须写意见"），
> 前端 `web/src/api/client.ts` 也已经有这条中文映射。

### 7.6 审计

| 场景 | action | after_data |
|---|---|---|
| 批量新建场景 | `process_baseline.scenario.create` | `created` 计数 + 场景名列表（截断） |
| 改场景 | `process_baseline.scenario.update` | `scenario_id` / 变更字段 / 变更前后的 `version_no` |
| 删场景 | `process_baseline.scenario.delete` | `scenario_id` / 场景名 / 被级联清理的步骤数与关联数 |
| 覆盖步骤 | `process_baseline.steps.update` | `before_count` / `after_count` |
| 覆盖关联 | `process_baseline.links.update` | `before_count` / `after_count` |
| 发起反推 | `process_baseline.derive.run` | `document_id` / `document_version_id` / `template_id` / `provider` / 统计 |
| 提交审核 | `process_baseline.review.submit` | `revision_id` / `scenario_count` / `step_count` / `link_count` / `comment` |
| 审核通过 | `process_baseline.review.approve` | `revision_id` / `version_no` / 三个计数 / `self_approved` |
| 审核驳回 | `process_baseline.review.reject` | `revision_id` / `comment` |

审计条目含 `project_id` / `actor_id` / `target_type` / `target_id`；
**失败操作不写审计**（校验失败在建行之前，自然没有审计）。

> **`self_approved`**：自审放行时留痕，方便事后分辨「双人复核」与「单人兜底」
> （与 04 的 `approve_review` 同一口径，`app/baselines/service.py:1647-1648`）。

## 8. 前端

### 8.1 入口：基线管理内的二级子菜单

`ProjectDetailPage.tsx` 的 `baseline-management` Tab 改为：

```tsx
{
  key: 'baseline-management',
  label: '基线管理',
  children: (
    <ProjectBaselineManagementTab projectId={projectId} canManage={canManage} />
  ),
}
```

`ProjectBaselineManagementTab.tsx` 内部是二级 `Tabs`：

| 子 Tab | key | 内容 |
|---|---|---|
| 功能基线 | `function` | **现状原样**：`Card「功能基线结构」` + `ProjectBaselineTree` + `ProjectBaselineSnapshots` |
| 流程基线 | `process` | `ProjectProcessBaselineTab` |

- `defaultActiveKey="function"` → **现有用户路径不变**，进来还是先看到功能基线；
- 功能基线面板**一个字节的现有渲染逻辑都不改**，保证 e2e 的
  `TAB_ANCHORS["基线管理"] = "baseline-keyword"` 锚点仍在
  （`web/src/pages/ProjectBaselineTree.tsx:486`）。

> **顶层 Tab 仍然是 10 个**：antd `Tabs` 的非活动面板是**懒渲染**，
> 内层二级 Tabs 在 e2e 计数时**尚未挂载**，`get_by_role("tab")` 的
> `to_have_count(10)` 仍然成立。AC-212 断言这一点。

### 8.2 组件拆分（单文件 < 400 行，验证约定 §4.3）

| 文件 | 预估行数 | 职责 |
|---|---|---|
| `web/src/pages/ProjectBaselineManagementTab.tsx` | ~90 | 二级 Tabs 外壳（状态与事件编排） |
| `web/src/pages/ProjectProcessBaselineTab.tsx` | ~280 | 场景列表 + 工具条 + 编辑 / 删除 / 刷新（编排） |
| `web/src/pages/processBaselineColumns.tsx` | ~180 | 列表列定义（纯渲染） |
| `web/src/pages/ProcessBaselineDrawer.tsx` | ~330 | 详情抽屉（元数据 + 步骤 + 关联） |
| `web/src/pages/ProcessBaselineStepsEditor.tsx` | ~180 | 步骤编辑器（照抄 `TestCaseStepsEditor.tsx` 改写） |
| `web/src/pages/ProcessBaselineDeriveModal.tsx` | ~230 | 反推弹窗（选文档 / 版本 / 模板 → 候选勾选 → 采纳） |
| `web/src/pages/ProcessBaselineReviewDrawer.tsx` | ~250 | 快照列表 + 提交 / 通过 / 驳回 + 快照内容 |
| `web/src/pages/processBaselineMeta.ts` | ~80 | 状态 / 来源 / 目标类型的中文文案与颜色 |

`ProjectDetailPage.tsx`（当前 379 行）只做**减法**——把基线管理的内容换成新组件，
**行数不增**。

### 8.3 交互要点

- **步骤编辑**：受控数组 + 「上移 / 下移 / 删除」按钮 + 「新增步骤」。
  **不用拖拽**（antd Table 里要额外引依赖，且无障碍性差——08 期已定这个取舍）。
  保存走 `PUT .../steps` **整体覆盖**；**前端不发 `step_no`**（服务端重排）。
- **关联编辑**：一个多选下拉（可关联的功能基线清单）+ 已选列表（可删）。
  保存走 `PUT .../links` 整体覆盖。
- **反推弹窗**：选文档 → 选生效版本 → 选模板 → 「开始反推」→ 候选表（勾选）→
  「采纳为场景」。**候选默认全不勾**（PRD 1.4 原则二：高风险行为人工确认）。
- **权限渲染**：`canManage`（项目管理员）才渲染新建 / 反推 / 编辑 / 删除 / 关联 /
  提交审核 / 通过 / 驳回。成员与访客**一个写入口都看不到**（不是「渲染了点了报 403」），
  只显示一句只读提示——与 09 期同一口径。
- **审核中**：列表上的写入口**禁用**并提示「审核中，暂不可编辑」；
  通过 / 驳回在快照抽屉里。

### 8.4 `data-testid` 命名（沿用「区域-动作-目标」，统一前缀 `process-baseline-`）

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

> **antd 的两个坑**（09 期踩过）：
> ① 行的锚点要用 `onRow` 返回 `data-testid`，`rowClassName` 只能给 class；
> ② **disabled 的按钮不派发鼠标事件**，Tooltip 必须挂在外层 `<span>` 上。

## 9. 验收标准

验证口径遵循 [specs/验证约定.md](../验证约定.md)：后端用例命名 `test_ac_<AC号>_<场景>`，
e2e 命名 `test_ac_<AC号>_<场景>_ui`，前台截图落 `.screenshots/<任务号>/` 且文件名含 AC 编号。

### AC-197 数据模型与迁移 `0025`

- **Given** 一个已跑到 `0024` 的库
- **When** `alembic upgrade head`
- **Then** `current` = `0025`；四张新表存在：`process_baselines` / `process_baseline_steps` /
  `process_baseline_links` / `process_baseline_revisions`
- **Then** `process_baselines.source_type` 的 CHECK 只接受 `manual` / `document_derived`，
  其它值被 MySQL 拒（3819）
- **Then** `process_baselines.status` 的 CHECK 只接受 `active` / `archived`
- **Then** `process_baseline_links.target_type` 的 CHECK 只接受 `function` / `feature_point`
- **Then** `process_baseline_revisions.status` 的 CHECK 只接受 `submitted` / `approved` / `rejected`
- **Then** `process_baseline_steps.step_no >= 1` 的 CHECK 生效
- **Then** 唯一键 `uk_pbaselines_project_name` / `uk_pbsteps_baseline_no` /
  `uk_pblinks_baseline_target` / `uk_pbrevisions_project_no` 全部生效
- **Then** `0025 → 0024 → 0025` 往返干净，**两库** head 均为 `0025`
- **Then** **功能基线与流程基线的版本号互不干扰**：同项目里功能基线发 `v1.0`、
  流程基线也发 `v1.0`；`baseline_revisions` 与 `process_baseline_revisions`
  各自的 `version_no` 序列独立递增
- **Then** `prompt_templates` 里 `task_type='process_baseline'` 的模板**有且只有一条 active**

### AC-198 场景手工 CRUD

- **Given** 一个项目管理员
- **When** `POST /scenarios` 传一条 `source_type='manual'` 的场景
- **Then** 201；`source_type='manual'`；**六列追溯字段全为 NULL**；`version_no=1`
- **When** `PATCH /scenarios/{id}` 改名称
- **Then** 200；`version_no` **+1**（2）；审计 `process_baseline.scenario.update` 记录变更前后
- **When** 再建一个同名场景
- **Then** 409 `PROCESS_BASELINE_DUPLICATE_NAME`，**不新增行**
- **When** `DELETE /scenarios/{id}`
- **Then** 场景行删除；**步骤行与链接行同时被清理**（数据库级 CASCADE）；
  审计 `process_baseline.scenario.delete`
- **When** 场景状态置 `archived`
- **Then** 默认列表（`status='active'`）**不返回**它；`status='all'` 才返回
- **Then** 归档场景**不参与快照**（提交审核后的 `scenario_count` 不含它）

### AC-199 步骤整体覆盖

- **Given** 一个已存在步骤的场景
- **When** `PUT /scenarios/{id}/steps` 传空数组
- **Then** 400 `PROCESS_BASELINE_STEP_INVALID`；**旧步骤原样保留**（行数不变）
- **When** 传 101 步
- **Then** 400 `PROCESS_BASELINE_STEP_INVALID`；旧步骤原样保留
- **When** 传 3 步、其中第 2 步的 `action` 是空白字符串
- **Then** 400 `PROCESS_BASELINE_STEP_INVALID`；**旧步骤原样保留**（整组拒）
- **When** 传 2 步合法
- **Then** 200；`step_no` 重排为 **1、2**；库里的 `step_no` 与请求数组顺序一致
- **When** 传入带 `step_no` 的请求体
- **Then** `step_no` 被**忽略**，服务端按数组顺序重排
- **Then** `action` / `expected` 超过 1000 字符时被截断到 1000
- **Then** 审计 `process_baseline.steps.update` 含 `before_count` / `after_count`

### AC-200 关联功能基线

- **Given** 一个场景与两个功能基线目标
- **When** `PUT /scenarios/{id}/links` 传两条关联
- **Then** 200；`process_baseline_links` 两行；**`target_id` 列上没有外键**
  （`information_schema` 里查不到指向 `baseline_functions` 的约束）
- **Then** `target_name` 由**服务端重查**写入（前端传错名字也会被覆盖）
- **When** 关联一个**不存在**或**属于别的项目**的 `target_id`
- **Then** 400 `PROCESS_BASELINE_LINK_INVALID`；**不新增行**
- **When** 关联一个已 `archived` 的功能
- **Then** 400 `PROCESS_BASELINE_LINK_INVALID`
- **When** 同一次提交里重复关联同一目标
- **Then** 400 `PROCESS_BASELINE_LINK_INVALID`
- **When** 04 **物理删除**了其中一个功能
- **Then** **链接行仍在**（`process_baseline_links` 行数不变）
- **Then** `GET /scenarios/{id}` 返回该条关联且 `target_deleted=true`，
  `target_name` 仍是删除前的名称快照
- **Then** **04 的删功能接口仍返回 204**（不因流程基线的链接行变成 500）
- **Then** 04 的 `baseline_functions` / `baseline_feature_points` 表**零改动**
  （`git diff --stat` 为空）

### AC-201 来源追溯与只读

- **Given** `source_type='manual'` 的场景
- **When** 传任何追溯字段
- **Then** 服务端**忽略并强制置 NULL**；响应里六列全为 `null`
- **Given** `source_type='document_derived'` 的场景
- **When** 缺 `source_document_id` / `source_version_id` / `source_chapter_id` 之一
- **Then** 400 `PROCESS_BASELINE_INVALID`，**整批不落库**
- **When** `source_version_id` 与 `source_document_id` 对不上
- **Then** 400 `PROCESS_BASELINE_INVALID`
- **When** `source_chapter_id` 属于**别的项目**的文档版本
- **Then** 400 `PROCESS_BASELINE_INVALID`
- **When** `PATCH /scenarios/{id}` 试图改 `source_document_id` 等追溯字段
- **Then** 服务端**不写**（追溯字段只读），`GET` 回来仍是原值
- **Then** `source_chapter_title` 是**快照**：章节改名后场景上的标题不变

### AC-202 反推引擎是纯函数

- **Given** 一个文档版本与一条 `task_type='process_baseline'` 的模板
- **When** 调 `POST /derive`
- **Then** `process_baselines` / `process_baseline_steps` / `process_baseline_links`
  三张表**行数全部不变**（反推不写表）
- **Then** 引擎函数的签名里**没有 `session` 参数**（结构上做不到写表）
- **Then** 输出的根结构是 `{"scenarios": [...]}`（**列表**，不是三级树）
- **Then** 模型返回坏 JSON → 整次失败，`LLMOutputInvalid`
- **Then** 模型返回 `{"scenarios": []}` → **不算失败**，记 `no_structured_content`
- **Then** 某个候选的 `name` 为空 → **只丢该候选**，其余候选正常返回
- **Then** 某个候选的 `target_id` **不在**本次提供的可关联清单里 → **只丢该条关联**，
  该候选与其步骤仍返回
- **Then** `char_count == 0` 的章节**不调模型**（记 `empty_content`）
- **Then** Prompt 里同时含「已有流程基线场景清单」与「可关联的功能基线清单（带 id）」
- **Then** 既有五个 Mock 分支的输出**一个字节不变**

### AC-203 反推候选采纳

- **Given** 反推返回 3 个候选
- **When** 勾选 2 个后 `POST /scenarios`（`source_type='document_derived'`，带自洽的追溯三元组）
- **Then** 201；`created=2`；两行的 `source_type='document_derived'` 且追溯三元组与请求一致
- **When** 勾选的候选里有一个**同名**已存在场景
- **Then** **整批拒绝**（409 `PROCESS_BASELINE_DUPLICATE_NAME`），
  **不产生半批落库**（`process_baselines` 行数不变）
- **When** 采纳的候选带 `links`
- **Then** 链接行按服务端重查的名称写入 `target_name`
- **Then** 审计 `process_baseline.scenario.create` 含 `created` 计数

### AC-204 提交即冻结

- **Given** 一个项目里有 2 个 active 场景
- **When** `POST /reviews/submit`
- **Then** 201；新建一条 `status='submitted'` 的快照；
  `draft_snapshot` **非空**；`structure_json` 为 `NULL`；`version_no` 为 `NULL`
- **Then** `scenario_count=2`；`step_count` / `link_count` 与实际一致
- **Then** `draft_snapshot` 里的场景含 `steps` 与 `links`
- **When** 提交后再 `PATCH /scenarios/{id}` 改名称
- **Then** 409 `PROCESS_BASELINE_IN_REVIEW`；**场景内容未变**
- **When** 提交后再 `PUT .../steps` / `PUT .../links` / `DELETE /scenarios/{id}`
- **Then** 同样 409 `PROCESS_BASELINE_IN_REVIEW`
- **When** 项目内已有一份 `status='submitted'` 的快照时再提交
- **Then** 409 `PROCESS_BASELINE_IN_REVIEW`；**不新建快照**
- **When** 项目内没有任何 active 场景时提交
- **Then** 400 `PROCESS_BASELINE_INVALID`；**不新建快照**
- **Then** 审计 `process_baseline.review.submit` 含三个计数

### AC-205 通过转正与版本号

- **Given** 一份 `status='submitted'` 的快照
- **When** `POST /reviews/{id}/approve`
- **Then** 200；`status='approved'`；`version_no=0`（展示为 `v1.0`）
- **Then** **`structure_json` 与 `draft_snapshot` 逐字节相同**
- **Then** `scenario_count` / `step_count` / `link_count` 与 `draft_snapshot` 里的 `counts` 一致
- **When** 再走一轮提交 → 通过
- **Then** 第二份快照 `version_no=1`（展示为 `v1.1`）；**不覆盖**第一份
- **Then** 唯一键 `uk_pbrevisions_project_no` 生效（同项目不会有两份 `v1.0`）
- **Then** 审计 `process_baseline.review.approve` 含 `version_no` 与三个计数
- **Then** 通过后场景**解锁**（可再次编辑）

### AC-206 驳回

- **Given** 一份 `status='submitted'` 的快照
- **When** `POST /reviews/{id}/reject` **不传意见**
- **Then** 400 `REVIEW_COMMENT_REQUIRED`；快照状态**不变**（仍 `submitted`）
- **When** 传意见
- **Then** 200；`status='rejected'`；`version_no` **仍为 NULL**；`structure_json` **仍为 NULL**；
  `draft_snapshot` **保留**
- **Then** 场景**解锁**（可编辑）
- **Then** 审计 `process_baseline.review.reject` 含 `comment`
- **When** 对已 `rejected` 的快照再点通过
- **Then** 409 `PROCESS_BASELINE_REVIEW_STATUS_INVALID`

### AC-207 权限矩阵

- **Given** member / guest
- **When** 读接口（场景列表 / 详情 / 快照列表 / 快照详情）
- **Then** 200
- **When** 新建 / 改 / 删 / 覆盖步骤 / 覆盖关联 / 反推 / 提交审核 / 通过 / 驳回
- **Then** 403 `NOT_PROJECT_ADMIN`
- **Given** 非项目成员
- **When** 读接口
- **Then** 403 `NOT_PROJECT_MEMBER`
- **Given** 项目不存在
- **Then** 404 `PROJECT_NOT_FOUND`
- **Given** 系统管理员
- **When** 写接口
- **Then** 通过（兜底）

### AC-208 归档项目

- **Given** 项目已归档
- **When** 写接口（新建 / 改 / 删 / 覆盖步骤 / 覆盖关联 / 反推 / 提交审核 / 通过 / 驳回）
- **Then** 409 `PROJECT_ARCHIVED`
- **When** 读接口
- **Then** 200
- **Given** 归档项目里的**普通成员**（不是管理员）
- **When** 调写接口
- **Then** **409**（**不是 403**）——归档先于角色判

### AC-209 审计

- **Given** 跑完一期
- **Then** 9 个 action 各有落库：`process_baseline.scenario.create` / `.scenario.update` /
  `.scenario.delete` / `.steps.update` / `.links.update` / `.derive.run` /
  `.review.submit` / `.review.approve` / `.review.reject`
- **Then** 审计条目带 `project_id` / `actor_id` / `target_type` / `target_id`
- **Then** `review.approve` 的 `after_data` 含 `self_approved` 标记
- **Given** 一个失败操作（如步骤校验失败）
- **Then** **不产生**任何 `process_baseline.*` 审计

### AC-210 本期不做标签（显式欠账）

- **Given** 迁移 `0025` 已执行
- **Then** 库里**不存在**任何流程基线的标签表
- **Then** `baseline_labels` 表结构**零改动**（`target_type` 的 CHECK 仍是
  `('function','feature_point')`）
- **Then** 路由表里**不存在**流程基线的标签接口
- **Then** 场景的响应体里**没有** `label_types` / `labels` 字段
- **Then** `git diff --stat` 显示 `app/baselines/` **零改动**
- **Then** spec §13 登记了「增量分析支持流程基线打标」这条欠账

### AC-211 本期不做保留策略与被引用即保护（显式欠账）

- **Given** 迁移 `0025` 已执行
- **Then** `projects` 表**没有新增列**（`baseline_snapshot_max_count` 仍是唯一的快照上限列）
- **Then** 路由表里**不存在**流程基线的快照删除 / 保留策略 / 清理候选 / 告警接口
- **Then** 流程基线的快照**永久保留**（没有任何代码路径能删它）
- **Then** `git diff --stat` 显示 `app/models/project.py` **零改动**
- **Then** spec §13 登记了「流程基线快照保留策略」这条欠账

### AC-212 前端二级子菜单

- **Given** 打开项目详情的「基线管理」Tab
- **Then** 出现两个子 Tab：「功能基线」/「流程基线」
- **Then** **默认停在「功能基线」**，功能基线树与快照面板**照常渲染**
  （`baseline-keyword` 锚点可见）
- **Then** 切到「流程基线」→ 流程基线列表渲染出来
- **Then** **顶层仍然是 10 个 Tab**（`get_by_role("tab")` 计数为 10，
  「自动化执行」仍是最后一个）
- **Then** `tests/e2e/test_tabs_ui.py` 与 `tests/e2e/test_t116_closing_ui.py`
  的既有断言**原样通过**（一个字节都没改）
- **Then** e2e 用例命名 `test_ac_212_*_ui`；截图 `.screenshots/T122/` 文件名含 AC 编号

### AC-213 前端场景管理

- **When** 新建一个场景（名称 + 前置条件 + 两步步骤 + 一条关联）
- **Then** 列表出现新行；详情抽屉能看到元数据、2 行步骤、1 条关联
- **When** 在抽屉里「上移」第 2 步并保存
- **Then** 只读步骤表与库里的顺序一致（**前端不发 `step_no`**）
- **When** 发起反推 → 候选表出现候选 → 勾选 → 采纳
- **Then** 列表出现新场景，来源显示「文档解析」
- **When** 提交审核 → 通过
- **Then** 快照列表出现 `v1.0`；点开能看到场景集合
- **Given** 成员登录
- **Then** **无**新建 / 反推 / 编辑 / 删除 / 关联 / 审核按钮，场景与快照可读，
  显示一句只读提示
- **Then** e2e 用例命名 `test_ac_213_*_ui`；截图 `.screenshots/T122/` 文件名含 AC 编号

### AC-214 零回归与红线

- **Given** 全量测试套件
- **When** 跑全量
- **Then** **零真实 socket**：测试目录不出现 `requests` / `urlopen` / `aiohttp` / `socket.socket`
- **Then** 既有 **1259 条**测试**一条不删、不改期望值**
- **Then** 04 / 05 / 06 / 07 / 08 / 09 定向回归**零失败**
- **Then** 两库迁移 head 均为 `0025`；`0025 → 0024 → 0025` 往返干净
- **Then** `git diff --stat` 显示上游目录只有两处改动：
  `app/llm/mock.py`（新增一个前缀分支，既有五个分支行为一个字节不变）
  与 `app/models/incremental.py`（`prompt_templates` 的 CHECK 扩一个枚举值）
- **Then** `app/baselines/` / `app/test_points/` / `app/incremental/`（服务层）/
  `app/test_cases/` / `app/automation/` / `app/models/project.py` **零改动**
  （注意：`app/models/incremental.py` 是**模型**文件，不在 `app/incremental/` 包内）

## 10. 非功能

- **零真实网络请求**：本期不引入任何网络客户端。反推只调注入的 `LLMProvider`。
- **同步执行**：与 04 / 05 / 07 / 08 / 09 一致，不引入异步队列。
- **步骤规模上限**：单场景最多 **100 步**（与 08 一致）。
- **关联规模上限**：单场景最多 **50 条**关联（超出 → 400 `PROCESS_BASELINE_LINK_INVALID`）。
- **批量新建上限**：一次 `POST /scenarios` 最多 **20 个**场景（超出 → 400）。
- **文本截断**：场景名 255 / 描述 500 / 前置条件 1000 / 步骤 action 与 expected 各 1000。
- **快照体积**：`draft_snapshot` / `structure_json` 用 MEDIUMTEXT（16MB），
  单份快照的场景数上限受「批量 20 个」约束，实际体积可控。
- **列表分页**：`page_size` 上限 200（与 04 / 08 一致）。
- **大模型不可用**：反推时 provider 抛异常 → 502 / `LLM_CALL_FAILED`（沿用 06 的错误类），
  **不产生半截候选**。
- **API Key 不明文**：沿用 06 期口径，本期不涉及密钥。

## 11. 依赖与影响

| 依赖 | 状态 |
|---|---|
| 04 `baseline_functions` / `baseline_feature_points` | ✅ 已上线（`0012`）——**只读**，用于关联目标校验与名称快照 |
| 04 `baseline_revisions` | ✅ 已上线（`0012`）——**零改动**，流程基线**另有**自己的快照表 |
| 03 `document_versions` / `document_chapters` | ✅ 已上线——反推的输入与追溯来源 |
| 06 `prompt_templates` | ⚠️ **本期唯一的上游 schema 改动**：CHECK 扩 `'process_baseline'` |
| 06 `llm_run_logs` | ✅ **零改动**——本期反推不写运行留痕（与 04 的推导同构） |
| `app/common/permissions.py` | ✅ 5 个权限函数，直接复用 |
| `app/common/audit.py` | ✅ `write_audit` 直接复用 |
| `app/common/settings.py` | ✅ `get_setting` 直接复用（自审开关） |
| `app/llm/json_utils.py` | ✅ `parse_llm_json` 直接复用 |
| **新增运行时依赖** | **无** |

### 上游 schema 改动声明（本期唯一的两处上游改动）

| # | 位置 | 改动 | 为什么必须 | 影响面 |
|---|---|---|---|---|
| 1 | `app/llm/mock.py` | 新增一个分支：`req.system.startswith("[PROCESS_BASELINE_SYSTEM]")` → 返回一个最小场景 | Mock 靠 system 前缀分流；不加工具就分不出「这是流程基线推导」 | **既有五个分支一个字节不变**（`git diff --stat` 实测） |
| 2 | `app/models/incremental.py` | `TASK_TYPES` 与 `ck_ptemplates_task_type` 各加一个 `'process_baseline'` | 提示词模板要有落表位置，且**类型必须可区分** | CHECK 扩值是**放宽**不是改语义；既有四个类型的模板与断言不受影响 |

> **为什么第 2 处不能省**：复用 `task_type='document_parse'` 会让 04 的推导下拉里
> 同时出现「基线推导」与「流程基线推导」两个模板，而 04 的服务端只校验
> `task_type == 'document_parse'`（`app/baselines/service.py:2416-2420`）——
> 用户选了流程基线模板，04 的解析器会拿到 `{"scenarios": [...]}`，
> 根结构校验失败，**报错信息完全指不到真因**。
>
> `llm_run_logs.task_type` 为什么不动：04 的文档推导**不写运行留痕**
> （`run_document_derive` 里没有 `run_log.record_run`），本期的反推同构 → 不需要。

**对既有模块的影响**：

| 模块 | 影响 |
|---|---|
| `app/models/process_baseline.py` | **新增** 4 个模型 |
| `app/models/__init__.py` | 加 4 个模型的 import 与 `__all__` |
| `app/common/errors.py` | 加 8 个错误类 + `__all__` |
| `app/main.py` | 注册 1 个路由（`process_baselines_router`） |
| `app/models/incremental.py` | `TASK_TYPES` + `ck_ptemplates_task_type` 各加一个枚举值 |
| `app/llm/mock.py` | 新增一个前缀分支 |
| `web/src/api/index.ts` | 新增 `processBaselines` 命名空间（13 个方法 + 类型） |
| `web/src/api/client.ts` | 新增 8 条错误码中文 |
| `web/src/pages/ProjectDetailPage.tsx` | 基线管理 Tab 改为渲染新组件（**行数不增**） |
| `app/baselines/` / `app/incremental/`（服务层）/ `app/test_points/` / `app/test_cases/` / `app/automation/` | **零改动** |

## 12. 风险与规避

| 风险 | 规避 |
|---|---|
| **两套基线抢版本号**——共用表会让功能基线的 `v1.0` 占掉流程基线的 `v1.0` | 分表存储（§3.1）；AC-197 显式断言两套序列独立 |
| **审核期间内容漂移**——04 是通过时冻结，冻结出来的可能不是审核人看的那份 | 提交即冻结 + 审核期锁定（§3.5 / §3.8）；AC-205 断言 `structure_json` 与 `draft_snapshot` **逐字节相同** |
| **04 物理删功能导致 500**——建 FK 会让 04 的既有删除接口炸 | `target_id` 不建外键 + 名称快照 + `target_deleted` 标记（§3.4）；AC-200 断言 04 删功能**仍返回 204** |
| **关联表达不了多对多**——两个可空外键列只能表达 0..1 | 关联表（§4.3）；AC-200 断言一个场景可关联多个目标 |
| **模型瞎猜 `target_id`**——不给功能基线清单，产出的关联全是编的（06 期 L2 翻车史） | Prompt 给「可关联的功能基线清单（带 id）」；越界 id **只丢该条关联**（§3.10 / §5.4）；AC-202 断言 |
| **反推重复抽取**——不给已有清单，每次把整份文档重抽一遍 | Prompt 给「已有流程基线场景清单」；同名合并（§5.4） |
| **反推写出脏数据**——引擎直接写表，坏结果也落库 | 引擎**签名里没有 `session`**（结构上做不到写表）；采纳走独立的批量接口（§5.4）；AC-202 断言三张表行数不变 |
| **批量采纳半批落库**——5 条里第 3 条校验失败，前 2 条已建 | **整批拒**（§5.1）；AC-203 断言行数不变 |
| **步骤半截状态**——校验失败时旧步骤已被删 | **先校验整组再动手**（§5.2）；AC-199 断言旧步骤原样保留 |
| **Prompt 越界引用**——服务端的候选里塞不存在的 id | 候选里的 `target_id` 不在清单里 → **只丢该条关联**（§5.4） |
| **e2e 的 Tab 计数失效**——加了二级 Tabs，`get_by_role("tab")` 计数变 12 | antd 非活动面板懒渲染 → 计数时内层未挂载；AC-212 断言计数仍为 10，且**既有 e2e 文件一个字节都不改** |
| **组件超 400 行**——`ProjectDetailPage.tsx` 已 379 行 | 基线管理内容**外提**到 `ProjectBaselineManagementTab.tsx`；主文件只做减法（§8.2） |
| **降级时模板残留撞 3819**——旧 CHECK 不认 `'process_baseline'` | `downgrade` 里**先删模板行再重建旧 CHECK**（§4.5）；迁移往返要**两库**都跑 |
| **标签与保留策略的欠账被当成漏做** | AC-210 / AC-211 **显式断言「不存在」**，spec §13 登记去向（§2.2 / §3.2 / §3.3） |
| **上游 schema 改动越界** | 只有 §11 声明的两处；`git diff --stat` 实测并在 AC-214 断言 |
| **既有测试被改动** | 既有 1259 条**零期望值改动**；新增测试只能增；AC-214 断言 |

## 13. 后续期（明确不在本期）

| 期 | 内容 |
|---|---|
| — | **增量分析支持流程基线打标**（PRD 2.4.2 的流程基线「标签」）——需扩 04 的 `baseline_labels` CHECK + 改 05 的引擎目标类型（本期 §3.2 的欠账） |
| — | **流程基线快照保留策略 + 被引用即保护 + 清理候选 + 告警 + 删除留痕**——需新增项目列 `process_snapshot_max_count`（本期 §3.3 的欠账） |
| — | 流程基线的**分点审核**（逐场景批准 / 驳回）——需新的审核明细表 |
| — | 流程基线快照被**测试点 / 用例 / 执行报告**引用后，纳入「被引用即保护」 |
| — | 流程基线的**变更历史**与**关联增量分析记录**展示（PRD 2.4.2「基线详情页」） |
| — | 流程基线的**标签筛选**（PRD 2.4.2「基线检索」的标签维度） |
| — | 流程基线的 **Excel 导入导出** |
| — | 场景 ↔ **测试点 / 测试用例**的关联（PRD 未要求，需改 08 的表结构） |
| — | 场景的**版本筛选**（列表按快照版本过滤） |
| — | Skill 模式（PRD 2.5）——延续 06 / 07 / 08 / 09，只做直连 |

---

## 附录：与 PRD 原文的逐条对照表

> 对照范围：PRD 2.4.2「流程基线」（`:442-445`）与「通用能力」（`:447-464`），
> 以及该节的「验收标准」（`:466-474`）中与流程基线相关的条目。

### A. 「流程基线」小节（`:442-445`）

| PRD 原文 | 本期对应 | 做 / 不做 | 原因 |
|---|---|---|---|
| 存放完整业务场景操作步骤 | `process_baselines` + `process_baseline_steps`（§4.1 / §4.2） | ✅ 做 | 本期主体 |
| 场景名称 | `process_baselines.name` | ✅ 做 | |
| 前置条件 | `process_baselines.precondition` | ✅ 做 | |
| 操作步骤列表 | `process_baseline_steps`（整体覆盖、序号服务端重排） | ✅ 做 | 照抄 08 的 `test_case_steps` |
| 预期结果 | `process_baseline_steps.expected` | ✅ 做 | 与 `action` 同在步骤表，每步一行 |
| 关联功能基线 | `process_baseline_links`（M:N、无 FK、名称快照） | ✅ 做 | §3.4 |
| **标签** | — | ❌ **不做** | 标签语义依赖增量分析打标，增量分析只认功能基线。**AC-210 显式断言「不存在流程基线标签」**，欠账见 §13 |
| **版本号** | `process_baselines.version_no`（场景修订次数）+ `process_baseline_revisions.version_no`（快照 `v1.{n}`） | ✅ 做 | PRD 同时出现在「流程基线」字段清单与「通用能力·版本快照」里，**是两个东西**，分别落位（§2.3 第 8 条） |
| 状态 | `process_baselines.status`（`active` / `archived`） | ✅ 做 | |
| 来源：文档反推 / 手工添加 | `source_type`（`document_derived` / `manual`）+ 反推引擎 + 采纳接口 | ✅ 做 | §5.1 / §5.4 |

### B. 「通用能力」小节（`:447-464`）

| PRD 原文 | 本期对应 | 做 / 不做 | 原因 |
|---|---|---|---|
| 版本快照：每次审核通过生成不可变快照（v1.0、v1.1…） | `process_baseline_revisions`（通过时转正 `structure_json` + 分配 `version_no`） | ✅ 做 | §5.5 |
| 「覆盖三级结构」 | **覆盖「场景集合」**（场景 + 步骤 + 关联） | ⚠️ **语义替换** | 三级结构是功能基线的形态；流程基线是平铺场景列表。**继承「快照」的语义，替换「载体」**（§3.1） |
| 标签关联具体快照 | — | ❌ **不做** | 本期无标签 |
| 快照保留策略 `baseline_snapshot_max_count`（项目级） | — | ❌ **不做** | 项目级单列会让两套基线**混算**；独立要新增项目列（整套功能）。**AC-211 断言「`projects` 表无新增列」** |
| 被引用即保护 | — | ❌ **不做** | 流程基线快照当前**零下游引用**，保护对象是空集（§3.3） |
| 清理候选需人工确认 | — | ❌ **不做** | 依赖保留策略（被砍的第一环） |
| 告警 | — | ❌ **不做** | 同上 |
| 删除留痕 | — | ❌ **不做** | 同上 |
| 审核流程：草稿 → 提交审核 → 项目管理员审核通过/驳回 | `POST /reviews/submit` / `approve` / `reject` | ✅ 做 | §5.5。**「草稿」态由场景本身承担**（未提交的场景就是草稿），不额外建状态列 |
| 基线检索：按模块、来源类型、标签、关键词、版本筛选 | 关键词 / 来源类型 / 状态 三个筛选 | ⚠️ **部分做** | 模块与标签维度对流程基线**不适用**（无层级、无标签）；版本维度在快照列表里（§2.2） |
| 基线详情页展示变更历史与关联增量分析记录 | — | ❌ **不做** | 本期无变更历史表；`source_analysis_id` 列已预留但恒为 NULL（§13） |
| 基线反推：从历史文档按「章节 → 模块/功能/功能点」映射生成草案 | 逐章节 → **场景候选**，支持直连模式 | ✅ 做（**映射目标不同**） | 映射是「章节 → 场景」；PRD 的「模块/功能/功能点」是功能基线的形态。§5.4 |

### C. 2.4.2 的「验收标准」（`:466-474`）与流程基线的相关性

| PRD 原文 | 本期对应 | 结论 |
|---|---|---|
| 三种方式均可产出模块，按排序展示 | — | **不适用**（「模块」是功能基线的概念；流程基线是场景平铺列表，无排序层级） |
| 模块下有功能时删除被阻止并展示迁移/删功能入口 | — | **不适用**（功能基线的删除策略，本期不改 04） |
| 批量迁移后归属正确、追溯保留、审计可查 | — | **不适用**（同上） |
| 文档推导的功能/功能点必填追溯信息；手工添加无需追溯 | 流程基线场景**同构**：文档推导必填追溯三元组、手工不要求 | ✅ 做（§5.1 / AC-201） |
| 功能与功能点均可打标，默认仅展示功能级 | — | **不适用 / 不做**（标签本期不做） |
| 清除标签后默认不再展示，下游不参考，审计可查 | — | **不适用 / 不做**（同上） |
| 快照默认永久保留 | 流程基线快照**本期也永久保留** | ✅ 做（**实现口径不同**：04 是「默认不启用保留策略即永久保留」，本期是「根本没有保留策略」） |
| 开启 N 后超限快照进入候选而非自动删除 | — | ❌ **不做**（§3.3） |
| 被引用快照禁止删除仅告警 | — | ❌ **不做**（§3.3） |
| 删除与开关变更可审计 | — | ❌ **不做**（§3.3） |
