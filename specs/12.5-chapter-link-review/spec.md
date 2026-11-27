# 12.5 · 章节引用图 UX 补丁 · 规格

> 对齐需求：用户 2026-11-26 实测反馈 12 期的「章节引用图」抽屉，
> 提了 6 个痛点。核心是**缺人工评审闭环**——AI 分析出来的边直接落库生效，
> 用户没有机会逐条判断对错。
> 上游依赖：12-chapter-link-ai（`document_chapter_links` 表、`source` 三值、
> `POST /links/analyze`、`DELETE /links/{id}`、前端 `ChapterLinkDrawer.tsx`）。
> 本期口径（用户 2026-11-26 拍板）：
> - **复用 `document_chapter_links` 表，不新建表**（延续 12 期红线）；
> - AI 分析产出的边**先进入「待评审」区**，人工勾选确认（可批量采纳）后才生效；
> - 错的直接删除；
> - **前端删除「按规则重抽」入口**（后端 `extract_links` 代码保留不动）；
> - 分析期间**锁住整个抽屉**的其他交互。
> 本文是待 review 的规格，未写任何业务代码。评审通过后才拆任务落地。

## 0. 一句话结论（先看这个）

| 问题 | 结论 |
|---|---|
| 本期做什么 | 给「章节引用图」补**人工评审闭环**，并修 5 个 UX 缺陷（状态提示语 / 分析锁屏 / 删重抽按钮 / 表单引导 / 详情弹窗） |
| 数据落哪 | **复用 `document_chapter_links`**，**新增 `status` 列**（`pending` / `approved` 两个值），**不动 `source`** |
| 为什么不用 `source` 表达待评审 | `source` 是**来源**（谁产生的），`status` 是**生命周期**（人认可了没）。两者正交，见 [plan.md §2](./plan.md) |
| 待评审边存在哪 | **存在同一张表**，`status='pending'`。不新建表，不加第二套存储 |
| 待评审边「生效」的定义 | **只影响 05 期第二遍的图传播**（`second_pass.py` 读引用图算 `possible_impact`）。传播只读 `status='approved'` 的边 |
| AI 分析行为变化 | AI 分析**只写 `status='pending'` 的边**（不再直接落成生效边）。已 `approved` 的边**保留不动** |
| 采纳动作 | `POST .../links/{id}/approve`（单条）+ `POST .../links/approve-batch`（批量） |
| 驳回动作 | **不新建「驳回」接口**：待评审区直接「删除」即可（用户原话「错的直接删除」） |
| 前端 | 抽屉分「待评审区」/「已生效区」两块；顶部提示语**状态驱动**；分析期间锁抽屉；删「按规则重抽」按钮；补表单引导文案；操作列加「详情」按钮 |

---

## 1. 背景与问题

12 期把「章节引用图」升级为「AI 一键分析 + 人工可改可删可补」，但用户实测后指出
**6 个痛点**，其中第 1 个是结构性的：

### 痛点 1（最重要）：缺少人工评审闭环

AI 分析出来的边**直接落库即生效**。用户提出的诉求是：

> 「AI 分析完后，边先进入待评审区，由我勾选确认（或批量采纳）后，才真正生效。
> 错的直接删除。」

**「真正生效」在系统里的确切含义**（必须定义清楚，否则「生效」是空话）：
在本仓库里，章节引用边**只有一个下游消费者**——05 期第二遍的
`app/incremental/second_pass.py::build_point_index` 读引用图做「图传播」，
沿 `references` / `depends_on` 边跳一跳，把源章节的 `changed` / `affected`
结论传播成 `possible_impact` 冲突。

所以：**边「生效」= 能参与图传播**。待评审的边必须被传播逻辑排除，
否则「待评审」只是前端的一个标签，语义上等于没做。

### 痛点 2：状态提示语错乱

抽屉顶部蓝色提示语「系统已通过 AI 自动识别章节间的引用关系……」**一直静态显示**，
哪怕这个版本从来没跑过 AI 分析。用户诉求：

> 「改为状态驱动：空数据时提示『点击 AI 分析』，分析完成后才显示该文案。」

### 痛点 3：AI 分析期间未锁屏

AI 分析转圈时，底下的「删除」「手工补链」和各类下拉框**还能点**。
用户诉求：大模型调用期间禁用整个抽屉的其他交互，防止并发冲突。

### 痛点 4：移出废弃功能

前端「按规则重抽」按钮要**彻底删掉**（纯正则命中率太低，已被大模型碾压）。
**后端 `extract_links` 代码保留不动**，只去前端入口。

> **注意**：12 期红线之一是「`extract_links` / `_collect` / 正则一个字节不动」。
> 本期只删前端入口，后端接口（`POST /links/extract`）与 05 期的
> `_ensure_rule_links` 自动调用**都不动**——后者是增量分析二遍的内部依赖，
> 删了会打破 05 期既有行为。

### 痛点 5：表单引导文案缺失

手工补链处，源章节 / 类型 / 目标章节的 placeholder 与说明必须清晰
（比如给类型加上「引用 / 依赖 / 相关」的说明）。

> **现状盘点**（12 期 T135 已做了一部分）：源章节 placeholder 已是「请选择源章节」，
> 目标章节已是「请选择目标章节」，类型下拉**已经**带「引用 —— A 章节提到…」
> 说明，实体名 placeholder 已有格式示例。
> **本期要补的是「标签级说明」**：`Form.Item` 的 `label` 只有「源章节」「类型」
> 「目标章节」三个裸词，没有告诉用户这个字段在**引用图的语义里**是什么。
> 本期给三个字段各加一行 `extra` 说明文字，并给「类型」下拉补 `optionRender`
> 的两行式展示（名称 + 说明分行，避免长句挤在一行看不清）。

### 痛点 6：增加「详情」按钮（可解释性）

用户诉求：

> 「AI 分析的结果必须支持查看细节。在表格操作列加一个『详情』按钮，
> 点击后弹窗展示大模型给出的分析理由（rationale）和置信度（confidence）。
> 让用户能根据理由判断是否采纳。」

**关键缺口**：12 期的 AI 边**只落了 `confidence`，没落 `rationale`**——
`link_analyze.py` 解析出了 `rationale`（截断 500 字），但 `_persist_ai_links`
**没有把它写进数据库**，表里也没有这一列。所以「详情」要展示 rationale，
**必须本期新增一列**。

---

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| **待评审状态** | `document_chapter_links` 新增 `status` 列（`pending` / `approved`），默认 `approved` |
| **AI 分析落待评审** | `POST /links/analyze` 产出的边 `status='pending'`，**不再直接生效** |
| **单条采纳** | `POST .../links/{link_id}/approve` → 200，边 `status='approved'` |
| **批量采纳** | `POST .../links/approve-batch`（body: `link_ids: [int]`）→ 200，返回采纳条数 |
| **列表带状态** | `GET /links` 返回的每条边带 `status` 与 `rationale` |
| **图传播只读生效边** | `second_pass.py` 的 `build_point_index` 只收 `status='approved'` 的边 |
| **rationale 落库** | 新增 `rationale` 列（`String(1000)`，可空），AI 边的分析理由 |
| **状态驱动提示语** | 抽屉顶部提示语按「无数据 / 有待评审 / 有已生效」三态切换 |
| **分析期间锁抽屉** | 大模型调用期间禁用抽屉内所有其他交互 |
| **删「按规则重抽」按钮** | 前端移除该按钮；后端 `extract_links` 与接口**保留不动** |
| **表单引导文案** | 源章节 / 类型 / 目标章节各加 `extra` 说明；类型下拉两行式展示 |
| **「详情」按钮** | 表格操作列加「详情」→ 弹窗展示 rationale + confidence + 两端章节 |
| **审计** | 采纳（单条 / 批量）写审计；分析落待评审沿用既有 `document.chapter_link.analyze` |

### 2.2 本期不做（红线，违反即返工）

| 不做 | 为什么 |
|---|---|
| **不新建表** | 延续 12 期红线。待评审边存在同一张表，靠 `status` 区分 |
| **不用 `source` 表达「待评审」** | `source` 语义是「谁产生的」（rule / manual / ai），与「人认可了没」正交。详见 [plan.md §2](./plan.md) |
| **不删后端 `extract_links` 与 `POST /links/extract`** | 用户只要求删前端入口；后端还有 05 期 `_ensure_rule_links` 在用，删了会打破 05 期既有行为 |
| **不改 05 期的 `extract_links` / `_collect` / 正则** | 12 期红线延续 |
| **不改 05 期第二遍的判定逻辑与错误码** | 只在**读引用图**的查询上加一个 `status='approved'` 过滤条件，不动算法 |
| **不做「驳回」状态** | 用户原话「错的直接删除」。待评审区删除即可，不需要 `rejected` 态 |
| **不新建「候选边」表 / 不做两段式存储** | 12 期 Backlog 里的「候选待确认两段式」当时指的是**独立表**，本期用 `status` 列原地实现，**不再拆表** |
| **不实现人工边的「待评审」** | 只有 AI 产出的边需要评审。人工边（`manual`）默认 `approved`，规则边（`rule`）默认 `approved` |
| **不做批量删除** | 用户只提了批量采纳 |
| **不引入新前端依赖** | `web/package.json` 不动 |
| **不改既有测试的期望值** | 既有 1533 条 pytest + 70 条 e2e 一条不删、不改断言 |
| **任何测试不允许产生真实 socket** | 沿用既有约定 |

### 2.3 与上游的兼容约束

1. **上游 schema 改动仅两处**：`document_chapter_links` 加 `status` 列 + `rationale` 列
   （同一张表的两列，都带 CHECK）。`app/llm/mock.py` **不动**（既有六个分支行为不变）。
2. **既有边的默认状态是 `approved`**：迁移给存量行回填 `'approved'`，
   否则 12 期已经落库的 AI 边会突然变成「待评审」，等于**倒退**。
3. **零真实 socket**：本期不引入任何网络客户端。AI 分析仍只调注入的 `LLMProvider`。
4. **05 期第二遍的 `chapter_link_count` 统计口径**：`_ensure_rule_links` 统计的是
   `source='rule'` 的行数，**不受本期影响**（规则边默认 `approved` 且数量口径不变）。

---

## 3. 业务语义裁决

### 3.1 「待评审」用 `status` 列，不用 `source`

**裁决：`status` 新列。**

`source` 与「待评审」在语义上**正交**：

| 维度 | 回答的问题 | 取值 |
|---|---|---|
| `source` | 这条边**是谁产生的**？ | `rule`（正则）/ `manual`（人工）/ `ai`（大模型） |
| `status` | 这条边**人认可了没**？ | `pending`（待评审）/ `approved`（已生效） |

如果复用 `source`（比如加一个 `'ai_pending'`），会立刻炸掉三处：

1. **`source` 的 CHECK 是固定枚举**，加值要迁移（本来就要迁移，成本一样）；
2. **`_persist_ai_links` 的幂等逻辑**是「删 `(version_id, source='ai')` 再插」——
   复用 `source` 就得改成「删 `source='ai_pending'`」，于是**重新分析会吃掉已采纳的边**，
   用户刚点完采纳，一刷新发现边不见了；
3. **下游过滤**要按「所有 AI 边」和「已生效 AI 边」两套条件分别写，
   而 `status` 一列就够：`status='approved'`。

更根本的：`source='manual'` 的边是**人工补的**，天然已生效；
`source='rule'` 的边是**正则抽的**，天然已生效；
只有 `source='ai'` 的边需要人审。**「要不要审」由来源决定，「审没审」由状态记录**——
所以状态必须是独立的维度。

> **`rejected` 状态为什么不做**：用户说「错的直接删除」。删掉就是删掉，
> 留一条 `rejected` 的行反而要让用户分辨「这俩都是不能用的，但一个是我删的一个是我驳回的」。
> 删除会写审计，历史可追。

### 3.2 「生效」的定义

**边生效 = 参与 05 期第二遍的图传播**。

`app/incremental/second_pass.py::build_point_index` 里的这段查询：

```python
link_rows = session.execute(
    select(DocumentChapterLink.from_chapter_id, DocumentChapterLink.to_chapter_id)
    .where(
        DocumentChapterLink.version_id == analysis.document_version_id,
        DocumentChapterLink.link_type.in_(_PROPAGATION_LINK_TYPES),
        DocumentChapterLink.to_chapter_id.is_not(None),
    )
    ...
)
```

**本期加一个条件**：`DocumentChapterLink.status == "approved"`。

**只加这一个条件**，不动算法、不动错误码、不动 `_PROPAGATION_LINK_TYPES`。

> **注意 `mentions_entity` 边**：它本来就不参与传播（`_PROPAGATION_LINK_TYPES`
> 只有 `references` / `depends_on`），所以状态过滤对它天然无影响。

### 3.3 AI 分析的行为变化

12 期：AI 分析 → 边直接落库（等价于已生效）。
本期：AI 分析 → 边落库为 `status='pending'`（待评审）。

**已生效的 AI 边在重新分析后怎么办？**

裁决：**保留不动**。

12 期的幂等口径是「删 `(version_id, source='ai')` 再插」。本期改成：

```
1. 删除 (version_id, source='ai', status='pending') 的旧行   ← 只清「上一轮还没审的」
2. 插入新的 AI 边，status='pending'
3. 已 status='approved' 的 AI 边 **原样保留**
```

**为什么保留**：用户辛辛苦苦逐条采纳过的边，重新分析一次就被冲掉，
等于让人工评审白做。

**冲突怎么办**：唯一键 `uk_chlinks_to_chapter` 是
`(version_id, from_chapter_id, link_type, to_chapter_id)`，**不含 `status` 也不含 `source`**。
所以「已采纳的 AI 边」与「新分析出的同一条待评审边」会撞唯一键。

处理口径（与 12 期「人工边优先」同一哲学）：
- 新分析出的边，如果命中**任何已存在的同一条边**（不论来源、不论状态）→ **跳过不插**；
- 如果命中**人工边** → 跳过（12 期既有口径，本期不变）。

### 3.4 采纳语义

| 操作 | 前置 | 结果 |
|---|---|---|
| 单条采纳 | 边存在、属该版本、`status='pending'` | `status='approved'` |
| 批量采纳 | 同上，逐条校验 | 全部成功 → 逐条改状态；任一条不合法 → **整批 404/409，不部分成功** |
| 重复采纳 | 边已是 `approved` | **幂等**：返回 200，不报错 |

**为什么重复采纳幂等而不是报错**：07 期的测试点评审是「已评审过就 409」
（`TEST_POINT_REVIEW_STATE_INVALID`）。但那条规则的前提是**评审是有决策语义的动作**
（通过 / 驳回，驳回后状态变了，重复「通过」语义上确实矛盾）。

本期采纳**没有驳回态**，唯一状态迁移是 `pending → approved`。
重复采纳是「再确认一次」，语义上完全成立 → **幂等返回 200** 更符合直觉，
也让前端「批量采纳」可以放心地重复点。

> **批量采纳的原子性**：整批要么全成、要么全不成。
> 部分成功会让用户不知道哪些进了、哪些没进。
> 实现上：先校验全部 id，全部通过才统一改状态 + 统一写一条审计。

### 3.5 「待评审」的默认状态与来源无关

| 来源 | 默认 `status` | 理由 |
|---|---|---|
| `ai` | **`pending`** | AI 产出，必须人审 |
| `manual` | `approved` | 人工补的，人自己写的 |
| `rule` | `approved` | 正则抽的，不参与 AI 评审流程 |

### 3.6 删除语义不变

12 期的 `DELETE /links/{id}` 三种来源都可删，本期**不变**。
只是删除 `status='pending'` 的边时，前端提示语要区分：

| 删谁 | 前端提示 |
|---|---|
| `status='pending'`（待评审的 AI 边） | 「确认删除这条待评审的引用关系？」 |
| `status='approved'` | 沿用 12 期口径（`rule` 边额外提示「重抽会重新生成」） |

> **「按规则重抽」按钮已删**，所以「重抽会重新生成」的提示语**在前端已无对应入口**——
> 但后端 `POST /links/extract` 还在（05 期 `_ensure_rule_links` 在用）。
> 保留这条提示语是为了口径完整：万一用户通过别的途径触发重抽，
> 提示语仍然正确。**文案不改**（12 期 e2e 断言了「按规则重抽」「重新生成」两个词）。

### 3.7 「没有引用关系」不是错误（延续 12 期）

模型返回 `{"references": []}` → 写 0 行，`analyzed_count=0`，不抛异常。

---

## 4. 数据模型（复用 `document_chapter_links`，迁移 `0028`）

### 4.1 新增两列

```
status    VARCHAR(16) NOT NULL DEFAULT 'approved'   -- pending / approved
rationale VARCHAR(1000) NULL                        -- AI 分析理由
```

**为什么 `status` 放在同一张表而不是复用 `source`**：见 [§3.1](#31-待评审用-status-列不用source)。

**为什么 `status` 的默认值是 `'approved'`**：
存量行（12 期已落库的 AI 边、05 期的规则边、05 期的人工边）迁移时全部回填
`'approved'`——它们**都已经是生效边**，不该因为加了个列就倒退成待评审。
手工补链（`create_link`）也写 `'approved'`。

**为什么 `rationale` 长度取 1000**：与 `incremental_conclusions.rationale` /
`test_points` 的 `rationale` 对齐（都是 `String(1000)`），
前端弹窗展示时不用二次截断。引擎侧已把 rationale 截断到 500 字，落库不会超列宽。

### 4.2 CHECK 约束

```
ck_chlinks_status   CHECK (status IN ('pending','approved'))
```

**为什么不做 `rejected`**：见 [§3.1](#31-待评审用-status-列不用source)。

### 4.3 ORM 侧同步

`app/models/chapter_link.py`：

- 新增 `CHAPTER_LINK_STATUSES = ("pending", "approved")`；
- `ck_chlinks_status` CHECK；
- `status` 列（`String(16)`, `nullable=False`, `server_default=text("'approved'")`）；
- `rationale` 列（`String(1000)`, `nullable=True`）。

### 4.4 迁移 `0028`

`revision="0028"`、`down_revision="0027"`。

**upgrade 顺序**：
1. `op.add_column("document_chapter_links", sa.Column("status", sa.String(16), nullable=True, server_default=text("'approved'")))`；
2. `op.add_column("document_chapter_links", sa.Column("rationale", sa.String(1000), nullable=True))`；
3. `op.create_check_constraint("ck_chlinks_status", "document_chapter_links", "status IN ('pending','approved')")`；
4. `op.alter_column("document_chapter_links", "status", nullable=False, server_default=text("'approved'"))`
   ——把可空列变成非空（先加可空、回填、再收紧，三步走，避免存量行 NULL）。

**downgrade 顺序**（严格反序）：
1. 先 `DELETE FROM document_chapter_links WHERE status = 'pending'`
   ——**必须先删**，否则重建旧表结构时非空约束与残留数据会打架；
2. `op.drop_constraint("ck_chlinks_status", ...)`；
3. `op.drop_column("rationale")`；
4. `op.drop_column("status")`。

> **为什么不用 `op.alter_column(..., nullable=False)` 直接收紧**：
> MySQL 上把可空列改成非空时，若表里有 NULL 行会报错（1138）。
> 所以**先加列（带 server_default）**——server_default 会把存量行填成 `'approved'`，
> 此时列里已经没有 NULL，再收紧约束是安全的。

---

## 5. 业务语义

### 5.1 AI 分析流程（改）

```
POST .../links/analyze
  1. ensure_writable_admin（404 → 409 → 403 固定顺序）
  2. _load_version（文档/版本不存在 → 404）
  3. 取模板：task_type='chapter_link_analyze' + status='active'（没有 → 404 TEMPLATE_NOT_FOUND）
  4. documents_service.list_chapters(...) 取章节树（含 content）
  5. 调引擎 analyze(...)（纯函数，无 session）
  6. 落库：
     a. 删 (version_id, source='ai', status='pending') 旧行
     b. 插新行，status='pending'，rationale=模型给的理由
     c. 跳过命中「已存在的同一条边」的（不论来源/状态）→ 不撞唯一键
  7. write_audit("document.chapter_link.analyze")
  8. 写 llm_run_logs 留痕（task_type='chapter_link_analyze'）
  9. commit
```

### 5.2 采纳流程

```
POST .../links/{link_id}/approve
  1. ensure_writable_admin
  2. _load_version
  3. 查边：id == link_id AND version_id == version_id
     → 不存在 → 404 CHAPTER_LINK_NOT_FOUND
  4. status 已是 'approved' → 直接返回 200（幂等）
  5. status='pending' → 改 'approved' + flush
  6. write_audit("document.chapter_link.approve")
  7. commit

POST .../links/approve-batch   body: {"link_ids": [1, 2, 3]}
  1. ensure_writable_admin
  2. _load_version
  3. 校验：全部 id 都要属于该版本 → 否则 404（整批不成）
  4. 逐条改 status='approved'（已是 approved 的跳过）
  5. write_audit("document.chapter_link.approve")（一条审计，after_data 带 id 列表与条数）
  6. commit → {"approved_count": 3}
```

### 5.3 权限矩阵

| 操作 | 项目管理员 | 普通成员 | 访客 | 系统管理员 |
|---|---|---|---|---|
| 查看引用图（GET /links） | ✅ | ✅ | ✅ | ✅ |
| 手工补链（POST /links） | ✅ | ❌ | ❌ | ✅ |
| AI 分析（POST /links/analyze） | ✅ | ❌ | ❌ | ✅ |
| 采纳（单条 / 批量） | ✅ | ❌ | ❌ | ✅ |
| 删除边（DELETE /links/{id}） | ✅ | ❌ | ❌ | ✅ |

> 权限口径与 12 期一致：写操作统一用 `ensure_writable_admin`
> → 非成员与角色不符**都是** 403 `NOT_PROJECT_ADMIN`（区分会泄露项目是否存在）。

### 5.4 审计

| 操作 | action | target_type |
|---|---|---|
| AI 分析 | `document.chapter_link.analyze` | `document_chapter_link` |
| 删除边 | `document.chapter_link.delete` | `document_chapter_link` |
| **采纳（单条 / 批量共用）** | `document.chapter_link.approve` | `document_chapter_link` |

> 单条与批量**共用一个 action**：审计登记表按 action 逐个跑场景，
> 拆两个 action 要多写一个场景函数。语义上「采纳引用边」是同一件事。

---

## 6. 接口

### 6.1 `GET /links`（响应体扩字段，不改路径）

每条边新增两个字段：

```json
{
  "id": 12,
  "from_chapter_title": "2.1 登录流程",
  "to_chapter_title": "3 支付回调",
  "link_type": "references",
  "confidence": 0.85,
  "source": "ai",
  "status": "pending",
  "rationale": "2.1 节提到「回调逻辑见第 3 章」……",
  "created_at": "2026-11-26T10:00:00"
}
```

**`status` 与 `rationale` 都不返回 null 的情况**：
`status` 恒非空；`rationale` 对 `source='ai'` 的边恒非空（引擎给了理由），
对其它来源为 null。

### 6.2 `POST /links/{link_id}/approve`（新增）

响应 `200 ChapterLinkOut`（采纳后的那条边）。

### 6.3 `POST /links/approve-batch`（新增）

请求：

```json
{ "link_ids": [12, 13, 14] }
```

响应 `200`：

```json
{ "approved_count": 3 }
```

### 6.4 错误码（**零新增**）

**本期不新增任何错误码**，全部复用既有的：

| 场景 | HTTP | code | 来源 |
|---|---|---|---|
| 边不存在 / 不属于该版本（含批量里有不存在的 id） | 404 | `CHAPTER_LINK_NOT_FOUND` | 12 期已有 |
| 非项目管理员 | 403 | `NOT_PROJECT_ADMIN` | 既有 |
| 项目已归档 | 409 | `PROJECT_ARCHIVED` | 既有 |
| 项目不存在 | 404 | `PROJECT_NOT_FOUND` | 既有 |

**为什么不新增「已评审过」的错误码**：本期的采纳是**幂等**的
（见 [§3.4](#34-采纳语义)）——已 `approved` 的边再采纳一次返回 200。
07 期的测试点评审是「已评审过就 409」，但那条规则的前提是
**评审是有决策语义的动作**（通过 / 驳回，驳回后状态变了，
重复「通过」语义上确实矛盾）。

本期采纳**没有驳回态**，唯一的状态迁移是 `pending → approved`，
重复采纳就是「再确认一次」，语义上完全成立。

**为什么不为了「将来加驳回」而预留错误码**：本项目的错误码要在
`web/src/api/client.ts` 配中文文案，定义了却永远不抛的错误码
就是死代码 + 白占一个文案位。**需要时再加**。

**批量的原子性**：批量采纳时只要有**一个** id 不属于该版本，
**整批失败** → 404 `CHAPTER_LINK_NOT_FOUND`（不是逐条跳过）。
「部分成功」会让用户不知道哪些进了、哪些没进。

### 6.5 前端 API 客户端

```ts
analyzeChapterLinks(...)      // 已有
approveChapterLink(...)        // 新增：单条采纳
approveChapterLinksBatch(...)  // 新增：批量采纳
deleteChapterLink(...)         // 已有
```

---

## 7. 前端

### 7.1 抽屉布局（三区）

```
┌─ 抽屉：章节引用图 ────────────────────────── [✨ AI 一键分析引用] ─┐
│  ⚠ 状态提示语（Alert，**状态驱动**）                              │
│  ⟳ 分析中提示（仅 analyzing 时）                                  │
│                                                                  │
│  【待评审区】（仅 status='pending' 的边，>0 才显示）               │
│   表格：源章节 / 类型 / 目标 / 置信度 / 来源 / 操作(详情|采纳|删除) │
│   工具条：全选复选框 + 「批量采纳（N）」按钮 + 「清空」           │
│                                                                  │
│  【已生效区】（status='approved' 的边）                          │
│   表格：源章节 / 类型 / 目标 / 置信度 / 来源 / 操作(详情|删除)     │
│                                                                  │
│  【补一条引用关系】（表单）                                       │
└──────────────────────────────────────────────────────────────────┘
```

### 7.2 状态驱动的提示语（痛点 2）

| 状态 | 提示语文案 | Alert 类型 |
|---|---|---|
| 该版本**一条边都没有** | 「当前版本还没有引用关系。点击右上角【✨ AI 一键分析引用】自动识别，也可手动补充。」 | `info` |
| **有待评审**的边（N > 0） | 「AI 已识别出 N 条引用关系，**待你确认后生效**。确认前不会参与增量分析的传播计算。」 | `warning` |
| **无待评审**且有已生效边 | 「系统已通过 AI 自动识别章节间的引用关系，您可以修改或删除错误结果，也可以手动补充。」 | `info` |
| 分析**进行中** | 「正在调用模型分析章节引用关系，可能需要 1–2 分钟…」 | 独立的 `Typography.Text`（12 期已有） |

> **12 期的原提示语不能删**——它是「无待评审 + 有已生效边」这一态的文案，
> e2e 断言的「系统已通过 AI 自动识别章节间的引用关系」仍然有效。

### 7.3 分析期间锁抽屉（痛点 3）

用 antd v6 的 `ConfigProvider componentDisabled`：

```tsx
<ConfigProvider componentDisabled={analyzing}>
  ...抽屉内容...
</ConfigProvider>
```

`componentDisabled` 会让**所有** antd 组件（Button / Select / Radio / Input /
Table 内的按钮 / Popconfirm 触发器）自动禁用。

**但 AI 分析按钮自己不能被禁**（它自己有 `loading`），所以 AI 按钮要放在
`ConfigProvider` **外面**（即 `Drawer` 的 `extra` 插槽），或者显式
`disabled={false}` 覆盖。

> **已实测**：antd v6 `ConfigProvider` 的 `componentDisabled` 覆盖
> Button / Select / Radio / Input / Table / Popconfirm 等 33 个组件
> （见 `web/node_modules/antd/es/config-provider/DisabledContext.js`）。

**额外兜底**：即使 `componentDisabled` 漏了某个组件，
「补链」按钮也要显式 `disabled={analyzing}`——**双保险**。

### 7.4 删「按规则重抽」按钮（痛点 4）

- 删除 `ChapterLinkDrawer.tsx` 里的「按规则重抽」`Button`；
- 删除 `extracting` state 与 `reExtract()` 函数；
- 删除 `extractChapterLinks` 的 import；
- **保留** `web/src/api/index.ts` 里的 `extractChapterLinks` 函数
  （后端接口还在，删前端函数不影响后端，留着以后要用）。
  > **决策**：前端 API 客户端函数**保留**。理由：① 后端接口确实还在；
  > ② 删了它将来要恢复得重新写；③ 它是纯 API 封装，不构成「用户可见的入口」。
  > 用户诉求是「把前端那个按钮彻底删掉」——按钮删了就算达标。

### 7.5 表单引导文案（痛点 5）

三个字段各加一行 `Form.Item` 的 `extra` 说明：

| 字段 | label | extra 说明 |
|---|---|---|
| 源章节 | 源章节 | 「从这里出发的章节，例如「2.1 登录流程」」 |
| 类型 | 类型 | 「三选一：引用（A 提到 B）/ 依赖（A 的实现依赖 B）/ 相关（A 提到某个功能点或术语）」 |
| 目标章节 | 目标章节 | 「被引用的章节，例如「3 支付回调」；不能选自己」 |

**类型下拉两行式展示**：用 `optionRender` 把选项渲染成
「引用」一行 + 说明一行（`description` 字段），比现在的
「引用 —— A 章节提到「见 B 章节」」挤在一行更易读。

```tsx
const LINK_TYPE_OPTIONS = [
  { value: 'references', label: '引用', description: 'A 章节提到「见 B 章节」' },
  { value: 'depends_on', label: '依赖', description: 'A 章节的实现依赖 B 章节' },
  { value: 'mentions_entity', label: '相关', description: 'A 章节提到某个功能点或术语' },
]
```

### 7.6 「详情」按钮（痛点 6）

- 表格操作列加「详情」按钮（`data-testid="chapter-link-detail-btn-{id}"`）；
- 点击 → `Modal` 弹窗，展示：
  - 源章节 → 目标章节（标题）
  - 关系类型（`linkTypeTag`）
  - 来源（`linkSourceTag`）
  - 状态（待评审 / 已生效）
  - **分析理由**（`rationale`，无则显示「无」）
  - **置信度**（`confidence`，无则显示「无」）
- 弹窗组件单独拆出（`ChapterLinkDetailModal.tsx`），避免抽屉文件超 400 行。

### 7.7 `data-testid` 命名

沿用「区域-动作-目标」，统一前缀 `chapter-link-`：

| testid | 说明 |
|---|---|
| `chapter-link-hint` | 状态驱动的提示语（**取代** 12 期的 `chapter-link-ai-hint`） |
| `chapter-link-analyzing-tip` | 分析中提示（12 期已有，不动） |
| `chapter-link-pending-section` | 待评审区容器 |
| `chapter-link-effective-section` | 已生效区容器 |
| `chapter-link-pending-select-all` | 待评审区全选复选框 |
| `chapter-link-pending-batch-approve-btn` | 批量采纳按钮 |
| `chapter-link-approve-btn-{id}` | 单条采纳按钮 |
| `chapter-link-detail-btn-{id}` | 详情按钮 |
| `chapter-link-detail-modal` | 详情弹窗 |
| `chapter-link-delete-btn-{id}` | 删除按钮（12 期已有，不动） |
| 既有 `chapter-link-*-select` / `-input` / `-btn` | 不动 |

> **12 期的 `chapter-link-ai-hint` 改名成 `chapter-link-hint`**：
> 它不再是「AI 专用提示」，而是「状态驱动提示」。
> 12 期的 e2e 断言了 `chapter-link-ai-hint` 的可见性 → **必须同步改 e2e**。
> **改的是 testid，不是文案**——文案「系统已通过 AI 自动识别章节间的引用关系」
> 在「已生效」这一态仍然出现，断言文本依然成立。

---

## 8. 验收标准

### 8.1 既有测试的主动更新清单（需用户裁决）

本项目红线（`specs/验证约定.md` §2 第 6 条）：
「严禁修改既有测试来强行通过……如果是老测试真的过期了，
**必须在回复中向用户显式说明原因，经用户同意后**才可修改测试期望值。」

本期**必须**改 3 处既有断言，逐条说明原因（**都不是为了让代码通过而改**，
而是本期 spec 明确改变了契约）：

| # | 位置 | 现状 | 为什么过期 | 改成 |
|---|---|---|---|---|
| 1 | `tests/incremental/test_chapter_link_migration.py::test_chapter_links_table_has_no_new_column` | 断言列集合**恰好**是 10 列（12 期「表结构零改动」的证明） | 本期**明确要加 2 列**（`status` / `rationale`），spec §4.1 已声明 | 断言列集合**恰好**是 12 列，且包含 `status` / `rationale` |
| 2 | `tests/incremental/test_chapter_link_migration.py::test_migration_head_is_0027`<br>`tests/process_baselines/test_migration.py::test_ac_197_migration_head_is_0027` | 断言 head == `0027` | 本期加迁移 `0028`，head 必然变 | 断言 head == `0028` |
| 3 | `tests/e2e/test_chapter_link_ai_ui.py` 里 `chapter-link-ai-hint` 的 testid 定位 | 用 `chapter-link-ai-hint` 定位提示语 | 本期提示语改为**状态驱动**（不再是「AI 专用」），testid 随之改名（spec §7.7） | testid 改 `chapter-link-hint`；**文案断言一个字不动**（「系统已通过 AI 自动识别章节间的引用关系」在「已生效」态仍然出现） |
| 4 | `tests/e2e/test_chapter_link_ai_ui.py` 的 `_open_link_drawer`<br>`tests/e2e/test_incremental_second_pass_ui.py::test_ac_86_chapter_link_ui` | 都用 `chapter-link-table` 定位表格 | 表格拆成「待评审」/「已生效」两张，`chapter-link-table` **不再存在** | 改定位**抽屉内容区** `.ant-drawer-body`；需要断言表格内容时按需取 `chapter-link-pending-table` / `chapter-link-effective-table` |
| 5 | `tests/e2e/test_chapter_link_ai_ui.py::test_ac_220` 的提示语文案断言 | 打开抽屉（**空数据**）后断言「系统已通过 AI 自动识别…」 | 提示语改为状态驱动后，空数据显示「当前版本还没有引用关系…」，原文案只在「无待评审 + 有已生效边」时出现 | **文案断言不改**，只改为先 `seed_chapter_links(..., status="approved")` 造一条已生效边再断言 |

> 第 3 ~ 5 条的**文案断言都不改**：12 期断言的是提示语**内容**，
> 本期只是让它变成「条件显示」——条件满足时内容完全一致。
> 改动的是「定位方式」与「前置造数」，不是「期望的文案」。
> 12 期的 e2e 另外还断言了「访客能看到提示语」——
> 本期访客在「无待评审 + 有已生效边」时**仍然能看到**这条提示语，断言依然成立。
>
> 第 4 条的第 2 个文件是 T143 实跑 e2e 时才发现的（计划里只提到 12 期那一个文件）：
> 05 期第二期的 `test_ac_86_chapter_link_ui` 也在用同一个 testid。

### AC-229 待评审状态落库

AI 分析后，边落库为 `status='pending'`，**不是**直接生效；
`source='ai'`、`confidence` 与 `rationale` 都有值。

### AC-230 采纳后生效

单条采纳 → `status='approved'`；
批量采纳 → 全部变 `approved'`，响应 `approved_count` 等于采纳条数。

### AC-231 待评审边不参与图传播

一条 `status='pending'` 的 `references` 边**不产生** `possible_impact` 冲突；
改成 `approved` 后**产生**。

### AC-232 重新分析不冲掉已采纳的边

分析 → 采纳 1 条 → 重新分析 → 该条**仍是 `approved`**；
上一轮**未采纳**的待评审边被替换为新一轮的结果。

### AC-233 状态驱动的提示语

- 无任何边 → 提示「点击右上角【✨ AI 一键分析引用】」（含「还没有引用关系」）；
- 有待评审 → 提示含「待你确认后生效」与待评审条数；
- 只有已生效边 → 提示含「系统已通过 AI 自动识别章节间的引用关系」。

### AC-234 分析期间锁抽屉

AI 分析进行中：删除按钮、补链按钮、类型下拉、源/目标章节下拉**全部 disabled**。

### AC-235 移除「按规则重抽」前端入口

抽屉里**没有**「按规则重抽」按钮；
后端 `POST /links/extract` **仍可用**（200）。

### AC-236 表单引导文案

「源章节」「类型」「目标章节」三个 `Form.Item` 都有 `extra` 说明文字；
类型下拉展开后每项**两行**（名称 + 说明）。

### AC-237 详情弹窗

点「详情」→ 弹窗展示 rationale 与 confidence；
`source='ai'` 的边能看到模型给的理由。

### AC-238 权限矩阵

非项目管理员（普通成员 / 访客）看不到采纳 / 批量采纳 / 详情按钮；
后端 `approve` / `approve-batch` 对非管理员返回 403 `NOT_PROJECT_ADMIN`；
归档项目返回 409 `PROJECT_ARCHIVED`。

### AC-239 零回归与红线

既有 1533 条 pytest + 70 条 e2e 全绿（**减去 §8.1 列出的 5 处主动更新**，
更新后的断言必须更强而不是更弱）；
`extract_links` / `_collect` / 正则一个字节不动；
`app/llm/mock.py` 既有六个分支行为不变；
后端 `POST /links/extract` 行为不变。

---

## 9. 非功能

- **幂等**：AI 分析重复调用，`status='pending'` 的行数不累加；已采纳的边不丢。
- **可追溯**：分析 / 采纳 / 删除都写审计；采纳带 `before_data`（旧 status）。
- **原子性**：批量采纳整批成或整批不成。
- **零真实 socket**：测试不产生任何网络请求（`MockProvider` + `httpx.MockTransport`）。
- **性能**：图传播的过滤条件是加一个等值判断，走 `idx_chlinks_version` 索引，无退化。

---

## 10. 依赖与影响

### 上游 schema 改动声明（本期仅一处表）

| 位置 | 改动 | 为什么 |
|---|---|---|
| `app/models/chapter_link.py` | 加 `status` 列 + `rationale` 列 + `ck_chlinks_status` | 承载待评审状态与分析理由 |
| `migrations/versions/0028_chapter_link_review_status.py` | 加两列 + CHECK + 回填 | 数据层迁移 |
| `app/incremental/second_pass.py` | 读引用图的查询加 `status='approved'` | 待评审边不参与传播（**只加一个条件**） |
| `app/incremental/links.py` | 分析落库改 `pending` + 写 rationale；新增采纳服务 | 业务逻辑 |
| `app/incremental/links_router.py` | 新增 2 个端点 | 接口 |
| `app/incremental/schemas.py` | `ChapterLinkOut` 扩 2 字段 + 新增 batch schema | 契约 |
| `app/common/errors.py` | **零新增** | 采纳幂等，复用既有错误码 |

**`app/llm/mock.py` 零改动**（12 期红线：「既有六个分支行为一个字节不变」）。

---

## 11. 风险与规避

| 风险 | 影响 | 规避 |
|---|---|---|
| 存量 AI 边迁移后变待评审 | 12 期的成果倒退 | 迁移用 `server_default='approved'` 回填存量；`create_link` 显式写 `'approved'` |
| 唯一键 `uk_chlinks_to_chapter` 撞车 | 分析报 500 | 新分析出的边命中任何已存在的同一条 → 跳过（与 12 期「人工边优先」同哲学） |
| 「待评审」只是前端标签 | 语义上等于没做 | 图传播查询必须加 `status='approved'`（AC-231 专门验证） |
| 重新分析冲掉已采纳的边 | 人工评审白做 | 只删 `status='pending'` 的旧行；AC-232 专门验证 |
| 批量采纳部分成功 | 用户不知道哪些进了 | 先全量校验再统一改状态 |
| `componentDisabled` 漏掉某个组件 | 分析期间仍能点 | AI 按钮放 `ConfigProvider` 外 + 补链按钮显式 `disabled={analyzing}` 双保险 |
| 12 期 e2e 断言的 testid 改名 | e2e 挂 | 同步改 e2e（`chapter-link-ai-hint` → `chapter-link-hint`），**文案断言不动** |
| 删「按规则重抽」按钮后 05 期 `_ensure_rule_links` 仍会抽规则边 | 用户困惑（怎么还有规则边的 AI 标签） | 规则边来源列显示「规则」，与 AI 边区分；12 期既有行为，不改 |
| 批量采纳 id 跨版本 | 越权采纳 | 校验 `version_id` 归属；跨版本 id → 404（整批不成） |

---

## 12. 后续期（明确不在本期）

| 能力 | 说明 |
|---|---|
| 引用图可视化（图而非表格） | 当前是表格展示，真正的「图」留待后续 |
| AI 产出实体边 | 需要先解决「实体名的规范与校验」问题 |
| 引用边置信度阈值筛选 | 前端暴露 `link_type` / `source` / `confidence` 过滤 |
| 「驳回」状态 | 本期用「删除」代替；若将来要保留被驳回的记录再加 `rejected` |
| 评审人 / 评审时间留痕 | 本期 `approve` 审计里有操作者，但没有 `reviewed_by` 列 |
| 批量删除 | 本期只做批量采纳 |
