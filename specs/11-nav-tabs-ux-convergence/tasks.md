# 11 · 导航栏 UX 收敛 · 任务清单

> 配套 [spec.md](./spec.md)（AC-215 ~ AC-219）与 [plan.md](./plan.md)。
> 执行口径一律以 [specs/验证约定.md](../验证约定.md) 为准，本文件不重复展开。
> 每个任务 = 一个提交，提交信息写清「做了什么 / 为什么」。
> **未明确要求不推送、不打 tag。**

## 0. 前置条件与基线（2026-11-24 核实）

| 项 | 基线 |
|---|---|
| 10 收官 | T117~T123 完成，两库 head `0025` |
| 后端全量 | **1444 passed**（串行，e2e 默认 `-m "not e2e"`） |
| e2e 全量 | **64 passed**（`scripts\run_e2e.py`） |
| 前端 | `npm run build` 通过；项目详情 **10 个 Tab**；基线管理内含二级子菜单 |
| 迁移 head | 两库均 `0025`（**本期不写迁移**） |
| PRD | 无新增 PRD 条目——本期是用户 2026-11-24 的**体验反馈驱动的 UX 收敛** |
| 环境自检 | `python scripts\dev_check.py` 全 `[ OK ]`；跑前台加 `--expect-db e2e` |
| 用户拍板 | ① 隐藏「版本快照」（只移除入口、不删代码）② 合并「申请」进「成员」③ 成员内部用**二级 Tabs** ④ 快照内容挂进「文档」Tab ⑤ **前端只改 2 个文件** ⑥ **文档一并同步** |
| AC 编号 | **AC-215 ~ AC-219**（10 期最后一号是 AC-214，必须连续） |
| 任务号 | **T124 ~ T128**（10 期收官是 T123） |
| 红线 | **每个任务改动文件数 ≤ 5**（验证约定 §2 第 5 条「细颗粒度交付」） |

## 1. 执行约定

1. **开跑前自检**：`.\.venv\Scripts\python.exe scripts\dev_check.py`，
   任一 `[FAIL]` 先修环境再动代码。
2. **定向 → 全量 → e2e → 构建**：
   - 定向：`.\.venv\Scripts\python.exe scripts\run_e2e.py -k ac_XXX`
   - 全量：`.\.venv\Scripts\python.exe -m pytest`（**串行**）
   - e2e：`.\.venv\Scripts\python.exe scripts\run_e2e.py`（自带自检与收尾）
   - 构建：`cd web; npm run build`
3. **用例命名**：e2e `test_ac_<AC号>_<场景>_ui`，与 spec 的 AC 编号一一对应。
4. **零真实 socket**：本期不引入任何网络客户端。
5. **不改既有期望值**：01~10 的 1444 条后端用例一条不删、不改断言。
6. **后端零改动**：`app/` 目录本期的 `git diff --stat` 必须**为空**。
7. **前台必须真点**：前端任务结束在浏览器里走一遍，截图落 `.screenshots/<任务号>/`，
   **文件名含 AC 编号**。
8. **文档回填**：T127 补 `README.md` / `PROGRESS.md` / `specs/验证约定.md`；
   T128 补收官总结与本文件 §4 验证记录表。

## 2. 任务拆分

### T124 前端收敛：顶层 10 → 8 个 Tab + 「成员」二级子菜单 + 顶层计数断言

**文件数**：**5**（红线要求 ≤ 5）

**前置**：`dev_check.py` 全 `[ OK ]`；T123 已提交。

**背景**：用户 2026-11-24 体验反馈——顶层 10 个 Tab 太多，要求彻底收敛：
隐藏「版本快照」、合并「申请」进「成员」、重排顺序。

**产出**

- `web/src/pages/ProjectMembersTab.tsx`（**新增**）：「成员列表」/「加入申请」
  二级 Tabs 外壳（`defaultActiveKey="members"`）+ 成员表 + 申请表
  + 添加成员 Modal + 列定义 + 角色/状态文案常量
- `web/src/pages/ProjectDetailPage.tsx`：`items` 数组重排为 8 项
  （删 `baselines` / `applications`，`documents` 提到第 2 位、`members` 垫底）；
  「文档」item 内嵌「版本快照」卡片；「成员」item 换成 `<ProjectMembersTab />`；
  成员相关代码迁移到子组件
- `tests/e2e/test_tabs_ui.py`：`TAB_NAMES` / `TAB_ANCHORS` 改 8 项；
  顶层计数限定 `get_by_role("tablist").first`；循环内点击加 `exact=True`
- `tests/e2e/test_automation_ui.py`：顶层计数限定 tablist；
  `to_have_count(10)` → `8`；`nth(9)/nth(8)` → `nth(7)/nth(6)`
- `tests/e2e/test_process_baseline_ui.py`：`to_have_count(10)` → `8`；
  `nth(9)/nth(8)` → `nth(7)/nth(6)`

**关键实现约束**

- `baselineKey` state 与 `reloadOverview` 里的 `setBaselineKey(key => key + 1)`
  **一个字节都不动**——它是「文档变更 → 快照表自动刷新」的唯一触发器
- `reloadApplications` 的 `catch {}` **静默降级**保留——非管理员进「加入申请」
  子 Tab 显示空列表、不弹 403 toast
- `canManage` / `canWrite` 判定**留在父组件**——`myRole` 依赖 `members`，
  子组件是**受控**的（props 传 `members` / `applications` / handler）
- `ProjectBaselinesTab.tsx` / `ProjectDocumentsTab.tsx` / `ProjectTodoCard.tsx`
  **一个字节都不改**
- ⚠️ `tsconfig.app.json` 的 `noUnusedLocals: true`——迁移后父组件里残留任何一个
  未使用的 import / 常量 / state，`npm run build` 会**直接失败**

**验证**

- `cd web; npm run build` 通过
- `cd web; npm run lint` 通过
- 后端全量：`.\.venv\Scripts\python.exe -m pytest` → **1444 passed**（零回归，
  后端未改动）
- e2e：**🔴 预期红**（7 个文件红——`t116` / `t123` 仍写死 10 项、
  `documents` / `applications` 入口路径已变、`access` / `projects` / `smoke`
  的 `name="成员"` 会 strict violation）。
  **这是预期内的红窗，不是回归**——见 §3「预期红窗」。
  定向：`run_e2e.py -k "tabs or automation or process_baseline"` → 这 3 个文件必须绿
- 人工核对（`http://localhost:5173`，`admin` / `Admin12345`）：
  ① 顶层 **8 个** Tab，顺序 概览 → 文档 → 基线管理 → 增量分析 → 测试点 →
  测试用例 → 自动化执行 → 成员；② 顶层**没有**「版本快照」「申请」；
  ③ 「文档」Tab 内**能看到「版本快照」卡片**；④ 「成员」Tab 内有**两个二级 Tab**
  （成员列表 / 加入申请），默认停在「成员列表」
- 红线：`git diff --stat <base>..HEAD -- app/` → **为空**；
  `-- web/src/pages/ProjectBaselinesTab.tsx` / `ProjectDocumentsTab.tsx` /
  `ProjectTodoCard.tsx` → **均为空**
- 截图：`.screenshots/T124/`（文件名含 AC-215 / AC-216 / AC-218）

**AC**：AC-215、AC-216、AC-218
**提交**：`feat(web): 顶层 Tab 收敛为 8 个与成员二级子菜单`

**T124 补充记录（执行情况）**

- **文件数正好 5 个**（红线 ≤ 5）：`ProjectMembersTab.tsx`（新）/
  `ProjectDetailPage.tsx` / `test_tabs_ui.py` / `test_automation_ui.py` /
  `test_process_baseline_ui.py`。
- **`ProjectDetailPage.tsx` 373 → 239 行**（只做减法：删两个顶层 item +
  成员逻辑迁走；新增「版本快照」卡片约 10 行）。新组件 246 行（< 400 阈值）。
- **`noUnusedLocals` 挡了 3 处**（`tsconfig.app.json` 开着）：
  ① 子组件的 `projectId` prop 没用上——**去掉**（handler 在父组件闭包里已带
  `projectId`，子组件根本不需要）；② 父组件的 `Button` / `Table` import 迁走后
  没人用了——**删掉**。这是本任务最容易踩的坑。
- **保住了一个原行为**：「添加成员」失败时**弹窗保持打开**（用户能直接改值重试）。
  原实现里 `setAdding(false)` 在 `try` 内、API 调用成功之后；拆成受控组件后
  子组件拿不到「成功还是失败」→ `onSubmitAddMember` 改成**返回 boolean**，
  父组件 `catch` 分支返回 `false`，子组件据此决定关不关弹窗。
- **子组件是受控的**：`members` / `applications` / 三个 handler 全部由父组件持有
  （`canManage` 依赖 `myRole`，而 `myRole` 来自 `members`——
  放子组件会让父组件拿不到角色，形成循环依赖）。副作用：**不重复请求成员列表**。
- **「版本快照」卡片的刷新链路一个字节没动**：`baselineKey` state +
  `reloadOverview` 里的 `setBaselineKey(key => key + 1)` 都在原位，
  `ProjectBaselinesTab` 的 props 也没变——只是从顶层 Tab 换成了「文档」Tab
  里的卡片。浏览器实测：开发库里已有 V1/V2/V3 三条真实基线，卡片里能看到。
- **浏览器实跑核对**（`http://localhost:5173`，`admin` / `Admin12345`）：
  ① 顶层**恰好 8 个** Tab，顺序 概览 → 文档 → 基线管理 → 增量分析 → 测试点 →
  测试用例 → 自动化执行 → 成员；② 顶层**没有**「版本快照」「申请」；
  ③ 「文档」Tab 内「版本快照」卡片可见，**3 行真实数据**（V1/V2/V3）；
  ④ 「成员」Tab 内两个二级子 Tab，**默认停在「成员列表」**，成员表 + 「添加成员」
  按钮都在；⑤ 切「加入申请」→ 申请表出现（空态「暂无数据」，符合预期——
  开发库里没有待审批申请）；⑥ 「基线管理」的功能基线 / 流程基线嵌套**未被破坏**；
  ⑦ 8 个顶层 Tab 逐个点开，**无崩溃、无空白页、无错误 toast**；
  ⑧ 控制台无 JS 报错、无 4xx/5xx（只有 4 条 AntD 废弃 API 警告，
  与本次重构无关）。
- **红线 diff 实测**（基准 = `dd4f3d4`）：
  `git diff --stat HEAD -- app/` → **为空**；
  `-- web/src/pages/ProjectBaselinesTab.tsx` / `ProjectDocumentsTab.tsx` /
  `ProjectTodoCard.tsx` / `web/package.json` → **均为空**。
- **全量数字**：后端全量 **1444 passed**（串行，exit 0，483.21s，64 deselected）；
  e2e 全量 **59 passed / 5 failed**——**5 个失败全是 T125 范围的预期红窗**
  （`t116` / `t123` 仍写死 10；`applications` / `documents`×2 入口路径已变），
  T124 自身的 3 个 e2e 文件**全绿**。前端构建通过、lint **0 errors**。

---

### T125 e2e 入口路径改写 + 收官核对断言

**文件数**：**4**（红线要求 ≤ 5）

**前置**：T124 已提交。

**背景**：顶层 Tab 从 10 变 8 是**原子变更**——旧 e2e 的 `to_have_count(10)` 与
`name="版本快照"` / `name="申请"` 必然同时失效。本任务把剩下两个 e2e 文件的
顶层名单与入口路径全部改到位。

**产出**

- `tests/e2e/test_t116_closing_ui.py`：`TAB_NAMES` / `TAB_ANCHORS` 改 8 项；
  顶层计数限定 `get_by_role("tablist").first`；循环内点击加 `exact=True`；
  `nth(9)/nth(8)` → `nth(7)`→成员 / `nth(6)`→自动化执行；
  docstring 里的「10 个 Tab」名单同步改
- `tests/e2e/test_t123_closing_ui.py`：同上（`top_tabs` 本来就限定了 tablist，
  只需改名单 / `exact=True` / 索引 / docstring）
- `tests/e2e/test_documents_ui.py`：3 处
  `get_by_role("tab", name="版本快照", exact=True).click()` →
  `get_by_role("tab", name="文档").click()`；
  L185 的注释「先看一次基线，让组件挂载并缓存 V1」改为「快照随文档 Tab 挂载」
- `tests/e2e/test_applications_ui.py`：L31
  `get_by_role("tab", name="申请").click()` →
  `get_by_role("tab", name="成员", exact=True).click()` +
  `get_by_test_id("project-members-subtab-applications").click()`；
  断言内容（`待审批` / `e2e 申请理由`）**原样保留**

**关键实现约束**

- ⚠️ **AC-54 的时序**（`test_documents_ui.py::test_ac_54_new_version_archives_old_and_baseline_refreshes`）：
  断言的是「**不刷新页面**，基线表应已重载」。新流程下快照卡片随「文档」Tab
  一起挂载，`baselineKey` 自增照样触发 `ProjectBaselinesTab` 的重载 →
  **断言依然成立**，不要改断言内容，只改导航路径。
- ⚠️ 「申请」子 Tab 的定位**必须用 `data-testid`**（`project-members-subtab-applications`），
  不能用 `get_by_role("tab", name="加入申请")`——顶层「成员」与内层「成员列表」
  构成子串关系（见 §3 坑位 ①）。

**验证**

- e2e：**🔴 预期红**（3 个文件红——`access` / `projects` / `smoke` 的
  `name="成员"` 会 strict violation）。
  定向：`run_e2e.py -k "closing or documents or applications"` → 这 3 个文件必须绿
- 后端全量：`pytest` → **1444 passed**（零回归）
- `cd web; npm run build` 通过（**未改动前端**，仅回归确认）
- 人工核对：
  ① 「文档」Tab → 上传文档 → 确认生效 → **不刷新页面**，「版本快照」卡片
  里的表**自动出现 V1**；② 「成员」Tab → 点「加入申请」子 Tab → 能看到申请行
- 红线：`git diff --stat <base>..HEAD -- app/` → **为空**
- 截图：`.screenshots/T125/`（文件名含 AC-216 / AC-217）

**AC**：AC-216、AC-217
**提交**：`test(e2e): 顶层 Tab 断言改 8 项与两处入口路径改写`

**T125 补充记录（执行情况）**

- **文件数正好 4 个**（红线 ≤ 5）。
- **e2e 全量直接转绿：64 passed**（218.60s）——比 tasks.md §3 预测的
  「T125 后还剩 3 个文件红」**更早**。原因见下面「实测纠正」。
- **AC-54 的时序断言保住了**：断言内容（V1 / V2 / 已生效 / 已归档）**一个字没动**，
  只把「切到版本快照 Tab 看」改成「在文档 Tab 里直接看快照卡片」——
  快照卡片随文档 Tab 常驻（Tabs 切走不卸载），`baselineKey` 自增照样触发重载。
  **顺带把用例简化了**：原先要「先看一次基线让组件挂载 → 回文档页 → 再看基线」
  来回切 3 次 Tab，现在全程在「文档」Tab 里，少 2 次 Tab 切换。
- **实测纠正：裸 `name="成员"` 到底会不会 strict violation**
  —— **只在「成员」Tab 正处于激活状态时才会**。

  在真实页面（8001/5174）上实测的命中数：

  | 场景 | 裸 `name="成员"` | `exact=True` | 内层子 Tab 在 DOM |
  |---|---|---|---|
  | 刚进详情页（默认停在概览） | **0** | 0 | 0 |
  | 点开「成员」之后 | **2** ⚠️ | 1 | 1 |
  | 离开「成员」（切到概览）之后 | **1** | 1 | 1 |

  **根因**：内层「成员列表」是**懒渲染**的（antd `Tabs` 的 `forceRender` 默认
  undefined，未激活的面板不进 DOM）。所以：
  - 「成员」没被点开过 → 内层子 Tab **根本不在 DOM** → 裸写法安全；
  - 「成员」正激活 → 内层子 Tab 在 DOM 里 → 裸写法命中 2 个 → strict violation；
  - 「成员」访问过又离开 → 面板变 `display:none`（`removeOnLeave` 为 false，
    DOM 保留但不可见）→ Playwright 默认 `include_hidden=False` →
    **不可见的元素不计入** → 裸写法又安全了。

  → **`test_access_ui.py` / `test_projects_ui.py` / `test_smoke.py` 里那 4 处
  裸 `name="成员"` 都是「第一次点开成员」**（之前没点过成员 Tab），
  所以**不会** strict violation——**T126 的这 4 处修改在当前用例路径下不是必需的**。
- **必须加 `exact=True` 的是 `test_applications_ui.py` 那一处**——
  它是「先点顶层成员 → 再点子 Tab」，点完之后内层子 Tab 已在 DOM 且可见，
  同一个用例里若再有一次裸 `name="成员"` 就会撞。
- **跑出来一个既有 flaky**（与本次改动无关）：
  `test_ac_214_process_baseline_full_flow` 在文档反推那步点 Select 选项超时
  （`.ant-select-dropdown:visible .ant-select-item-option` has_text="支付需求"）。
  **单跑通过**（1 passed），**定向跑通过**（14 passed），**全量跑也通过**
  （64 passed）——属于 10 期遗留的时序抖动，**没有改它**（红线：本任务只改
  T125 范围内的 4 个文件）。
- **红线 diff 实测**（基准 = T124 的 `4467b79`）：
  `git diff --stat HEAD -- app/` → **为空**；
  `-- web/` → **为空**（本任务纯 e2e 断言改写，**前端一个字节都没动**）。
- **全量数字**：后端全量 **1444 passed**（串行，exit 0，**跑了两遍**：
  732.94s / 678.68s，64 deselected）；e2e 全量 **64 passed**（218.60s，
  **条数与 T123 持平**——只改断言，未增删用例）；`npm run build` 通过。

---

### T126 「成员」点击精确化（收掉 strict mode violation）

**文件数**：**3**（红线要求 ≤ 5）

**前置**：T125 已提交。

**背景**：顶层「成员」与内层「成员列表」**名字互相包含**，而 Playwright 的
`get_by_role(name=)` 默认是**子串匹配**（`exact=False` → 选择器带 `i` 标志），
裸写法**在「成员」Tab 激活时**会 strict violation。本任务把这 4 处收掉。

> ⚠️ **T125 实测后的范围修正**：这 4 处（`test_access_ui.py` L35、
> `test_projects_ui.py` L63/L79、`test_smoke.py` L51）**都是「第一次点开成员」**，
> 而内层子 Tab 是**懒渲染**的（未激活时不在 DOM）→ 裸写法**当前不会**报错。
> 所以本任务**不是修 bug，是加固**——把「靠用例路径恰好安全」变成「写法本身就安全」。
> 保留它的理由：① 用例顺序或路径一变（比如将来某个用例先访问过成员 Tab 再回来）
> 就会撞上 strict violation；② `exact=True` 是**语义正确**的写法——
> 本来要的就是顶层那个「成员」。

**产出**

- `tests/e2e/test_access_ui.py`：L35 `get_by_role("tab", name="成员")` → 加 `exact=True`
- `tests/e2e/test_projects_ui.py`：L63、L79 同上
- `tests/e2e/test_smoke.py`：L51 同上

**关键实现约束**

- 只加 `exact=True` 这一个参数，**断言内容一个字节都不改**
  （`member-table` 可见、「添加成员」按钮不可见等）
- `defaultActiveKey="members"` 保证「成员列表」是默认子 Tab →
  这 3 个文件的断言逻辑**天然成立**，不需要先点子 Tab

**验证**

- e2e 全量：**🟢 64 passed**（本任务完成后 e2e 全部转绿）
- 后端全量：`pytest` → **1444 passed**（零回归）
- `cd web; npm run build` 通过（**未改动前端**，仅回归确认）
- 人工核对：用**普通成员**账号登录 → 「成员」Tab 能正常进入；
  「加入申请」子 Tab 显示**空列表**且**不报错**（403 静默降级）
- 红线：`git diff --stat <base>..HEAD -- app/` → **为空**
- 截图：`.screenshots/T126/`（文件名含 AC-218）

**AC**：AC-218
**提交**：`test(e2e): 成员 Tab 定位加 exact 避免子串误命中`

**T126 补充记录（执行情况）**

- **文件数正好 3 个**（红线 ≤ 5），**4 处**加 `exact=True`：
  `test_access_ui.py` L37、`test_projects_ui.py` L64/L81、`test_smoke.py` L52。
  **断言内容一个字没动**——只加了 `exact=True` 参数 + 一行说明注释。
- **这是加固，不是修 bug**（依据见上面的「范围修正」框）：
  T125 已实测确认这 4 处当前不会报错，本任务把「靠用例路径恰好安全」
  变成「写法本身就安全」。
- **又撞到同一个既有 flaky**：`test_ac_214_process_baseline_full_flow`
  在文档反推那步点 Select 选项超时。
  **第一次全量跑失败（1 failed / 63 passed）→ 单跑通过（1 passed）→
  第二次全量跑通过（64 passed）**。
  这是本任务第二次撞到它（T125 也撞过一次），**确认是 10 期遗留的时序抖动，
  不是本次改动引入**——该用例的代码 T124~T126 三次都没碰过。
  按红线「本任务只改 3 个文件」，**没有动它**，登记到 Backlog。
- **红线 diff 实测**（基准 = T125 的 `1265c64`）：
  `git diff --stat HEAD -- app/` → **为空**；`-- web/` → **为空**
  （本任务纯 e2e 定位加固，**前端一个字节都没动**）。
- **全量数字**：后端全量 **1444 passed**（串行，exit 0，380.77s，64 deselected）；
  e2e 全量 **64 passed**（214.80s，**条数与 T123 持平**）；
  `npm run build` 通过。

---

### T127 文档口径同步：8 个 Tab + 新增子串匹配坑位

**文件数**：**4**（红线要求 ≤ 5）

**前置**：T126 已提交。

**背景**：项目文档里到处写着「顶层 10 个 Tab」，还有一条「Tab 计数要限定顶层 tablist」
的坑位说明。本期把口径改到 8 个，并补一条**新坑**——
`get_by_role(name=)` 默认子串匹配。

**产出**

- `README.md`：L99「前端 Tab 宿主」一行 → 「顶层 8 个 Tab：概览 / 文档 / 基线管理 /
  增量分析 / 测试点 / 测试用例 / 自动化执行 / 成员」
- `PROGRESS.md`：§4 现状表的「项目详情 Tab」行 → 8 个 + 补一句
  「「成员」内含二级子菜单（成员列表 / 加入申请）」；
  §4「两个已知的坑」里的 antd 两层 Tabs 那条 → 数字改 8 + 2 = 10；
  **新增一条坑**：`get_by_role(name=)` 默认子串匹配 → 顶层「成员」与内层「成员列表」
  冲突，须 `exact=True` 或限定 tablist
- `specs/验证约定.md`：§1 现状的前端行 → 8 个 Tab 名单；
  §5.13 的「顶层仍是 10 个」→ 「8 个」；§5.13 的「Tab 计数要限定顶层 tablist」
  小节数字改 8 + 2 = 10；**新增 §5.14**「11-nav-tabs-ux-convergence · 导航栏 UX 收敛」
  的前台核对点（§5.13 是 10 期，**不得重号**）
- `web/src/pages/ProjectBaselineManagementTab.tsx`：注释里的
  「顶层 Tab 仍然是 10 个」/「`to_have_count(10)`」→ 8 个（**仅注释**，
  组件逻辑一个字节都不改）

**关键实现约束**

- **不改历史期次 spec（01~10）的归档内容**——它们记录的是当时的历史事实
  （例如 10 期 spec §2.2 写「不加第 11 个顶层 Tab」是对的——那是 10 期的口径）
- `ProjectBaselineManagementTab.tsx` **只改注释**，不碰任何逻辑
- `specs/验证约定.md` 的 §5.14 是**新增小节**，插在 §5.13 之后、§6 之前

**验证**

- `cd web; npm run build` 通过（注释改动后确认没碰坏语法）
- e2e：**🟢 64 passed**（零回归）
- 后端全量：`pytest` → **1444 passed**（零回归）
- 文档自查：`grep -rn "10 个 Tab" README.md PROGRESS.md specs/验证约定.md web/src`
  → 只应命中**历史期次 spec**里的，不应命中「当前状态」类文档
- 红线：`git diff --stat <base>..HEAD -- app/` → **为空**

**AC**：AC-215、AC-219
**提交**：`docs(progress): 顶层 8 个 Tab 口径与子串匹配坑位同步`

**T127 补充记录（执行情况）**

- **文件数正好 4 个**（红线 ≤ 5）：`README.md` / `PROGRESS.md` /
  `specs/验证约定.md` / `web/src/pages/ProjectBaselineManagementTab.tsx`。
- **`ProjectBaselineManagementTab.tsx` 只改注释**（L28-L30，3 行 → 3 行）：
  「顶层 Tab 仍然是 10 个 / `to_have_count(10)` 仍然成立」→
  「顶层 Tab 是 8 个（11 期 T124 起由 10 个收敛为 8 个）… 顶层计数要限定
  `get_by_role("tablist").first`」。**组件逻辑一个字节都没改**。
- **`PROGRESS.md` 改了两处**（都在 §4）：现状表的「项目详情 Tab」行
  （10 个 → 8 个 + 补「成员」内含二级子菜单 + 「版本快照」并入「文档」卡片）；
  §4 的坑位清单——第 6 条的数字（12 → 8 + 2 = 10）并补「11 期实测纠正」，
  **新增第 9 条**「Playwright 的 `get_by_role(name=)` 默认是子串匹配」。
  标题也从「两个已知的坑」改成「已知的坑」（坑位从 8 条变 9 条）。
- **`specs/验证约定.md` 新增 §5.14**（11 期前台核对点，插在 §5.13 之后、§6 之前，
  **不与 10 期 §5.13 重号**）；§5.13 的「顶层仍是 10 个」**保留原样**
  （那是 10 期当时的历史事实），只在末尾加了一句「11 期起顶层为 8 个，见 §5.14」。
- **文档自查通过**：`grep "10 个 Tab"` 在 `README.md` / `PROGRESS.md` /
  `specs/验证约定.md` / `web/src` 里**只命中历史期次记录**——
  `PROGRESS.md` L958 / L1036 是 09 期 T115 / T116 的归档事实，
  `specs/验证约定.md` L456 是 09 期 §5.12 的 AC-194 记录，
  L629 / L630 是变更历史表格；**「当前状态」类文档零命中**。
- **红线 diff 实测**（基准 = T126 的 `f970720`）：
  `git diff --stat -- app/` → **为空**；
  `-- web/src/pages/ProjectBaselinesTab.tsx` / `ProjectDocumentsTab.tsx` /
  `ProjectTodoCard.tsx` / `web/package.json` / `web/src/api/index.ts` /
  `web/src/api/client.ts` → **均为空**。
- **全量数字**：后端全量 **1444 passed**（串行，exit 0，498.34s，64 deselected）；
  e2e 全量 **64 passed**（219.74s，**条数与 T123 持平**）；
  `npm run build` 通过；`npm run lint` **0 errors**（36 warnings 全是既有的
  `react(set-state-in-effect)`，与本次改动无关）。
- **零真实 socket**：`tests\e2e` 全量 grep `requests|urlopen|aiohttp|socket.socket`
  → **零命中**。

---

### T128 收尾：全量回归 + 收官总结

**文件数**：**2**（红线要求 ≤ 5）

**前置**：T127 已提交。

**背景**：把「顶层 Tab 从 10 收敛到 8」这个结论写进项目文档，
并做一次完整的红线复核。

**产出**

- `specs/11-nav-tabs-ux-convergence/收官总结.md`（**新增**）：
  交付清单 / 关键设计 / e2e 改动汇总 / AC 矩阵 / 验证结果 / 红线复核 / 踩坑 / Backlog
  （**照 10 期 `specs/10-process-baseline/收官总结.md` 的体例**）
- 本文件 §4 验证记录表回填

**验证**

- e2e 全量：**🟢 64 passed**（条数与 T123 持平——本期只改断言，不新增用例）
- 后端全量：`.\.venv\Scripts\python.exe -m pytest` → **1444 passed**，exit 0，只增不减
- `cd web; npm run build` 通过
- `cd web; npm run lint` 通过
- **红线 diff 复核**（基准 = T123 收官提交）：
  `git diff --stat <base>..HEAD` 显示
  - `app/` **全为空**（后端零改动）
  - `web/src/pages/ProjectBaselinesTab.tsx` / `ProjectDocumentsTab.tsx` /
    `ProjectTodoCard.tsx` **全为空**
  - `web/package.json` **为空**（零新依赖）
  - `tests/e2e/` 只改断言，**没有新增或删除用例**（条数仍 64）
- 零真实 socket：`grep -r "requests\|urlopen\|aiohttp\|socket.socket" tests\e2e` → 无结果
- **不推送、不打 tag**（未明确要求）

**AC**：AC-219
**提交**：`docs(progress): 11 期导航栏 UX 收敛收官`

**T128 补充记录（验证执行情况）**

- **红线 diff 复核**（基准 = `b9c01fe` = T123 收官提交）：

  | 路径 | 结果 |
  |---|---|
  | `app/` | **全为空**（后端零改动） |
  | `web/src/pages/ProjectBaselinesTab.tsx` / `ProjectDocumentsTab.tsx` / `ProjectTodoCard.tsx` | **全为空** |
  | `web/package.json` / `web/src/api/index.ts` / `web/src/api/client.ts` | **全为空**（零新依赖、零新错误码） |
  | `alembic/` `migrations/` | **全为空**（本期不写迁移，两库 head 仍 `0025`） |
  | `tests/e2e/` | 10 个文件、103 insertions / 71 deletions，**`def test_` 行新增 0 条 / 删除 0 条**——只改断言，**条数仍 64** |

- **全量数字**（全部实跑，非引用）：
  - 后端全量 `.\.venv\Scripts\python.exe -m pytest` → **1444 passed**，
    64 deselected, exit 0, **498.34s**（0:08:18）
  - e2e 全量 `.\.venv\Scripts\python.exe scripts\run_e2e.py` → **64 passed**,
    exit 0, **219.74s**（0:03:39）
  - `cd web; npm run build` → **通过**（`tsc -b && vite build`，1613 modules transformed）
  - `cd web; npm run lint` → **0 errors**（36 warnings 全是既有的
    `react(set-state-in-effect)`，与本期无关）
  - `scripts\dev_check.py` → 环境自检**通过**（两库 head 均 `0025`、
    04 基线表 5 张齐、e2e 库校验 `aitest_copilot_e2e` 正确）
- **零真实 socket**：`tests\e2e` 全量 grep
  `requests|urlopen|aiohttp|socket.socket` → **零命中**。
- **本期改动文件总数**：18 个（前端 3 + e2e 10 + 文档 5），
  拆成 5 个任务、**每任务 ≤ 5 个文件**，符合红线。
- ⚠️ **截图目录的实测纠正**：`shot` 夹具按 `@pytest.mark.task` 分目录，
  而本期**没有改那 10 个 e2e 文件的 task 标记**（要改就得再动 10 个文件，
  超 T124~T126 的红线），所以本期 e2e 跑出的 **56 张**截图仍落在各用例的
  **历史期次目录**（T110 / T116 / T123 / T54 / T37 / T42 / T31），
  **不在** `.screenshots/T124~T126/`。截图是 gitignored 的本地证据，
  不影响任何提交；DoD 第 5 条已按实际情况如实标注。

---

## 3. ⚠️ 预期红窗（T124 ~ T126 期间 e2e 必然红）

顶层 Tab 数量从 10 变成 8 是**原子变更**——旧 e2e 的
`to_have_count(10)` 与 `name="版本快照"` / `name="申请"` 必然同时失效，
**无法做到「前端先改、e2e 后改」的中间绿态**。

| 时点 | e2e 状态 | 红的文件与原因 |
|---|---|---|
| T124 前 | 🟢 64 passed | — |
| **T124 后** | 🔴 | `t116` / `t123` 仍写死 10 项；`documents` / `applications` 入口路径变了；`access` / `projects` / `smoke` 的 `name="成员"` → **strict mode violation** |
| **T125 后** | 🔴 | 只剩 `access` / `projects` / `smoke` 的 `name="成员"` → strict mode violation |
| **T126 后** | 🟢 64 passed | 全部改完 |

**规则**：

1. T125 与 T126 **必须紧接着 T124 落地**，不留跨天间隔；
2. 每个任务的提交信息里**显式写明**当次 e2e 的预期状态（红 / 绿），
   不让「e2e 红了」被误判成回归；
3. **后端全量 pytest 每个任务都是绿的**（后端零改动），红的只有 e2e。

### 两个已实测确认的坑

**坑 ①：Playwright 的 `get_by_role(name=)` 默认是子串匹配**

用 playwright 1.65.2 在本机实测（DOM 里放顶层 `成员` + 内层 `成员列表` 两个 `role="tab"`）：

| 写法 | 命中数 | 命中内容 |
|---|---|---|
| `get_by_role("tab", name="成员")` | **2** | `['成员', '成员列表']` ← **子串匹配** |
| `get_by_role("tab", name="成员", exact=True)` | **1** | `['成员']` |
| `get_by_role("tab", name="自动化执行")` | 1 | `['自动化执行']` |
| `get_by_role("tablist").first.get_by_role("tab", name="成员")` | **1** | `['成员']` |

裸 `get_by_role("tab", name="成员").click()` 直接抛 **strict mode violation**
（resolved to 2 elements）。

根因：`exact=False` → 属性选择器带 `i` 标志
（`playwright/_impl/isomorphic/string_utils.py:75-87`）→ 默认**子串、不区分大小写**。

**顶层「成员」与内层「成员列表」名字互相包含** →
顶层断言必须 `exact=True` 或限定 `tablist`。

**坑 ②：antd 两层 `Tabs` 都用 `role="tab"`**（10 期 T122 已记录）

新结构下内层子 Tab 变多（成员内 2 个 + 基线管理内 2 个）。
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

→ 顶层计数统一写 `get_by_role("tablist").first.get_by_role("tab")`
（顶层 tablist 在 DOM 里排第一）。

⚠️ **T125 的 `test_t116_closing_ui.py` 索引断言在点击循环之后**——
裸 locator 已有 10 个 tab，`nth(9)` 会命中**内层子 Tab**。
把 L88 改成 `tablist.first` 后，索引断言自动回到顶层语义。

## 4. 验证记录表（骨架，执行时逐行回填）

| 任务 | 文件数 | 定向 | 后端全量 | 前端构建 | e2e | 截图 | 结论 |
|---|---|---|---|---|---|---|---|
| T124 | **5** | T124 自身的 3 个 e2e 文件**全绿**（`test_tabs_ui` / `test_automation_ui` / `test_process_baseline_ui`） | **1444 passed**（零回归，483.21s） | `npm run build` 通过；`npm run lint` **0 errors**（新增文件零告警） | **🔴 预期红**：全量 **59 passed / 5 failed**，5 个失败全是 T125 范围（`t116` / `t123` 仍写死 10；`applications` / `documents`×2 入口路径已变） | 浏览器实跑核对（8 Tab 顺序、版本快照卡片、成员二级子 Tab、基线管理嵌套未破坏、8 个 Tab 逐个点开无报错） | 通过 |
| T125 | **4** | `run_e2e.py -k "closing or documents or applications"` → **14 passed** | **1444 passed**（零回归，**跑两遍** 732.94s / 678.68s） | 通过（**未改前端**，仅回归确认） | **🟢 64 passed**（218.60s）——比预测的更早转绿；**条数不变** | 浏览器实跑核对（版本快照卡片随文档 Tab 常驻、加入申请子 Tab 可达） | 通过 |
| T126 | **3** | `run_e2e.py -k "access or projects or smoke"` → 3 文件绿 | **1444 passed**（零回归，380.77s） | 通过（**未改前端**，仅回归确认） | **🟢 64 passed**（214.80s）——第一次跑撞既有 flaky 失败 1 条，单跑与第二次全量均通过 | 不涉及（纯定位加固） | 通过 |
| T127 | **4** | 不涉及（纯文档） | **1444 passed**（零回归，498.34s，exit 0，64 deselected） | `npm run build` 通过（仅注释改动）；`npm run lint` **0 errors**（36 warnings 全是既有 `set-state-in-effect`） | **🟢 64 passed**（219.74s，条数与 T123 持平） | 不涉及（纯文档） | **通过** |
| T128 | **2** | 不涉及 | **1444 passed**（串行，exit 0，498.34s） | 通过 | **🟢 64 passed**（219.74s，条数与 T123 持平） | 不涉及 | **红线复核全绿**（收官总结.md 待写） |

**基线口径（不可下调）**

- 后端全量：**≥ 1444 passed**，串行，exit 0，数量只增不减
- e2e 全量：**≥ 64 passed**（**条数不变**——本期只改断言，不新增用例）
- 迁移 head：两库均为 `0025`（本期不写迁移）
- `app/`：**零改动**
- 顶层 Tab：**恒为 8 个**，顺序 概览 → 文档 → 基线管理 → 增量分析 → 测试点 →
  测试用例 → 自动化执行 → 成员

## 5. 完成定义（DoD）

对齐验证约定 §2 的五条，逐条落到本期：

- [x] 每个任务开跑前 `dev_check.py` 通过
- [x] 每个任务的定向 e2e 通过（T124 / T125 的**全量红窗**按 §3 判定，不算失败）
- [x] 全量 pytest 通过，数量 ≥ 1444 且只增不减（**串行，exit 0**）
      —— 实测 **1444 passed**（498.34s，64 deselected）
- [x] 全量 e2e 通过，数量 ≥ 64（T126 起全绿）—— 实测 **64 passed**（219.74s）
- [x] **截图证据**（文件名含 AC 编号）—— 本期 e2e 跑出 **56 张**新鲜截图，
      覆盖 8 个顶层 Tab 逐个点开（T110 / T116 / T123）、「版本快照」卡片随
      「文档」Tab 常驻（T54）、「加入申请」子 Tab 可达（T37）、普通成员视角（T42 / T31）。
      ⚠️ **实测纠正**：截图目录**不在** `.screenshots/T124~T126/`——
      `shot` 夹具按 `@pytest.mark.task` 分目录，而本期**没有改这 10 个 e2e 文件的
      task 标记**（改了就要再动 10 个文件，超 T124~T126 的红线），所以仍落在
      各用例的**历史期次目录**。截图本身是 gitignored 的本地证据，
      **不影响任何提交**。
- [x] **细颗粒度交付**：每个任务改动文件数 ≤ 5（已实测：5 / 4 / 3 / 4 / 2）
- [x] 既有测试零期望值改动（e2e 只改 Tab 路径与期望值，不删用例）
      —— 实测：`git diff <base> -- tests/e2e/` 里 `def test_` 行**新增 0 条 / 删除 0 条**
- [x] 后端 `app/` 零改动；`ProjectBaselinesTab.tsx` / `ProjectDocumentsTab.tsx` /
      `ProjectTodoCard.tsx` / `web/package.json` 零改动
      —— 实测（基准 `b9c01fe` = T123 收官）：`git diff --stat <base> -- app/` **为空**，
      上面 4 个文件 + `web/src/api/index.ts` / `client.ts` **均为空**
- [x] 文档口径同步到「顶层 8 个 Tab」
      —— `README.md` / `PROGRESS.md` / `specs/验证约定.md` /
      `ProjectBaselineManagementTab.tsx` 四个文件全部改完

**尚未完成（属 T128 交付物，不在本轮验证范围）**：
`specs/11-nav-tabs-ux-convergence/收官总结.md` 尚未撰写。
