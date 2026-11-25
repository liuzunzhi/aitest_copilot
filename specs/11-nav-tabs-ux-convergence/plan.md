# 11 · 导航栏 UX 收敛 · 技术方案

> 配套 [spec.md](./spec.md)（AC-215 ~ AC-219）与 [tasks.md](./tasks.md)（T124 ~ T128）。
> 定位：**纯前端导航重构**——后端 `app/` 零改动，e2e 断言同步改到位。
> **本方案按「细颗粒度交付」红线拆分**：每个任务改动文件数 **≤ 5**。

## 1. 总体思路

```
ProjectDetailPage.tsx（宿主：只做编排）
├── items[] 重排为 8 项（删 baselines / applications，documents 提前，members 垫底）
├── documents item  ──→ <Space vertical>
│                         ├── ProjectDocumentsTab   （不动）
│                         └── Card「版本快照」
│                              └── ProjectBaselinesTab （不动，props 不变）
├── members item    ──→ ProjectMembersTab.tsx（新）
│                         └── 二级 Tabs（defaultActiveKey="members"）
│                              ├── 「成员列表」→ member-table
│                              └── 「加入申请」→ application-table
└── 权限判定 / baselineKey / reloadApplications 全部保留在宿主
```

三条关键设计：

1. **只删入口，不删能力**——两张表的内容都还在，只是换了位置。
   `ProjectBaselinesTab` 与 `ProjectDocumentsTab` 两个文件**一个字节都不改**。
2. **状态留在宿主，子组件受控**——`canManage` 依赖 `myRole`，
   而 `myRole` 来自 `members`；把 `members` 放进子组件会让宿主拿不到角色，
   形成循环依赖。父组件持有 state、子组件只管渲染与交互 → **数据源单一，不重复请求**。
3. **断言写法要跟着结构变**——antd 两层 `Tabs` 都用 `role="tab"`，
   且 Playwright 的 `name=` 默认**子串匹配**：
   顶层「成员」与内层「成员列表」互相包含 → 顶层断言必须
   `exact=True` 或限定 `tablist`。

## 2. 目录与文件

### 2.1 本期新增 / 修改的全部文件（18 个，分 5 个任务）

**前端（3 个）**

| 文件 | 动作 | 任务 |
|---|---|---|
| `web/src/pages/ProjectMembersTab.tsx` | **新增** | T124 |
| `web/src/pages/ProjectDetailPage.tsx` | 改 | T124 |
| `web/src/pages/ProjectBaselineManagementTab.tsx` | 改（仅注释里的数字） | T127 |

**e2e（10 个）**

| 文件 | 动作 | 任务 |
|---|---|---|
| `tests/e2e/test_tabs_ui.py` | 顶层名单 / 锚点 / 计数 / 循环 | T124 |
| `tests/e2e/test_automation_ui.py` | 计数 + 索引 | T124 |
| `tests/e2e/test_process_baseline_ui.py` | 计数 + 索引 | T124 |
| `tests/e2e/test_t116_closing_ui.py` | 顶层名单 / 锚点 / 计数 / 循环 / 索引 | T125 |
| `tests/e2e/test_t123_closing_ui.py` | 同上 | T125 |
| `tests/e2e/test_documents_ui.py` | 3 处「版本快照」入口 → 「文档」Tab | T125 |
| `tests/e2e/test_applications_ui.py` | 「申请」入口 → 成员 Tab → 子 Tab | T125 |
| `tests/e2e/test_access_ui.py` | `name="成员"` 加 `exact=True` | T126 |
| `tests/e2e/test_projects_ui.py` | `name="成员"` 加 `exact=True` | T126 |
| `tests/e2e/test_smoke.py` | `name="成员"` 加 `exact=True` | T126 |

**文档（5 个）**

| 文件 | 动作 | 任务 |
|---|---|---|
| `README.md` | Tab 数量与名单 | T127 |
| `PROGRESS.md` | §4 现状 + §4 坑位 | T127 |
| `specs/验证约定.md` | §1 现状 + §5.13 数字 + 新增 §5.14 前台核对点 | T127 |
| `specs/11-nav-tabs-ux-convergence/收官总结.md` | **新增** | T128 |
| `specs/11-nav-tabs-ux-convergence/tasks.md` | 验证记录表回填 | T128 |

**前期产出（不计入任务文件数，评审通过后随首个任务一起提交）**

```
specs/11-nav-tabs-ux-convergence/spec.md
specs/11-nav-tabs-ux-convergence/plan.md
specs/11-nav-tabs-ux-convergence/tasks.md
```

### 2.2 明确不碰（`git diff --stat` 必须为空）

```
app/**                              （后端零改动）
web/src/api/index.ts                （listBaselines / listProjectApplications 都不动）
web/src/api/client.ts               （零新错误码）
web/src/pages/ProjectBaselinesTab.tsx   （组件保留，挂载点变了，文件零改动）
web/src/pages/ProjectDocumentsTab.tsx   （props 不变，快照卡片内联在宿主里）
web/src/pages/ProjectTodoCard.tsx       （3 个跳转 key 全部保留）
web/package.json                    （零新依赖）
```

## 3. 前端实现细节

### 3.1 `ProjectMembersTab.tsx`（新增，预估 ~180 行）

```tsx
import { App as AntdApp, Button, Form, InputNumber, Modal, Popconfirm, Select, Space, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Application, Member } from '../api'

interface Props {
  projectId: number
  members: Member[]
  applications: Application[]
  canManage: boolean
  onSubmitAddMember: (userId: number, role: string) => Promise<void>
  onChangeRole: (member: Member, role: string) => Promise<void>
  onRemoveMember: (member: Member) => Promise<void>
}
```

**结构**：

```tsx
<Tabs
  defaultActiveKey="members"
  data-testid="project-members-subtab"
  items={[
    {
      key: 'members',
      label: <span data-testid="project-members-subtab-members">成员列表</span>,
      children: (
        <div>
          {canManage ? (
            <Space style={{ marginBottom: 16 }}>
              <Button type="primary" onClick={() => setAdding(true)}>添加成员</Button>
            </Space>
          ) : null}
          <Table<Member> rowKey="user_id" columns={memberColumns} dataSource={members}
            pagination={false} data-testid="member-table" />
        </div>
      ),
    },
    {
      key: 'applications',
      label: <span data-testid="project-members-subtab-applications">加入申请</span>,
      children: (
        <Table<Application> rowKey="id" columns={applicationColumns}
          dataSource={applications} pagination={false} data-testid="application-table" />
      ),
    },
  ]}
/>
```

**要点**：

| 要点 | 做法 | 原因 |
|---|---|---|
| `defaultActiveKey="members"` | 默认停在「成员列表」 | `member-table` 在 3 个既有 e2e 里被断言「可见」 |
| label 用 `<span data-testid>` 包裹 | 照抄 `process-baseline-subtab-function` 的做法 | e2e 精确定位，避开 `role="tab"` 名字冲突 |
| 申请表补 `data-testid="application-table"` | 新增锚点 | 原「申请」Tab 没有 testid，现在有了 |
| 「添加成员」按钮 | **只在 `canManage` 时渲染** | 与原行为一致（访客/成员看不到写入口） |
| 添加成员 Modal | 整个搬进子组件，`data-testid="modal-ok"` 不变 | `test_projects_ui.py` 依赖这个 testid |
| 申请表无分页 | `pagination={false}` | 与原「申请」Tab 一致 |

### 3.2 `ProjectDetailPage.tsx` 的改动

**顶层 `items` 数组（重排后）**：

```tsx
items={[
  { key: 'overview', label: '概览', children: (...) },                    // 不变
  { key: 'documents', label: '文档', children: (                          // 位置 3 → 2
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <ProjectDocumentsTab projectId={projectId} canWrite={canWrite} onChanged={reloadOverview} />
      <Card title="版本快照" size="small">
        <ProjectBaselinesTab projectId={projectId} refreshKey={baselineKey} />
      </Card>
    </Space>
  )},
  { key: 'baseline-management', label: '基线管理', children: (...) },      // 位置 5 → 3
  { key: 'incremental', label: '增量分析', children: (...) },              // 位置 7 → 4
  { key: 'test-points', label: '测试点', children: (...) },                // 位置 8 → 5
  { key: 'test-cases', label: '测试用例', children: (...) },                // 位置 9 → 6
  { key: 'automation', label: <span data-testid="automation-tab">自动化执行</span>, children: (...) }, // 位置 10 → 7
  { key: 'members', label: '成员', children: (                             // 位置 2 → 8（末位）
    <ProjectMembersTab
      projectId={projectId}
      members={members}
      applications={applications}
      canManage={canManage}
      onSubmitAddMember={submitAddMember}
      onChangeRole={changeRole}
      onRemoveMember={handleRemove}
    />
  )},
]}
```

**保留在宿主的（一个字节都不动）**：

| 内容 | 行号 | 为什么必须留 |
|---|---|---|
| `baselineKey` state | L77 | 快照刷新链路的起点 |
| `reloadOverview` 里的 `setBaselineKey(key => key + 1)` | L102 | 文档变更 → 快照表自动刷新 |
| `members` / `applications` state | L80-L81 | 受控传参 + `myRole` 权限判定 |
| `reloadMembers` / `reloadApplications` | L119-L135 | 页面级生命周期 |
| `reloadApplications` 的 `catch {}` 静默降级 | L131-L134 | 非管理员进「加入申请」不弹 403 toast |
| `canManage` / `canWrite` 判定 | L88-L96 | `myRole` 依赖 `members` |

**迁走的（spec §4.4 的对照表）**：`memberColumns` / `applicationColumns` /
`submitAddMember` / `changeRole` / `handleRemove` / 添加成员 Modal /
`PROJECT_ROLE_LABELS` / `APPLICATION_STATUS_LABELS` / `STATUS_COLORS`。

**⚠️ `noUnusedLocals: true`**（`tsconfig.app.json`）：
迁移后父组件里残留任何一个未使用的 import / 常量 / state，
`npm run build` 会**直接失败**。这是本任务最容易踩的坑。

**预估行数**：394 → **~300 行**（只做减法，符合验证约定 §4.3 的 400 行阈值）。

### 3.3 「版本快照」刷新链路（必须完整保留）

```
文档上传 / 确认生效
  → ProjectDocumentsTab.onChanged()                    ← 不动
  → ProjectDetailPage.reloadOverview()                 ← 不动
  → setBaselineKey((key) => key + 1)                   ← 不动
  → ProjectBaselinesTab 的 refreshKey prop 变化         ← 不动（props 没变）
  → useEffect([reload, refreshKey]) 触发重载            ← 不动
```

`ProjectBaselinesTab` 在「文档」Tab 内**始终挂载**
（antd `Tabs` 切走不卸载组件，`destroyOnHidden` 默认 false），
所以不需要来回切 Tab 就能看到刷新——**比旧的「版本快照」独立 Tab 更好**。

## 4. e2e 断言改动

### 4.1 ⚠️ 已实测确认的 Playwright 匹配语义

用 playwright 1.65.2 在本机实测（DOM 里放顶层 `成员` + 内层 `成员列表` 两个 `role="tab"`）：

| 写法 | 命中数 | 命中内容 |
|---|---|---|
| `get_by_role("tab", name="成员")` | **2** | `['成员', '成员列表']` ← **子串匹配** |
| `get_by_role("tab", name="成员", exact=True)` | **1** | `['成员']` |
| `get_by_role("tab", name="自动化执行")` | 1 | `['自动化执行']` |
| `get_by_role("tablist").first.get_by_role("tab", name="成员")` | **1** | `['成员']` |

裸 `get_by_role("tab", name="成员").click()` 直接抛 **strict mode violation**。

**根因**：`exact=False` → 属性选择器带 `i` 标志
（`playwright/_impl/isomorphic/string_utils.py:75-87`）→ 默认**子串、不区分大小写**。

### 4.2 三份重复的 `TAB_NAMES` / `TAB_ANCHORS`

`test_tabs_ui.py` / `test_t116_closing_ui.py` / `test_t123_closing_ui.py`
是三份**完全复制粘贴**的副本。本期**统一改成**：

```python
TAB_NAMES = [
    "概览", "文档", "基线管理", "增量分析",
    "测试点", "测试用例", "自动化执行", "成员",
]

TAB_ANCHORS = {
    "概览": "project-overview",
    "文档": "document-table",
    "基线管理": "baseline-keyword",
    "增量分析": "incremental-analysis-table",
    "测试点": "test-point-analysis-table",
    "测试用例": "test-case-analysis-table",
    "自动化执行": "automation-asset-table",
    "成员": "member-table",
}
```

「版本快照」「申请」两项**删除**。
「成员」的锚点仍是 `member-table`（默认就在「成员列表」子 Tab 里）。

### 4.3 顶层计数：必须限定 `tablist`

内层子 Tab 变多（成员内 2 个 + 基线管理内 2 个）。
antd 的 `Tabs` 非活动面板**懒渲染** → **进 Tab 之前**计数天然安全；
但循环**逐个点开**顶层 Tab 后，裸 `get_by_role("tab")` 会多算**当前激活**那个
顶层 Tab 的内层子 Tab。

**已实测**（本机 playwright 1.65.2 + 忠实复刻 antd v6 的 DOM 与
`.rc-tabs-content-hidden { display: none }`）：

| 场景 | 裸 `get_by_role("tab")` | `tablist.first` 内 |
|---|---|---|
| 刚进页面（内层未访问） | **8** | 8 |
| 点开「基线管理」 | **10** | 8 |
| 点开「成员」（基线管理已隐藏） | **10** | 8 |
| 两个内层都访问过 | **10** | 8 |

**规律：只有「当前激活」的顶层 Tab 的内层子 Tab 会被计入**
（已离开的顶层 Tab 面板是 `display:none`，里面的子 Tab 不计入；
`include_hidden=True` 才会数到 12）→ 裸计数是 **8 + 2 = 10**，**不是 12**。

| 文件 | 行号 | 现状 | 改法 |
|---|---|---|---|
| `test_tabs_ui.py` | L58 | `get_by_role("tab")` | → `get_by_role("tablist").first.get_by_role("tab")` |
| `test_t116_closing_ui.py` | L88 | `get_by_role("tab")` | 同上 |
| `test_automation_ui.py` | L145 | `get_by_role("tab")` | 同上 |
| `test_t123_closing_ui.py` | L145 | 已限定 | **不动** |
| `test_process_baseline_ui.py` | L162 | 已限定 | **不动** |

> ⚠️ **`test_t116_closing_ui.py` 的索引断言在点击循环之后**（L104-L105），
> 此时裸 locator 已有 10 个 tab → `nth(9)` 会命中**内层子 Tab**。
> 把 L88 改成 `tablist.first` 后，索引断言自动回到顶层语义。

### 4.4 索引断言（4 处）

| 文件 | 旧 | 新 |
|---|---|---|
| `test_t116_closing_ui.py` L104-L105 | `nth(9)`→自动化执行<br>`nth(8)`→测试用例 | `nth(7)`→成员<br>`nth(6)`→自动化执行 |
| `test_t123_closing_ui.py` L161-L162 | 同上 | 同上 |
| `test_automation_ui.py` L146-L148 | `to_have_count(10)`<br>`nth(9)`/`nth(8)` | `to_have_count(8)`<br>`nth(7)`/`nth(6)` |
| `test_process_baseline_ui.py` L163-L165 | 同上 | 同上 |

> ⚠️ **语义变化**：旧顺序「自动化执行」是**最后一个**；新顺序「**成员**」是最后一个。
> 注释与语义断言同步改。

### 4.5 循环内点击加 `exact=True`

三份文件的循环统一改为：

```python
for name in TAB_NAMES:
    admin_page.get_by_role("tab", name=name, exact=True).click()
    anchor = TAB_ANCHORS[name]
    if anchor:
        expect(admin_page.get_by_test_id(anchor)).to_be_visible()
    expect(admin_page.get_by_role("tab", name=name, exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
```

### 4.6 入口路径改写

**「申请」（`test_applications_ui.py` L31）**：

```python
# 旧：admin_page.get_by_role("tab", name="申请").click()
admin_page.get_by_role("tab", name="成员", exact=True).click()
admin_page.get_by_test_id("project-members-subtab-applications").click()
```

断言内容（`待审批` / `e2e 申请理由`）**原样保留**。

**「版本快照」（`test_documents_ui.py` L132 / L185 / L208）**：

```python
# 旧：admin_page.get_by_role("tab", name="版本快照", exact=True).click()
# 新：快照已挂进「文档」Tab
admin_page.get_by_role("tab", name="文档").click()
```

> ⚠️ **L185 / L208 的时序**：`test_ac_54_new_version_archives_old_and_baseline_refreshes`
> 断言的是「**不刷新页面**，基线表应已重载」。
> 新流程下快照卡片随「文档」Tab 一起挂载，`baselineKey` 自增照样触发重载 → **断言依然成立**。
> L185 的注释「先看一次基线，让组件挂载并缓存 V1」要改成「快照随文档 Tab 挂载」。

### 4.7 「成员」点击加 `exact=True`（4 处）

顶层「成员」与内层「成员列表」构成子串关系，裸写法 strict mode violation。

| 文件 | 行号 |
|---|---|
| `test_access_ui.py` | L35 |
| `test_projects_ui.py` | L63、L79 |
| `test_smoke.py` | L51 |

### 4.8 不需要改的顶层 Tab 点击（22 处）

顶层 Tab 名与内层子 Tab 名**不构成子串包含关系**
（文档 / 概览 / 基线管理 / 增量分析 / 测试点 / 测试用例 / 自动化执行），
以下文件的点击**保持原样**：

`test_baselines_ui.py`（6）、`test_incremental_ui.py`（2）、
`test_incremental_apply_ui.py`（2）、`test_incremental_second_pass_ui.py`（3）、
`test_test_points_ui.py`（2）、`test_test_cases_ui.py`（1）、
`test_automation_ui.py`（3）、`test_llm_settings_ui.py`（1）、
`test_todos_ui.py`（3）、`test_process_baseline_ui.py`（3）、
`test_documents_ui.py`（文档/概览 3 处）。

### 4.9 e2e 改动汇总

| 文件 | 改动点 | 数量 |
|---|---|---|
| `test_tabs_ui.py` | `TAB_NAMES` / `TAB_ANCHORS` / 计数限定 tablist / 循环加 `exact=True` | 4 |
| `test_automation_ui.py` | 计数限定 tablist / `to_have_count(10)`→8 / 索引 | 3 |
| `test_process_baseline_ui.py` | `to_have_count(10)`→8 / 索引 | 3 |
| `test_t116_closing_ui.py` | 名单 / 锚点 / 计数限定 / 循环 / 索引 | 5 |
| `test_t123_closing_ui.py` | 同上 | 5 |
| `test_documents_ui.py` | 3 处「版本快照」入口 | 3 |
| `test_applications_ui.py` | 「申请」入口 | 1 |
| `test_access_ui.py` | `exact=True` | 1 |
| `test_projects_ui.py` | `exact=True` | 2 |
| `test_smoke.py` | `exact=True` | 1 |

## 5. 任务拆分（红线：每个任务 ≤ 5 个文件）

| 任务 | 主题 | 文件数 | 文件清单 |
|---|---|---|---|
| **T124** | 前端收敛（8 Tab + 成员二级子菜单）+ 顶层计数断言 | **5** | `ProjectMembersTab.tsx`（新）<br>`ProjectDetailPage.tsx`<br>`test_tabs_ui.py`<br>`test_automation_ui.py`<br>`test_process_baseline_ui.py` |
| **T125** | e2e 入口路径改写 + 收官核对断言 | **4** | `test_t116_closing_ui.py`<br>`test_t123_closing_ui.py`<br>`test_documents_ui.py`<br>`test_applications_ui.py` |
| **T126** | 「成员」点击精确化 | **3** | `test_access_ui.py`<br>`test_projects_ui.py`<br>`test_smoke.py` |
| **T127** | 文档口径同步 | **4** | `README.md`<br>`PROGRESS.md`<br>`specs/验证约定.md`<br>`ProjectBaselineManagementTab.tsx`（仅注释） |
| **T128** | 收尾：全量回归 + 收官总结 | **2** | `specs/11-nav-tabs-ux-convergence/收官总结.md`（新）<br>`specs/11-nav-tabs-ux-convergence/tasks.md`（回填） |

**每个任务 ≤ 5 个文件**，符合验证约定 §2 第 5 条的「细颗粒度交付」红线。

### 5.1 ⚠️ 任务间的「预期红窗」（必须知情）

顶层 Tab 数量从 10 变成 8 是**原子变更**——旧 e2e 的
`to_have_count(10)` 与 `name="版本快照"` / `name="申请"` **必然同时失效**，
无法做到「前端先改、e2e 后改」的中间绿态。

因此 T124 落地后到 T126 落地前，**e2e 全量不是绿的**，这是预期内的：

| 时点 | e2e 状态 | 红的原因 |
|---|---|---|
| T124 前 | 🟢 64 passed | — |
| **T124 后** | 🔴 7 个文件红 | `t116`/`t123` 仍写死 10 项；`documents`/`applications` 入口路径变了；`access`/`projects`/`smoke` 的 `name="成员"` strict violation |
| **T125 后** | 🔴 3 个文件红 | `access`/`projects`/`smoke` 的 `name="成员"` strict violation |
| **T126 后** | 🟢 64 passed | 全部改完 |

**规则**：
- T125 与 T126 **必须紧接着 T124 落地**，不留跨天间隔；
- 每个任务提交信息里**显式写明**当次 e2e 的预期状态（红 / 绿），
  不让「e2e 红了」被误判成回归；
- 后端全量 pytest **每个任务都是绿的**（后端零改动），
  红的只有 e2e。

### 5.2 「禁止混搭」的对照

验证约定 §2 第 5 条第三款：「纯后端接口、纯前端组件、基础表结构与复杂业务关联，
严禁在同一个 Task 内混合提交。」

| 任务 | 性质 | 是否混搭 |
|---|---|---|
| T124 | 纯前端组件 + 其直接断言 | ❌ 不混搭（前端组件 + 同批前端断言是一个交付单元） |
| T125 / T126 | 纯 e2e 断言改写 | ❌ 不混搭 |
| T127 | 纯文档 | ❌ 不混搭 |
| T128 | 收尾 + 总结 | ❌ 不混搭 |

**本期没有任何后端 / 迁移 / 表结构改动**——后端 `app/` 零改动。

## 6. 验证策略

### 6.1 每个任务

```powershell
# 0. 环境自检
.\.venv\Scripts\python.exe scripts\dev_check.py

# 1. 前端构建（改了前端才跑）
cd web; npm run build

# 2. 后端全量（后端零改动，但每任务都跑，确认零回归）
.\.venv\Scripts\python.exe -m pytest

# 3. e2e（T124 / T125 按预期是红的，T126 之后必须绿）
.\.venv\Scripts\python.exe scripts\run_e2e.py
```

### 6.2 定向 e2e（定位用）

```powershell
.\.venv\Scripts\python.exe scripts\run_e2e.py -k "tabs or closing or automation or process_baseline"
```

### 6.3 人工核对点（T126 之后）

`http://localhost:5173`，`admin` / `Admin12345`，打开任意项目详情页：

| # | 核对项 | 期望 |
|---|---|---|
| 1 | 顶层 Tab 数量与顺序 | **8 个**：概览 → 文档 → 基线管理 → 增量分析 → 测试点 → 测试用例 → 自动化执行 → 成员 |
| 2 | 顶层无「版本快照」「申请」 | 确认 |
| 3 | 「文档」Tab 内有「版本快照」卡片 | 能看到 `baseline-table`；上传文档并确认生效后该表自动刷新出新版本 |
| 4 | 「成员」Tab 内有两个二级 Tab | 「成员列表」/「加入申请」；默认停在「成员列表」，能看到成员表与「添加成员」按钮 |
| 5 | 点「加入申请」 | 能看到申请列表（申请人 / 申请理由 / 期望角色 / 状态） |
| 6 | 用**普通成员**账号登录 | 「成员」Tab 能正常进入；「加入申请」显示空列表而**不报错**（403 静默降级） |

### 6.4 红线复核

```powershell
git diff --stat <base>..HEAD -- app/                          # 必须为空
git diff --stat <base>..HEAD -- web/src/pages/ProjectBaselinesTab.tsx   # 必须为空
git diff --stat <base>..HEAD -- web/src/pages/ProjectDocumentsTab.tsx   # 必须为空
git diff --stat <base>..HEAD -- web/src/pages/ProjectTodoCard.tsx       # 必须为空
git diff --stat <base>..HEAD -- web/package.json                       # 必须为空
```

## 7. 风险与对策

| 级别 | 风险 | 对策 |
|---|---|---|
| **P0** | `tsc` 的 `noUnusedLocals` 因迁移残留变量而构建失败 | spec §4.4 对照表逐项清空父组件；`npm run build` 立即暴露 |
| **P0** | 顶层「成员」与内层「成员列表」子串冲突 → strict violation | 已实测确认；4.7 的 4 处 + 4.5 的循环统一 `exact=True` |
| **P0** | 内层子 Tab 污染顶层计数（8 → 12） | 4.3 的 3 处统一限定 `tablist` |
| **P0** | 「加入申请」对非管理员触发 403 toast | 保留 `reloadApplications` 的 `catch {}` 静默降级；人工核对点第 6 条验证 |
| **P1** | T124~T126 之间的 e2e 红窗被误判为回归 | §5.1 明确写进 tasks.md 的每个任务；提交信息显式声明预期状态 |
| **P1** | `member-table` 不在默认子 Tab → 3 个既有 e2e 失效 | `defaultActiveKey="members"`；人工核对点第 4 条验证 |
| **P1** | AC-54 的「不刷新页面基线自动重载」时序失效 | `baselineKey` 链路保留；e2e `test_ac_54` 覆盖该场景 |
| **P1** | 父组件 `canManage` 依赖 `myRole`（依赖 `members`）→ 循环依赖 | 父组件持有 `members`、子组件受控（§3.2） |
| **P2** | 「自动化执行不再是最后一个 Tab」语义注释过时 | §4.4 同步改索引与语义注释 |

## 8. Backlog

- 「加入申请」子 Tab 支持**审批操作**（当前只读，与原「申请」Tab 行为一致）；
- 「版本快照」表支持按文档筛选 / 导出；
- 顶层 Tab 支持 URL 记忆（`?tab=xxx`）——目前刷新会回到「概览」；
- 「成员」Tab 支持未读角标（有 N 条待审批申请时提示）。
