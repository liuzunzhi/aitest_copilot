# 09 · 自动化执行与测试报告 · 规格

> 对齐需求：PRD 2.4.6 自动化执行、PRD 2.4.7 测试报告。
> 上游依赖：08-test-case-analysis（`test_cases` / `test_case_steps` / 步骤分步建模）、
> 04-baseline（基线结构与快照）、07-test-points（评审口径）、03-documents（章节追溯）。
> 本期口径（用户 2026-11-21 拍板）：
> - **跳过流程基线**，直接做「扫描入库 + 资产列表 + 关联用例 + 执行 + 单次报告」；
> - **Playwright 本期只扫描入库、只读，不执行**（守住零 socket 与轻量闭环）；
> - **执行权限限项目管理员**（成员只能看报告）；
> - 前置任务 **T110.5 工作台待办计数**；
> - **T111 顺手修复**清除标签原因枚举与 PRD 不符的历史 Bug。
> 本文是待 review 的规格，未写任何业务代码。评审通过后才拆任务落地。

## 0. 一句话结论（先看这个）

| 问题 | 结论 |
|---|---|
| 本期做什么 | **最小执行闭环**：扫描导入 → 资产列表 → 关联用例 → 手动触发执行 → 单次报告 |
| 数据落哪 | 3 张新表（`automation_assets` / `automation_runs` / `automation_run_items`），迁移 `0024` |
| 资产怎么进库 | **扫描只出清单，人工确认后才入库**（PRD 2.4.6「不自动全部导入」） |
| 执行什么 | **只执行 Pytest**；Playwright 资产只入库、只读，执行入口置灰 |
| 执行怎么跑 | 本地 `subprocess` + **强制超时（默认 300s）** + **超时 kill** + **`communic()` 读输出**（防 PIPE 死锁） |
| 扫描安全 | 目录必须落在 `AUTOMATION_ROOT` 内，**`Path.resolve()` 防目录穿越** |
| 执行权限 | **项目管理员**（成员只读报告） |
| 报告追溯 | 复用 08 已落库的用例快照（`test_point_name` / `target_*` / `chapter_*`），**不额外建追溯表** |

---

## 1. 背景与目标

08 期把主链路推到了「可交付的测试用例」：评审通过的测试点 → 大模型 → 可追溯、可评审、可导出的测试用例。

但测试用例**还不是可执行资产**：PRD 4.1 主链路的最后两环——

```
自动化执行（扫描导入 Pytest / Playwright，人工确认入库 → 执行器执行）
测试报告（可追溯 + 趋势）
```

——完全空白。`app/` 下无任何 executor / report / scan 模块，`get_overview()` 里的
`latest_execution` 至今硬编码为 `None`（`app/projects/service.py:344`）。

本期目标：**只消费 08 已有的评审通过用例**，把「用例 → 自动化资产 → 执行结果 → 报告」
这一段打通：

- 支持**扫描导入**已有 Pytest / Playwright 资产，**人工确认后入库**；
- 资产可与测试用例**关联**，形成「用例 ↔ 脚本」的双向可查；
- 选资产**一键执行**，产出可追溯的执行记录与单次报告；
- 报告能**反向追溯到需求来源**（PRD 2.4.7「可追溯链」）；
- 补齐 PRD 2.3.1 缺失的**工作台待办计数**（T110.5）。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 扫描导入 | 扫描 `AUTOMATION_ROOT` 下的目录，识别 Pytest / Playwright 资产，产出**清单 + 解析置信度**，**人工确认后入库** |
| 资产列表 | 关联用例 / 脚本文件 / 类型 / 识别到的用例数 / 最近执行结果；查看文件内容 |
| 关联用例 | 资产 ↔ `test_cases` 关联（1:1），可解绑 |
| 手动触发执行 | 选择单个或多个资产，一键执行；仅 Pytest 可执行 |
| 执行记录 | 状态 / 退出码 / 统计 / 日志 / 耗时 |
| 单次报告 | 用例明细（通过 / 失败 / 跳过）、失败原因、耗时、日志、**可追溯链** |
| 工作台待办 | T110.5：聚合「待审核基线 / 待评审测试点 / 待评审用例」计数 + 前端卡片 |
| 枚举修复 | T111：`clear_reason` 枚举对齐 PRD 2.4.2 的 6 类原因 + 迁移修正存量数据 |

### 2.2 本期不做（红线，违反即返工）

- **不做执行器管理**（注册节点 / 远程 Agent / Docker / 心跳 / 连通性检测）→ 留后续期。
- **不做凭据管理**（token / 数据库密码 / 凭据 ID 引用）→ 留后续期。
  PRD 1.4 原则三要求凭据全局统一管控，属于独立期。
- **不做 Playwright 执行**：只扫描入库 + 只读，执行入口置灰并提示。理由见 §3.4。
- **不做 HttpRunner / Appium 扫描**：PRD 2.4.6 首批是 Pytest / Playwright / HttpRunner，
  本期取前两个；Appium 明确是二期。
- **不做趋势视图**（多次执行通过率变化、失败用例复现率）→ PRD §5 明确列 **P2**。
- **不做报告导出**（PDF / HTML / Excel）与**分享链接** → PRD §5 明确列 **P2**。
- **不做「无资产 → 用例生成脚本」**：需要 LLM 参与，与本期执行解耦。
- **不做资产 ↔ 用例的 1:N 映射**：本期一个 pytest 文件关联一条用例，
  多函数映射多用例留后续期（§3.4 决策 4）。
- **不做 Skill 模式**（PRD 2.5）：延续 06 / 07 / 08，只做直连。
- **不改 04 / 05 / 07 / 08 的判定逻辑与错误码**：T111 的枚举修复是**唯一**例外，
  且严格限定在「枚举值改名 + 存量数据迁移」，不改任何判定流程（见 §4.5）。
- **不改 `app/llm/`**：本期不调模型。

### 2.3 与上游的兼容约束

1. **用例是唯一执行入口**：执行针对**资产**，但报告的追溯链锚定在**用例**上。
   资产 `linked_case_id` 可空——未关联用例的资产也能执行，报告中该行无追溯链。
2. **`linked_case_id` 不建外键**：08 的 `delete_case` 是**物理删除**，
   建 FK 会把 08 的既有行为变成 500（`IntegrityError`）。沿用 08 的
   `test_point_id` 同一思路：逻辑引用 + 读取时判定「源用例已删除」。
3. **报告追溯读快照，不联表**：08 的 `test_cases` 已落库
   `test_point_name` / `target_name` / `chapter_title` / `precondition` 快照，
   报告直接读这些字段，**不必回查测试点 / 章节表**，也不受上游删除影响。
4. **零真实 socket**：本期不引入任何网络客户端。扫描是本地文件 I/O，
   执行是本地 subprocess。测试同样不产生真实网络请求。
5. **执行器依赖注入**：`subprocess.run` 的可执行路径、超时、cwd 全部可注入，
   测试用 `tmp_path` 造最小 pytest 文件执行，**不碰平台自身的测试套件**。

## 3. 业务语义裁决

### 3.1 资产入库必须人工确认

PRD 2.4.6：「扫描器以插件形式注册……**由人工确认后入库，不自动全部导入**」。

因此 `POST /scan` **只返回清单，不写表**；入库是另一个动作 `POST /assets`，
前端在扫描结果弹窗里勾选后提交。这与 PRD 1.4 原则二「高风险行为人工确认」一致：
批量新建几十个实体是高风险行为。

**扫描结果里识别不到的文件**（既非 Pytest 也非 Playwright）不进清单，
但要在响应里给出 `skipped` 统计与原因（`unrecognized`），让用户知道「扫到了但没认出来」。

### 3.2 解析置信度怎么算

置信度是**规则命中分**，不是模型判断（本期不调模型）：

| 框架 | 匹配规则 | 基础置信度 |
|---|---|---|
| Pytest | 文件名 `test_*.py` 或 `*_test.py` | 0.90 |
| Pytest | 文件名匹配 + 文件内含 `def test_` 函数 | 0.95 |
| Pytest | 文件名匹配但**无** `def test_` | 0.60 |
| Playwright | 文件名 `*.spec.ts/js` 或 `*.test.ts/js` | 0.90 |
| Playwright | 文件名匹配 + 含 `test(` / `test.describe(` | 0.95 |
| Playwright | 文件名匹配但无 `test(` 调用 | 0.60 |

`detected_cases` 记识别到的用例函数 / `test()` 块数量。
**置信度 < 0.7 的资产在入库弹窗里默认不勾选**，并标「低置信度，请人工确认」。

### 3.3 同名冲突：重新扫描怎么办

同一项目下 `file_path` 唯一（唯一索引 `(project_id, file_path)`）。
重新扫描同一目录时，已入库的资产**不重复插入**，而是在扫描清单里标记
`status='existing'` 并返回既有的 `asset_id`——前端默认勾选（已入库的资产本就该在库里）。

若用户想覆盖（比如文件内容大改导致用例数变化），走 `PATCH /assets/{id}`
更新 `detected_cases` 等元数据，**不新建行**。

### 3.4 执行边界

| # | 裁决 | 理由 |
|---|---|---|
| 1 | **只执行 Pytest** | Playwright 需要 node / npx 运行时 + 浏览器二进制。引入它会让 09 期从「轻量闭环」变成「运行时管理」，并显著抬高「零 socket」的难度（浏览器会发起网络请求）。PRD 把 Web 场景的执行交给执行器管理，那部分本期不做。 |
| 2 | Playwright 资产**只读** | 扫描入库、查看内容、关联用例都可做；执行按钮置灰，提示「Playwright 执行能力待后续期」。 |
| 3 | 执行 = **本地 subprocess** | 固定命令 `python -m pytest <相对路径> -q`，工作目录 = `AUTOMATION_ROOT` 解析后的目录。 |
| 4 | 资产 ↔ 用例 **1:1** | 一个 pytest 文件里通常有多个测试函数，但 08 的用例是「一条用例 = 一组步骤」的语义。本期一个文件关联一条用例，多函数映射多用例留后续期（否则要重做「一个文件多结果行」的明细模型）。 |
| 5 | 执行限**项目管理员** | 见 §6 权限矩阵。执行 pytest = 任意代码执行，风险等级与「发起生成」同级。 |
| 6 | 同步执行 | 与 05 / 07 / 08 一致，不引入后台队列。超时 300s 兜底。 |

### 3.5 报告追溯链

PRD 2.4.7：「用例 → 测试点 → 需求章节 / 基线版本 → 增量分析结论」。

本期能给的（全部来自 08 已落库的用例快照字段，**零额外联表**）：

```
用例名称 → 所属测试点（test_point_name）→ 功能/功能点（target_name）→ 需求章节（chapter_title）
```

本期**不能**给的：增量分析结论链路。

> **为什么不做增量结论追溯**：增量结论挂在 `incremental_conclusions` 上，
> 键是 `(analysis_id, target_type, target_id)`，而用例快照里**没有** `analysis_id`。
> 要接上就得在 08 的用例表上再加一列——那是改 08 的表结构，超出本期红线。
> 替代方案是在报告里给**基线版本**（`baseline_revision_id`）——
> 但 08 的用例同样没有这列。**结论：追溯链止于「需求章节」**，
> PRD 2.4.7 的完整链路留后续期（届时需给 `test_cases` 补一列基线版本引用）。

## 4. 数据模型（3 张新表，迁移 `0024`）

列类型与 07 / 08 同口径：`BIGINT(unsigned=True)` / `DATETIME(fsp=3)` / `JSON` / `String(n)`，
时间列 `server_default=text("CURRENT_TIMESTAMP(3)")`。

> **`Automation*` 开头的模型类要写 `__test__ = False`**：`Automation` 不撞 pytest 的
> `Test*` 收集规则，但 `AutomationRun` 之类的类名安全起见统一加上
> （08 的 `TestCase*` 已踩过这个坑，`app/models/test_case.py` 有先例）。
> 错误类不用管——`ApiError` 基类已设 `__test__ = False`，子类自动免疫。

### 4.1 `automation_assets`（自动化资产）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| name | VARCHAR(255) | 非空，文件名（含扩展名） |
| file_path | VARCHAR(1024) | 非空，**相对 `AUTOMATION_ROOT` 的相对路径** |
| framework | VARCHAR(16) | 非空，`pytest` / `playwright` |
| source | VARCHAR(16) | 非空，默认 `scanned`，`scanned` / `manual` |
| parse_confidence | DECIMAL(3,2) | 可空，识别置信度（0.60 ~ 0.95） |
| detected_cases | INT | 非空，默认 0，识别到的用例数 |
| linked_case_id | BIGINT | 可空，**无外键**（逻辑引用 `test_cases.id`），索引 |
| status | VARCHAR(16) | 非空，默认 `active`，`active` / `archived` |
| created_by | BIGINT | FK → users.id，非空 |
| created_at | DATETIME(3) | 非空 |

索引：`idx_autoassets_project`、`idx_autoassets_framework`、`idx_autoassets_linked_case`。
唯一：`uk_autoassets_project_path(project_id, file_path)`。
CheckConstraint：`ck_autoassets_framework`、`ck_autoassets_source`、`ck_autoassets_status`。

> **`file_path` 存相对路径，不存绝对路径**：绝对路径会随部署环境漂移，
> 且泄露服务器目录结构。绝对路径由服务端在执行时用 `AUTOMATION_ROOT` 拼出来。

### 4.2 `automation_runs`（执行记录）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| framework | VARCHAR(16) | 非空，本次执行涉及的框架（本期固定 `pytest`） |
| status | VARCHAR(16) | 非空，默认 `running`，`running` / `succeeded` / `failed` |
| exit_code | INT | 可空，pytest 的退出码 |
| stats | JSON | 可空，`{total, passed, failed, skipped}` |
| log | TEXT | 可空，执行输出（上限 100KB，超出截断并注明） |
| error | VARCHAR(500) | 可空，失败原因（超时 / 启动失败 / 解析失败） |
| started_at / finished_at | DATETIME(3) | 可空 |
| created_by | BIGINT | FK → users.id，非空 |
| created_at | DATETIME(3) | 非空 |

索引：`idx_autoruns_project`。
CheckConstraint：`ck_autoruns_status`。

> **`status` 的语义**：`succeeded` = pytest 进程**正常跑完**（退出码 0）；
> `failed` = 退出码非 0（含测试失败、超时、启动失败）。
> **测试用例失败 ≠ 执行失败**——pytest 退出码 1 表示「有测试失败」，
> 这在报告里是正常的业务结果，不是系统错误。
> `error` 只在「跑不起来」时填（超时 / 文件不存在 / 启动异常）。

### 4.3 `automation_run_items`（执行明细）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT | PK 自增 |
| project_id | BIGINT | FK → projects.id，索引 |
| run_id | BIGINT | FK → automation_runs.id，索引，**ON DELETE CASCADE** |
| asset_id | BIGINT | FK → automation_assets.id，索引，**ON DELETE CASCADE** |
| linked_case_id | BIGINT | 可空，**无外键**（逻辑引用 `test_cases.id`） |
| case_title | VARCHAR(255) | 可空，**用例名称快照**（用例被删后报告仍可读） |
| result | VARCHAR(16) | 非空，`passed` / `failed` / `skipped` |
| error | VARCHAR(1000) | 可空，失败原因 |
| duration_ms | INT | 可空，耗时（毫秒） |

唯一：`uk_autorunitems_run_asset(run_id, asset_id)`。
索引：`idx_autorunitems_run`、`idx_autorunitems_asset`。
CheckConstraint：`ck_autorunitems_result`。

> **明细的粒度是「资产」，不是「pytest 测试函数」**：pytest 一个文件里有 N 个测试函数，
> 一次执行会产生 N 条结果。本期按**文件**聚合明细——
> 一个资产一行，`result` 取该文件内所有测试函数的**汇总**
> （有失败 → `failed`；全跳过 → `skipped`；否则 `passed`），
> `error` 记第一条失败信息。
> 逐函数粒度留后续期（届时 `automation_run_items` 需要拆成「文件 → 用例函数」两层）。

> **为什么快照 `case_title`**：08 的删用例是物理删除。资产关联的用例被删后，
> 报告必须仍能显示「当时关联的是哪条用例」——与 08 的 `test_point_name` 快照同一思路。

### 4.4 迁移 `0024`

`down_revision = "0023"`。upgrade 顺序（按外键依赖）：

1. `create_table("automation_assets")`
2. `create_table("automation_runs")`
3. `create_table("automation_run_items")`（FK → automation_runs / automation_assets，CASCADE）
4. **T111 的枚举修正**（见 §4.5）——与建表在同一迁移里

downgrade 严格反序：删三张表 → 回滚枚举修正。

> **枚举修正为什么放在 `0024` 而不是单独一个迁移**：T111 同时要建表，
> 合成一个迁移少一次往返验证。但**必须能单独回滚**——
> `downgrade` 里枚举修正的还原（把新值改回旧值）要写在删表**之后**，
> 顺序不能反。

### 4.5 T111 附带：清除标签原因枚举修正（历史 Bug）

**问题**：PRD 2.4.2 规定的 6 类清除原因是：

| PRD 原文 | 语义 |
|---|---|
| 误判 | 增量分析结论错误 |
| 基线已调整 | 基线被手工修正，原标签不再适用 |
| 回溯覆盖 | 历史版本回溯分析覆盖原标签 |
| 需求撤销 | 需求取消，对应变更不再生效 |
| 需求已完成（变更已纳入基线） | 变更已测试完成并沉淀进基线，标签使命结束 |
| 其他（备注必填） | 上述均不适用时填写备注 |

而代码里现在是（`app/baselines/service.py:90` 与 `app/baselines/schemas.py:28`，两处重复定义）：

```python
CLEAR_REASONS = (
    "requirement_done",
    "requirement_cancelled",
    "misjudged",
    "priority_changed",   # ← PRD 无此项
    "duplicate_label",    # ← PRD 无此项
    "other",
)
```

**`priority_changed`（优先级变化）与 `duplicate_label`（标签重复）在 PRD 里根本不存在**，
而 PRD 的「基线已调整」「回溯覆盖」两类**无法表达**。

**这不是命名风格问题，是能力缺失**：用户遇到「基线被手工修正了，原标签不再适用」时，
根本选不到对应原因，只能被迫选「其他」并填备注——统计口径从此失真。

**修正方案**：

| 旧值 | 新值 | PRD 对应 |
|---|---|---|
| `requirement_done` | `requirement_done`（**不变**） | 需求已完成（变更已纳入基线） |
| `requirement_cancelled` | `requirement_cancelled`（**不变**） | 需求撤销 |
| `misjudged` | `misjudged`（**不变**） | 误判 |
| `priority_changed` | `baseline_adjusted` | **基线已调整** |
| `duplicate_label` | `backtrace_override` | **回溯覆盖** |
| `other` | `other`（**不变**） | 其他（备注必填） |

**存量数据修正**：迁移里用 `UPDATE baseline_labels SET clear_reason='baseline_adjusted' WHERE clear_reason='priority_changed'`
和 `SET clear_reason='backtrace_override' WHERE clear_reason='duplicate_label'`。
`downgrade` 反向 UPDATE 回旧值。

**影响面（必须逐项核对）**：

| 位置 | 改动 |
|---|---|
| `app/baselines/service.py` 的 `CLEAR_REASONS` | 改 2 个值 |
| `app/baselines/schemas.py` 的 `CLEAR_REASONS` | 改 2 个值（**与 service 重复定义，应统一**） |
| `web/src/api/index.ts` 的 `ClearReason` 类型 | 改 2 个值 |
| `web/src/pages/baselineMeta.ts` 的 `CLEAR_REASON_META` | 改 2 个值 + **改中文文案**（`priority_changed: '优先级变化'` → `baseline_adjusted: '基线已调整'`；`duplicate_label: '标签重复'` → `backtrace_override: '回溯覆盖'`） |
| `baseline_labels.clear_reason` 列 | **无 CHECK 约束**（`0012` 只对 `target_type` / `label_type` / `status` 建了 CHECK），**不需要改表结构**，只需 UPDATE 存量 |
| `CASCADE_CLEAR_REASON = "target_deleted"` | **不动**——它是服务层内部写入的级联标记，不经人工清除接口，不在 PRD 的 6 类里 |
| `app/incremental/apply.py` 的 `CLEAR_REASON = "misjudged"` | **不动**——`misjudged` 未改名 |
| 既有测试 | `tests/` 里现有用例只用了 `misjudged` / `requirement_done` / `other` / `just_because`，**一个都没用到被改的两个值** → 既有测试**零期望值改动**（已 grep 确认） |

**统一枚举的额外收益**：`service.py` 与 `schemas.py` 各写一份 `CLEAR_REASONS`，
迟早会漂移。本期把 `schemas.py` 改成 `from app.baselines.service import CLEAR_REASONS`，
**只留一个出处**。

## 5. 业务语义：扫描与执行

### 5.1 扫描流程

```
POST /automation/scan  { "directory": "sub/dir" }
    1. 校验：项目存在(404) → 归档(409) → 角色(403)
    2. 解析 AUTOMATION_ROOT（配置项，默认 var/automation）
    3. directory 拼接 → Path.resolve() → 必须在 root 内（否则 400）
    4. 遍历目录（跳过隐藏目录 / __pycache__ / node_modules / .venv）
    5. 逐文件按 §3.2 规则匹配 → 命中则产出候选
    6. 已入库的同路径资产 → 标记 status='existing' + 返回既有 asset_id
    7. 返回清单（不入库）+ 统计（scanned / matched / skipped）
```

**目录遍历的安全边界**：
- `directory` **只接受相对路径**；传绝对路径或含 `..` 的路径 → 400
  （`Path.resolve()` 之后再做 `is_relative_to(root)` 二次校验，双保险）。
- 跳过目录列表是**硬编码常量**，不接受用户输入。
- 单次扫描的文件数上限 **2000**，超出 → 400（避免误扫整个磁盘）。

### 5.2 执行流程

```
POST /automation/runs  { "asset_ids": [1, 2] }
    1. 校验：项目存在(404) → 归档(409) → 角色(403，项目管理员)
    2. 资产校验：全部存在、属本项目、framework='pytest'、status='active'
       —— 含 Playwright 资产 → 400 AUTOMATION_FRAMEWORK_NOT_EXECUTABLE
    3. 建 automation_runs(status='running') + commit
    4. 逐资产执行：
         - subprocess.run([python, -m, pytest, rel_path, -q],
                         cwd=root, timeout=300, capture_output=True, text=True)
         - 用 communicate() 读取输出（subprocess.run 内部即 communicate）
         - 超时 → TimeoutExpired → kill 子进程 → result='failed'，
           error='执行超时（超过 300 秒）'
       解析 pytest 输出 → 逐资产算 result / error / duration_ms
         写 automation_run_items
    5. 汇总 stats → status='succeeded'（退出码 0）/ 'failed'
       → finished_at → commit
    6. 审计 automation.run.execute
```

**超时与 kill 的具体口径**（用户 2026-11-21 拍板的安全红线）：

| # | 要求 | 实现 |
|---|---|---|
| 1 | **强制超时，默认 300s** | `subprocess.run(..., timeout=300)`；超时抛 `subprocess.TimeoutExpired` |
| 2 | **超时直接 kill** | `subprocess.run` 在超时时**已经**杀掉子进程并等待回收；额外用 `Popen` 路径时必须显式 `kill()`。本期统一用 `subprocess.run`（其内部 `communicate(timeout=)` 抛异常前会 `process.kill()` + `process.wait()`） |
| 3 | **必须用 `communic()` 读输出** | `subprocess.run` 的 `capture_output=True` 内部走 `communicate()`，天然避免 **PIPE 死锁**（子进程输出塞满管道缓冲区时父进程阻塞等待退出）。**禁止**使用 `subprocess.PIPE` + `process.stdout.read()` 的写法 |
| 4 | 平台自身的 pytest **绝不被执行** | 执行的相对路径必须在 `AUTOMATION_ROOT` 内；测试用的示例文件放在 `tmp_path`，不指向 `tests/` |

**超时值可配置**：新增配置项 `automation_exec_timeout_seconds`（默认 300），
便于测试用小值验证超时分支（测试用 2s，不真的等 300s）。

### 5.3 pytest 输出解析

用 `pytest -q` 的输出解析出三类计数：

```
======================== 2 failed, 3 passed, 1 skipped in 1.23s ========================
```

解析规则（正则，容错）：
- `(\d+) passed` / `(\d+) failed` / `(\d+) error` / `(\d+) skipped` → 统计
- 全部没匹配到 → `stats` 记 `{'total': None}` 并在 `log` 里保留原始输出
- **不解析失败详情**（traceback）→ `error` 只取**第一条**失败摘要（截断 1000 字符）

> **为什么不做完整的 junit-xml 解析**：那需要加 `--junit-xml` 参数并解析 XML，
> 收益是逐用例级结果——但本期明细粒度是「资产」（§4.3 已说明），
> 逐用例级结果用不上。留到做逐函数粒度时再引入。

## 6. 角色与权限

角色沿用 `project_members.role` 三档 + 系统管理员兜底：

| 操作 | 访客 guest | 成员 member | 项目管理员 | 系统管理员 |
|---|---|---|---|---|
| 资产列表 / 详情 / 文件内容 | 可 | 可 | 可 | 可（兜底） |
| 执行记录列表 / 单次报告 | 可 | 可 | 可 | 可 |
| **发起扫描** | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |
| **资产入库 / 改关联 / 归档** | 403 | 403 | 可 | 可 |
| **触发执行** | 403 | 403 `NOT_PROJECT_ADMIN` | 可 | 可 |

- 非项目成员访问读接口 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404 `PROJECT_NOT_FOUND`。
- 归档项目内读接口正常，写接口 → 409 `PROJECT_ARCHIVED`（**先判归档，再判角色**）。
- **复用 `app/common/permissions.py` 的既有 5 个函数**，不新写权限判定：
  - 读：`ensure_readable(session, project_id=..., actor=...)`
  - 写：`ensure_writable_project(...)` → `ensure_admin(..., action="扫描自动化资产")`
- **执行权限限项目管理员**（用户 2026-11-21 拍板）：执行 pytest = 任意代码执行，
  风险等级与「发起生成」同级。成员只能**看报告**。

## 7. 接口

前缀：`/api/projects/{project_id}/automation`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/scan` | 项目管理员 | 扫描目录，返回清单 + 置信度 + 统计（**不写表**） |
| GET | `/assets` | 成员 | 资产列表（框架 / 关联用例 / 状态 筛选，分页） |
| POST | `/assets` | 项目管理员 | 人工确认批量入库（从扫描结果采纳） |
| GET | `/assets/{asset_id}` | 成员 | 资产详情（含文件内容） |
| PATCH | `/assets/{asset_id}` | 项目管理员 | 改关联用例 / 归档 / 更新元数据 |
| POST | `/runs` | 项目管理员 | 触发执行（`asset_ids[]`），同步跑完返回 |
| GET | `/runs` | 成员 | 执行记录列表（分页） |
| GET | `/runs/{run_id}` | 成员 | 单次报告（明细 + 追溯链 + 统计） |

**校验顺序固定**（与 04 / 05 / 07 / 08 一致）：

```
项目 404 → 归档 409 → 角色 403 → 资源/业务校验 400 → 执行
```

**任何一步失败都不产生执行记录**（校验在建行之前）。

### 7.1 `POST /scan` 请求与响应

```json
// 请求
{ "directory": "web-tests" }
```

```json
// 响应
{
  "root": "var/automation",
  "scanned_files": 42,
  "matched": 5,
  "skipped": 37,
  "assets": [
    {
      "file_path": "web-tests/test_login.py",
      "name": "test_login.py",
      "framework": "pytest",
      "parse_confidence": 0.95,
      "detected_cases": 3,
      "status": "new",
      "existing_asset_id": null
    },
    {
      "file_path": "web-tests/login.spec.ts",
      "name": "login.spec.ts",
      "framework": "playwright",
      "parse_confidence": 0.90,
      "detected_cases": 2,
      "status": "new",
      "existing_asset_id": null
    }
  ]
}
```

`status` 取值：`new`（未入库） / `existing`（已入库，`existing_asset_id` 给出既有 id）。

### 7.2 `POST /assets` 请求与响应

```json
// 请求
{
  "assets": [
    { "file_path": "web-tests/test_login.py", "name": "test_login.py",
      "framework": "pytest", "parse_confidence": 0.95, "detected_cases": 3 },
    { "file_path": "web-tests/login.spec.ts", "name": "login.spec.ts",
      "framework": "playwright", "parse_confidence": 0.90, "detected_cases": 2 }
  ]
}
```

**服务端不信任前端传的置信度与用例数**——入库时**重新扫描该文件**并重算，
前端传的值仅作对照。这是为了防止「前端说 0.95 实际 0.1」的数据污染。

响应：`{ "created": 2, "skipped": 0, "items": [{file_path, asset_id}] }`
`skipped` = 因同名冲突且前端标 `skip` 而未入库的数量。

### 7.3 `POST /runs` 请求与响应

```json
// 请求
{ "asset_ids": [1, 2] }
```

```json
// 响应
{
  "id": 7,
  "status": "succeeded",
  "exit_code": 1,
  "stats": { "total": 2, "passed": 1, "failed": 1, "skipped": 0 },
  "items": [
    { "asset_id": 1, "result": "passed", "duration_ms": 820,
      "linked_case_id": 12, "case_title": "连续输错密码 5 次后账号锁定", "error": null },
    { "asset_id": 2, "result": "failed", "duration_ms": 1150,
      "linked_case_id": 13, "case_title": "扫码登录成功", "error": "1 failed, 2 passed" }
  ]
}
```

> **`exit_code` = 1 而 `status` = `succeeded`**：pytest 有测试失败时退出码是 1，
> 但**进程正常跑完了**。`status` 表达「系统是否正常完成执行」，
> 明细里的 `result` 表达「用例是否通过」。两者不能混。

### 7.4 `GET /runs/{run_id}` 单次报告

```json
{
  "id": 7,
  "status": "succeeded",
  "started_at": "2026-11-21T10:00:00",
  "finished_at": "2026-11-21T10:00:02",
  "duration_ms": 1970,
  "stats": { "total": 2, "passed": 1, "failed": 1, "skipped": 0 },
  "log": "===== 2 failed, 3 passed, 1 skipped in 1.23s =====\n...",
  "items": [
    {
      "asset_id": 1,
      "file_path": "web-tests/test_login.py",
      "framework": "pytest",
      "result": "passed",
      "duration_ms": 820,
      "error": null,
      "traceability": {
        "linked_case_id": 12,
        "case_title": "连续输错密码 5 次后账号锁定",
        "test_point_name": "扫码登录连续失败 5 次后锁定",
        "target_name": "用户扫码登录",
        "chapter_title": "4.2 登录失败次数限制",
        "source_case_deleted": false
      }
    }
  ]
}
```

`traceability.source_case_deleted` = 关联的用例已被 08 物理删除 → 追溯链只显示快照值，
并在前端标「源用例已删除」。

### 7.5 错误码（新增 8 个）

| 类名 | code | HTTP | 场景 |
|---|---|---|---|
| `AutomationScanPathInvalid` | `AUTOMATION_SCAN_PATH_INVALID` | 400 | 目录越界 / 绝对路径 / 含 `..` / 不存在 |
| `AutomationScanTooLarge` | `AUTOMATION_SCAN_TOO_LARGE` | 400 | 扫描文件数超上限 |
| `AutomationAssetNotFound` | `AUTOMATION_ASSET_NOT_FOUND` | 404 | 资产不存在 / 不属于该项目 |
| `AutomationAssetInvalid` | `AUTOMATION_ASSET_INVALID` | 400 | 入库参数不合法（框架非法 / 路径为空） |
| `AutomationFrameworkNotExecutable` | `AUTOMATION_FRAMEWORK_NOT_EXECUTABLE` | 400 | 选了 Playwright 资产要执行 |
| `AutomationRunNotFound` | `AUTOMATION_RUN_NOT_FOUND` | 404 | 执行记录不存在 / 不属于该项目 |
| `AutomationRunInputEmpty` | `AUTOMATION_RUN_INPUT_EMPTY` | 400 | `asset_ids` 为空 |
| `AutomationExecFailed` | `AUTOMATION_EXEC_FAILED` | 500 | 执行器启动失败（进程拉不起来） |

全部加进 `app/common/errors.py` 的 `__all__`。

### 7.6 审计

| 场景 | action | after_data |
|---|---|---|
| 扫描 | `automation.scan` | `directory` / `scanned_files` / `matched` / `skipped` |
| 资产入库 | `automation.asset.create` | `created` / `skipped` 计数 + 文件名列表（截断） |
| 改关联 / 归档 | `automation.asset.update` | `asset_id` / 变更字段 |
| 触发执行 | `automation.run.execute` | `run_id` / `asset_ids` / `stats` |

审计条目含 `project_id` / `actor_id` / `target_type` / `target_id`；**失败操作不写审计**。

> **扫描也写审计**：扫描是「读文件系统」，但会暴露目录结构，且是入库的前置动作。
> 记一条便于事后追查「谁在什么时候扫了哪个目录」。

## 8. T110.5：工作台待办计数

PRD 2.3.1：「待办事项：**项目管理员**：待审批的项目加入申请、待确认的文档版本、
待审核的基线变更、待评审的测试点、待评审的用例、最近执行失败的任务。」

07 / 08 都因「口径统一」把这条延后（PROGRESS §6 两处登记）。本期 T110.5 落地，
**口径如下**（三项，均为**当前用户可管理**的项目内计数）：

| 计数 | 口径 | 来源 |
|---|---|---|
| `pending_baseline_reviews` | `baseline_revisions.status='submitted'` | 04 |
| `pending_test_point_reviews` | `test_points.status='pending'` | 07 |
| `pending_test_case_reviews` | `test_cases.status='pending'` | 08 |

**为什么只有这三项**：PRD 列了五项，另外两项——
「待审批的项目加入申请」属于 02 的申请流程（`project_applications`），
「待确认的文档版本」属于 03（`document_versions.status='pending'`），
这两项的实现成本与 04/07/08 同量级，但**它们不与本期的执行闭环强相关**。
本期只做**测试主链路上的三环**（基线 → 测试点 → 用例），构成「基线产出 → 评审 → 用例」的
完整待办链路；申请与文档版本待办登记到后续期。

### 8.1 接口

新增 `GET /api/projects/{project_id}/todos`，权限 = **项目成员可读**（成员也该看到待评审数）。

```json
{
  "pending_baseline_reviews": 2,
  "pending_test_point_reviews": 5,
  "pending_test_case_reviews": 8,
  "total": 15
}
```

- 一次 `IN` 子查询 / 三个 `COUNT` 查询即可，不做 N+1。
- 计数范围**限定在当前项目**（项目隔离）。
- 非成员 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404。

### 8.2 前端

`ProjectDetailPage.tsx` 的**概览 Tab**（`overview`）里加一张「我的待办」卡片：
三个数字 + 点击跳转到对应 Tab（基线管理 / 测试点 / 测试用例）。

> **落点选择**：放在**项目详情的概览 Tab**，不是「我的项目」列表页。
> 理由：待办是**项目内**的事，挂在项目详情里上下文最准；
> 挂在列表页则需要为每个项目拉一次待办数，N+1 请求。

## 9. 前端

- `ProjectDetailPage.tsx`：`items` 追加 `{key:'automation', label:'自动化执行'}`
  （插在「测试用例」之后），项目详情 Tab 由 9 个变 **10 个**。
- `ProjectAutomationTab.tsx`：三段式
  - 上：资产表（文件名 / 框架 / 置信度 / 用例数 / 关联用例 / 最近结果 / 操作）
  - 中：扫描入库弹窗（目录输入 + 扫描结果清单 + 勾选 + 置信度标记）
  - 下：执行记录表（状态 / 统计 / 耗时 / 发起时间）+ 执行按钮 + 报告抽屉
- `AutomationReportDrawer.tsx`：单次报告（统计 + 明细表 + 追溯链 + 日志）
- `web/src/api/index.ts` 追加 `automation` 命名空间（8 个方法 + 类型）
- `web/src/api/client.ts` 追加 8 个错误码中文

**`data-testid` 命名沿用「区域-动作-目标」**：

```
automation-tab / automation-scan-btn / automation-scan-modal
automation-scan-table / automation-scan-confirm-btn
automation-asset-table / automation-asset-row-{id}
automation-asset-link-select / automation-run-btn
automation-run-table / automation-report-drawer / automation-report-item-table
automation-todo-card
```

**访客 / 成员只读**：资产表与执行记录可见；扫描、入库、关联、执行按钮**不渲染**
（不是「渲染了点了报 403」——前端就不给入口）。

**Playwright 资产的执行按钮**：置灰 + tooltip「Playwright 执行能力待后续期」。

## 10. 验收标准

验证口径遵循 [specs/验证约定.md](../验证约定.md)：后端用例命名 `test_ac_<AC号>_<场景>`，
e2e 命名 `test_ac_<AC号>_<场景>_ui`，前台截图落 `.screenshots/<任务号>/` 且文件名含 AC 编号。

### AC-181 清除标签原因枚举对齐 PRD

- **Given** PRD 2.4.2 规定的 6 类原因
- **When** 迁移 `0024` 升级
- **Then** 枚举含 `requirement_done` / `requirement_cancelled` / `misjudged` /
  `baseline_adjusted` / `backtrace_override` / `other`，**不含** `priority_changed` / `duplicate_label`
- **Then** 存量 `priority_changed` → `baseline_adjusted`、`duplicate_label` → `backtrace_override`
- **Then** `downgrade` 后枚举与存量值**逐字节还原**为旧值
- **Then** `CASCADE_CLEAR_REASON='target_deleted'` **不受影响**（级联清除仍写入该值）
- **Then** `app/incremental/apply.py` 的自动清除仍写 `misjudged`
- **Then** 前端 `ClearReason` 类型与中文文案同步（`baseline_adjusted: '基线已调整'`、
  `backtrace_override: '回溯覆盖'`）
- **Then** `service.py` 与 `schemas.py` 的枚举**只有一处定义**（schemas 从 service 导入）
- **Then** 既有测试**零期望值改动**（既有用例未用到被改的两个值）

### AC-182 扫描目录不得越界

- **Given** `AUTOMATION_ROOT` = `var/automation`
- **When** `POST /scan` 传 `directory='../../etc'`
- **Then** 400 `AUTOMATION_SCAN_PATH_INVALID`，**不扫描任何文件**
- **When** 传绝对路径 `C:\\Windows`
- **Then** 400 `AUTOMATION_SCAN_PATH_INVALID`
- **When** 传 `directory='sub/../sub2'`（解析后仍在 root 内）
- **Then** **允许**（`Path.resolve()` 后的结果在 root 内即放行）
- **When** 传一个 `..` 穿越后**仍在 root 内**的路径
- **Then** 允许——**判定基准是 resolve 后的实际路径**，不是字符串里有没有 `..`
- **Then** 服务端**不返回** `AUTOMATION_ROOT` 的绝对路径（只给相对展示名）
- **Then** 扫描**不写表**（`automation_assets` 行数不变）

### AC-183 扫描识别与置信度

- **Given** 目录下有 `test_a.py`（含 2 个 `def test_`）、`b_test.py`（无测试函数）、
  `c.spec.ts`（含 1 个 `test(`）、`readme.md`
- **When** `POST /scan`
- **Then** 清单含 3 条（`readme.md` 进 `skipped`）
- **Then** 置信度：`test_a.py` = 0.95、`b_test.py` = 0.60、`c.spec.ts` = 0.95
- **Then** `detected_cases`：`test_a.py` = 2、`b_test.py` = 0
- **Then** 低置信度（< 0.7）项标记为需人工确认
- **Then** 响应含 `scanned_files` / `matched` / `skipped` 统计
- **Then** 隐藏目录 / `__pycache__` / `node_modules` **不被扫描**

### AC-184 人工确认后入库

- **Given** 扫描结果含 3 条资产
- **When** `POST /assets` 提交 2 条
- **Then** `automation_assets` 新增 2 行，`source='scanned'`、
  `parse_confidence` / `detected_cases` **由服务端重扫得出**（不采信前端传值）
- **Then** 同路径重复入库 → 唯一索引不冲突，返回 `skipped` 计数，**不新增行**
- **Then** 再次 `POST /scan` → 已入库的项 `status='existing'` 且带 `existing_asset_id`
- **Then** 关联用例：可 `PATCH` 关联 / 解绑；关联的用例必须属于本项目
- **Then** 审计 `automation.asset.create` / `automation.asset.update`

### AC-185 执行强制超时且超时即 kill

- **Given** 一个会 `time.sleep(999)` 的 pytest 文件
- **When** 触发执行（超时配置为 2s）
- **Then** 执行**在超时后返回**（不挂起）
- **Then** `automation_runs.status='failed'`、`error` 含「超时」
- **Then** **子进程已被杀死**（断言进程不存在 / 执行能在超时 + 余量内返回）
- **Then** `automation_run_items` 有该资产行，`result='failed'`
- **Then** **不产生真实 socket**

### AC-186 PIPE 死锁防护

- **Given** 一个 pytest 文件，其 stdout 输出**远超管道缓冲区**（如 1MB）
- **When** 触发执行
- **Then** 执行**正常返回**（不挂起）
- **Then** `automation_runs.log` 含该输出的片段
- **Then** 断言实现**走 `communicate()` 语义**（`subprocess.run` 的 `capture_output=True`
  即 communicate；**禁止** `stdout.read()` 阻塞式写法）

### AC-187 只执行 Pytest，Playwright 拒绝

- **Given** 选中的资产里含 1 个 `framework='playwright'`
- **When** 触发执行
- **Then** 400 `AUTOMATION_FRAMEWORK_NOT_EXECUTABLE`
- **Then** **不产生执行记录**（校验在建行之前）
- **Given** 只选 pytest 资产
- **Then** 正常执行，`automation_runs.framework='pytest'`

### AC-188 执行结果与退出码语义

- **Given** 一个 pytest 文件里有 1 个通过、1 个失败
- **When** 触发执行
- **Then** `automation_runs.status='succeeded'`（进程正常跑完）
- **Then** `exit_code=1`（pytest 有失败时退出码为 1）
- **Then** `stats` = `{total:1, passed:0, failed:1, skipped:0}`（按资产聚合）
- **Then** 明细 `result='failed'`、`error` 含失败摘要
- **Given** 一个 pytest 文件里 1 个通过、1 个跳过
- **Then** 明细 `result='passed'`（有失败才是 failed；全跳过才是 skipped）
- **Given** 全部跳过
- **Then** 明细 `result='skipped'`

### AC-189 权限矩阵

- **Given** member / guest
- **When** 读接口（资产列表 / 详情 / 执行记录 / 报告）
- **Then** 200
- **When** 扫描 / 入库 / 改关联 / **触发执行**
- **Then** 403 `NOT_PROJECT_ADMIN`
- **Given** 非项目成员
- **When** 读接口
- **Then** 403 `NOT_PROJECT_MEMBER`
- **Given** 成员（不是管理员）
- **When** `POST /runs`
- **Then** 403（**执行限项目管理员**，成员只能看报告）

### AC-190 归档项目

- **Given** 项目已归档
- **When** 触发执行 / 扫描 / 入库
- **Then** 409 `PROJECT_ARCHIVED`
- **When** 读接口
- **Then** 200

### AC-191 单次报告与可追溯链

- **Given** 资产关联了一条用例（用例有测试点 / 目标 / 章节快照）
- **When** 查看 `GET /runs/{id}`
- **Then** 明细含 `traceability`：用例名称 / 测试点名称 / 目标名称 / 章节标题
- **Given** 关联的用例被 08 物理删除
- **When** 查看报告
- **Then** 明细**仍存在**，`case_title` 保留快照
- **Then** `traceability.source_case_deleted=true`
- **Then** **08 的删用例接口仍返回 204**（不因 FK 冲突变 500）
- **Then** 报告含 `stats` / `log` / `duration_ms`

### AC-192 执行记录与审计

- **Given** 触发一次执行
- **Then** `automation_runs` 新增一行，`status` / `exit_code` / `stats` / `log` 齐全
- **Then** `automation_run_items` 每资产一行
- **Then** 审计 `automation.run.execute` 含 `run_id` / `stats`
- **Then** 审计 `automation.scan` 含 `directory` / 统计
- **Then** **失败操作不写审计**（如 Playwright 被拒、目录越界）

### AC-193 工作台待办计数

- **Given** 项目有 2 条 `baseline_revisions.status='submitted'`、
  5 条 `test_points.status='pending'`、8 条 `test_cases.status='pending'`
- **When** `GET /projects/{id}/todos`
- **Then** 返回 `pending_baseline_reviews=2` / `pending_test_point_reviews=5` /
  `pending_test_case_reviews=8` / `total=15`
- **Given** 另一个项目也有待评审数据
- **Then** 本项目的计数**不含**另一个项目的数据（项目隔离）
- **Given** 非项目成员
- **Then** 403 `NOT_PROJECT_MEMBER`
- **Then** 概览 Tab 展示「我的待办」卡片，三个数字可点击跳转到对应 Tab

### AC-194 前端可用

- 项目详情出现「自动化执行」Tab，位于「测试用例」之后
- 扫描 → 清单展示 → 勾选入库 → 资产表出现新行
- 关联用例 → 资产表显示用例名
- 触发执行 → 执行记录新增一行 → 点开报告 → 明细与追溯链正确
- Playwright 资产的执行按钮置灰
- 成员登录 → 无扫描 / 入库 / 执行按钮，资产与报告可读
- e2e 用例命名 `test_ac_194_*_ui`；截图 `.screenshots/T115/`，文件名含 AC 编号

### AC-195 断网与红线

- **Given** 全量测试套件
- **When** 跑全量
- **Then** **零真实 socket**：测试目录不出现 `requests` / `urlopen` / `aiohttp` / `socket.socket`
- **Then** 执行器测试**不执行平台自身的 `tests/` 目录**（用 `tmp_path` 造样例）
- **Then** 代码里**没有** Skill 模式分支

### AC-196 01–08 零回归

- **Given** 01–08 的既有行为
- **When** 跑全量 pytest 与 e2e
- **Then** 1107 条既有测试**一条不删、不改期望值**
- **Then** 04 / 05 / 06 / 07 / 08 定向回归零失败
- **Then** 迁移 head 两库均为 `0024`，`0024 → 0023 → 0024` 往返干净

## 11. 非功能

- **零真实网络请求**（本期不引入任何网络客户端）。
- **同步执行**：与 05 / 07 / 08 一致，不引入异步队列；超时 300s 兜底。
- **执行隔离**：执行的相对路径必须在 `AUTOMATION_ROOT` 内；平台自身的 `tests/` 目录**永远不会被执行**。
- **日志上限**：`automation_runs.log` 存上限 100KB，超出截断并在前端注明「输出已截断」。
- **大模型不可用**：本期**不涉及模型**，无降级逻辑。
- **API Key 不明文**：沿用 06 期口径；本期不涉及密钥。
- **单次执行规模上限**：一次最多 20 个资产（超出 → 400），避免一次同步请求跑太久。

## 12. 依赖与影响

| 依赖 | 状态 |
|---|---|
| 08 `test_cases` / `test_case_steps` | ✅ 已上线（`0023`） |
| 04 `baseline_revisions` | ✅ 已上线（`0012`） |
| 07 `test_points` | ✅ 已上线（`0022`） |
| 03 `document_versions` | ✅ 已上线 |
| `app/common/permissions.py` | ✅ 5 个权限函数，直接复用 |
| `app/common/audit.py` | ✅ `write_audit` 直接复用 |
| **新增配置项** | `automation_root`（默认 `var/automation`）、`automation_exec_timeout_seconds`（默认 300） |
| **新增运行时依赖** | **无**（`subprocess` 是标准库） |

**对既有模块的影响**：

| 模块 | 影响 |
|---|---|
| `app/models/__init__.py` | 加 3 个模型的 import 与 `__all__` |
| `app/common/errors.py` | 加 8 个错误类 + `__all__` |
| `app/common/config.py` | 加 2 个配置项 |
| `app/main.py` | 注册 1 个路由（`automation_router`） |
| `app/baselines/service.py` / `schemas.py` | **仅** `CLEAR_REASONS` 改 2 个值 + 枚举归一（T111） |
| `app/baselines/schemas.py` | 改为从 `service` 导入 `CLEAR_REASONS`（消除重复定义） |
| `app/projects/router.py` | 加 1 个 `GET /todos` 路由 |
| `web/src/api/index.ts` / `client.ts` | 加 `automation` 命名空间 + 8 个错误码 + `ClearReason` 改 2 值 |
| `web/src/pages/baselineMeta.ts` | `CLEAR_REASON_META` 改 2 值 + 改中文 |
| `web/src/pages/ProjectDetailPage.tsx` | 加第 10 个 Tab + 概览「我的待办」卡片 |
| `app/test_points/` / `app/incremental/` / `app/test_cases/` / `app/llm/` | **零改动** |

## 13. 后续期（明确不在本期）

| 期 | 内容 |
|---|---|
| — | **流程基线**（PRD 2.4.2 另一个子菜单：场景 / 前置条件 / 操作步骤 / 预期结果） |
| — | 执行器管理（注册节点 / 远程 Agent / Docker / 心跳 / 连通性检测） |
| — | 凭据管理（全局统一管控，PRD 1.4 原则三） |
| — | Playwright 执行、HttpRunner / Appium 扫描 |
| — | 趋势视图、报告导出（PDF / HTML / Excel）、分享链接（PRD §5 的 P2） |
| — | 逐测试函数粒度的执行明细（junit-xml 解析） |
| — | 资产 ↔ 用例的 1:N 映射 |
| — | 报告的完整追溯链（用例 → 基线版本 → 增量分析结论）——需给 `test_cases` 补基线版本引用列 |
| — | 工作台待办的另外两项：待审批的项目加入申请、待确认的文档版本 |
| — | 「无资产 → 用例生成脚本」 |
| — | Skill 模式（PRD 2.5） |
