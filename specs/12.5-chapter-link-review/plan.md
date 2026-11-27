# 12.5 · 章节引用图 UX 补丁 · 技术方案

> 配套 [spec.md](./spec.md)（AC-229 ~ AC-239）与 [tasks.md](./tasks.md)（T137 ~ T144）。
> 定位：**补丁任务**——在 12 期「章节引用图 AI 分析」之上补**人工评审闭环**，
> 并修 5 个 UX 缺陷。复用现有表与 LLM 基础设施，不重写。
>
> **本文重点回答用户点名的问题**：
> 「为了实现『待评审』状态，是在 `document_chapter_links` 表加 `status` 字段，
> 还是复用现有的 `source` 字段？并给出迁移方案。」
> → 答案在 [§2](#2-重点裁决待评审用-status-列还是复用-source-字段)。

## 1. 总体思路

```
ChapterLinkDrawer（前端抽屉）
      │  POST /links/analyze            POST /links/{id}/approve
      │  DELETE /links/{id}              POST /links/approve-batch
      ▼                                  ▼
links_router                     links_router
      │                                  │
      ▼                                  ▼
links.analyze_links              links.approve_link / approve_links
  （改动：落库 status='pending'）   （新增：status → 'approved'）
      │                                  │
      ▼                                  ▼
link_analyze.analyze（纯函数，不变）    write_audit("document.chapter_link.approve")
      │
      ▼
_persist_ai_links（改动：写 status + rationale）
```

五条关键设计：

1. **`status` 新列，`source` 不动** —— 来源与生命周期是两个正交维度（[§2](#2-重点裁决待评审用-status-列还是复用-source-字段)）。
2. **「生效」= 参与图传播** —— 唯一的下游消费者是 05 期第二遍的 `build_point_index`，
   只加一个 `status='approved'` 过滤条件（[§4](#4-下游图传播只读生效边)）。
3. **重新分析不冲掉已采纳的边** —— 只删 `status='pending'` 的旧行（[§5](#5-ai-分析的落库改动)）。
4. **采纳幂等 + 批量原子** —— 重复采纳返回 200；批量要么全成要么全不成（[§6](#6-采纳服务层)）。
5. **前端三区 + 状态驱动** —— 待评审区 / 已生效区 / 补链表单，
   提示语三态切换，分析期间 `ConfigProvider componentDisabled` 锁抽屉（[§8](#8-前端方案)）。

---

## 2. 【重点裁决】待评审用 `status` 列，还是复用 `source` 字段？

### 2.1 结论

**加 `status` 列。`source` 一个字节不改。**

新增两列（同一张表）：

| 列 | 类型 | 语义 |
|---|---|---|
| `status` | `VARCHAR(16) NOT NULL DEFAULT 'approved'` | `pending`（待评审）/ `approved`（已生效） |
| `rationale` | `VARCHAR(1000) NULL` | AI 给出的分析理由（详情弹窗要展示） |

### 2.2 为什么不能复用 `source`

`source` 与「待评审」在语义上**正交**：

| 维度 | 回答的问题 | 取值 |
|---|---|---|
| `source` | 这条边**是谁产生的**？ | `rule`（正则抽）/ `manual`（人工补）/ `ai`（大模型） |
| `status` | 这条边**人认可了没**？ | `pending`（待评审）/ `approved`（已生效） |

复用一个字段去表达两个维度，会立刻炸掉四处：

**① 幂等逻辑会吃掉已采纳的边。**

12 期的 AI 分析落库口径（`app/incremental/links.py::_persist_ai_links`）是：

```python
session.execute(
    delete(DocumentChapterLink).where(
        DocumentChapterLink.version_id == version_id,
        DocumentChapterLink.source == "ai",
    )
)
```

「先删 `(version_id, source='ai')` 再插」——这是幂等的来源。

如果用 `source='ai_pending'` 表达待评审，这条 delete 就变成
「删 `source='ai_pending'`」，于是：

```
分析 → 3 条待评审 → 用户采纳 1 条（source 改成 'ai'？）
分析 → 删 source='ai_pending' → 插 3 条新的
```

**用户刚点完采纳的那条边，在下一次分析后凭空消失。**
人工评审的成果被一次重跑清零——这比不做评审还糟。

**② 「谁产生的」这个信息会丢。**

用户采纳了一条 AI 边之后，这条边还是 **AI 产出的**（它的 `confidence` /
`rationale` 来自模型）。如果 `source` 被改写成 `'manual'`，
「这条边是 AI 认出来的」这个信息就没了——而这恰恰是**可解释性**的基础
（详情弹窗要告诉用户「模型为什么这么认为」）。

**③ 下游过滤要写两套条件。**

- 用 `source`：传播逻辑要写成
  `source IN ('rule','manual','ai_approved')`——每加一个来源就要改这个列表，
  而且每加一个新来源都必须记得把它加进「已生效」白名单，**漏一个就静默少传播一条边**。
- 用 `status`：传播逻辑只要 `status='approved'`，**来源是什么与它无关**。

**④ 唯一键已经不含 `source`，加不加都一样要迁移。**

`uk_chlinks_to_chapter` 是
`(version_id, from_chapter_id, link_type, to_chapter_id)`——
**既不含 `source` 也不含 `status`**。所以无论用哪种方案，迁移成本都是「改 CHECK / 加列」，
用 `source` 一点迁移成本都省不下来，却换来了①②③三个问题。

### 2.3 与「不新建表」红线不冲突

12 期的红线是「不新建 `document_chapter_references` 表」。
本期**同样不新建表**——待评审的边**存在同一张 `document_chapter_links`**，
靠 `status` 列区分。

12 期 Backlog 里写的「候选待确认两段式」指的是**独立表 + 独立存储**，
本期用**状态列原地实现**，**更轻**，也不违反红线。

### 2.4 三种来源的默认状态

| 来源 | 默认 `status` | 理由 |
|---|---|---|
| `ai` | **`pending`** | AI 产出，必须人审 |
| `manual` | `approved` | 人工补的，人自己写的 |
| `rule` | `approved` | 正则抽的，不进 AI 评审流程 |

**存量行的迁移回填值 = `'approved'`**：12 期已落库的 AI 边**已经是生效边**，
加个列不该让它们倒退成待评审。

### 2.5 为什么不加 `rejected` 状态

用户原话：「错的直接删除。」

加一个 `rejected` 态会让用户要分辨两种「都不能用」的状态：
「这条是我删的」 vs 「这条是我驳回的」——对用户没有价值，
却要多一套枚举、一个状态标签、一套前端展示逻辑。

删除会写审计（`document.chapter_link.delete`），历史可追。

---

## 3. 数据层与迁移方案

### 3.1 迁移 `0028`

`revision="0028"`、`down_revision="0027"`。

```python
revision: str = "0028"
down_revision: str | None = "0027"
```

**upgrade 的四步（顺序不能换）**：

```python
def upgrade() -> None:
    # ① 先加可空列，带 server_default —— server_default 会把存量行填成 'approved'
    op.add_column(
        "document_chapter_links",
        sa.Column("status", sa.String(16), nullable=True,
                  server_default=text("'approved'")),
    )
    # ② rationale 可空，直接加
    op.add_column(
        "document_chapter_links",
        sa.Column("rationale", sa.String(1000), nullable=True),
    )
    # ③ 再加 CHECK
    op.create_check_constraint(
        "ck_chlinks_status",
        "document_chapter_links",
        "status IN ('pending','approved')",
    )
    # ④ 最后收紧成非空（此时列里已无 NULL）
    op.alter_column(
        "document_chapter_links",
        "status",
        nullable=False,
        server_default=text("'approved'"),
    )
```

**为什么是「先加可空 → 收紧非空」而不是直接加非空**：

MySQL 上把列改成 `NOT NULL` 时，若表里有 NULL 行会直接报错（1138）。
所以顺序必须是：
1. 加可空列 + `server_default` → 存量行被填成 `'approved'`，列里已无 NULL；
2. 加 CHECK → 只有合法值能进；
3. `alter_column(nullable=False)` → 安全。

**downgrade 的三步（严格反序）**：

```python
def downgrade() -> None:
    # ① 必须先删残留的 pending 行——它们是本期独有的状态值
    op.execute(sa.text(
        "DELETE FROM document_chapter_links WHERE status = 'pending'"
    ))
    # ② 删 CHECK
    op.drop_constraint("ck_chlinks_status", "document_chapter_links", type_="check")
    # ③ 删两列
    op.drop_column("document_chapter_links", "rationale")
    op.drop_column("document_chapter_links", "status")
```

> **为什么 downgrade 要先删 pending 行**：
> 如果先删列、留着那些行，它们会变成 `status=NULL` 的「孤儿行」，
> 而且这些行是本期特有语义（待评审的 AI 边），
> 降级后用户已经没法区分它们。**先删干净再拆结构**——
> 与 `0026` / `0027` 的 downgrade 口径一致（都先删残留行再重建 CHECK）。

### 3.2 ORM 同步（`app/models/chapter_link.py`）

```python
CHAPTER_LINK_SOURCES = ("rule", "manual", "ai")          # 不变
CHAPTER_LINK_STATUSES = ("pending", "approved")          # 新增

# __table_args__ 新增
CheckConstraint(
    "status IN ('pending','approved')", name="ck_chlinks_status"
),

# 列
status: Mapped[str] = mapped_column(
    String(16), nullable=False, server_default=text("'approved'"),
    comment="pending=待评审（仅 AI 产出）；approved=已生效",
)
rationale: Mapped[str | None] = mapped_column(
    String(1000), nullable=True, comment="AI 分析理由（详情弹窗展示）"
)
```

**`source` 列、CHECK、索引、唯一键一个不动**。

### 3.3 迁移往返检查

```powershell
# 两库都跑
.\.venv\Scripts\alembic.exe upgrade head      # 0027 → 0028
.\.venv\Scripts\alembic.exe downgrade -1       # 0028 → 0027
.\.venv\Scripts\alembic.exe upgrade head      # 0027 → 0028
```

**必须实跑并核对**：
- 降级后 `document_chapter_links` 的列集合**逐字节回到 10 列**；
- 降级后 `status='pending'` 的行**确实被清掉了**（不留孤儿行）；
- 升级后存量行的 `status` **全是 `'approved'`**（造存量数据实跑确认，
  不是只看 alembic 版本号——这是 08 期在 `clear_reason` 上踩过的坑）。

---

## 4. 下游：图传播只读生效边

### 4.1 唯一需要改的地方

`app/incremental/second_pass.py::build_point_index`：

```python
link_rows = session.execute(
    select(DocumentChapterLink.from_chapter_id, DocumentChapterLink.to_chapter_id)
    .where(
        DocumentChapterLink.version_id == analysis.document_version_id,
        DocumentChapterLink.link_type.in_(_PROPAGATION_LINK_TYPES),
        DocumentChapterLink.to_chapter_id.is_not(None),
        DocumentChapterLink.status == "approved",   # ← 本期新增的唯一条件
    )
    .order_by(DocumentChapterLink.from_chapter_id, DocumentChapterLink.to_chapter_id)
).all()
```

**只加这一个条件**。算法、错误码、`_PROPAGATION_LINK_TYPES` 全不动。

### 4.2 为什么这一条是「待评审」能不能落地的关键

如果只做前端分区、DB 里不分状态，那么：
待评审的边**照样参与图传播** → 照样产生 `possible_impact` 冲突 →
**照样影响增量分析的结论**。

那「待评审」就只是一个前端标签，语义上等于没做。

**AC-231 专门验证这一点**：
一条 `status='pending'` 的 `references` 边**不产生** `possible_impact`；
改成 `approved` 后**产生**。

### 4.3 05 期的 `chapter_link_count` 统计口径不变

`app/incremental/service.py::_ensure_rule_links` 统计的是 `source='rule'` 的行数，
规则边默认 `approved`，**口径与数量都不变**。
（`_ensure_rule_links` 本身也**不动**——它是 05 期的内部依赖。）

---

## 5. AI 分析的落库改动

### 5.1 `_persist_ai_links` 的新口径

```python
def _persist_ai_links(session, *, version_id, actor, references):
    # ① 只删「上一轮还没审的」——已采纳的边原样保留
    session.execute(
        delete(DocumentChapterLink).where(
            DocumentChapterLink.version_id == version_id,
            DocumentChapterLink.source == "ai",
            DocumentChapterLink.status == "pending",
        )
    )

    # ② 收集「已存在的同一条边」（不论来源、不论状态）→ 跳过，避免撞唯一键
    existing_keys = {
        (row.from_chapter_id, row.link_type, row.to_chapter_id)
        for row in session.scalars(
            select(DocumentChapterLink).where(
                DocumentChapterLink.version_id == version_id,
                DocumentChapterLink.to_chapter_id.is_not(None),
            )
        ).all()
    }

    rows = [
        DocumentChapterLink(
            version_id=version_id,
            from_chapter_id=item["from_chapter_id"],
            to_chapter_id=item["to_chapter_id"],
            link_type=item["link_type"],
            entity=None,
            confidence=item.get("confidence"),
            rationale=item.get("rationale"),     # ← 本期新增写入
            source="ai",
            status="pending",                    # ← 本期新增：落待评审
            created_by=actor.id,
        )
        for item in references
        if (item["from_chapter_id"], item["link_type"], item["to_chapter_id"])
        not in existing_keys
    ]
    ...
```

### 5.2 两个设计点

**① 为什么「已采纳的 AI 边」要跳过而不是覆盖？**

唯一键 `uk_chlinks_to_chapter` =
`(version_id, from_chapter_id, link_type, to_chapter_id)`，
**不含 `source` 也不含 `status`**。

重新分析时，如果模型又认出了同一条边：
- 插新行 → 撞唯一键（500）；
- 覆盖旧行 → 把用户已采纳的边打回待评审（人工评审白做）；
- **跳过** → 已采纳的边保持 `approved`，新一轮的结果由「尚未被采纳的那批」承载。

**跳过是最保守也最符合直觉的**（与 12 期「人工边优先」同一哲学）。

**② 为什么 `rationale` 这次能落库？**

12 期的引擎（`link_analyze.py::parse_references`）**已经解析出了 `rationale`**
（截断 500 字），只是 `_persist_ai_links` **没把它写进数据库**，
表里也没有这一列。本期补上这一列 + 这一行写入，**引擎零改动**。

`MAX_RATIONALE_LEN = 500` < 列宽 1000，**不会超列宽**。

---

## 6. 采纳服务层

### 6.1 `approve_link`（单条）

```python
def approve_link(session, *, project_id, document_id, version_id, actor, link_id):
    ensure_writable_admin(...)          # 404 → 409 → 403
    _load_version(...)

    link = session.scalar(
        select(DocumentChapterLink).where(
            DocumentChapterLink.id == link_id,
            DocumentChapterLink.version_id == version_id,
        )
    )
    if link is None:
        raise ChapterLinkNotFound("引用关系不存在或不属于该文档版本")

    before = {"status": link.status, "link_id": link.id}
    link.status = "approved"            # 已是 approved → 幂等，值不变
    session.flush()

    write_audit(
        session, "document.chapter_link.approve",
        actor_id=actor.id, actor_role=actor.global_role,
        project_id=project_id,
        target_type="document_chapter_link", target_id=link.id,
        before_data=before,
        after_data={"status": "approved"},
    )
    session.commit()
```

**幂等**：已是 `approved` 的边，赋值后值不变 → 照样 200。

### 6.2 `approve_links_batch`（批量）

```python
def approve_links_batch(session, *, project_id, document_id, version_id, actor, link_ids):
    ensure_writable_admin(...)
    _load_version(...)

    if not link_ids:
        raise InvalidChapterLink("请选择要采纳的引用关系")

    rows = session.scalars(
        select(DocumentChapterLink).where(
            DocumentChapterLink.id.in_(link_ids),
            DocumentChapterLink.version_id == version_id,
        )
    ).all()

    # 整批校验：缺一个就整批不成
    found = {row.id for row in rows}
    missing = [item for item in link_ids if item not in found]
    if missing:
        raise ChapterLinkNotFound("引用关系不存在或不属于该文档版本")

    for row in rows:
        row.status = "approved"
    session.flush()

    write_audit(
        session, "document.chapter_link.approve",
        ..., after_data={"link_ids": sorted(found), "approved_count": len(rows)},
    )
    session.commit()
    return len(rows)
```

**原子性**：先全量校验 → 全通过才统一改状态 + 统一写一条审计。
「部分成功」会让用户不知道哪些进了、哪些没进。

**空数组**：直接 400 `INVALID_CHAPTER_LINK`（复用既有错误码，零新增）。

---

## 7. 目录与文件

```
app/models/chapter_link.py                          # + status / rationale 列 + CHECK
app/incremental/second_pass.py                      # 读引用图加 status='approved' 过滤（1 个条件）
app/incremental/links.py                            # 分析落库改 pending + 写 rationale；+ 采纳服务
app/incremental/links_router.py                     # + POST /{id}/approve、POST /approve-batch
app/incremental/schemas.py                          # ChapterLinkOut 扩 2 字段；+ ChapterLinkApproveBatch
migrations/versions/0028_chapter_link_review_status.py   # 加两列 + CHECK

web/src/api/index.ts                                # ChapterLink 扩 2 字段；+ 2 个采纳函数
web/src/api/client.ts                               # 零改动（本期零新增错误码）
web/src/pages/ChapterLinkDrawer.tsx                 # 三区 + 状态提示 + 锁屏 + 删重抽 + 表单引导
web/src/pages/ChapterLinkDetailModal.tsx            # 新增：详情弹窗
web/src/pages/incrementalMeta.tsx                   # + LINK_STATUS_META / linkStatusTag

tests/incremental/test_chapter_link_review.py       # 新增：采纳服务层用例
tests/incremental/test_chapter_link_review_api.py   # 新增：接口层用例
tests/incremental/test_chapter_link_review_migration.py  # 新增：迁移断言
tests/incremental/test_chapter_link_migration.py    # 改：列集合 / head（§8.1）
tests/process_baselines/test_migration.py           # 改：head（§8.1）
tests/e2e/test_chapter_link_review_ui.py            # 新增：前台核对
tests/e2e/test_chapter_link_ai_ui.py                # 改：testid 改名（§8.1）
tests/e2e/support.py                                # seed 支持 status / rationale
specs/验证约定.md                                    # §5.16 前台核对点
PROGRESS.md                                          # §3 当前状态
```

**`app/llm/mock.py` 零改动**（12 期红线）。
**`app/common/errors.py` 零改动**（零新增错误码）。
**`app/incremental/link_analyze.py` 零改动**（引擎已解析出 rationale）。
**`app/incremental/service.py` 零改动**（`_ensure_rule_links` 口径不变）。

---

## 8. 前端方案

### 8.1 组件拆分

`ChapterLinkDrawer.tsx` 12 期已经 374 行，本期再加三区 + 详情 + 锁屏会超 400 行
（`specs/验证约定.md` §4.3 的拆分阈值）。

拆成：

| 文件 | 职责 |
|---|---|
| `ChapterLinkDrawer.tsx` | 抽屉骨架 + 数据加载 + 状态编排 |
| `ChapterLinkDetailModal.tsx` | 详情弹窗（纯展示） |
| `ChapterLinkTable.tsx` | 表格（待评审区 / 已生效区共用，靠 props 区分） |

> **决策**：表格抽成独立组件。理由：两个区用的是**同一套列定义**，
> 只是操作列多一个「采纳」按钮——不抽就要写两遍列定义。

### 8.2 状态驱动的提示语

```tsx
function hintOf(links: ChapterLink[]) {
  const pending = links.filter((item) => item.status === 'pending')
  if (links.length === 0) {
    return {
      type: 'info' as const,
      message: '当前版本还没有引用关系。点击右上角【✨ AI 一键分析引用】自动识别，也可手动补充。',
    }
  }
  if (pending.length > 0) {
    return {
      type: 'warning' as const,
      message: `AI 已识别出 ${pending.length} 条引用关系，待你确认后生效。确认前不会参与增量分析的传播计算。`,
    }
  }
  return {
    type: 'info' as const,
    message: '系统已通过 AI 自动识别章节间的引用关系，您可以修改或删除错误结果，也可以手动补充。',
  }
}
```

**12 期的原提示语一字不改**，只是变成了「第三态」的文案。

### 8.3 分析期间锁抽屉

```tsx
<Drawer extra={<Button loading={analyzing} ...>✨ AI 一键分析引用</Button>}>
  <ConfigProvider componentDisabled={analyzing}>
    ...抽屉内容（提示语 / 两个区 / 表单）...
  </ConfigProvider>
</Drawer>
```

**AI 按钮在 `ConfigProvider` 外面** —— 它自己有 `loading`，
不需要被 `componentDisabled` 禁掉（禁了就点不动了，用户以为死了）。

**已实测**：antd v6 的 `ConfigProvider componentDisabled` 覆盖 33 个组件
（`web/node_modules/antd/es/config-provider/DisabledContext.js`）：
Button / Select / Radio / Input / Table / Popconfirm / Modal 等。

**双保险**：补链按钮额外显式 `disabled={analyzing}`。

### 8.4 删「按规则重抽」

从 `ChapterLinkDrawer.tsx` 移除：
- 「按规则重抽」`Button`；
- `extracting` state；
- `reExtract()` 函数；
- `extractChapterLinks` 的 import。

**保留** `web/src/api/index.ts` 的 `extractChapterLinks` 函数（后端接口还在）。

### 8.5 表单引导文案

```tsx
<Form.Item
  name="from_chapter_id"
  label="源章节"
  extra="从这里出发的章节，例如「2.1 登录流程」"
  rules={[{ required: true, message: '请选择源章节' }]}
>
```

**类型下拉两行式**：

```tsx
const LINK_TYPE_OPTIONS = [
  { value: 'references', label: '引用', description: 'A 章节提到「见 B 章节」' },
  { value: 'depends_on', label: '依赖', description: 'A 章节的实现依赖 B 章节' },
  { value: 'mentions_entity', label: '相关', description: 'A 章节提到某个功能点或术语' },
]

<Select
  options={LINK_TYPE_OPTIONS}
  optionRender={(option) => (
    <div>
      <div>{option.data.label}</div>
      <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>{option.data.description}</div>
    </div>
  )}
/>
```

### 8.6 详情弹窗

```tsx
<Modal open={detail != null} onCancel={close} footer={null} data-testid="chapter-link-detail-modal">
  <Descriptions column={1} size="small" bordered>
    <Descriptions.Item label="源章节">{detail.from_chapter_title}</Descriptions.Item>
    <Descriptions.Item label="目标章节">{detail.to_chapter_title ?? `实体「${detail.entity}」`}</Descriptions.Item>
    <Descriptions.Item label="关系类型">{linkTypeTag(detail.link_type)}</Descriptions.Item>
    <Descriptions.Item label="来源">{linkSourceTag(detail.source)}</Descriptions.Item>
    <Descriptions.Item label="状态">{linkStatusTag(detail.status)}</Descriptions.Item>
    <Descriptions.Item label="分析理由">{detail.rationale ?? '无'}</Descriptions.Item>
    <Descriptions.Item label="置信度">{detail.confidence ?? '无'}</Descriptions.Item>
  </Descriptions>
</Modal>
```

**「详情」按钮对所有来源的边都可见**（不只是 AI 边）——
规则边与人工边的 rationale 为空，显示「无」。
（用户诉求是「AI 分析的结果必须支持查看细节」，但**详情按钮只给 AI 边**
会让用户看到表格里有的行没有这个按钮，**界面不整齐**；
给全表都加、成本是同一个弹窗。）

---

## 9. 接口一览

| 方法 | 路径 | 权限 | 响应 |
|---|---|---|---|
| GET | `.../links` | 成员 | `list[ChapterLinkOut]`（**扩 2 字段**） |
| POST | `.../links` | 管理员 | 201 `ChapterLinkOut`（**扩 2 字段**） |
| POST | `.../links/extract` | 管理员 | 200 `list[ChapterLinkOut]`（**前端入口已删，后端保留**） |
| POST | `.../links/analyze` | 管理员 | 200 `ChapterLinkAnalyzeOut`（**落库改 pending**） |
| DELETE | `.../links/{link_id}` | 管理员 | 204 |
| POST | `.../links/{link_id}/approve` | 管理员 | 200 `ChapterLinkOut`（**新增**） |
| POST | `.../links/approve-batch` | 管理员 | 200 `{"approved_count": N}`（**新增**） |

**路由顺序注意**：`POST /links/approve-batch` 必须注册在
`POST /links/{link_id}/approve` **之前**——FastAPI 按声明顺序匹配，
`{link_id}` 是路径参数，会把 `approve-batch` 当成 link_id 吃掉。

> **实际实现**：两个路径的字面量段数不同
> （`/approve-batch` 是 1 段，`/{link_id}/approve` 是 2 段），
> 实际不会冲突。但**仍然把 `approve-batch` 放前面**——避免以后有人加
> `POST /links/{link_id}/xxx` 时踩坑，也符合「具体路径优先」的直觉。

---

## 10. 测试计划

| 层 | 文件 | 覆盖 |
|---|---|---|
| 数据层 | `tests/incremental/test_chapter_link_review_migration.py` | 列集合 = 12 列 / CHECK 扩枚举 / 存量回填 / head = 0028 |
| 引擎/服务 | `tests/incremental/test_chapter_link_review.py` | 采纳幂等 / 批量原子 / 批量跨版本 404 / 分析落 pending / 重分析不冲掉已采纳 |
| 传播 | `tests/incremental/test_chapter_link_review_propagation.py` | **AC-231**：pending 边不传播，approved 边传播 |
| 接口 | `tests/incremental/test_chapter_link_review_api.py` | 权限矩阵 / 审计 / 列表带 status / 详情字段 |
| e2e | `tests/e2e/test_chapter_link_review_ui.py` | AC-233 ~ AC-238 前台核对 |
| e2e（改） | `tests/e2e/test_chapter_link_ai_ui.py` | testid 改名（§8.1） |

**审计覆盖**：新增 `document.chapter_link.approve` →
`tests/common/test_audit_coverage.py` 的 `SCENARIOS` 加一项。

---

## 11. 验证命令

```powershell
# 开跑前自检
.\.venv\Scripts\python.exe scripts\dev_check.py

# 定向
.\.venv\Scripts\python.exe -m pytest tests\incremental -k "chapter_link_review" -q

# 全量（只增不减）
.\.venv\Scripts\python.exe -m pytest -m "not e2e"

# e2e
.\.venv\Scripts\python.exe scripts\run_e2e.py

# 前端
cd web; npm run build; npm run lint

# 迁移往返（两库都跑）
.\.venv\Scripts\python.exe scripts\check_migration_roundtrip.py
```

---

## 12. 实施中可能踩的坑（预判）

| 坑 | 表现 | 对策 |
|---|---|---|
| `alter_column(nullable=False)` 在有 NULL 的列上炸 1138 | 迁移失败 | 先加可空列 + server_default（存量被填），再收紧 |
| downgrade 后留 `status=NULL` 的孤儿行 | 数据不干净 | downgrade **先删 pending 行再删列** |
| FastAPI 路由顺序 | `/approve-batch` 被 `{link_id}` 吃掉 | 具体路径先注册 |
| `componentDisabled` 把 AI 按钮也禁了 | 用户点不动 AI 按钮 | AI 按钮放 `ConfigProvider` 外 |
| 「已采纳」被重分析冲掉 | 人工评审白做 | 只删 `status='pending'` 的旧行 |
| 唯一键撞车 500 | 分析接口报错 | 插入前跳过「已存在的同一条边」 |
| 迁移后存量 AI 边变待评审 | 12 期成果倒退 | server_default 回填 `'approved'` |
| 传播逻辑漏加 `status` 过滤 | 「待评审」形同虚设 | AC-231 专门验证 |
