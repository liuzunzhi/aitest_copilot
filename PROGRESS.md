# AI 辅助测试平台 - 当前开发进展看板

> **给 AI 的强制指令**：每次新任务开始前，必须先阅读本文件，并严格遵循当前冲刺任务，严禁越界写代码。

## 1. 项目路径映射

- **代码路径**：`D:\aitest_copilot`
- **需求/Spec 路径**：仓库内 `specs/`（与代码同一代码库）
  - 模块目录：`01-auth` / `02-projects` / `03-documents` / `04-baseline` / `05-incremental-analysis`
  - **验证约定**：`specs/验证约定.md`

## 2. 项目整体进度

- [x] 01-auth (登录)
- [x] 02-projects (项目与申请)
- [x] 03-documents (文档解析) —— **已完成（含 T84-PDF：PDF 解析支持）**
- [x] 04-baseline (基线管理、快照、标签) —— **已完成（含 T67 收尾）**
- [x] 05-increment-analysis (增量分析) —— **第一期（T68~T70）+ 第二期（T71~T78）+ 第三期 T79~T83 全部完成**
- [x] 06-real-llm (真实大模型接入与提示词模板管理) —— **T84-PDF ~ T87 全部完成，L2 真实联调已跑通**
- [x] 07-test-points (测试点分析) —— **T99 ~ T104 全部完成**（建表 + 迁移 `0022`；上下文组装 + 引擎；权限搬迁 + 服务层 + 11 个接口；引用保护 + 待复核标记；前端「测试点」Tab；收尾与文档回填）
- [x] 08-test-case-analysis (测试用例分析) —— **T105 ~ T110 全部完成**（建表 + 迁移 `0023`；上下文组装 + 引擎；服务层 + 13 个接口；评审 / 手工 CRUD / 步骤覆盖 / 待复核派生 / Excel 导出；前端「测试用例」Tab；收尾与文档回填）
- [x] 09-automation (自动化执行与测试报告) —— **已完成**（T110.5 工作台待办计数、T111 数据层与枚举修正、T112 扫描器与入库服务、T113 执行器、T114 执行编排与报告、T115 前端「自动化执行」Tab、T116 收尾与文档回填）
- [x] 10-process-baseline (流程基线) —— **已完成**（T117 数据层建表 `0025`、T118 场景 CRUD + 步骤覆盖 + 关联功能基线、T119 反推引擎 + 候选采纳、T120 审核与提交即冻结的版本快照、T121 权限与审计收口、T122 前端二级子菜单 + 场景管理、T123 收尾与文档回填）

## 3. 当前冲刺任务（⚠️ 务必先做这个）

**当前目标**：10 流程基线 —— **T117 ~ T123 全部完成，已收官**。

**PRD 2.4.2「基线管理」下的两个子菜单现在都做完了**：

| 子菜单 | 内容 |
|---|---|
| **功能基线**（04 期） | 模块 → 功能 → 功能点三级树 + 标签 + 快照 + 保留策略 |
| **流程基线**（10 期） | 场景 + 前置条件 + 操作步骤 + 预期结果 + 关联功能基线 + 文档反推 + 审核快照 |

**下一步**：无指定任务。10 期的后续期欠账见 §6 Backlog
（流程基线打标 / 快照保留策略 / 分点审核 / 变更历史 / 场景↔用例关联 等）。

> **收官总结**：`specs/10-process-baseline/收官总结.md`（交付清单 / 数据模型 / 关键设计 /
> 接口一览 / AC 矩阵 / 验证结果 / 红线复核 / 踩坑 / Backlog）。

> **10 期红线（用户 2026-11-21 裁决「跳过流程基线」→ 2026-11-22 起补做）**：
> - **独立建表**，不复用功能基线的表（04 的 CHECK 写死了层级名，
>   `baseline_revisions` 的唯一键会让两套基线**抢同一个版本号**）；
> - **标签不做**（显式欠账，AC-210）；
> - **快照保留策略 / 被引用即保护不做**（显式欠账，AC-211）；
> - **关联单向 + 关联表 + 不建 FK + 名称快照**（04 的删功能是物理删除，
>   建 FK 会把 04 的既有行为变成 500）；
> - **提交时冻结**（审核人看到的与最终冻结的逐字节相同）；
> - **基线管理内二级 Tabs**（`defaultActiveKey="function"`，现有用户路径不变）。


### T110.5 已完成（工作台待办计数，09 期前置任务）

> 兑现 PRD 2.3.1 的工作台待办（07 / 08 两期欠账，本期落地测试主链路上的三环）。
>
> - **后端**：`app/projects/service.py::get_todos` + `GET /api/projects/{id}/todos`
>   （三个 `COUNT`，各自带 `project_id`）。
> - **前端**：新增 `web/src/pages/ProjectTodoCard.tsx`，挂在**项目详情页的概览 Tab**；
>   `ProjectDetailPage.tsx` 的 `Tabs` 改为**受控**（`activeKey` + `onChange`），
>   待办数字可跳转到「基线管理 / 测试点 / 测试用例」三个 Tab。
> - **权限**：用 `ensure_readable` 而不是本文件其它路由的
>   `require_project_member_or_system_admin`——后者对**不存在的项目**也返 403，
>   区分不出 404。成员与访客均可读（待办是团队共享队列）。
> - **验证**：后端全量 **1117 passed**（1107 + 10）；e2e **51 passed**（48 + 3）；
>   `npm run build` 通过；截图 `.screenshots/T110.5/`（3 张）。
> - **仍欠**：PRD 2.3.1 的另两项待办——「待审批的项目加入申请」（02）、
>   「待确认的文档版本」（03）——登记到后续期。

### T111 + T112 已完成（数据层与枚举修正 / 扫描器与入库服务）

> **T111（数据层）**：`app/models/automation.py` 三张表 + 迁移 `0024`
> （`automation_assets` / `automation_runs` / `automation_run_items`）
> + 8 个错误类 + 2 个配置项（`automation_root` / `automation_exec_timeout_seconds`）。
>
> - **枚举修正**：`priority_changed` → `baseline_adjusted`（PRD：基线已调整）、
>   `duplicate_label` → `backtrace_override`（PRD：回溯覆盖）。
>   这两个旧值**在 PRD 里根本不存在**，而 PRD 要求的两类**无法表达**——
>   是能力缺失，不是命名风格问题。存量用两条 UPDATE 就地改写，
>   `downgrade` **反向改回去**（否则降级后代码只认旧枚举名，历史数据会被判非法）。
>   `CASCADE_CLEAR_REASON='target_deleted'` 与 `apply.CLEAR_REASON='misjudged'` **不动**。
> - **枚举归一**：原先 `service.py` 与 `schemas.py` 各写一份 `CLEAR_REASONS`，迟早漂移。
>   收敛到 `app/baselines/constants.py`——**不能**让 `schemas.py` 反向 import `service.py`
>   （`service.py` 已 import `schemas.py`，反向依赖会形成**循环导入**），
>   所以常量放在无依赖的独立文件里。
> - **验证**：两库 `0024 → 0023 → 0024` 往返干净，head 均 `0024`；
>   **降级后 `clear_reason` 逐字节还原为旧值**（造存量数据实跑确认，
>   不是只看 alembic 版本号）；后端全量 **1117 passed**（零回归）。
>
> **T112（扫描器 + 入库服务）**：`app/automation/`（`scanner.py` / `service.py` /
> `schemas.py` / `router.py`）+ `app/main.py` 注册路由；5 个接口、3 条路径。
>
> - **扫描器是纯函数**（不碰数据库、不碰配置）→ 路径安全与规则匹配可脱离运行时验证。
> - **路径安全是红线**：`resolve()` + `is_relative_to(root)` 双检，
>   **绝对路径单独判**（Windows 上 `root / abs` 会退化成 root 内的相对拼接，
>   `is_relative_to` 挡不住）。判定基准是 resolve 后的实际路径——
>   `sub/../sub2` 解析后仍在 root 内即放行，`../../etc` 越界即拒。
> - **扫描只出清单不写表**（PRD 2.4.6「由人工确认后入库」），
>   入库是另一个动作；**入库时服务端重扫重算**置信度与用例数，不采信前端传值。
> - **遍历用 `os.walk` 原地剪枝**（`rglob` 不支持按目录剪枝，否则 `node_modules`
>   里的文件也会被计数、进而撞上文件数上限）；单文件只读前 64KB；上限 2000 个文件。
> - **验证**：`tests\automation` **85 passed**（T111 的 47 + T112 新增 38）；
>   后端全量 **1202 passed**（1117 + 85），exit 0，只增不减；`npm run build` 通过；
>   红线实测上游目录（`test_points` / `incremental` / `test_cases` / `llm` / `baselines`）零改动。
> - **两处实现决定**（与 spec 的措辞略有出入，已在此登记）：
>   ① `directory` 传空串 = 扫整个 root（spec 未规定空串；2000 文件上限仍兜底）；
>   ② 响应里的 `root` 只给**相对展示名**，绝不返回绝对路径（泄露服务器目录结构）。

> **08 期红线（用户裁决）**：
> - **不做 Skill 模式**（PRD 2.5）；**不做 2.4.6 自动化执行、2.4.7 测试报告**；
> - **Excel 只做导出，不做导入**（PRD 2.4.5 提了「批量导入导出」，
>   用户裁决只做导出；导入进 Backlog）；
> - **工作台待评审计数与 07 一起延后**（用户裁决）；
> - **待复核读时派生、不落库**（用户裁决）——库里没有这一列，
>   靠 `source_point_fingerprint` 内容指纹派生；
> - **不改 04 / 05 / 07 的判定逻辑与错误码**——`app/llm/` 只允许给 Mock 加一个前缀分支
>   （实测 `git diff --stat`：`app/llm/mock.py` +29/-4，其余上游目录零改动）；
> - **任何测试不允许产生真实 socket**。
>
> **任务顺序**：`T105 → T106 → T107 → T108 → T109 → T110`。
> 规格与方案见 `specs/08-test-case-analysis/`。

> **历史：07 测试点分析 —— T99 ~ T104 已全部完成并收官**
> （建表 + 迁移 `0022`；上下文组装 + 纯引擎；权限搬迁 + 服务层 + 11 个接口 + 审计 + 留痕；
> 引用保护 + 待复核标记；前端「测试点」Tab；全量回归与文档回填）。

> **历史：06 真实大模型接入 —— T84-PDF + T84 + T85 + T86 + T87 已完成，
> L2 真实联调已跑通**（真实 MiniMax-M3：12 章 → 15 条结论落库）。
>
> **06 期红线（用户 2026-11-17 裁决）**：
> - 不做 Skill 双轨制 / Token 计费 / 不碰自动化执行；
> - API Key 绝不明文落库，不出现在响应 / 审计 / 日志 / 异常 / 运行日志；
> - **不改 05 的判定逻辑与业务语义**——但**允许且必须**把 05 两处
>   `json.loads` 换成容错解析入口 `parse_llm_json`（真实模型必然返回
>   Markdown 围栏的 JSON，不容错则整次分析直接 502）；
>   L2 联调后又补一条：**允许且必须**把基线目标清单放进 Prompt
>   （真实模型不知道 `target_id`，不给清单只能瞎猜，结论全被 AC-79 丢弃）——
>   两次都只改「喂给模型什么」，**判定逻辑一行没动**；
> - 不做模板新建 / 删除（只做列表 + 编辑）；
> - 不引入无超时的网络调用；**任何测试不允许产生真实 socket**。
>
> **任务顺序**：`T84-PDF → T84 → T85 → T86 → T87`。
> T84-PDF 是 06 的**前置排头兵**（T87 验收要用真实 `.pdf` 走端到端）。
>
> **真实联调分两层**：
> - **L1 自动化**（进 CI，零 socket）：真实 `.pdf`/`.docx` + `httpx.MockTransport`
>   返回**带 Markdown 围栏的 JSON**，一条用例同时覆盖 PDF 与容错；
> - **L2 人工**（不计入 pytest）：真实 DeepSeek（API Key 走系统设置页存
>   `llm_providers` 表，**不写 `.env`**）+ 真实文档。

### T84-PDF 已完成（03 模块支持 PDF）

> 范围：`pdfplumber` 纯文本提取 + 字号/加粗/编号规则切章节 + 表格还原成
> `a | b` + 扫描件整文降级；**不改 `app/documents/service.py` 与
> `app/common/errors.py`**（章节落库口径不变，`UNSUPPORTED_DOC_TYPE`
> 回归「未知扩展名」语义）。

### T84 已完成（配置落库 + 密钥加密 + 动态 Provider + JSON 容错）

> 范围：两张新表（迁移 `0017`）+ Fernet 加密 + `OpenAICompatProvider` +
> 查库降级工厂 + `parse_llm_json` 容错解析入口。
> **05 的判定逻辑零改动**——`app/incremental/` 下只换了 2 处解析入口
> （`engine.py` / `second_pass.py`），字段校验 / 标签分类 / 丢弃规则 /
> 错误码全部原样。

### T85 + T86 已完成（配置管理接口 + 模板管理接口 + 运行留痕）

> 范围：`app/llm_admin/` 三个路由（配置管理 / 模板管理 / 只读模板列表）
> + 05 两段接入 `llm_run_logs` 运行留痕。
> **05 仍是纯增量改动**——`app/incremental/service.py` 只多了写日志的调用，
> 判定逻辑与业务语义一个字节没动（`git diff` 实测 +90 / -0）。

### L2 真实联调已跑通（2026-11-18，真实 MiniMax-M3）

> 真实模型 + 真实文档 + 真实基线 → **12 章 → 15 条结论全部落库**，
> `discarded_count=0`（没有一条被当成越界丢弃）。耗时 60.8s。

首轮 502，暴露两处**只有真实模型才能暴露**的问题：

1. **推理模型的 `<think>` 思考块**——思考过程里出现 JSON 片段，
   `parse_llm_json` 的括号兜底从思考块内部起算 → 截出垃圾。
   修法：`app/llm/json_utils.py` 加 `strip_think_block()`，在围栏剥离**之前**执行。
2. **Prompt 里从来没给过基线清单**——模型明说「baseline unavailable」，
   只能瞎猜 `target_id`（还照抄了模板示例里的 `1`），全被 AC-79 当越界丢弃。
   修法：Prompt 多拼一段 `## 可对照的基线目标`（迁移 `0019` 同时修掉
   模板里写死的 `"target_id": 1` 示例）。

**判定逻辑零改动**：字段校验、标签分类、丢弃规则、错误码全部原样，
只改了「喂给模型什么」。详见 `specs/06-real-llm/tasks.md` 的
「L2 真实联调发现」。

> 教训：**Mock 通过 ≠ 真实模型能跑**。Mock 时代测试直接硬编码了
> 正确的 `target_id`，把「模型拿不到基线」这个洞完全遮住了。

### T87 之后的两项内部环境适配（2026-11-18）

> 用户裁决：这是**内部测试环境**，单人管理员是常态。两处调整让 L2 联调能跑通。

1. **注册去掉图形验证码**（AC-11 在本环境不生效）。
   `app/common/captcha.py` 只保留**密码重置验证码**（AC-12）；
   `CaptchaRequired` / `CaptchaInvalid` 错误类一并删除。
   对外发布前要补回的完整清单见 `specs/01-auth/tasks.md` 的 **TOD-01**。
2. **基线审核允许自审**（迁移 `0018` 播种 `allow_baseline_self_approval=True`）。
   原来的「提交者不能审自己的提交」在只有一个管理员账号时是**死锁**。
   开关打开时 `approve_review` / `reject_review` 都放行，
   审计 `after_data.self_approved` 留痕；对外发布前改回 False。
   详见 `specs/04-baseline/tasks.md` 的「04 补记」。
3. **测试隔离真实大模型配置**：`tests/conftest.py` 新增 autouse 夹具，
   用例期间摘掉 `llm_providers` 的默认配置行。
   之前开发库里配了真 MiniMax 后，测试会**真的发网络请求**——
   既违反「任何测试不允许产生真实 socket」，又不确定。
4. **修 9 处「全表查审计」的脆弱断言**：审计查询改成按
   `actor_id` / `project_id` / `target_id` 过滤。
   开发库有了真实数据（手工建的项目、改角色留下的审计）后，
   全表比对必然失败——`git stash` 验证过这些失败在改动前就存在。

### 04 补做完成（用户 2026-11-18 提出，T88–T98 已落地）

- **TOD-03 分点审核**：整包审核 → 逐项勾选通过 / 局部驳回。
  > **已完成（T93–T98）**：`specs/04-baseline/spec-phase4-review.md`。
  > 新增 2 张表（`baseline_review_rounds` / `baseline_review_items`），
  > `structure_json` 不动、结构表不加 `node_status`；
  > 快照只冻结 approved 节点，驳回节点留草稿；
  > 05 清单**排除**被驳回节点（`baseline_index()` 按 approved 集合过滤，
  > **只改读取口径，不动判定逻辑**）；
  > 前端不改 `ProjectBaselineTree.tsx`，改为在快照页新增「分点审核」抽屉。
  > 任务 **T93–T98**（迁移 `0021_review_items`）。
- **TOD-04 从文档推导基线**：spec §2 明确本期不做，06 期 LLM 已通，
  技术上可行但从未实现。跨 03 + 04，建议单独立项。
  > **已完成（T88–T92）**：`specs/04-baseline/spec-phase4-derive.md`。
  > 结构表不动（追溯字段已预留），新增 `baseline_derives` +
  > `baseline_derive_candidates`（候选草稿）；同名冲突绝不覆盖；
  > 同步执行，坏 JSON 整次失败。
  > 任务 **T88–T92**（迁移 `0020_baseline_derive`）。
- **落地顺序已裁决（2026-11-18）**：**先做从文档推导**（T88–T92，迁移 0020），
  再做分点审核（T93–T98，迁移 0021，`down_revision = "0020"`）。
  AC 编号：推导占 AC-122~AC-131，审核占 AC-132~AC-140。
- **验证（2026-11-18）**：后端全量 pytest exit 0；`tests/baselines` **115 passed**；
  e2e 全量 **39 passed**；`npm run build` 通过；开发库与 e2e 库迁移 head 均为
  **`0021`**；零真实网络请求。细节见 `specs/04-baseline/tasks.md`
  「T88–T98 验证记录」。

### T87 已完成（前端系统设置页 + 05 动态模板 + L1 端到端）

> 范围：`AdminSettingsPage`（大模型配置 / 提示词模板两个 Tab）、`/admin/settings`
> 路由与侧边栏菜单、05 模板下拉改为动态拉取、`dev_check.py` 增加 `LLM_SECRET_KEY` 检查。
> **L1 自动化**：真实 `.pdf` / `.docx` 走「上传 → 解析 → 章节落库 → 发起分析 → 结论落库」，
> 模型侧 `httpx.MockTransport` 返回**带 Markdown 围栏的 JSON**，一条用例同时覆盖 AC-119 与 AC-120。
> **L2 真实联调仍待人工执行**：真实 DeepSeek Key 走系统设置页存 `llm_providers`，不写 `.env`。

- 配置响应只出掩码 `sk-****1234`；连通性失败是 **200 + `ok:false`**，前端按业务结果展示，
  不是 502。
- 模板只有正文变化才 `version_no += 1`；只改描述 / 状态不升版本。
- 05 模板下拉**必须滤掉第二遍模板**（同 task_type，靠名字前缀区分），否则第一遍会拿到
  不兼容的 Prompt 格式。
- e2e 造数：大模型配置按 `e2e-llm-` 前缀直删（连带留痕），模板正文在 `finally` 还原。

### 第二期范围（已完成，不可扩大）

- 只做**第二遍 · 全局裁决**：章节引用图 + 2b-1 功能点索引 / 2b-2 按点分治 / 2b-3 一跳图传播。
- **零真实网络请求**：仍只有 `MockProvider`（第二遍默认响应 `unchanged`）。
- 表结构只加三张：`document_chapter_links`（0014）、`incremental_decisions` / `incremental_conflicts`（0015）。

### 第二期红线（已遵守）

1. **不写 `baseline_labels`**——人工裁决只改冲突行，产出段是第三期的事。
2. **不做模板管理 UI / 模板 CRUD**——第二遍模板由迁移播种、只读。
3. **不自动裁决冲突**——冲突只能人工确认 / 驳回。
4. **不引入真实模型供应商**、不做密钥加密与运行日志表。
5. 不许顺手修无关模块——引用抽取代码放 05 包内，没改 03 的解析器。

### 第一期核心 AC（已覆盖，见下方历史任务）

**AC-① 章节局部结论能否正确落库**
- Given 项目有基线快照（含功能 F）+ 生效文档版本（含章节 C）+ Mock 返回固定 JSON（结论指向 F，`label_type='changed'`）
- When 发起分析
- Then `incremental_analyses` 新增一行 `status='succeeded'`
- Then `incremental_conclusions` 新增一行：`chapter_id=C`、`target_type='function'`、`target_id=F`、`label_type='changed'`
- Then 目标不在基线内的结论**被丢弃**并记错误码（不能静默写入脏数据）

**AC-② Prompt 是否从数据库读取并传给 Mock**
- Given `prompt_templates` 表里 `task_type='incremental'` 的模板，其 `system_prompt` / `user_prompt` 是**可识别的固定字符串**
- When 发起分析
- Then **Mock 收到的 `system` 等于该模板的 `system_prompt`**
- Then **Mock 收到的 `user` 以该模板的 `user_prompt` 开头**，且包含章节标题与章节正文
- Then 模板被删除 / `status='disabled'` → 发起分析返回对应错误码，**不产生分析记录**

## 4. 环境与验证现状

| 项 | 值 |
|---|---|
| 后端全量 pytest | **1444 passed**（串行；10 期 T123 收官，基线 1259 + 10 期新增 185） |
| e2e | **64 passed**（增量分析第一期 2 + 第二期 3 + 第三期 2 + PDF 1 + 系统设置 2 + 来源筛选 1 + 测试点 2 + 测试用例 4 + Tab 核对 2 + 待办计数 3 + 自动化执行 5 + 自动化收官 2 + **流程基线 4** + **10 期收官 2**），一条命令 `.\.venv\Scripts\python.exe scripts\run_e2e.py`（8001/5174 + `aitest_copilot_e2e`） |
| 前端构建 | `npm run build`（`web/` 目录，端口 5173，代理到 8000） |
| 开跑前自检 | `.\.venv\Scripts\python.exe scripts\dev_check.py`（跑 e2e 时加 `--expect-db e2e`） |
| 账号 | `admin` / `Admin12345` |
| 迁移 head | **`0025`**（06 期 T84 建 `0017`；`0018` 免审核开关；`0019` 第一遍模板修正；04 补期 `0020` 推导 / `0021` 分点审核；07 期 T99 建 `0022` 测试点；08 期 T105 建 `0023` 测试用例；09 期 T111 建 `0024` 自动化三表 + 清除原因枚举修正；10 期 T117 建 `0025` 流程基线四表 + 模板 CHECK 扩枚举） |
| 项目详情 Tab | **8 个**（概览 / 文档 / 基线管理 / 增量分析 / 测试点 / 测试用例 / 自动化执行 / 成员）——**「基线管理」内含二级子菜单**（「功能基线」/「流程基线」），**「成员」内含二级子菜单**（「成员列表」/「加入申请」）；「版本快照」并入「文档」Tab 内的卡片 |
| 流程基线数据 | 四张表 `process_baselines` / `process_baseline_steps` / `process_baseline_links` / `process_baseline_revisions`；**开发库当前均为 0 行**（本期只做能力落地，没往开发库塞业务数据；数据由用户自己建） |
| 截图目录 | 仓库根 `.screenshots/`（`E2E_SCREENSHOT_DIR` 可覆盖） |
| 运行时依赖 | `pdfplumber>=0.11`（T84-PDF 新增）；`cryptography>=43`（T84 新增）、`httpx>=0.28`（T84 从 dev 移入）；**`openpyxl>=3.1`（08 期新增，仅用于 Excel 导出）** |
| 环境变量 | **新增必填 `LLM_SECRET_KEY`**（已写入本地 `.env`，随机生成，不入库；`.env.example` 有说明） |
| 新增脚本 | `scripts/check_migration_roundtrip.py`（09 期：两库迁移往返 + 枚举逐字节还原断言）、`scripts/check_process_baseline_roundtrip.py`（10 期：两库 `0025 ↔ 0024` 往返 + 四张表与模板 CHECK 还原断言） |

### ⚠️ 已知的坑（别重复踩）

1. **`pytest -n 4` 下 `tests/projects/` 有既有 flaky**（与新改动无关）：
   `test_available_returns_all_unjoined_projects`、`test_ac_36_add_member`
   会偶发失败——根因是断言只按 `action` 过滤 AuditLog、未按项目隔离，并行 worker 撞车。
   **对照验证过**：回到改动前提交连跑 3 次同样失败；串行跑全绿、单跑这 2 条全绿。
   → **判定回归时用串行跑**，或先确认失败是否属于这 2 条。
2. **MySQL DDL 隐式提交**会破坏 pytest 夹具的外层事务。
   测试里造表必须用**独立引擎**（如内存 SQLite + `StaticPool` + `check_same_thread=False`），
   不能在夹具事务内 `CREATE TABLE`。
3. **子进程 pytest 会捡到平台自己的 `pyproject.toml`**（09 期 T113 实测踩到）：
   `AUTOMATION_ROOT` 默认在仓库内，pytest 从工作目录**向上**找配置文件，
   于是继承平台的 `addopts = "-q -m 'not e2e'"`——
   `-m 'not e2e'` 会**静默 deselect** 资产里标了 `e2e` 的用例，
   `-q` 叠成 `-qq` 会让**统计行整个消失**（`-qq` 只输出进度点）。
   执行器已做配置隔离（见 §5.13），但**自己写子进程 pytest 调用时也要注意**。
4. **Windows 上不能用 `os.kill(pid, 0)` 查进程是否存活**——它会真的去终止进程。
   正确做法：`ctypes` 调 `OpenProcess` + `GetExitCodeProcess`，
   返回码 `259`（`STILL_ACTIVE`）才算活着。
5. **全量 pytest 不能用 `-o addopts=`**（09 期 T114 踩到）：
   平台 `addopts` 里含 `-m 'not e2e'`，覆盖掉它会把 51 条 e2e 一起收进来
   → 它们要连 8001 端口 → 51 个 error。
   **要看用例数用 `-m "not e2e"`**，别动 `addopts`。
6. **antd 两层 `Tabs` 都用 `role="tab"`**（10 期 T122 实测踩到，11 期 T124 复核）：
   「基线管理」内引入了二级子菜单之后，进了这个 Tab
   `page.get_by_role("tab")` 会数到 **10**（顶层 8 + 内层 2）。
   **「顶层仍是 8 个 Tab」这条断言要限定顶层 tablist**：
   `page.get_by_role("tablist").first.get_by_role("tab")`。
   **11 期实测纠正**：只有**当前激活**的顶层 Tab 的内层子 Tab 会被计入——
   已离开的顶层 Tab 面板是 `display:none`（`removeOnLeave` 默认 false，
   DOM 保留但不可见），而 Playwright 默认 `include_hidden=False` 不计入隐藏元素。
   所以裸计数是 **8 + 2 = 10**，**不是 12**。
7. **antd v6 的 Select 值不在 `.ant-select-selection-item` 里**（10 期 T122 踩到）：
   v6 换成了 `.ant-select-content-has-value`（单选）/ `.ant-select-content`（多选）。
   断言「下拉已有值」要用新的类名，否则数到 0 条。
8. **antd Drawer 关闭后内容不销毁**（10 期 T122 踩到）：
   `destroyOnHidden` 没开时 DOM 里还在，只是隐藏——
   断言「抽屉关掉了」要用 `to_be_hidden()`，**不是** `to_have_count(0)`。
9. **Playwright 的 `get_by_role(name=)` 默认是「子串匹配」**（11 期 T124 实测踩到）：
   `exact=False` → 属性选择器带 `i` 标志（`playwright/_impl/isomorphic/string_utils.py`）。
   「成员」Tab 与它内层的「成员列表」子 Tab **名字互相包含** →
   裸 `get_by_role("tab", name="成员")` 在**「成员」Tab 正激活时**会命中 2 个 →
   **strict mode violation**。
   写顶层 Tab 的定位**统一加 `exact=True`**；内层子 Tab **用 `data-testid` 定位**
   （如 `project-members-subtab-applications`），别用 `role="tab"` 名字。
   补充：内层子 Tab 是**懒渲染**的（antd `Tabs` 的 `forceRender` 默认 undefined，
   未激活的面板不进 DOM），所以「第一次点开某顶层 Tab」时裸写法是安全的——
   但**依赖这个「恰好安全」很脆**，用例顺序一变就会撞。

## 5. 04 收尾完成情况（2026-11-17）

- [x] 把 `D:\aitest_copilot` 下的 17 个未推送提交 push 到远端（`db0b09b..683cfed`）
- [x] 补齐 04 的"快照引用保护扩展"——引用检查拆成**来源解析器**架构
      （`app/baselines/references.py`），标签引用与增量分析引用各一个解析器；
      增量分析解析器探测表是否存在，05 落地后**自动生效，04 无需再改**
- [x] 跑通测试 `pytest -k ac_04_cleanup`（11 passed）

**验证结果**：`pytest -k ac_04_cleanup` 11 passed；全量 484 passed；e2e 29 passed；构建通过。

**提交**：`1539646` / `0f06583` / `4ab12fe` / `9d3a885`，已推送到 `origin/main`。

## 5.1 05 收尾完成情况（2026-11-17）

### 第一期（T68~T70）· 第一遍 · 章节局部比对

- [x] 三张表 + 迁移 `0013_incremental`；`app/llm/` 抽象与 `MockProvider`
- [x] `engine.py` 第一遍 + `service.py` + `router.py` + 错误码 + 审计
- [x] 项目详情页第 7 个 Tab「增量分析」+ API 分节 + 错误码映射

**验证结果**：后端全量 516 passed；e2e 31 passed（新增 2 条）；构建通过。

### 第二期（T71~T78）· 第二遍 · 全局裁决

- [x] T71 章节引用图：迁移 `0014` + `links.py` 规则抽取 + `links_router.py` 三接口
- [x] T72 第二遍表结构：迁移 `0015`（`incremental_decisions` / `incremental_conflicts`
      + `analyses` 第二遍列）+ 第二遍模板种子
- [x] T73 2b-1 功能点索引 + 2b-2 按点分治（含证据一致性判定与 Mock 第二遍默认响应）
- [x] T74 2b-3 一跳图传播（`possible_impact` 只进人工队列）
- [x] T75 第二遍服务与四个接口（触发 / 裁决列表 / 冲突列表）
- [x] T76 人工裁决接口（确认 / 驳回，**不写 `baseline_labels`**）
- [x] T77 前端：第二遍区块 + 引用图抽屉 + 3 条 e2e
- [x] T78 收尾：全量 pytest 串行 + e2e 全量 + `dev_check` + build + 文档回填

**验证结果**：后端全量 **589 passed**（T70 后 516 + 新增 73）；e2e **34 passed**
（新增 3 条）；`npm run build` 通过；两个库迁移 head 均在 `0015`；
截图 `.screenshots/T77/`（5 张）。

**提交**：`2dd6161` / `41a4cf4`（T71）、`c51d2e6`（T72）、`478f429`（T73）、
`c51d7d1`（T74）、`d015b7f`（T75）、`8b1cc3f`（T76）、`a7d93a5`（T77）。

### 第三期（T79~T83）· 产出段

- [x] T79 产出段模型与迁移：`0016`（`incremental_labels` 映射表 + `analyses` 的 `apply_*` 列，
      唯一键 `(analysis_id, baseline_label_id)`，标签类型只收 `changed` / `affected`）
- [x] T80 产出引擎：`app/incremental/apply.py`（收集规则 / 复用或新建 submitted 快照 /
      写标签 + 映射 / 重跑逻辑清除），标签行只置 `cleared`、绝不物理删除
- [x] T81 产出服务与接口：`run_apply`（固定校验顺序 + 逻辑清除 + 落标签 + 审计）、
      `list_applied_labels`（历史行可查 + `revoked` 派生）、两个路由与 3 个错误码；审计覆盖补 1 条
- [x] T82 前端：`IncrementalApply.tsx`（状态 / 触发 / 产出标签表 / 撤销提示）挂进分析详情抽屉，
      `api/index.ts` 补两接口与类型、`client.ts` 补 3 个错误码中文
- [x] T83 收尾：后端全量 **626 passed**、e2e **36 passed**、构建通过、自检通过；
      `验证约定.md` §5.6 与本文件计数回填，第三期收尾完成

**T79 验证结果**：定向 15 passed；后端全量 **604 passed**（串行）；
`alembic downgrade 0015 → upgrade head` 往返通过；两个库迁移 head 均在 `0016`。

**T80 验证结果**：`tests/incremental/test_apply_engine.py` 11 passed；
后端全量 **615 passed**（串行）。未改 `app/baselines/` 任何代码，未物理删除标签行。

**T81 验证结果**：`tests/incremental/test_apply_flow.py` 10 passed，
审计覆盖清单新增 `incremental.apply.run` 1 条；后端全量 **626 passed**（串行）。

**T82 验证结果**：`npm run build` 通过；e2e 全量 **36 passed**
（新增 `test_incremental_apply_ui.py` 2 条）；截图 `.screenshots/T82/`（3 张）。

**T83 验证结果**：后端全量 **626 passed**（串行，exit 0）；e2e 全量 **36 passed**；
`npm run build` 通过；`run_e2e.py` 内联的 `dev_check --expect-db e2e` 通过；
两个库迁移 head 均在 `0016`；AC-104 复核通过（全链路只有 `MockProvider`，零真实网络请求）。

## 5.2 06 期 · T84-PDF 完成情况（2026-11-17）

**做了什么**：03 模块支持 PDF 上传（`pdfplumber` 运行时依赖）。

- [x] `app/documents/pdf.py`（新增）：逐页取**字符** → 按 top ±2pt 聚行 →
      横向间隙切列（表格还原成 `a | b`）→ 字号分档 + 编号正则判标题。
- [x] `app/documents/parser.py`：`SUPPORTED_SUFFIXES` 加 `.pdf`，
      新增 `_parse_pdf`（复用 `_TreeBuilder`，章节树与 md/docx 同构）。
- [x] `pyproject.toml`：`pdfplumber>=0.11` 进运行时依赖。
- [x] 前端：`accept` 加 `.pdf`、提示文案加 `.pdf`、`UNSUPPORTED_DOC_TYPE` 文案改。
- [x] 3 处既有测试期望值改：`test_parser.py`（PDF 不再是不支持类型，
      改用 `.xlsx`）、`test_upload.py`（PDF 上传成功 + 损坏 PDF 报错）、
      `test_documents_ui.py`（PDF 从「被拒」改成「上传成功」）。
- [x] 新增 `tests/documents/test_pdf_parser.py`（8 条）+ 上传侧 2 条。
- [x] `.env` 补 `LLM_SECRET_KEY`（随机生成），`.env.example` 补说明；
      `.gitignore` 补注释并确认 `测试用的需求文档_不提交git/` 命中。

**验证结果**：后端全量 **636 passed**（串行，exit 0）；e2e 全量 **37 passed**；
`npm run build` 通过；迁移 head 仍在 `0016`（本期不动迁移）。

**实现要点**：

- **为什么用 `pdfplumber` 而不是 `pypdf`**：实测样本 PDF（8 页、2508 字、文本型），
  `pdfplumber` 能拿到**字号**（`extract_words(extra_attrs=['size'])`）并还原表格；
  `pypdf` 拿不到字号，PDF 就只能走「整文输入 + LLM 拆解」，复杂度与成本都上一个台阶。
- **用字符而不是 `extract_words`**：`extract_words` 按空格切词，会**丢掉 PDF 里真实的
  空格字符**——`APP Application` 会粘成 `APPApplication`，中英混排的需求文档里
  这明显降低可读性。改用 `page.chars` 逐字符重建。
- **标题判据是两条硬条件**：
  ① 字号 > 正文字号（+0.6pt 缓冲）**且**命中编号正则；
  ② 或 **加粗** **且**命中多级编号（有些文档的小节标题字号与正文相同，
  只靠加粗区分，样本 PDF 的 `6.1WEB攻击防御手段` 就是这种）。
  两条都要求命中编号正则——否则正文里的 `1. 防止SQL注入` 列表项会被误判成标题。
- **编号正则刻意不匹配单级编号**（`1` / `2`）：`1. ` 是列表项的写法，
  点后不是数字；`\d+(\.\d+)+` 只匹配 `1.1` / `2.4.2` 这类多级编号。
  结尾用 `(?!\d)` 而不是 `\b`——`6.1WEB` 的数字与字母之间没有词边界。
- **正文字号取非加粗行的众数**：标题行可能比正文行还多（目录页、短文档），
  那时全量众数会被标题字号占据，导致「没有标题档」。
- **表格不单独识别**：PDF 里表格的绝对坐标与正文行不在同一条「行」序列里，
  单独跑 `find_tables()` 会与正文流**重复**（表格内容出现在章节里两次）。
  改为在行内按横向间隙切列（正文实测间隙 ≤ 6pt，表格列间隙 ≥ 20pt，取 10pt）。
- **扫描件降级**：提取不到任何文字 → 整文单章「全文」，**不报错**
  （与「txt 无标题整文单章」同一口径）。OCR 明确留到后续期。

## 5.3 06 期 · T84 完成情况（2026-11-18）

**做了什么**：真实大模型接入的**模型侧底座**（不含接口、不含前端）。

- [x] `app/models/llm.py`（新增）：`LLMProviderConfig`（`llm_providers`）+
      `LLMRunLog`（`llm_run_logs`），字段 / 索引 / CheckConstraint 对齐 spec §4。
- [x] `migrations/versions/0017_llm_providers.py`（新增）：`down_revision="0016"`，
      两表按序建、downgrade 反序直接删表、**无种子数据**。
- [x] `app/llm/crypto.py`（新增）：`encrypt` / `decrypt` / `mask`，
      Fernet 密钥由 `sha256(llm_secret_key)` 派生。
- [x] `app/llm/openai_compat.py`（新增）：`OpenAICompatProvider`
      （`transport` 可注入 → 测试零真实 socket）。
- [x] `app/llm/json_utils.py`（新增）：`parse_llm_json` 容错解析。
- [x] `app/llm/provider.py`：工厂改造成查库降级（无配置 → Mock 单例）。
- [x] `app/incremental/engine.py` + `second_pass.py`：**两处** `json.loads`
      换成 `parse_llm_json`，判定逻辑零改动。
- [x] `app/common/config.py`：`Settings.llm_secret_key` **必填**；
      `.env` / `.env.example` 同步。
- [x] `app/common/errors.py`：新增 7 个错误码类。
- [x] `pyproject.toml`：`cryptography>=43` 进运行时；`httpx>=0.28` 从 dev 移入运行时。
- [x] `tests/llm/`（新增 5 个文件）+ `tests/incremental/test_llm_json_fallback.py`：
      新增 **96 条**用例，全部用 `httpx.MockTransport`，**零真实 socket**。

**验证结果**：后端全量 **732 passed**（串行，exit 0）；e2e 全量 **37 passed**；
`npm run build` 通过；`dev_check.py` 通过；两个库迁移 head 均在 `0017`；
`alembic downgrade 0016 → upgrade head` 往返通过；`llm_providers` 表为空时
（= 断网降级 Mock 场景）全量仍全绿。

**实现要点**：

- **为什么「先降级、后接真」不是妥协而是安全阀**：没有配置、用户没配就发分析，
  平台仍然能跑（和今天一模一样），不会因为新功能把 05 打挂。
  `get_provider` 每次都查库（单表 + 唯一索引，查询成本可忽略），
  换来「管理员改完配置立即生效」，不用处理缓存一致性。
- **解密失败不降级，抛 `LLMConfigInvalid`（500）**：配置坏了必须让人知道，
  否则线上会用 Mock 跑出一堆空结论却没人发现。
- **唯一默认用「生成列 + 唯一索引」在库层兜底**：
  `default_key` 是 `STORED` 生成列 `IF(is_default=1, 1, NULL)`，
  唯一索引 `uk_llmprov_default` 挂在它上面。
  MySQL 唯一索引允许多个 NULL，所以非默认行不占位。
- **⚠️ 切换默认必须「先清后置」**：生成列是**即时计算**的——
  把新行 `is_default` 置 1 的那一刻它的 `default_key` 立刻落成 1，
  而老默认行还没清、`default_key` 还是 1 → 唯一索引当场报错。
  **反过来做（先置后清）必炸**，T85 的服务层要按这个顺序写。
- **Fernet 密钥由 `sha256(llm_secret_key)` 派生**：
  `base64.urlsafe_b64encode(sha256(secret).digest())`，
  任意长度的字符串都能当主密钥，用户不必手工生成 32 字节。
  换掉主密钥 = 库里已存的密文全部解不开。
- **`decrypt` 的错误消息是固定的**：Fernet 的原始异常里可能带密文片段，
  直接透出去等于把密文写进了日志。
- **`parse_llm_json` 只做三件事，不做「智能修复」**：
  剥围栏 → 取 `{` 到 `}` 区间兜底 → 失败就报错。
  **补引号 / 截断补全 / JSON5 容错一律不做**——那些会掩盖模型输出的真实问题，
  让「模型返回了坏 JSON」变成「平台悄悄改对了」，排查时更难定位。
  围栏与前置说明是**格式噪声**，去掉它是还原原文；补引号是**猜测**。
- **异常收敛成 6 类**：超时 / 连接失败 / 其他 HTTPError / 401-403 / 其他非 2xx /
  响应结构不符，全部 → `LLMCallFailed`（502 `LLM_CALL_FAILED`），
  消息给可读原因但**永远不带 API Key**。
- **不传 `temperature` / `max_tokens`**：不同供应商默认值差异大，
  传固定值反而制造行为不一致。
- **`test_ac_84_no_real_network_code` 改写而非删除**（用户 2026-11-18 裁决）：
  06 期引入了真实供应商，「代码里不出现 httpx 字样」的前提已不成立。
  改成两条可执行断言——① `OpenAICompatProvider` 必须支持 `transport` 注入；
  ② `app/` 下除它之外零真实网络客户端。另加一条
  `test_ac_84_tests_never_use_real_socket`：测试目录里不许出现
  `requests` / `urlopen` / `aiohttp` / `socket.socket`。
  **守卫意图（断网可跑）保住了，用例一条没删。**

## 5.4 06 期 · T85 + T86 完成情况（2026-11-18）

**做了什么**：配置管理接口 + 模板管理接口 + 05 运行留痕。

- [x] `app/llm_admin/`（新增包）：`__init__.py` / `schemas.py` /
      `provider_service.py` / `template_service.py` / `router.py`。
- [x] 三个路由（`app/main.py` 注册）：
      `/api/admin/llm-providers`（`require_system_admin`）、
      `/api/admin/prompt-templates`（`require_system_admin`）、
      `/api/prompt-templates`（只读，`current_user`）。
- [x] `app/llm/run_log.py`（新增）：运行留痕的统一写入口。
- [x] `app/incremental/service.py`：第一遍与第二遍各接一处留痕
      （**纯增量 +90 / -0，判定逻辑零改动**）。
- [x] `app/llm/openai_compat.py`：加 `provider_name` / `provider_id`
      快照——留痕要记「用的哪条配置」，不是「用的哪个类型」。
- [x] `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补 3 条：
      `llm.provider.create` / `llm.provider.update` / `prompt_template.update`。
- [x] 新增 `tests/llm/test_provider_api.py`（31 条）/
      `test_template_api.py`（27 条）/ `test_readonly_templates.py`（8 条）/
      `test_run_logs.py`（11 条），共 **77 条**。

**验证结果**：后端全量 **812 passed**（基线 732 + 80）；
e2e 全量 **37 passed**（零回归）；`npm run build` 通过。

**实现要点**：

- **响应里只有掩码**：只有 `api_key_masked`（`sk-****1234`），
  **没有 `api_key`、没有 `api_key_ciphertext`**。
  掩码靠「解密 → `mask()`」还原前缀，所以主密钥换掉时退化成
  `****{last4}`——宁可少给几个字符，也不让整个列表挂掉。
- **默认互斥严格「先清后置」**（T84 排的雷）：
  `_clear_other_defaults()` 逐行改 `is_default`（**不用批量 UPDATE**——
  批量更新绕过 ORM 脏检查，内存里的对象会留着旧值，
  后面 flush 可能把刚清掉的老默认行又立起来），
  flush 之后再把目标行置 1。
- **连通性测试失败返回 200 + `ok=false`**，不抛 502——
  它不是业务异常，是「这个配置连不通」的正常反馈，
  前端要在表单里内联展示。成功与失败**都**写一条
  `llm_run_logs(task_type='provider_test')`。
- **失败消息只取 `LLMCallFailed.message`**：其它异常只取**类型名**，
  不取 `str(exc)`——原始异常里可能带 URL、请求头等敏感片段。
- **模板版本自增只看正文**：`system_prompt` / `user_prompt` 变了才
  `version_no += 1`；只改 `description` / `status` **不**升版本
  （升了「模板版本」就失去「内容变了」的标记意义）。
  `task_type` **不在入参里**——改了等于换了个模板的身份，历史分析对不上。
- **运行留痕的调用次数是「本次任务」的**：`provider.calls` 是累计的，
  所以**跑前记基线、跑完相减**。直接取 `len(calls)` 会把历史调用算进来。
- **留痕表里根本没有 Prompt / token 列**——不是靠代码自觉，是表结构保证。
- **连通性测试的 transport 走依赖注入**（`provider_transport`）：
  生产是 `None`（真实网络），测试注入 `httpx.MockTransport`，
  **零真实 socket**。
- **校验一律在服务层做**：pydantic 校验失败会变成 422，
  而 spec 要求 400 `LLM_PROVIDER_INVALID` / `PROMPT_TEMPLATE_INVALID`
  （与 01–05 的既有口径一致）。

## 5.5 07 期 · T99 完成情况（2026-11-19）

**做完了什么**：测试点分析的**两张新表 + 迁移 `0022` + 播种模板 + 留痕枚举扩充 + 9 个错误码**。
**零业务逻辑**——本期只落结构，不碰任何判定。

- [x] `app/models/test_point.py`（新增）：`TestPointAnalysis`（`test_point_analyses`）+
  `TestPoint`（`test_points`），字段 / 索引 / 4 个 CHECK 对齐 spec §4；
  注册到 `app/models/__init__.py`。
- [x] `migrations/versions/0022_test_points.py`：`down_revision="0021"`，
  两表按外键顺序建、`downgrade` 反序直接删表。
- [x] `llm_run_logs.task_type` 的 CHECK 扩 `'test_point'`。
- [x] 播种 `task_type='test_point'` 模板（`[TEST_POINT_SYSTEM]` / `[TEST_POINT_USER]`）。
- [x] `app/common/errors.py`：9 个错误类 + `__all__`。
- [x] `tests/test_points/test_models.py`：12 条。

**验证结果**：后端全量 **876 passed**（串行，exit 0）；e2e 全量 **40 passed**（零回归）；
`npm run build` 通过；`dev_check.py` 通过；两个库迁移 head 均在 **`0022`**；
`0022 → 0021 → 0022` 往返干净（两库都跑）。

**实现要点**：

- **测试点不建唯一键**：同名测试点是合法的（不同功能的同名测试点，
  比如两个功能都要验「连续失败 5 次锁定」）。只靠 `idx_tpoints_target` 检索。
- **生成记录与测试点分两张表**：生成任务是一次性的、可能失败；测试点是产出物，
  有独立的评审生命周期，还可能被下游（08 期）引用。
  结构与 05 的 `analyses` / `conclusions` 一致。
- **`target_name` / `chapter_title` 落库快照**：目标或章节后来改名、被删，
  历史测试点仍然对得上原文。
- **MySQL 的 CHECK 违约抛 3819（`OperationalError`），不是 1062（`IntegrityError`）**——
  唯一索引才是 1062。断言要分开写。
- **`Test*` 开头的 ORM 类会被 pytest 当成测试类收集**（`PytestCollectionWarning`），
  模型类上写 `__test__ = False` 关掉。
- **模板示例里的 `target_id` 必须写 `"target_id": 123,`**（带逗号、冒号后有空格）。
  这正是 06 期 L2 踩过的坑：模板示例写死 `"target_id": 1`，真实模型照抄，
  真实的 10096 / 10097 全被当越界丢弃。
- **`llm_run_logs` 的 CHECK 验证做了三层**（不只看「迁移跑通了」）：
  ① `information_schema` 里能看到新约束文本含 `'test_point'`；
  ② 实插 `task_type='test_point'` → 成功；
  ③ 实插 `task_type='bogus_task'` → 被拒（3819）——
  证明是「扩了枚举」而不是「放开了口子」。

## 5.6 07 期 · T100 完成情况（2026-11-19）

**做完了什么**：Prompt 组装（`context.py`）+ 纯引擎（`engine.py`）+ Mock 前缀分支。
**引擎不写库**——丢弃判定因此可以纯函数级测试，不必起 HTTP、不必起数据库。

- [x] `app/test_points/context.py`：分段组装 + 三段渲染 + 标签 / 结论取数 +
  「全部撤销」判定。
- [x] `app/test_points/engine.py`：`run_generate()`（纯函数 + `on_chapter` 回调）+
  逐条校验与归一；**JSON 解析走 `parse_llm_json`**，不裸 `json.loads`。
- [x] `app/llm/mock.py`：加 `[TEST_POINT_SYSTEM]` 分支，**既有三个分支零影响**。
- [x] `tests/test_points/`：43 条（context 15 + engine 24 + mock 前缀 4）。

**验证结果**：后端全量 **919 passed**（串行，exit 0）；e2e 全量 **40 passed**（零回归）。

**实现要点**：

- **Prompt 严格分段**：模板正文 → 基线目标清单 → 标签依据 → 增量结论 → 章节正文。
  空段落整段省略（不留空标题），相对顺序永不改变。
  **截断只砍章节正文**，前缀保持不变。
- **三处排序全部确定性**（防 Prompt 漂移）：
  清单 `(target_type, target_id)` / 标签依据 `(target_type, target_id, label_type)` /
  增量结论 `(chapter_id, target_type, target_id)`。
  排序键是**元组按字典序**——`"feature_point" < "function"`，
  功能点排在功能前面（与 05 的 `render_baseline_brief` 一致）。
- **逐条校验口径**：`name` 缺失 / `target_type` 非法 → **整条丢弃**；
  `target_id` 不在清单 → **整条丢弃**（`TEST_POINT_TARGET_OUT_OF_BASELINE`）；
  `priority` 非法 → **归一到 medium**（不丢，优先级是展示属性）；
  `precondition` / `verification` 缺失 → **存空串**（不丢）；
  `target_id` 是数字字符串 → **归一成整数**（格式噪声，不是猜测性修复）。
- **测试必须显式给 Mock 队列**：Mock 默认响应的 `target_id=123` 不在真实清单里，
  全被当越界丢弃。`helpers.point_response(target_id=...)` 接收真实 id，
  生成命中清单的响应。**这是 06 期「Mock 通过 ≠ 真实模型能跑」的同一个坑**，
  必须在测试层堵死。
- **`AppError` 基类加 `__test__ = False`**：否则 `TestPointInvalid` 这类
  `Test*` 开头的**错误类**也会被 pytest 当成测试类收集
  （`PytestCollectionWarning`）。基类上一处，全期免疫。

## 5.7 07 期 · T101 完成情况（2026-11-19）

**做完了什么**：权限函数搬迁（05 → `app/common/permissions.py`）+ 服务层 +
11 个接口 + 审计 + 运行留痕。

- [x] `app/common/permissions.py`（新增）：5 个权限函数，**函数体不改**。
- [x] 05 的 `service.py`：保留**同名同签名**的别名，5 个失效 import 已清理。
- [x] `app/test_points/service.py` + `schemas.py` + `router.py`：11 个接口
  （6 条路径），`app/main.py` 注册。
- [x] 运行留痕 `record_run(task_type='test_point')`，`calls` **跑前记基线、跑完相减**。
- [x] 审计：`test_point.analysis.create` / `.delete` / `test_point.review` /
  `test_point.point.*`；`test_audit_coverage.py` 的 `SCENARIOS` 补 1 条。
- [x] `tests/test_points/`：39 条（flow 15 + 权限 7 + 留痕 4 + 手工评审 12 + 审计覆盖 1）。

**验证结果**：后端全量 **958 passed**（串行，exit 0）；e2e 全量 **40 passed**（零回归）；
`npm run build` 通过；05 / 06 定向回归全绿。

**实现要点**：

- **05 的别名必须继续生效**：`_ensure_project` / `_ensure_writable_project` /
  `_ensure_admin` / `_ensure_member` / `ensure_readable` 全部保留原名原签名。
  **唯一的行为变化是错误文案**——搬迁前 05 硬编码「不可发起增量分析」，
  现在由 `action` 参数传入，05 传「发起增量分析」，文案**逐字节一致**
  （e2e 有断言盯着那句文案）。
- **校验顺序有专门的用例盯着**：项目不存在 + 非成员 → 404；
  归档项目 + member → **409**（归档优先于角色）；
  member + 停用模板 → **403**（角色优先于模板）。
- **写接口与读接口的越权错误码不一样**：读接口非成员 → `NOT_PROJECT_MEMBER`，
  写接口非成员 → `NOT_PROJECT_ADMIN`。**这是刻意的**——区分「非成员」与
  「角色不符」会泄露项目是否存在（05 的 `ensure_admin` 注释里明写了这条）。
- **留痕的 calls 必须是「本次任务」的**：`provider.calls` 是累计的，
  跑前记基线、跑完相减。用例连跑两次生成，断言两条留痕的 `call_count`
  都是 **1**（而不是 1 和 2）。
- **踩坑：pydantic 会把多余字段悄悄丢掉**。`PointUpdate` 只声明 4 个字段，
  默认 `extra='ignore'` 会把 `{"status": "approved"}` 在校验阶段就丢掉，
  接口返回 200——用户以为改了，其实什么都没改。
  **修法**：`ConfigDict(extra="allow")` 让多余字段活到服务层判 400。
  （不用 `forbid`：那会变成 422，而 spec 要求 400 `TEST_POINT_INVALID`。）

## 5.8 07 期 · T102 完成情况（2026-11-19）

**做完了什么**：04 侧的引用保护 + 标签清除 → 测试点待复核标记。
**对 04 的改动只有两处**，且**两处都做了表探测保护**。

- [x] `app/baselines/references.py`：加 `_test_point_references` 解析器
  （`_table_exists` 探测）+ 注册进 `_BUILTIN_RESOLVERS`。
- [x] `app/baselines/service.py`：`clear_label()` 多一处调用
  `_mark_dependent_test_points_needs_review()`（**清除逻辑 / 错误码 / 审计一行没动**）。
- [x] `tests/test_points/test_needs_review.py`：8 条。

**验证结果**：后端全量 **966 passed**（串行，exit 0）；e2e 全量 **40 passed**（零回归）；
**04 全部 115 条零回归**（引用检查 + 清除标签定向 13 条也全绿）。

**实现要点**：

- **表探测保护**（04 的红线）：新解析器与待复核标记**都先 `_table_exists`**。
  表不存在 → 返回空列表 / 直接跳过，**不报错、不误判**。
  `_table_exists` 用 inspector 探测（不查 information_schema），MySQL / SQLite 都成立。
- **待复核只碰三列**：用 ORM 的 `update()` 语句，
  **不加载实体**——从物理上杜绝「误改别的字段」。
  名称 / 目标 / 优先级 / 前置条件 / 验证要点 / 章节 / 来源 / 评审状态
  **一个字都不动**。
- **也不改评审状态**：已评审通过（`status='approved'`）的测试点**仍保持 approved**
  ——清除标签不自动降级下游的评审结论（PRD 2.4.4）。
- **引用保护的接线方式与 05 完全同构**：直接进 `_BUILTIN_RESOLVERS`，
  **不 import-time 改全局注册表**——04 不 import 05 / 07 的任何模块，
  各自的表自己探测。
- **踩坑：引擎在同一章节内会对同一目标去重**。第一版测试想造「两条引用同一标签
  的测试点」，在同一章塞了两条 → 只落 1 条（T100 定下的 `seen` 去重口径）。
  改用**两个章节**，每章各产出一条指向同一目标。

## 5.9 07 期 · T103 完成情况（2026-11-19）

**做完了什么**：项目详情页新增第 8 个 Tab「测试点」——生成记录表 + 测试点表 +
发起生成弹窗 + 详情/评审抽屉 + 手工增删改。

- [x] `ProjectTestPointsTab.tsx`：生成记录（状态 / 统计 / 删除）、测试点列表
      （状态 / 目标类型筛选、优先级、待复核标记）、发起生成、手工增删改。
- [x] `TestPointDrawer.tsx`：详情 + 来源追溯（章节 / 标签 / 增量结论）+ 通过 / 驳回。
- [x] `testPointMeta.tsx`：优先级 / 状态 / 目标类型 / 来源 / 丢弃标识文案。
- [x] `api/index.ts` 07 分节（6 个类型 + 11 个函数）；`api/client.ts` 8 个错误码中文。
- [x] `tests/e2e/test_test_points_ui.py` 2 条（`@pytest.mark.task("T103")`）。

**验证结果**：`npm run build` 通过；e2e 全量 **42 passed**（新增 2 + 原 40 零回归）；
截图 `.screenshots/T103/`。

**实现要点**：

- **冲突二次确认**：打开弹窗时快照 `approved` 测试点，提交前用所选 `chapter_ids`
  求交集，有冲突才 `modal.confirm('将覆盖已有评审结果')`；服务端不静默覆盖。
- **e2e 种子造数**：Mock 的占位 `target_id=123` 必然越界（0 条产出），
  `seed_test_points()` 按真实表结构补写测试点，评审 / 增删改仍走真实接口。
- **`InputNumber` 的 `data-testid` 落在外层**，e2e 改用「目标 ID」表单项下的 `input`。

## 5.10 07 期 · T104 收尾（2026-11-19）

- [x] 迁移往返（开发库 + e2e 库）：`0022 → 0021 → 0022` 干净，两库 head 均 `0022`。
- [x] `dev_check.py` 全 `[ OK ]`；两库 04 基线表齐、模板各 1 条 active。
- [x] 后端全量 **966 passed, 42 deselected**（串行，exit 0）。
- [x] 04 / 05 / 06 定向回归：**115 / 154 / 174 passed**，均零回归。
- [x] e2e 全量 **42 passed**（内联 `dev_check --expect-db e2e`）。
- [x] `npm run build` 通过。
- [x] 文档回填：`PROGRESS.md`、`specs/验证约定.md`、`specs/07-test-points/tasks.md`。

**收尾时暴露并修掉的问题**：e2e 库第一次降级失败——`llm_run_logs` 里还有
T103 留下的 `task_type='test_point'` 留痕，旧 CHECK 不含该值。
根因是 `cleanup_e2e_data()` 没清 `llm_run_logs`；已补 `WHERE project_id IN (...)` 的清理。
（详见 `specs/07-test-points/tasks.md` T104 实现要点。）

**断网口径**：开发库保留 1 条 L2 真实配置，`tests/conftest.py` 的 autouse 夹具
在每条用例里摘掉它，966 passed 本身就是「无真实 Provider」的结果；e2e 库本就 0 条。

## 5.11 08 期 · T105~T110 收尾（2026-11-21）

**做完了什么**：PRD 2.4.5 的用例分析全链路——
评审通过的测试点 → 大模型 → 可追溯、可评审、可导出的测试用例。

- [x] T105：`app/models/test_case.py` 三张表 + 迁移 `0023` + 9 个错误类 +
      Mock 前缀分支 + `openpyxl` 依赖；`tests/test_cases` 29 条。
- [x] T106：`context.py`（三段式 Prompt）+ `engine.py`（纯函数丢弃 / 归一）34 条。
- [x] T107：`service.py` + `router.py` 13 个接口 + 审计 + 运行留痕 24 条。
- [x] T108：评审 / 手工 CRUD / 步骤覆盖 / 待复核派生 / Excel 导出 54 条。
- [x] T109：前端第 9 个 Tab「测试用例」+ 步骤编辑器（上移 / 下移）+ 导出；
      e2e 4 条（`@pytest.mark.task("T109")`）。
- [x] T110：两库迁移往返 + 全量回归 + 文档回填；
      新增 `tests/e2e/test_tabs_ui.py` 2 条核对**9 个 Tab 逐个点开**（AC-180）。

**验证结果**：后端全量 **1107 passed**（串行，exit 0）；
04 / 05 / 06 / 07 定向 **544 passed** 零回归；08 定向 **141 passed**；
e2e 全量 **48 passed**；`npm run build` 通过；
两库 head 均 **`0023`**、`0023 → 0022 → 0023` 往返干净；
截图 `.screenshots/T109/`（8 张）+ `.screenshots/T110/`（2 张）；
红线实测 `app/llm/mock.py` +29/-4，其余上游目录零改动。

**本期最关键的一个设计决定**：**不用 `updated_at` 判定「源测试点变了」**。
`test_points.updated_at` 在迁移 `0022` 里只有 `server_default`，
MySQL 方言不会把 SQLAlchemy 的 `server_onupdate` 渲染成 `ON UPDATE`，
应用代码也从不赋值——拿它比对**永远不触发待复核**。
改用 `source_point_fingerprint`（10 个字段的 SHA-256 内容指纹），
指纹字段清单只在 `app/test_cases/fingerprint.py` 一处，生成 / 读取 / ack 三处共用。
`test_cases.updated_at` 同理由服务层显式赋值。

**第二个决定**：`test_point_id` / `test_point_analysis_id` **都不建外键**。
07 的删测试点、删批次都是物理删除，建外键会把 07 的既有行为变成 500。
用逻辑引用 + 落库快照（`test_point_name` / `target_*` / `chapter_*`），
07 的两个删除接口实测仍返回 204。

**第三个决定**：输出契约里**没有测试点 id**，绑定哪个点由服务端按「当前测试点」决定。
06 期「模型照抄示例 id」的坑从结构上消失——模板示例里一个 id 都没有。

## 5.12 09 期 · T110.5 ~ T112（2026-11-21）

**做完了什么**：09 期前半程——数据层、枚举修正、扫描入库。

- [x] T110.5：`GET /api/projects/{id}/todos` 三项待办计数 + 概览 Tab「我的待办」卡片。
- [x] T111：`app/models/automation.py` 三张表 + 迁移 `0024` + 8 个错误类 +
      2 个配置项；**清除原因枚举修正**（`priority_changed` → `baseline_adjusted`、
      `duplicate_label` → `backtrace_override`）；枚举收敛到
      `app/baselines/constants.py`（避免 `schemas` ↔ `service` 循环导入）。
- [x] T112：`app/automation/`（`scanner.py` 纯函数 / `service.py` / `schemas.py` /
      `router.py`）+ 5 个接口（`POST /scan`、`GET /assets`、`POST /assets`、
      `GET /assets/{id}`、`PATCH /assets/{id}`）；`tests\automation` 共 **85 条**。

**验证结果**：后端全量 **1202 passed**（串行，exit 0，只增不减）；
`tests\automation` **85 passed**；`npm run build` 通过；
两库 head 均 **`0024`**、`0024 → 0023 → 0024` 往返干净，
降级后 `clear_reason` 逐字节还原为旧值；e2e 仍 **51 passed**（本期无前端改动）；
红线实测上游目录零改动。

**本期最关键的一个设计决定**：**扫描器做成纯函数**。
`scan_dir` / `resolve_scan_dir` 的签名里根本没有 `session`——
只要拿不到 Session，它就**不可能**写表，「扫描不写表」这条 PRD 要求
就从「靠自觉」变成「结构上做不到」。

**第二个决定**：**绝对路径必须单独判**。
`Path.resolve()` + `is_relative_to(root)` 双检挡住了 `../../etc`，
但挡不住 `C:\Windows`——Windows 上 `root / "C:\\Windows"` 会退化成
`root/C:\Windows`（仍在 root 内），`is_relative_to` 照样放行。
少判这一条，`POST /scan` 就是任意文件读取漏洞。

**第三个决定**：**入库时服务端重扫重算**置信度与识别到的用例数，
不采信前端传的值。前端传的值只是扫描时的快照（文件可能已改），
更重要的是不能让前端决定置信度——否则「随便写个 0.99」就能进库。

## 5.13 09 期 · T113 执行器（2026-11-21）

**做完了什么**：09 期的**纯执行层**——`app/automation/runner.py` +
`tests/automation/test_runner.py`（新增 25 条）。

- [x] `run_pytest(exe, root, rel_path, timeout, cwd)`：
      `timeout=` 强制超时 / `capture_output=True`（内部即 `communic()`）/
      `shell=False`（参数列表传，不经 shell）；`TimeoutExpired` 被按住不冒泡。
- [x] `parse_pytest_summary(output)`：按**形状**挑 pytest 的统计行，
      解析 `passed` / `failed` / `skipped` / `error`；挑不到 → `{'total': None}`（不抛错）。
- [x] `aggregate_result(counts)`：有失败 → failed；全跳过 → skipped；否则 passed。
- [x] `exe` / `root` / `timeout` / `cwd` **全部可注入**；越界与绝对路径直接拒。

**验证结果**：后端全量 **1227 passed**（1202 + 25，串行，exit 0，只增不减）；
`tests\automation` **110 passed**（85 + 25）；上游定向回归 **685 passed**，0 failed；
`npm run build` 通过；零真实 socket（`tests\automation` 无 `requests` /
`urlopen` / `aiohttp` / `socket.socket`）。

**本期踩到的真坑（实测发现，不是看文档看出来的）**：
**平台自己的 pytest 配置会漏进被执行的资产**。
`AUTOMATION_ROOT` 默认在仓库内（`var/automation`），pytest 从工作目录**向上**找配置文件，
捡到**平台自己的** `pyproject.toml`（`addopts = "-q -m 'not e2e'"`），后果两条都很隐蔽：
① `-m 'not e2e'` → 资产里标了 `e2e` 的用例被**静默 deselect**（少跑用例却装作跑完了）；
② `-q` 与我们自己的 `-q` 叠成 `-qq` → **pytest 的统计行整个消失**，
计数解析恒为 `{'total': None}`。第一版按 spec 写 `-q` 就是这么翻车的——
用探针脚本逐个 flag 组合试才定位到根因。

**修法**：配置隔离按「资产有没有自己的 pytest 配置」分流——
有自己的 → `-c <它>`（**它自己的 `addopts` 照常生效**）；
没有 → `-o addopts=`。
不统一用 `-o addopts=` 是因为它会连资产自己的 `addopts` 一起清空
（这条是被自己的断言抓住的）；不统一用 `-c` 是因为资产没有配置时无从指起。

**死锁用例做了变异测试**：把实现改成「管道 + `wait()` + `read()`」后，
被**两条独立断言**抓住（90 秒内没返回 / 源码出现 `stdout.read(`）；
改回正确实现后**零 diff**。——这印证了 plan §10 的判断：
它是唯一能抓住「有人把 `capture_output=True` 改成管道」的测试。

**「超时即 kill」的两条独立证据**：① 样例写出 PID，执行结束后查该 PID
→ 进程已不存在（Windows 走 `OpenProcess` + `GetExitCodeProcess`，
**不能用 `os.kill(pid, 0)`**——那在 Windows 上会真的去终止进程）；
② 样例睡醒后才写 `finished.marker`，文件始终不存在 → 没跑到自然结束。

## 5.14 09 期 · T114 执行编排与报告（2026-11-22）

**做完了什么**：把执行器接进服务层与接口层——**执行 → 记录 → 报告**闭环。

- [x] `app/automation/service.py` 追加：
      `execute_run`（校验 → 建 run → **逐资产执行 + 逐资产 commit** → 汇总 → 审计）、
      `list_runs`、`get_run_report`。
- [x] `app/automation/router.py` 追加：`POST /runs`、`GET /runs`、`GET /runs/{id}`。
- [x] `app/automation/schemas.py` 追加：`RunCreate` / `RunOut` / `RunReportOut` /
      `RunItemOut` / `TraceabilityOut`。
- [x] 审计 `automation.run.execute`（含 `run_id` / `asset_ids` / `stats` / `status`）；
      `tests/common/test_audit_coverage.py` 的 `SCENARIOS` 补 1 条。
- [x] `tests/automation/test_run_flow.py`（20 条）+ `test_permissions.py`（11 条）。

**验证结果**：后端全量 **1259 passed**（1227 + 32，串行，exit 0，只增不减）；
`tests\automation` **141 passed**（110 + 31）；上游定向回归 **685 passed**，0 failed；
**08 的 `tests\test_cases` 141 passed**——删用例接口仍返回 **204**，没被外键卡住；
`npm run build` 通过；零真实 socket。

**本期最关键的一个设计决定**：**状态语义靠 `error` 区分，不靠退出码**。
`status='succeeded'` = pytest 进程**正常跑完**（**哪怕退出码是 1**——
那只是「有测试失败」，是业务结果，不是系统错误）；
`status='failed'` = 跑不起来（超时 / 启动失败），此时 `error` 非空。
实测：1 通过 + 1 失败 → `exit_code=1` / `status='succeeded'` / `error=None`；
超时 → `status='failed'` / `error` 含「超时」。

**第二个决定**：**追溯链的 N+1 有专门的回归断言**。
`get_run_report` 用一次 `IN` 批量取关联用例，循环里只查内存。
断言不靠「代码里看着像一次 IN」，而是用 SQLAlchemy 事件钩子**数 SELECT 条数**——
3 条明细时查用例表**必须恰好 1 次**（N+1 的话会是 3 次）。

**第三个决定**：**明细快照 `case_title`**。08 的删用例是**物理删除**，
所以执行时把用例名快照进 `automation_run_items.case_title`——
用例删后报告仍可读（`source_case_deleted=true`），
且 **08 的删用例接口仍返回 204**（`linked_case_id` 不建外键）。

**踩坑：同名私有函数覆盖了 T112 的 `_cases_by_id`**。
T112 的 `_cases_by_id(session, assets)` 收**资产列表**，
T114 我先写了个同名的 `_cases_by_id(session, case_ids)` 收**用例 id 集合**——
Python 里后定义的那个**静默覆盖**前面的，T112 的资产列表接口当场炸成
`ArgumentError: Object <AutomationAsset> is not legal as a SQL literal value`。
修法：T114 改用 `_cases_by_ids`（复数），两个函数各司其职。
**同名私有函数是最容易踩的隐形雷**——它不报错，只是把别人的行为换掉。

**踩坑：全量 pytest 不能用 `-o addopts=`**。平台的 `addopts` 里含
`-m 'not e2e'`，覆盖掉它就会把 51 条 e2e 一起收进来 → 它们要连 8001 端口
→ 51 个 error。**要看用例数用 `-m "not e2e"`**。

## 5.15 09 期 · T115 前端「自动化执行」Tab（2026-11-22）

**做完了什么**：09 期的前端——项目详情第 **10** 个 Tab「自动化执行」，
把「扫描入库 → 资产列表 → 关联用例 → 触发执行 → 单次报告」这条闭环**端到端打通**。

- [x] `ProjectAutomationTab.tsx`（主文件，只留状态与事件编排）
      + `automationColumns.tsx`（两张表的列定义，纯渲染）
      + `AutomationScanModal.tsx` + `AutomationLinkModal.tsx`
      + `AutomationReportDrawer.tsx`
      + `automationMeta.tsx`（展示常量单独成文件，与 `testCaseMeta.tsx` 同构）。
- [x] `api/index.ts` 追加 `automation` 命名空间（8 个方法 + 类型）；
      `api/client.ts` 追加 8 个错误码中文。
- [x] `ProjectDetailPage.tsx` 加第 **10** 个 Tab「自动化执行」（插在「测试用例」之后）。
- [x] `tests/e2e/test_automation_ui.py` 5 条（全绿）；
      `test_tabs_ui.py` 补第 10 个 Tab；`support.py` 加样例文件写 / 删辅助。

**验证结果**：后端全量 **1259 passed**（串行，exit 0，零回归）；
e2e 全量 **56 passed**（51 + 5）；`npm run build` 通过；
截图 `.screenshots/T115/`（9 张，文件名含 AC-194）；`tests\automation` **141 passed** 未动。

**本期最关键的一个设计决定**：**状态文案分两套，绝不混用**。
执行记录里的状态说的是**执行进程**（`执行完成` / `执行失败`），
明细里的结果说的是**用例**（`通过` / `失败` / `跳过`）。
`status='succeeded'` 且 `exit_code=1` 是**正常情况**——pytest 进程跑完了，
只是有测试没过，那是**业务结果**不是系统错误。
前台用例的样例文件刻意写成「1 通过 + 1 失败」，正是为了把这条口径钉死。
（文案取「执行完成」而不是「成功」，就是为了跟用例的「通过」区分开。）

**第二个决定**：**写入口只有项目管理员才渲染**。
扫描 / 入库 / 改关联 / 触发执行四个按钮，成员与访客**一个都看不到**
（不是「渲染了点了报 403」——前端就不给入口），
只显示一句「只有项目管理员可以扫描、入库与执行，你可以查看资产与报告」。

**第三个决定**：**Playwright 资产的执行按钮置灰 + tooltip**
「Playwright 执行能力待后续期」。实现上有个细节：**disabled 的按钮不派发鼠标事件**，
Tooltip 必须挂在外层 `<span>` 上才会弹。

**踩坑：`e2e 后端的 cwd 是仓库根，所以 `AUTOMATION_ROOT` 指向的就是仓库里的
`var/automation`**。不往那儿写样例 pytest 文件，扫描永远返回空清单——
这是本期 e2e 造数最容易踩的一条。
样例由 `support.write_automation_samples` 写、`remove_automation_samples` 删；
`var/automation/` 已进 `.gitignore`（用户放自己测试脚本的地方，不该进版本库）。

**踩坑（暴露了一个既有竞态）：`helpers.pick_select_option` 在 Select 处于
`disabled` 时点击是**静默无效的**。
「模板」下拉的选项是异步加载的，机器一慢就会在加载完成前被点到——
dropdown 永远不开，后面等选项就超时。
T115 加了会**真起 pytest 子进程**的 e2e 用例后机器变慢，
这个**已存在**的竞态被顶了出来（`test_ac_157_generate_review_and_manual_crud_ui` 失败）。
**用 `git stash` 对照验证过**：改动前全量 e2e 51 passed，改动后 55 passed + 1 failed。
修法：点之前先 `expect(select).not_to_have_class(re.compile(r"ant-select-disabled"))`。
**这类「机器慢就暴露」的竞态，值得单独立一条——它平时不冒，改动一碰就冒。**

**验证约定的编号要留意**：`specs/验证约定.md` 的 **§5.11 已被 T110.5 占用**
（09 期工作台待办计数），所以 09 期的**自动化执行**前台核对点顺延为 **§5.12**。

## 5.16 09 期 · T116 收尾（2026-11-22）

**做完了什么**：09 期的收尾——全量回归 + 两库迁移往返 + 红线复核 + 文档回填 +
`specs/09-automation/收官总结.md`。**09 期正式收官。**

**验证结果**（全部实跑，非引用）：

| 项 | 结果 |
|---|---|
| 后端全量 pytest（串行） | **1259 passed**, 56 deselected, exit 0（454.96s） |
| e2e 全量 | **58 passed**（192.48s；56 + 收官核对 2） |
| 04 / 05 / 06 / 07 / 08 定向回归 | **685 passed**（177.96s），0 failed |
| 09 定向（automation + projects） | **301 passed**（152.12s） |
| 迁移往返（两库） | `0024 → 0023 → 0024` 干净，head 均 `0024`，枚举**逐字节还原** |
| 红线 diff（`0dd7549..HEAD`） | 上游目录（test_points / incremental / test_cases / llm / documents）**零改动**；`app/baselines/` 只有枚举修正 |
| 执行器三线 | `timeout=` / `capture_output=True` / **无** `stdout.read()` |
| 零真实 socket | `tests\automation` 无 `requests` / `urlopen` / `aiohttp` / `socket.socket` |

**新增 `scripts/check_migration_roundtrip.py`**（收尾脚本，可复用）：
两库各跑一遍往返，**造存量数据**（用旧枚举名写两行标签）再逐字节比对——
**只看 alembic 版本号不算验证**，「迁移跑通了」不等于「数据还原了」。

**踩坑：e2e 库跑完前台用例会被清空**，一个项目都不剩。
`baseline_labels.revision_id` 有外键 → 没有基线版本就造不出标签 →
脚本得自己补最小前置数据（一个项目 + 一个基线版本），收尾再一并删掉。
（开发库有真实数据，不受这个影响。）

**踩坑（第一次写这个脚本时连踩两次）**：
① `baseline_labels` 的必填列比想的多（`project_id` 不能省）；
② `baseline_revisions.status` 的 CHECK 只认 `submitted` / `approved` / `rejected`——
写 `draft` 被 MySQL 3819 拒了。**造数也得照着真实的 CHECK 写。**

**收官总结**：`specs/09-automation/收官总结.md`
（交付清单 / 数据模型 / 关键设计 / 接口一览 / AC 矩阵 / 验证结果 / 红线复核 / 踩坑 / Backlog）。

**T116 的前台核对**（`tests/e2e/test_t116_closing_ui.py` 2 条，截图 `.screenshots/T116/` 15 张）：
① **10 个 Tab 逐个点开无报错**（每个都断言内容区真的渲染出来了）；
② **「自动化执行」完整走一遍**：扫描 → 入库 → 关联 → 执行 → 报告，
断言追溯链里的章节标题（`4.2 登录失败次数限制`）真的显示出来了。

**主链路至此完整贯通**：
`文档 → 基线 → 增量分析 → 测试点 → 测试用例 → 自动化资产 → 执行报告`

## 5.17 10 期 · T117 ~ T123 流程基线（2026-11-22 ~ 2026-11-24）

**做完了什么**：10 期把 PRD 2.4.2「基线管理」下的**第二个子菜单**做完了——
流程基线（场景 / 前置条件 / 操作步骤 / 预期结果 / 关联功能基线 / 文档反推 / 审核快照）。
**10 期正式收官。**

**验证结果**（全部实跑，非引用）：

| 项 | 结果 |
|---|---|
| 后端全量 pytest（串行） | **1444 passed**, 64 deselected, exit 0（447.96s） |
| 04 ~ 09 定向回归 | **916 passed**（baselines / incremental / llm / test_points / test_cases / automation = 826 + common = 90），0 failed |
| 10 定向（process_baselines） | **176 passed**（T117 的 41 → T121 的 176；T122 / T123 零改动） |
| e2e 全量 | **64 passed**（62 + 收官核对 2），223.65s |
| 前端构建 | 通过 |
| 迁移往返（两库） | `0025 → 0024 → 0025` 干净，head 均 `0025`，**降级后 `task_type` 只剩旧四值** |
| 红线 diff（`379b353..HEAD`） | `app/baselines/` `app/test_points/` `app/incremental/service.py` `app/test_cases/` `app/automation/` `app/models/project.py` `app/documents/` `app/projects/` `app/llm_admin/` 与既有 3 个 e2e 文件 **零改动**；`app/llm/mock.py` 只有新增分支；`app/models/incremental.py` 只有 2 行枚举扩值 |
| 零真实 socket | `tests\process_baselines` / `tests\e2e` 无 `requests` / `urlopen` / `aiohttp` / `socket.socket` |

**本期最重要的三个设计裁决**（不是实现细节，是会影响后续期的口径）：

1. **独立建表，不复用功能基线的表**——04 的 `baseline_labels.target_type` CHECK 写死两个
   层级名、`baseline_review_items.entity_type` CHECK 写死三个、
   `baseline_revisions` 的唯一键让两套基线**抢同一个版本号**。共用表会污染既有 CHECK、
   打断 04–09 的回归断言。
2. **反推引擎是纯函数**——`run_derive()` 的签名里**根本没有 `session`**，
   「反推只出草案不写表」从「靠自觉」变成「**结构上做不到**」。
3. **提交即冻结 + 审核期锁定**——审核人看到的与最终冻结的**逐字节相同**
   （`structure_json` 直接由 `draft_snapshot` 转正）。

**新增 `scripts/check_process_baseline_roundtrip.py`**（收尾脚本，可复用）：
两库各跑一遍 `0025 → 0024 → 0025`，**造存量数据**（一个场景 + 一步）再比对——
**只看 alembic 版本号不算验证**，「迁移跑通了」不等于「数据还原了」。
断言降级后四张表已删、`task_type` **只剩旧的四个值**；升级后四张表已建、
`process_baseline` 模板**已重新播种**且旧四值模板仍在。

**T123 的前台核对**（`tests/e2e/test_t123_closing_ui.py` 2 条，截图 `.screenshots/T123/` 20 张）：
① **10 个顶层 Tab 逐个点开无报错**（每个都断言内容区真的渲染出来了）；
② **「基线管理」内两个子 Tab 逐个点开**（默认停在「功能基线」）；
③ **流程基线完整走一遍**：新建 → 编辑步骤 → 关联 → 反推 → 提交审核 → 通过 → 看快照。

**收官总结**：`specs/10-process-baseline/收官总结.md`
（交付清单 / 数据模型 / 关键设计 / 接口一览 / AC 矩阵 / 验证结果 / 红线复核 / 踩坑 / Backlog）。

**「基线管理」这个子菜单至此整体做完**：
功能基线（三级树 + 标签 + 快照 + 保留策略，04 期）
+ 流程基线（场景 + 步骤 + 关联 + 反推 + 审核快照，10 期）。

## 6. 待办（不属当前冲刺，等用户点头再做）

- [x] 06 期其余任务：T87（前端系统设置页 + 05 动态模板下拉 + L1/L2 联调收尾）—— 已完成
- **09 期欠账**（2026-11-21 开工时登记，详见 `specs/09-automation/spec.md` §13）：
  - 执行器管理（注册节点 / 远程 Agent / Docker / 心跳 / 连通性检测）→ 后续期
  - 凭据管理（全局统一管控，PRD 1.4 原则三）→ 后续期
  - Playwright 执行、HttpRunner / Appium 扫描 → 后续期
  - 趋势视图、报告导出（PDF / HTML / Excel）、分享链接（PRD §5 的 P2）→ 后续期
  - 逐测试函数粒度的执行明细（junit-xml 解析）→ 后续期
  - 资产 ↔ 用例的 1:N 映射 → 后续期
  - 报告的完整追溯链（用例 → 基线版本 → 增量分析结论）——需给 `test_cases` 补基线版本引用列
  - 工作台待办的另外两项：待审批的项目加入申请（02）、待确认的文档版本（03）
  - ~~**流程基线**（PRD 2.4.2 另一个子菜单：场景 / 前置条件 / 操作步骤 / 预期结果）~~ ——
    **已由 10 期 T117 ~ T123 全部落地**（用户 2026-11-21 裁决「跳过」，
    2026-11-22 起补做；见 §5.17 与 `specs/10-process-baseline/收官总结.md`）
- **10 期欠账**（2026-11-24 收官时登记，详见 `specs/10-process-baseline/spec.md` §13）：
  - **增量分析支持流程基线打标**（PRD 2.4.2 流程基线的「标签」）——
    需扩 04 的 `baseline_labels` CHECK + 改 05 的引擎目标类型。**不做的话流程基线
    是「只能手工维护的孤岛」**——建议排第一
  - **流程基线快照保留策略 + 被引用即保护 + 清理候选 + 告警 + 删除留痕**——
    需新增项目列 `process_snapshot_max_count`；04 已有成熟实现可照抄
  - 流程基线的**分点审核**（逐场景批准 / 驳回）——需新的审核明细表
  - 流程基线快照被**测试点 / 用例 / 执行报告**引用后纳入「被引用即保护」
  - 流程基线的**变更历史**与**关联增量分析记录**展示（PRD 2.4.2「基线详情页」）
  - 流程基线的**标签筛选**（PRD 2.4.2「基线检索」的标签维度）
  - 流程基线的 **Excel 导入导出**
  - 场景 ↔ **测试点 / 测试用例**的关联（PRD 未要求，需改 08 的表结构）
  - 场景的**版本筛选**（列表按快照版本过滤）
  - Skill 模式（PRD 2.5）——延续 06 / 07 / 08 / 09，只做直连
- **08 期欠账**（2026-11-21 收官时登记）：
  - **Excel 导入**（PRD 2.4.5 提了「批量导入导出」）——本期只做导出，
    用户裁决「Excel 只做导出」；导入若要做，需先定「导入模板的列定义 + 冲突口径」。
  - ~~工作台「待评审的用例」审计数~~ —— **已由 09 期 T110.5 落地**
    （概览 Tab「我的待办」卡片，含待评审用例 / 待评审测试点 / 待审核基线三项）。
  - 用例版本历史 / 快照——本期定位为可增删改的活文档，PRD 未强制。
  - 用例编号流水（PRD 2.4.5 的编号规则）——本期用自增 id，未做业务编号。
  - Skill 模式（PRD 2.5）：06 / 07 / 08 均只做直连模式，未做 Skill 包 / manifest / 回退开关。
- **07 期欠账**（2026-11-19 收官时登记）：
  - **无基线直接对文档分析**（PRD 2.4.4 输入②）：本期只做「增量结论 + 生效标签」；
    该路径需要先解决「测试点挂到哪个功能」的追溯问题，建议与 08 期用例生成一起评估。
  - ~~工作台「待评审的测试点」计数~~ —— **已由 09 期 T110.5 落地**。
  - 测试点版本历史 / 快照：本期定位为可增删改的活文档，PRD 未强制。
  - Skill 模式（PRD 2.5）：06 / 07 均只做直连模式，未做 Skill 包 / manifest / 回退开关。
  - Token 计费 / 配额：未做。
- PDF 扫描件 OCR（本期只做「无文字层 → 整文单章」降级）
- PDF 表格结构化落库（本期还原成 `a | b` 文本行，与 docx 同构）
- 05 第五期：模板管理 UI 与阈值回填（依赖基准集）
- 修 `tests/projects/` 的 xdist flaky（断言未按项目隔离）
- [x] （2026-11-19）前端「来源类型」筛选下拉值 `'document'` → `'document_derived'`
      （原值让「文档解析」永远 0 条）。新增 e2e
      `test_ac_73_source_filter_document_derived`：走真实「上传 → 生效 → 推导 → 采纳」
      造出 `document_derived` 功能，再验筛选双向命中；`cleanup_e2e_data` 补清理
      `baseline_derives` / `baseline_derive_candidates`。
      验证：后端全量 **864**（串行，exit 0）、e2e **40 passed**、`npm run build` 通过。
- [ ] 标签清除原因 6 类枚举与 PRD 2.4.2 不符（`priority_changed` / `duplicate_label`
  应为「基线已调整」/「回溯覆盖」）—— **由 09 期 T111 修复**（含存量数据迁移）
- 基准集与评估脚本（v2.2 §10；05 的召回策略与切分阈值全靠它回填）
