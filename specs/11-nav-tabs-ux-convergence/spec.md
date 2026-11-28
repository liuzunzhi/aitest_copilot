# 11 · 导航栏 UX 收敛 · 规格

> 对齐需求：用户 2026-11-24 体验反馈——项目详情页顶层 Tab 太多（10 个），
> 要求一次彻底的 UX 收敛：**隐藏「版本快照」**、**合并「申请」进「成员」**、
> **重排顺序**。
> 上游依赖：03-documents（文档版本与基线快照）、02-projects（成员与申请）、
> 04-baseline（基线管理二级子菜单的既有约定）。
> 本文是待 review 的规格，**未写任何业务代码**。评审通过后才拆任务落地。

## 0. 一句话结论（先看这个）

| 问题 | 结论 |
|---|---|
| 本期做什么 | **项目详情页顶层 Tab 从 10 个收敛到 8 个**：移除「版本快照」入口（内容迁进「文档」Tab）、移除「申请」入口（合并进「成员」Tab 的二级子菜单）、顶层顺序重排 |
| 顶层最终顺序 | **概览 → 文档 → 基线管理 → 增量分析 → 测试点 → 测试用例 → 自动化执行 → 成员** |
| 「版本快照」去哪了 | 组件**不删**，内容作为「文档」Tab 内的一张「版本快照」卡片继续可用（`baseline-table` 锚点保留） |
| 「申请」去哪了 | 变成「成员」Tab 内的二级子 Tab「加入申请」（与「基线管理 → 功能基线/流程基线」同构） |
| 「成员」内部形态 | **二级 Tabs**（`defaultActiveKey="members"`），默认停在「成员列表」——**现有用户路径不变** |
| 后端要不要动 | **零改动**。接口、权限、判定逻辑全不动；`app/` 目录本期的 `git diff --stat` 必须为空 |
| e2e 条数 | **64 条不变**（只改断言路径，不新增/删除用例） |
| 破坏性变更 | **有**——顶层 Tab 名称、顺序、索引全变；既有 e2e 断言必须同步改（见 §5） |

---

## 1. 背景与目标

### 1.1 现状

项目详情页（`web/src/pages/ProjectDetailPage.tsx`）的顶层 Tabs 已有 **10 个**：

```
概览 → 成员 → 文档 → 版本快照 → 基线管理 → 申请 → 增量分析 → 测试点 → 测试用例 → 自动化执行
```

这 10 个是 10 期（02~10）逐期累加出来的，每期加一个：

| 期次 | 引入的顶层 Tab |
|---|---|
| 02-projects | 概览 / 成员 / 申请 |
| 03-documents | 文档 / 版本快照 |
| 04-baseline | 基线管理 |
| 05-incremental | 增量分析 |
| 07-test-points | 测试点 |
| 08-test-case-analysis | 测试用例 |
| 09-automation | 自动化执行 |

### 1.2 用户反馈（2026-11-24）

> 「顶层 Tab 太多了，需要进行一次彻底的 UX 收敛。」

具体三点：

1. **隐藏「版本快照」**——从顶层 Tabs 中移除（**只移除前端入口，不删代码**）。
2. **合并「成员」与「申请」**——「申请」从顶层移除，合并进「成员」Tab 内部，
   用二级 Tabs（或上下卡片布局）切换「成员列表」和「加入申请」。
3. **调整最终顺序**：概览 → 文档 → 基线管理 → 增量分析 → 测试点 → 测试用例 → 自动化执行 → 成员。

### 1.3 本期目标

- 顶层 Tab **10 → 8**，顺序按用户拍板的上述 8 项重排；
- **不丢能力**：版本快照与加入申请两张表的内容都还能看到、能操作；
- **不删代码**：`ProjectBaselinesTab.tsx`、`listBaselines` API、
  `baselineKey` 刷新链路全部保留；
- **后端零改动**；
- **e2e 全绿**，断言同步改到位。

---

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 顶层 Tab 收敛 | 移除「版本快照」「申请」两个顶层 item；重排为用户拍板的 8 项顺序 |
| 版本快照内嵌 | `ProjectBaselinesTab` 挂进「文档」Tab 内的一张「版本快照」卡片，**组件文件零改动** |
| 成员二级子菜单 | 新增 `ProjectMembersTab.tsx`，「成员列表」/「加入申请」两个二级 Tab，默认停在「成员列表」 |
| 申请列表迁移 | 原「申请」Tab 的表格整体迁进「成员列表/加入申请」子 Tab，**功能与断言内容不变** |
| 权限保持 | 非项目管理员进「加入申请」子 Tab 显示空列表、**不报错**（403 静默降级保持不变） |
| e2e 断言同步 | 顶层 Tab 数量/名称/索引断言全部改到 8 项；两处入口路径改写 |
| 文档同步 | README / PROGRESS / 验证约定 / `ProjectBaselineManagementTab` 注释里的「10 个 Tab」口径 |

### 2.2 本期不做（显式欠账，登记在 Backlog）

| 不做 | 原因 |
|---|---|
| **不做「版本快照」入口的其它出口**（如文档列表行内点开） | 用户只要求「移除顶层 Tab」；换个位置重新露出一个入口等于没收敛 |
| **不删除 `ProjectBaselinesTab.tsx`** | 用户红线：「只移除前端入口，不删代码」 |
| **不删除 `listBaselines` API 与 `app/documents/router.py` 的 `GET /{id}/baselines`** | 同上；且后端本就要零改动 |
| **不改动 `app/` 任何文件**（含接口、权限、模型、迁移） | 本期是纯前端重构，后端接口与权限逻辑本就满足需求 |
| **不新增 e2e 用例**（条数保持 64） | 本期是导航重构，不新增能力；只改既有断言的路径与期望值 |
| **不重命名任何后端字段 / 枚举 / API 路径** | 与本期目标无关 |
| **不改历史期次 spec（01~10）的归档内容** | 它们记录的是**当时的历史事实**（例如 10 期 spec §2.2 写「不加第 11 个顶层 Tab」是对的——那是 10 期的口径） |
| **不做「成员」Tab 的卡片堆叠布局** | 用户已拍板用二级 Tabs（与「基线管理」同构） |

### 2.3 兼容性约束

1. **路由零影响**：顶层 Tab 由**本地 state** 驱动
   （`useState('overview')` + `<Tabs activeKey onChange>`），
   `web/src` 全量 grep `useSearchParams|searchParams|\?tab=` **零命中**——
   删除 `baselines` / `applications` 两个 key **不会产生死链或 404**。
2. **待办跳转不受影响**：`ProjectTodoCard` 的 3 个跳转 key
   （`baseline-management` / `test-points` / `test-cases`）在新的 8 个 Tab 里**全部保留**，
   [ProjectTodoCard.tsx](file:///d:/aitest_copilot/web/src/pages/ProjectTodoCard.tsx#L6) **零改动**。
3. **`baselineKey` 刷新链路必须保留**：`reloadOverview` 里的
   `setBaselineKey((key) => key + 1)` 是「文档变更 → 快照表自动刷新」的唯一触发器，
   `ProjectBaselinesTab` 的 `useEffect` 依赖 `[reload, refreshKey]`。
4. **申请接口仅管理员可读**：`GET /api/projects/{id}/applications` 对非 project_admin
   返回 403（`app/projects/router.py`），现有 `reloadApplications` 已用 `catch {}`
   静默降级为空数组——**合并后必须保留该降级**。

---

## 3. 顶层 Tab 最终形态

### 3.1 目标顺序（8 个）

| # | key | label | children | 备注 |
|---|---|---|---|---|
| 1 | `overview` | 概览 | `<Card>` + `Descriptions` + `ProjectTodoCard` | **不变** |
| 2 | `documents` | 文档 | `ProjectDocumentsTab` + **「版本快照」卡片** | 位置从 3 → 2 |
| 3 | `baseline-management` | 基线管理 | `ProjectBaselineManagementTab` | 位置从 5 → 3 |
| 4 | `incremental` | 增量分析 | `ProjectIncrementalTab` | 位置从 7 → 4 |
| 5 | `test-points` | 测试点 | `ProjectTestPointsTab` | 位置从 8 → 5 |
| 6 | `test-cases` | 测试用例 | `ProjectTestCasesTab` | 位置从 9 → 6 |
| 7 | `automation` | 自动化执行 | `ProjectAutomationTab` | 位置从 10 → 7 |
| 8 | `members` | 成员 | **`ProjectMembersTab`**（二级子菜单） | 位置从 2 → 8（末位） |

**移除的两个顶层 item**：

| 原 key | 原 label | 原行号 | 去向 |
|---|---|---|---|
| `baselines` | 版本快照 | [L317-L321](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L317-L321) | → 「文档」Tab 内的「版本快照」卡片 |
| `applications` | 申请 | [L329-L340](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L329-L340) | → 「成员」Tab 的「加入申请」子 Tab |

### 3.2 「成员」Tab 的二级结构

```
顶层 Tab「成员」
└── 二级 Tabs（data-testid="project-members-subtab"）
    ├── 「成员列表」  key=members         defaultActiveKey ← 默认选中
    │   ├── 添加成员按钮（仅 canManage 渲染）
    │   └── 成员表  data-testid="member-table"
    └── 「加入申请」  key=applications
        └── 申请表  data-testid="application-table"   ← 本期新增锚点
```

**设计理由**：与「基线管理 → 功能基线/流程基线」
（[ProjectBaselineManagementTab.tsx](file:///d:/aitest_copilot/web/src/pages/ProjectBaselineManagementTab.tsx)）
**完全同构**——同一套既有约定，不是新发明：

| 约定 | 基线管理 | 成员（本期） |
|---|---|---|
| 二级 Tabs 用 `defaultActiveKey`（非受控） | `defaultActiveKey="function"` | `defaultActiveKey="members"` |
| 外层容器带 `data-testid` | `process-baseline-subtab` | `project-members-subtab` |
| 每个 label 用 `<span data-testid>` 包裹 | `process-baseline-subtab-function` | `project-members-subtab-members` |
| 默认停在第一个子 Tab | 功能基线 | 成员列表 |

**为什么默认停在「成员列表」**：
`member-table` 在
[test_smoke.py L52-L57](file:///d:/aitest_copilot/tests/e2e/test_smoke.py#L52-L57)、
[test_projects_ui.py L80-L87](file:///d:/aitest_copilot/tests/e2e/test_projects_ui.py#L80-L87)、
[test_access_ui.py L36-L37](file:///d:/aitest_copilot/tests/e2e/test_access_ui.py#L36-L37)
三处 e2e 里被直接断言「可见」——默认停在「成员列表」让这 3 处**零改动**。

### 3.3 「文档」Tab 的新结构

```
顶层 Tab「文档」
└── Space direction="vertical"
    ├── ProjectDocumentsTab        （文档列表 + 上传 + 版本弹窗）
    └── Card title="版本快照"
        └── ProjectBaselinesTab    （data-testid="baseline-table"）
```

**为什么放在「文档」Tab 而不是「基线管理」**：
基线快照是「文档版本确认生效」的产物，语义归属文档；
且 `ProjectBaselinesTab`（文档版本快照表）与
`ProjectBaselineSnapshots`（基线审核快照）是**两个不同的东西**，
放进「基线管理」会出现两个「快照」概念并列，容易混淆。

**「版本快照」卡片的刷新链路**（**必须完整保留**）：

```
文档上传 / 确认生效
  → ProjectDocumentsTab.onChanged()
  → ProjectDetailPage.reloadOverview()
  → setBaselineKey(key => key + 1)
  → ProjectBaselinesTab 的 refreshKey prop 变化
  → useEffect([reload, refreshKey]) 触发重载
```

`ProjectBaselinesTab` 在「文档」Tab 内**始终挂载**（antd Tabs 切走不卸载），
所以不需要用户来回切 Tab 就能看到刷新——**比旧交互更好**。

---

## 4. 前端实现方案

### 4.1 目录与文件（本期前端只碰 2 个文件）

```
web/src/pages/ProjectDetailPage.tsx      （改）顶层 Tab 重排 + 快照内嵌 + 成员逻辑迁移
web/src/pages/ProjectMembersTab.tsx      （新）成员二级子菜单外壳
```

**明确不碰**（`git diff --stat` 必须为空）：

```
web/src/pages/ProjectBaselinesTab.tsx        （组件保留，挂载点变了，文件零改动）
web/src/pages/ProjectDocumentsTab.tsx        （props 不变，快照卡片内联在宿主里）
web/src/pages/ProjectTodoCard.tsx            （3 个跳转 key 全部保留）
web/src/pages/ProjectBaselineManagementTab.tsx（只改注释里的数字）
web/src/api/index.ts                         （listBaselines / listProjectApplications 都不动）
```

### 4.2 `ProjectDetailPage.tsx` 的改动清单

| # | 改动 | 说明 |
|---|---|---|
| 1 | **重排 `items` 数组**为 §3.1 的 8 项顺序 | 删 `baselines` / `applications` 两个 item；`documents` 提到第 2 位；`members` 移到末位 |
| 2 | **「文档」item 的 children 改成纵向布局** | `<Space direction="vertical">` 包 `ProjectDocumentsTab` + `<Card title="版本快照">` 包 `ProjectBaselinesTab` |
| 3 | **「成员」item 的 children 换成 `<ProjectMembersTab />`** | 内联 JSX 全部下沉 |
| 4 | **成员相关代码迁移到子组件** | 见 §4.4 迁移对照表（是**迁移**不是删除） |
| 5 | **`baselineKey` 链路保留** | `baselineKey` state 与 `reloadOverview` 里的自增**一个字节都不动** |
| 6 | **`reloadApplications` 的静默降级保留** | `catch {}` → `setApplications([])`，403 不弹 toast |

### 4.3 `ProjectMembersTab.tsx` 的 Props 契约

```ts
interface Props {
  projectId: number
  members: Member[]
  applications: Application[]
  /** 写入口限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canManage: boolean
  onSubmitAddMember: (userId: number, role: string) => Promise<void>
  onChangeRole: (member: Member, role: string) => Promise<void>
  onRemoveMember: (member: Member) => Promise<void>
}
```

**为什么是受控组件**（state 与 loader 留在父组件）：

1. `canManage` 的判定依赖 `myRole`，而 `myRole` 来自 `members`
   （[ProjectDetailPage.tsx L88-L96](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L88-L96)）——
   父组件本来就必须持有 `members`；
2. **数据源单一**：不重复请求成员列表（否则进「成员」Tab 会打两次
   `GET /api/projects/{id}/members`）；
3. `reloadMembers` / `reloadApplications` 已在父组件的 `useEffect` 里
   （[L137-L142](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L137-L142)），
   移进子组件会让这两个请求脱离页面级生命周期。

### 4.4 迁移对照表（父组件 → 子组件）

| 内容 | 现位置（父组件） | 去向 |
|---|---|---|
| `memberColumns` | [L179-L228](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L179-L228) | → 子组件 |
| `applicationColumns` | [L230-L253](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L230-L253) | → 子组件 |
| `submitAddMember` / `changeRole` / `handleRemove` | [L144-L177](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L144-L177) | → 子组件 |
| 添加成员 Modal（含 `data-testid="modal-ok"`） | [L364-L391](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L364-L391) | → 子组件 |
| `PROJECT_ROLE_LABELS` | [L42-L46](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L42-L46) | → 子组件 |
| `APPLICATION_STATUS_LABELS` | [L48-L54](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L48-L54) | → 子组件 |
| `STATUS_COLORS` | [L56-L62](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L56-L62) | → 子组件 |

**留在父组件的**：

| 内容 | 行号 | 原因 |
|---|---|---|
| `members` / `applications` state | [L80-L81](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L80-L81) | 受控传参 + `myRole` 权限判定 |
| `reloadMembers` / `reloadApplications` | [L119-L135](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L119-L135) | 页面级生命周期 + 403 静默降级 |
| `canManage` / `canWrite` | [L88-L96](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L88-L96) | `myRole` 依赖 `members` |
| `baselineKey` + `reloadOverview` | [L77](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L77) / [L98-L108](file:///d:/aitest_copilot/web/src/pages/ProjectDetailPage.tsx#L98-L108) | 快照刷新链路 |
| `addMember` / `updateMemberRole` / `removeMember` 的 API 调用与 message 反馈 | — | 通过 props 传 handler，子组件只管渲染与交互 |

### 4.5 子组件的渲染约定

```tsx
<Tabs
  defaultActiveKey="members"
  data-testid="project-members-subtab"
  items={[
    {
      key: 'members',
      label: <span data-testid="project-members-subtab-members">成员列表</span>,
      children: (/* 添加成员按钮 + member-table */),
    },
    {
      key: 'applications',
      label: <span data-testid="project-members-subtab-applications">加入申请</span>,
      children: (/* application-table */),
    },
  ]}
/>
```

**组件文件行数**：预估 **~180 行**（< 400 行阈值，验证约定 §4.3）。
父组件 `ProjectDetailPage.tsx` **做减法**（394 行 → ~300 行）。

---

## 5. e2e 断言改动（本期核心工作量）

### 5.1 ⚠️ 已实测确认的 Playwright 匹配语义

用 playwright 1.65.2 在本机实测（DOM 里放顶层 `成员` + 内层 `成员列表` 两个 `role="tab"`）：

| 写法 | 命中数 | 命中内容 |
|---|---|---|
| `get_by_role("tab", name="成员")` | **2** | `['成员', '成员列表']` ← **子串匹配** |
| `get_by_role("tab", name="成员", exact=True)` | **1** | `['成员']` |
| `get_by_role("tab", name="自动化执行")` | 1 | `['自动化执行']` |
| `get_by_role("tablist").first.get_by_role("tab", name="成员")` | **1** | `['成员']` |

裸 `get_by_role("tab", name="成员").click()` 直接抛 **strict mode violation**
（resolved to 2 elements）。

**根因**：Playwright 的 `name=` 默认是**子串、不区分大小写**匹配
（`exact=False` → 属性选择器带 `i` 标志，
见 `playwright/_impl/isomorphic/string_utils.py:75-87`）。

**对本期的直接影响**：
顶层「成员」与内层「成员列表」**名字互相包含** →
顶层 Tab 的计数与点击断言必须**要么加 `exact=True`、要么限定 `tablist`**。

### 5.2 三份重复的 `TAB_NAMES` / `TAB_ANCHORS`

`test_tabs_ui.py` [L21-L46](file:///d:/aitest_copilot/tests/e2e/test_tabs_ui.py#L21-L46)、
`test_t116_closing_ui.py` [L31-L55](file:///d:/aitest_copilot/tests/e2e/test_t116_closing_ui.py#L31-L55)、
`test_t123_closing_ui.py` [L31-L55](file:///d:/aitest_copilot/tests/e2e/test_t123_closing_ui.py#L31-L55)
是三份**完全复制粘贴**的副本。

**统一改为**：

```python
TAB_NAMES = [
    "概览",
    "文档",
    "基线管理",
    "增量分析",
    "测试点",
    "测试用例",
    "自动化执行",
    "成员",
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

- 「版本快照」「申请」两项**删除**（不再有顶层 Tab）；
- 「成员」的锚点仍是 `member-table`——**默认就在「成员列表」子 Tab 里**，断言逻辑不变；
- 计数断言 `expect(tabs).to_have_count(len(TAB_NAMES))` **自动变 8**。

### 5.3 索引断言（4 处）

| 文件 | 旧 | 新 |
|---|---|---|
| `test_t116_closing_ui.py` [L104-L105](file:///d:/aitest_copilot/tests/e2e/test_t116_closing_ui.py#L104-L105) | `nth(9)`→自动化执行<br>`nth(8)`→测试用例 | `nth(7)`→成员<br>`nth(6)`→自动化执行 |
| `test_t123_closing_ui.py` [L161-L162](file:///d:/aitest_copilot/tests/e2e/test_t123_closing_ui.py#L161-L162) | 同上 | 同上 |
| `test_automation_ui.py` [L146-L148](file:///d:/aitest_copilot/tests/e2e/test_automation_ui.py#L146-L148) | `to_have_count(10)`<br>`nth(9)`/`nth(8)` | `to_have_count(8)`<br>`nth(7)`/`nth(6)` |
| `test_process_baseline_ui.py` [L163-L165](file:///d:/aitest_copilot/tests/e2e/test_process_baseline_ui.py#L163-L165) | 同上 | 同上 |

> ⚠️ **语义变化**：旧顺序里「自动化执行」是**最后一个**；
> 新顺序里「**成员**」是最后一个，「自动化执行」是**倒数第二个**。
> 所以「自动化执行仍是最后一个」这类**注释与语义断言**要同步改：
> ```python
> expect(top_tabs.nth(7)).to_contain_text("成员")
> expect(top_tabs.nth(6)).to_contain_text("自动化执行")
> ```

### 5.4 顶层计数断言必须限定 `tablist`

新结构下内层子 Tab 变多（成员内 2 个 + 基线管理内 2 个）。
antd 的 `Tabs` 非活动面板是**懒渲染**（`destroyOnHidden` 默认 false，
`@rc-component/tabs/es/TabPanelList/index.js`）——内层子 Tab 在**未进入**该顶层 Tab 时**不挂载**，
所以**进 Tab 之前**计数天然安全。

但循环**逐个点开**顶层 Tab 时，裸 `get_by_role("tab")` 的计数会变：

> **已实测**（本机 playwright 1.65.2 + 忠实复刻 antd v6 的 DOM 与
> `.rc-tabs-content-hidden { display: none }`）：
>
> | 场景 | 裸 `get_by_role("tab")` | `tablist.first` 内 |
> |---|---|---|
> | 刚进页面（内层未访问） | **8** | 8 |
> | 点开「基线管理」 | **10** | 8 |
> | 点开「成员」（基线管理已隐藏） | **10** | 8 |
> | 两个内层都访问过 | **10** | 8 |
>
> **规律：只有「当前激活」的顶层 Tab 的内层子 Tab 会被计入**
> （已离开的顶层 Tab 面板是 `display:none`，里面的子 Tab 不计入；
> `include_hidden=True` 才会数到 12）。
> 所以裸计数是 **8 + 2 = 10**，**不是 12**。

**因此**（3 处必改）：

| 文件 | 行号 | 改法 |
|---|---|---|
| `test_t116_closing_ui.py` | [L88](file:///d:/aitest_copilot/tests/e2e/test_t116_closing_ui.py#L88) | `get_by_role("tab")` → `get_by_role("tablist").first.get_by_role("tab")` |
| `test_tabs_ui.py` | [L58](file:///d:/aitest_copilot/tests/e2e/test_tabs_ui.py#L58) | 同上 |
| `test_automation_ui.py` | [L145](file:///d:/aitest_copilot/tests/e2e/test_automation_ui.py#L145) | 同上 |

（`test_t123_closing_ui.py` [L145](file:///d:/aitest_copilot/tests/e2e/test_t123_closing_ui.py#L145)
与 `test_process_baseline_ui.py` [L162](file:///d:/aitest_copilot/tests/e2e/test_process_baseline_ui.py#L162)
**已经**用了 `get_by_role("tablist").first`，**无需改**。）

> ⚠️ **`test_t116_closing_ui.py` 的索引断言位置特别关键**：
> 它的 `expect(tabs.nth(9))` 在**点击循环之后**
> （[L104-L105](file:///d:/aitest_copilot/tests/e2e/test_t116_closing_ui.py#L104-L105)），
> 此时裸 locator 已有 10 个 tab → `nth(9)` 会命中**内层子 Tab** 而不是顶层第 10 个。
> 把 L88 改成 `tablist.first` 后，索引断言自动回到顶层语义。
> `test_tabs_ui.py` 的索引断言在**点击循环之前**，改成 `tablist.first` 同样更保险。

### 5.5 循环内点击必须加 `exact=True`

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

顶层 Tab 名与内层子 Tab 名无重复（子 Tab 名是「成员列表」「加入申请」「功能基线」「流程基线」），
`exact=True` 后不会误命中。

### 5.6 其余顶层 Tab 的点击：保持原样

下列文件点的是**顶层 Tab**，且顶层 Tab 名与内层子 Tab 名**不构成子串包含关系**
（文档 / 概览 / 基线管理 / 增量分析 / 测试点 / 测试用例 / 自动化执行），
**不需要改**：

| 文件 | 行号 | 说明 |
|---|---|---|
| `test_documents_ui.py` | [L66](file:///d:/aitest_copilot/tests/e2e/test_documents_ui.py#L66) / [L118](file:///d:/aitest_copilot/tests/e2e/test_documents_ui.py#L118) / [L189](file:///d:/aitest_copilot/tests/e2e/test_documents_ui.py#L189) | 文档 / 概览 |
| `test_baselines_ui.py` | 6 处 | 基线管理 |
| `test_incremental_ui.py` | 2 处 | 增量分析 |
| `test_incremental_apply_ui.py` | 2 处 | 增量分析 |
| `test_incremental_second_pass_ui.py` | 2 处 + 1 处文档 | 增量分析 / 文档 |
| `test_test_points_ui.py` | 2 处 | 测试点 |
| `test_test_cases_ui.py` | 1 处 | 测试用例 |
| `test_automation_ui.py` | [L87](file:///d:/aitest_copilot/tests/e2e/test_automation_ui.py#L87) / [L149](file:///d:/aitest_copilot/tests/e2e/test_automation_ui.py#L149) / [L392](file:///d:/aitest_copilot/tests/e2e/test_automation_ui.py#L392) | 自动化执行 |
| `test_llm_settings_ui.py` | [L122](file:///d:/aitest_copilot/tests/e2e/test_llm_settings_ui.py#L122) | 增量分析（系统设置页的「提示词模板」Tab 不受影响） |
| `test_todos_ui.py` | [L57](file:///d:/aitest_copilot/tests/e2e/test_todos_ui.py#L57) / [L63](file:///d:/aitest_copilot/tests/e2e/test_todos_ui.py#L63) / [L66](file:///d:/aitest_copilot/tests/e2e/test_todos_ui.py#L66) | 测试点 / 概览 / 测试用例 |
| `test_process_baseline_ui.py` | [L78](file:///d:/aitest_copilot/tests/e2e/test_process_baseline_ui.py#L78) / [L140](file:///d:/aitest_copilot/tests/e2e/test_process_baseline_ui.py#L140) / [L415](file:///d:/aitest_copilot/tests/e2e/test_process_baseline_ui.py#L415) | 基线管理 |

### 5.7 「申请」入口改写

`test_applications_ui.py` [L31](file:///d:/aitest_copilot/tests/e2e/test_applications_ui.py#L31)：

```python
# 旧：admin_page.get_by_role("tab", name="申请").click()
admin_page.get_by_role("tab", name="成员", exact=True).click()
admin_page.get_by_test_id("project-members-subtab-applications").click()
```

断言内容（`待审批` / `e2e 申请理由`）**原样保留**。

### 5.8 「版本快照」入口改写

`test_documents_ui.py` 三处（[L132](file:///d:/aitest_copilot/tests/e2e/test_documents_ui.py#L132)、
[L185](file:///d:/aitest_copilot/tests/e2e/test_documents_ui.py#L185)、
[L208](file:///d:/aitest_copilot/tests/e2e/test_documents_ui.py#L208)）：

```python
# 旧：admin_page.get_by_role("tab", name="版本快照", exact=True).click()
# 新：快照已挂进「文档」Tab，点「文档」即可
admin_page.get_by_role("tab", name="文档").click()
```

> ⚠️ **L185 / L208 的时序要点**：
> `test_ac_54_new_version_archives_old_and_baseline_refreshes` 的核心断言是
> 「**不刷新页面**，基线表应已重载」。
> 新流程：进「文档」Tab → **快照卡片随文档 Tab 一起挂载** → 追加 V2 →
> 确认生效 → `reloadOverview` → `baselineKey` 自增 →
> `ProjectBaselinesTab` 的 `useEffect([reload, refreshKey])` 触发重载。
> **断言依然成立**（`ProjectBaselinesTab` 在「文档」Tab 内始终挂载，切 Tab 不卸载）。
> L185 处的注释「先看一次基线，让组件挂载并缓存 V1」需改为「快照随文档 Tab 挂载」。

### 5.9 成员相关断言：零改动

| 文件 | 行号 | 说明 |
|---|---|---|
| `test_access_ui.py` | [L35-L37](file:///d:/aitest_copilot/tests/e2e/test_access_ui.py#L35-L37) | 点「成员」→ `member-table` 可见 → 「添加成员」按钮不可见 |
| `test_projects_ui.py` | [L63-L64](file:///d:/aitest_copilot/tests/e2e/test_projects_ui.py#L63-L64) / [L79-L87](file:///d:/aitest_copilot/tests/e2e/test_projects_ui.py#L79-L87) | 归档只读 / 成员管理 |
| `test_smoke.py` | [L51-L60](file:///d:/aitest_copilot/tests/e2e/test_smoke.py#L51-L60) | 成员表列头与内容 |

> ⚠️ **但 `name="成员"` 的裸写法要加 `exact=True`**：
> 顶层「成员」与内层「成员列表」构成子串关系，裸写法会 **strict mode violation**。
> 这 3 个文件共 **4 处** `get_by_role("tab", name="成员")` 要加 `exact=True`。

### 5.10 e2e 改动汇总

| 文件 | 改动点 | 数量 |
|---|---|---|
| `test_tabs_ui.py` | `TAB_NAMES` / `TAB_ANCHORS` / 计数限定 tablist / 循环加 `exact=True` | 4 处 |
| `test_t116_closing_ui.py` | 同上 + 索引 `nth(9)/nth(8)` → `nth(7)/nth(6)` | 5 处 |
| `test_t123_closing_ui.py` | 同上 + 索引改写 | 5 处 |
| `test_automation_ui.py` | 计数限定 tablist / `to_have_count(10)`→8 / 索引改写 | 3 处 |
| `test_process_baseline_ui.py` | `to_have_count(10)`→8 / 索引改写 | 3 处 |
| `test_documents_ui.py` | 3 处「版本快照」入口 → 「文档」Tab | 3 处 |
| `test_applications_ui.py` | 「申请」入口 → 成员 Tab → 子 Tab | 1 处 |
| `test_access_ui.py` | `name="成员"` 加 `exact=True` | 1 处 |
| `test_projects_ui.py` | `name="成员"` 加 `exact=True` | 2 处 |
| `test_smoke.py` | `name="成员"` 加 `exact=True` | 1 处 |

> **合计 10 个 e2e 文件**（不是 7 个——§5.9 的 3 个「成员」点击也要改）。
> 考虑到红线「单次不超过 5 个文件」，e2e 改动必须**拆成 2~3 个任务**（见 tasks.md）。

---

## 6. 文档同步（口径）

| 文件 | 位置 | 改动 |
|---|---|---|
| `README.md` | [L99](file:///d:/aitest_copilot/README.md#L99) | 「顶层 10 个 Tab：概览 / 成员 / 文档 / 版本快照 / 基线管理 / 申请 / 增量分析 / 测试点 / 测试用例 / 自动化执行」→「顶层 8 个 Tab：概览 / 文档 / 基线管理 / 增量分析 / 测试点 / 测试用例 / 自动化执行 / 成员」 |
| `PROGRESS.md` | [L298](file:///d:/aitest_copilot/PROGRESS.md#L298) | 同上；补一句「「成员」内含二级子菜单（成员列表 / 加入申请）」 |
| `PROGRESS.md` | [L328-L334](file:///d:/aitest_copilot/PROGRESS.md#L328-L334) | 「顶层 10 个 / 12」→「顶层 8 个 / 8+2=10」；**新增一条坑**：「`get_by_role(name=)` 默认子串匹配 → 顶层「成员」与内层「成员列表」冲突，须 `exact=True` 或限定 tablist」 |
| `specs/验证约定.md` | [L11](file:///d:/aitest_copilot/specs/验证约定.md#L11) | 前端现状行的 Tab 名单与数量 |
| `specs/验证约定.md` | [L496](file:///d:/aitest_copilot/specs/验证约定.md#L496) | 「顶层仍是 10 个」→「顶层仍是 8 个」 |
| `specs/验证约定.md` | [L504-L513](file:///d:/aitest_copilot/specs/验证约定.md#L504-L513) | 数字改 8；**新增一条**「`get_by_role(name=)` 默认子串匹配」的坑位说明 |
| `web/src/pages/ProjectBaselineManagementTab.tsx` | [L28-L30](file:///d:/aitest_copilot/web/src/pages/ProjectBaselineManagementTab.tsx#L28-L30) | 注释「顶层 Tab 仍然是 10 个 / `to_have_count(10)`」→「8 个 / `to_have_count(8)`」 |

**不改**：历史期次 spec（01~10）的归档内容——它们记录的是**当时的历史事实**。

---

## 7. AC 编号与任务映射

| AC | 主题 | 任务 | 测试位置 |
|---|---|---|---|
| **AC-215** | 顶层 Tab 收敛为 8 个 + 顺序正确 | T124 / T127 | `tests/e2e/test_tabs_ui.py` |
| **AC-216** | 「版本快照」内容并入「文档」Tab（`baseline-table` 仍可用） | T124 / T125 | `tests/e2e/test_documents_ui.py` |
| **AC-217** | 「申请」并入「成员」Tab 的「加入申请」子 Tab | T125 | `tests/e2e/test_applications_ui.py` |
| **AC-218** | 「成员」二级子菜单默认停在「成员列表」（现有路径不变） | T124 / T126 | `tests/e2e/test_access_ui.py` / `test_smoke.py` |
| **AC-219** | 零回归与红线（后端零改动 / 既有 e2e 全绿） | T127 / T128 | 全量套件 |

**AC 编号连续性**：10 期最后一号是 **AC-214**，本期从 **AC-215** 起（必须连续）。
**任务号连续性**：10 期收官是 **T123**，本期从 **T124** 起。

---

## 8. 红线声明

| # | 红线 | 验证方式 |
|---|---|---|
| 1 | **后端 `app/` 零改动** | `git diff --stat <base>..HEAD -- app/` → **为空** |
| 2 | **不删 `ProjectBaselinesTab.tsx`** | `git diff --stat <base>..HEAD -- web/src/pages/ProjectBaselinesTab.tsx` → **为空** |
| 3 | **不改 `ProjectDocumentsTab.tsx`** | 同上 → **为空**（快照卡片内联在宿主里，不透传 prop） |
| 4 | **不改 `ProjectTodoCard.tsx`** | 同上 → **为空**（3 个跳转 key 全保留） |
| 5 | **不改 `web/package.json`** | 同上 → **为空**（零新依赖） |
| 6 | **不新增/删除 e2e 用例** | e2e 全量仍是 **64 条** |
| 7 | **既有 e2e 断言改动仅限 Tab 路径与期望值** | 逐条 diff 复核（§5.10 的 10 个文件） |
| 8 | **顶层 Tab 恒为 8 个** | 三处 `to_have_count(8)` + 顺序断言 |

---

## 9. 风险登记

| 级别 | 风险 | 对策 |
|---|---|---|
| **P0** | `tsc` 的 `noUnusedLocals` 因迁移残留变量而构建失败 | 迁移对照表（§4.4）逐项清空父组件；`npm run build` 立即暴露 |
| **P0** | 顶层「成员」与内层「成员列表」**子串冲突** → strict mode violation | 已实测确认；顶层断言统一 `exact=True` + 限定 `tablist`（§5.1 / §5.4 / §5.5） |
| **P0** | 内层子 Tab 污染顶层 Tab 计数（8 → 12） | 顶层计数统一 `get_by_role("tablist").first`（§5.4） |
| **P0** | 「加入申请」子 Tab 对非管理员触发 403 toast | 保留 `reloadApplications` 的 `catch {}` 静默降级；人工核对点专门验证 |
| **P1** | `member-table` 不在默认子 Tab → 3 个既有 e2e 失效 | `defaultActiveKey="members"`；人工核对点验证 |
| **P1** | AC-54 的「不刷新页面基线自动重载」时序失效 | `baselineKey` 链路保留；e2e `test_ac_54` 覆盖该场景 |
| **P1** | 父组件 `canManage` 依赖 `myRole`（依赖 `members`）→ 迁移时形成循环依赖 | 父组件持有 `members` state、子组件受控（§4.3） |
| **P2** | 「自动化执行不再是最后一个 Tab」语义注释过时 | §5.3 同步改索引与语义注释 |

---

## 10. Backlog（本期不做，等用户点头）

- 「成员」Tab 内的申请列表**支持审批操作**（当前只读展示，与原「申请」Tab 行为一致）；
- 「版本快照」表支持**按文档筛选** / **导出**；
- 顶层 Tab 支持 **URL 记忆**（`?tab=xxx`）——目前切 Tab 不写 URL，刷新会回到「概览」；
- 「成员」二级子菜单支持**未读角标**（有 N 条待审批申请时在「成员」Tab 上提示）；
- [x] **修掉 e2e 既有 flaky**（2026-11-28 已修）：`tests/e2e/test_t123_closing_ui.py::test_ac_214_process_baseline_full_flow`
  在「文档反推」那步点 Select 选项会超时
  （`.ant-select-dropdown:visible .ant-select-item-option` has_text="支付需求"）。
  **根因**（实测采样定位，不是「慢」也不是动画时序）：`ProcessBaselineDeriveModal`
  打开时才异步拉文档列表，在数据到达前点开下拉，`options` 由 `[]` 变有值触发重渲染，
  **antd Select 把下拉关掉了**——之后 30 秒 `.ant-select-dropdown:visible` 恒为 0
  （而 `.ant-select-item-option` 一直在 DOM 里）。
  **修法**：加载期间给文档下拉加 `loading` + `disabled`；e2e 补条件等待。
  连跑 3 次 + 全量 e2e 77 passed 稳定。坑位见 `PROGRESS.md` §4 第 13 条。

---

## 11. 待 review

本文与 [plan.md](./plan.md) / [tasks.md](./tasks.md) 配套，**未写任何业务代码**。
评审通过后才按 tasks.md 逐任务落地。
