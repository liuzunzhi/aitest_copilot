# 09 · 自动化执行与测试报告 · 技术方案

> 配套 [spec.md](./spec.md)（AC-181 ~ AC-196）与 [tasks.md](./tasks.md)（T110.5 ~ T116）。
> 定位：在 08「可交付的测试用例」之上补「自动化执行 + 单次报告」这一段，**不重写基础设施**。

## 1. 总体思路

```
approved 用例（08）
      │
      ├─ scanner.scan_dir()          ← 目录遍历 + 规则匹配 + 置信度（纯函数）
      │
      ├─ service.confirm_assets()    ← 人工确认后入库（服务端重扫，不采信前端）
      │
      ├─ runner.run_pytest()         ← subprocess + 强制超时 + kill + communicate()
      │
      └─ router / report             ← 资产列表、关联、执行记录、单次报告
```

三条关键设计：

1. **扫描与入库分离** —— 扫描只出清单（不写表），入库是另一个动作。
   PRD 2.4.6 明确「由人工确认后入库，不自动全部导入」；PRD 1.4 原则二要求高风险行为人工确认。
2. **执行器的三个安全动作不可省** —— 强制超时、超时 kill、`communic()` 读输出。
   第三条最容易漏：`PIPE` + `stdout.read()` 在子进程输出量大时会**死锁**，
   表现是接口请求永久挂起。
3. **追溯链读快照，不联表** —— 08 已把 `test_point_name` / `target_name` /
   `chapter_title` 落库在用例行上，报告直接读，**零额外联表、零额外表**。

## 2. 目录与文件

```
app/automation/
├── __init__.py
├── scanner.py       # 目录遍历 + 规则匹配 + 置信度（纯函数，可注入 root）
├── runner.py        # subprocess 执行 + 输出解析（可注入 exe/timeout/cwd）
├── service.py       # 扫描确认 / 资产 CRUD / 关联 / 执行编排 / 报告聚合
├── schemas.py       # Pydantic 请求 / 响应模型
└── router.py        # 8 个路由

app/models/automation.py            # AutomationAsset / AutomationRun / AutomationRunItem
migrations/versions/0024_automation.py   # 三表 + 枚举修正
tests/automation/…                  # 见 §10
web/src/pages/ProjectAutomationTab.tsx
web/src/pages/AutomationReportDrawer.tsx
web/src/pages/automationMeta.tsx
tests/e2e/test_automation_ui.py
```

`app/common/config.py` 加 2 个配置项；`app/common/errors.py` 加 8 个错误类。

## 3. 数据层

### 3.1 模型

`app/models/automation.py` 照 07 / 08 的写法：`Mapped[...]` + `mapped_column`，
`__tablename__` = `automation_assets` / `automation_runs` / `automation_run_items`，
列类型照抄 08（`BIGINT(unsigned=True)` / `DATETIME(fsp=3)` / `JSON` / `String(n)`，
`created_at` 用 `server_default=text("CURRENT_TIMESTAMP(3)")`）。

- **三个类都写 `__test__ = False`**：`Automation` 不撞 pytest 的 `Test*` 规则，
  但统一加上更省心（08 的 `TestCase*` 已有先例，见 `app/models/test_case.py`）。
- 不建 ORM `relationship`（07 / 08 也不用），一律显式查询。
- `AutomationRunItem.run_id` / `.asset_id` 的 FK 带 `ondelete="CASCADE"`（数据库级）。
- **`linked_case_id` 绝不建 FK**：08 的 `delete_case` 是物理删除，
  建 FK 会把 08 的既有行为变成 500（与 08 的 `test_point_id` 同一教训）。

### 3.2 迁移 `0024`

`down_revision = "0023"`。upgrade 顺序：

1. `create_table("automation_assets")`
2. `create_table("automation_runs")`
3. `create_table("automation_run_items")`
4. 枚举修正：两条 `UPDATE baseline_labels`

downgrade 严格反序：

1. 枚举还原：两条反向 `UPDATE baseline_labels`
2. `drop_table("automation_run_items")` → `automation_runs` → `automation_assets`

> **枚举还原必须在删表之前还是之后？** —— 顺序其实无所谓（两张表互不相关），
> 但**枚举还原必须在 `downgrade` 里做完**，否则「降级后存量值仍是新枚举名、
> 代码只认旧枚举名」→ 04 的清除标签接口会对历史数据报 `INVALID_CLEAR_REASON`。
> 降级往返要**两库都跑**，且降级后用 `SELECT DISTINCT clear_reason` 断言只有旧值。

> **为什么枚举修正不单独开一个迁移**：T111 同时要建三张表，
> 合成一个迁移少一次往返验证。代价是 `downgrade` 要同时处理两件事——
> 但它们互不依赖，写起来是直的。

### 3.3 错误码

`app/common/errors.py` 末尾追加 8 个类（`ApiError` 子类），补进 `__all__`。
命名与 07 / 08 的 `TestPoint*` / `TestCase*` 保持同一形态：`Automation*`。

## 4. 配置

```python
# app/common/config.py
automation_root: str = Field(default="var/automation", min_length=1)
automation_exec_timeout_seconds: int = Field(default=300, gt=0, le=3600)
```

- `automation_root` 是**相对项目根**的路径（与既有的 `upload_dir` 同一写法）。
- 解析在服务层做一次：`Path(get_settings().automation_root).resolve()`。
- **测试覆盖**：测试里用 `monkeypatch` 改 `automation_root` 指向 `tmp_path`，
  不污染开发库的真实目录。

## 5. 扫描器（`scanner.py`）

```python
@dataclass
class ScannedAsset:
    file_path: str          # 相对 root 的 POSIX 路径
    name: str
    framework: str         # 'pytest' | 'playwright'
    parse_confidence: float
    detected_cases: int

def scan_dir(root: Path, directory: str, limit: int = 2000) -> tuple[list[ScannedAsset], int]:
    """返回 (资产清单, 扫描文件数)。目录越界由调用方先校验。"""
```

**纯函数**：不碰数据库、不碰配置、不写文件。所以规则匹配与置信度可以纯函数级测试，
不必起 HTTP、不必起数据库（与 06 / 07 / 08 的引擎同一思路）。

### 5.1 路径安全（关键）

```python
def resolve_scan_dir(root: Path, directory: str) -> Path:
    """把用户传入的相对目录解析到 root 内；越界抛 AutomationScanPathInvalid。"""
    candidate = (root / directory).resolve()
    if not candidate.is_relative_to(root):
        raise AutomationScanPathInvalid("扫描目录超出允许范围")
    return candidate
```

- **判定基准是 `resolve()` 后的实际路径**，不是字符串里有没有 `..`——
  `sub/../sub2` 解析后仍在 root 内，应放行；`../../etc` 解析后越界，应拒绝。
- `is_relative_to` 是 Python 3.9+ 的 `pathlib` 方法，本项目 `requires-python >= 3.11`，可用。
- **绝对路径输入**：`root / "C:\\Windows"` 在 POSIX 语义下会变成 `root/C:\Windows`，
  仍在 root 内——**所以还要显式拒绝 `Path(directory).is_absolute()`**。
  这条不能省，`is_relative_to` 挡不住它。

### 5.2 遍历规则

```python
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules",
             ".pytest_cache", ".mypy_cache", "dist", "build", ".idea"}
```

- 递归遍历，但**跳过 `SKIP_DIRS`**（硬编码常量，不接受用户输入）。
- 隐藏文件（`.` 开头）跳过。
- 文件数超 `limit`（2000）→ 抛 `AutomationScanTooLarge`。
- 单文件读取**只读前 64KB** 用于规则匹配——不把整个文件读进内存。

### 5.3 规则匹配与置信度

```python
PYTEST_NAME_RE = re.compile(r"^(test_.*|.*_test)\.py$")
PLAYWRIGHT_NAME_RE = re.compile(r"^.*\.(spec|test)\.(ts|js)$")
PYTEST_FUNC_RE = re.compile(r"^\s*(async\s+)?def\s+(test_\w+)", re.MULTILINE)
PLAYWRIGHT_CALL_RE = re.compile(r"\btest\s*\(")
```

| 命中情况 | framework | 置信度 | detected_cases |
|---|---|---|---|
| pytest 文件名 + 有 `def test_` | pytest | 0.95 | 函数计数 |
| pytest 文件名 + 无 | pytest | 0.60 | 0 |
| playwright 文件名 + 有 `test(` | playwright | 0.95 | 匹配计数 |
| playwright 文件名 + 无 | playwright | 0.60 | 0 |
| 都不匹配 | — | — | 进 `skipped`（`unrecognized`） |

> **置信度是规则命中分，不是模型判断**：本期不调模型（§2.2 红线）。
> 规则分可解释、可测试、零成本。真正的语义解析留后续期。

## 6. 执行器（`runner.py`）

### 6.1 三个安全动作（用户拍板的红线，逐条对应）

```python
def run_pytest(
    exe: Path, root: Path, rel_path: str, timeout: int,
) -> tuple[int, str, str | None]:
    """返回 (exit_code, output, error)。error 非空表示「跑不起来」。"""
    try:
        proc = subprocess.run(
            [str(exe), "-m", "pytest", rel_path, "-q"],
            cwd=str(root),
            capture_output=True,      # ← 内部走 communicate()，防 PIPE 死锁
            text=True,
            timeout=timeout,          # ← 强制超时
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr, None
    except subprocess.TimeoutExpired as exc:
        return -1, _safe_text(exc), f"执行超时（超过 {timeout} 秒）"
    except (OSError, ValueError) as exc:
        return -1, "", f"执行器启动失败：{type(exc).__name__}"
```

| 红线 | 实现 | 为什么必须 |
|---|---|---|
| **强制超时（默认 300s）** | `subprocess.run(..., timeout=timeout)` | 没有超时的执行会让 HTTP 请求永久挂起，拖垮整个后端 |
| **超时直接 kill** | `subprocess.run` 在超时时**已经** `kill()` 子进程并 `wait()` 回收 | 残留的 pytest 进程会继续占用 CPU 与端口 |
| **`communic()` 读输出** | `capture_output=True` 内部即 `communicate()` | **禁止** `PIPE` + `process.stdout.read()`：子进程输出塞满管道缓冲区时父进程阻塞等待退出 → **死锁** |

> **`subprocess.run` 的超时语义**（CPython 源码 `Popen.communicate`）：
> 超时后调用 `self.kill()`（SIGKILL）再 `self.wait()` 回收，然后**重新抛 `TimeoutExpired`**。
> 所以「超时即 kill」由标准库保证，我们只需要**捕获 `TimeoutExpired` 不让它冒泡**。
> 唯一要额外小心的是 `TimeoutExpired.stdout` / `.stderr` 可能仍是 `None`
> （超时发生在输出读取之前）——所以用 `_safe_text()` 兜底，**不要直接 `.decode()`**。

> **显式禁止 `shell=True`**：命令参数以列表传入，**不经 shell 解析**——
> 文件名里的空格、`;`、`$` 不会变成命令注入。这是执行器的第三条安全线。

### 6.2 输出解析

```python
_COUNT_RE = {
    "passed":  re.compile(r"(\d+)\s+passed"),
    "failed":  re.compile(r"(\d+)\s+failed"),
    "skipped": re.compile(r"(\d+)\s+skipped"),
    "error":   re.compile(r"(\d+)\s+error"),
}
```

- 逐个正则匹配，**取第一个匹配的组**（pytest 的 `-q` 摘要行在一行里）。
- 全都没匹配 → `stats = {'total': None}`，`log` 保留原始输出（前端标「无法解析统计」）。
- **不解析 traceback 详情** → `error` 只取第一条失败摘要（截断 1000 字符）。

> **为什么不上 `--junit-xml`**：XML 能给逐用例级结果，但本期明细粒度是「资产」
> （spec §4.3 已说明），逐用例级结果用不上。等做逐函数粒度时再引入。

### 6.3 资产级结果聚合

一个 pytest 文件里可能有 N 个测试函数 → 一次执行产生 N 条结果，
但明细是**资产级**（一行一资产）：

| 聚合规则 | result |
|---|---|
| 有任何失败 / error | `failed` |
| 全部跳过（且无失败） | `skipped` |
| 其余 | `passed` |

`error` 取第一条失败摘要。

> **注意与 `automation_runs.stats` 的口径差异**：
> `runs.stats` 是**本次执行的测试函数总数**（pytest 摘要里的 passed+failed+skipped），
> `run_items` 是**资产数**。两者单位不同，前端要分开展示，不要混在一张统计里。
> spec §7.3 的响应示例里 `stats.total=2` 是资产数——**这里以 spec 为准**，
> 实现时 `stats` 统一记**资产维度**（total/passed/failed/skipped 都按资产算），
> pytest 的函数级计数放进 `log` 里。这样 `stats` 与明细行数始终一致，用户不会困惑。

## 7. 服务层（`service.py`）

### 7.1 扫描确认

```python
def confirm_assets(session, actor, project_id, payload) -> dict:
    # 1 校验：项目 404 → 归档 409 → 角色 403
    # 2 逐条：重新扫描该文件 → 重算 confidence / detected_cases（不采信前端传值）
    # 3 同路径已存在 → 跳过（唯一索引 uk_autoassets_project_path）
    # 4 写 automation_assets + 审计 automation.asset.create
```

**服务端重扫的理由**：前端传的值是「扫描时的快照」，文件可能已被改动；
更重要的是**不能让前端决定置信度**——否则「一个随便写的 0.99」就能进库。

### 7.2 资产 CRUD 与关联

- `list_assets`：一次全量取 → Python 层过滤（框架 / 状态 / 关联用例）→ 稳定排序 → 切片分页。
- `link_case(asset_id, case_id)`：
  - `case_id` 为空 → 解绑；
  - 非空 → 校验用例**存在且属本项目**（`select(TestCase).where(id==..., project_id==...)`），
    **不要求 approved**（与 08 手工用例允许挂 pending 点同一思路）。
  - **不回写 08 的用例表**——关联是单向的（资产 → 用例），不建反向字段。
- `archive_asset`：`status='archived'`。归档的资产**不可执行**（AC-187 的校验里查）。

### 7.3 执行编排

```python
def execute_run(session, actor, project_id, asset_ids) -> dict:
    # 1 校验：项目 404 → 归档 409 → 角色 403（项目管理员）
    # 2 资产校验：存在 / 属本项目 / framework='pytest' / status='active'
    #    → Playwright 混入 → 400 AUTOMATION_FRAMEWORK_NOT_EXECUTABLE
    #    → asset_ids 为空 → 400 AUTOMATION_RUN_INPUT_EMPTY
    # 3 建 automation_runs(status='running') + commit
    # 4 逐资产执行 + 写 automation_run_items（逐资产 commit）
    # 5 汇总 stats → status='succeeded'（exit_code==0）/ 'failed'
    # 6 审计 automation.run.execute
```

- **`status` 的判定**：`succeeded` = pytest 进程**正常跑完**（不管退出码）。
  退出码 1（测试失败）在报告里是正常业务结果，**不是系统错误**。
  `failed` 只在「跑不起来」时出现——但本期 `runs.status` 的 `failed` 同时覆盖
  「有测试失败」与「超时」，靠 `error` 字段区分：
  - `error` 为空 → 是「有测试失败」（业务结果）
  - `error` 非空 → 是「跑不起来」（系统问题）
- **逐资产 commit**：某个资产超时不影响后续资产继续跑（与 05 的「逐章节落库」同一思路）。
- **`stats` 按资产聚合**（见 §6.3 的口径说明）。

### 7.4 报告聚合

```python
def get_run_report(session, project_id, run_id) -> dict:
    # 1 校验：项目 404 → 成员可读
    # 2 取 run + items（一次 IN 批量取）
    # 3 追溯链：一次 IN 批量取 test_cases → 读快照字段
    # 4 组装 traceability
```

**追溯链的快照字段全部来自 08 的 `test_cases`**（`test_point_name` / `target_name` /
`chapter_title` / `title`），**不联查测试点与章节表**：

| traceability 字段 | 来源 |
|---|---|
| `case_title` | `test_cases.title` |
| `test_point_name` | `test_cases.test_point_name` |
| `target_name` | `test_cases.target_name` |
| `chapter_title` | `test_cases.chapter_title` |
| `source_case_deleted` | 批量查 `test_cases` 时未命中该 `linked_case_id` |

> **一次 IN 查询取全部用例**：`linked_case_id` 列表可能几十个，
> 逐条查就是 N+1。批量取后在 Python 层建 `{case_id: TestCase}` 映射。

### 7.5 T110.5 待办计数

```python
def get_todos(session, project_id) -> dict:
    # 三个 COUNT，各自限定 project_id
    return {
        "pending_baseline_reviews": n1,
        "pending_test_point_reviews": n2,
        "pending_test_case_reviews": n3,
        "total": n1 + n2 + n3,
    }
```

- **三个独立的 `COUNT` 查询**（不是三个 `IN` 子查询）——三个表结构不同，
  子查询写法反而更绕。三个 `COUNT` 在 MySQL 上都是索引扫描，代价可忽略。
- 计数**严格限定 `project_id`**（项目隔离红线）。

## 8. 接口层（`router.py`）

- 8 个路由，前缀 `/api/projects/{project_id}/automation`。
- 每个写接口固定 4 步：`项目 404 → 归档 409 → 权限 403 → 业务校验`。
- `POST /scan` 与 `POST /runs` 是**同步**接口，前端要有 loading 与足够长的超时
  （前端 axios 超时要单独调大，或走轮询——与 04 推导的同步执行同一策略）。
- 响应模型全部 `ConfigDict(extra="forbid")`（入参）/ Pydantic 出参模型。

### 8.1 `GET /todos` 落在 `app/projects/router.py`

待办是**项目级**数据，但语义上是「工作台」。落点选择：

| 方案 | 优点 | 缺点 |
|---|---|---|
| `GET /projects/{id}/todos`（**采用**） | 复用 `projects` 路由组；权限逻辑现成；前端概览 Tab 直接调 | 无 |
| `GET /todos`（工作台级） | 一个接口拿全部项目的待办 | 要做「当前用户可见的所有项目」的聚合 + 权限过滤，复杂度高；且前端概览 Tab 是项目内的 |

**采用前者**：待办数挂在**项目详情概览 Tab**，上下文最准，也不用做跨项目聚合。

## 9. 前端

- `ProjectDetailPage.tsx`：
  - `items` 追加 `{key:'automation', label:'自动化执行'}`（插在「测试用例」之后）；
  - **概览 Tab** 加「我的待办」卡片（三个数字 + 跳转按钮）。
- `ProjectAutomationTab.tsx`：三段式（资产表 / 执行记录表 / 两个弹窗）。
  超 400 行按验证约定 §4.3 拆子组件。
- `AutomationReportDrawer.tsx`：单次报告（统计 + 明细表 + 追溯链 + 日志）。
- `automationMeta.tsx`：框架 / 结果 / 状态的中文文案与颜色（与 `testCaseMeta.tsx` 同构）。
- `web/src/api/index.ts` 追加 `automation` 命名空间（8 个方法 + 类型）。
- `web/src/api/client.ts` 追加 8 个错误码中文。

**权限渲染**：`canManage`（项目管理员）才渲染扫描 / 入库 / 关联 / 执行按钮。
**成员与访客**：资产表与执行记录可读，写入口**不渲染**。

**Playwright 资产**：执行按钮 `disabled` + tooltip「Playwright 执行能力待后续期」。

## 10. 测试策略

| 层 | 文件 | 重点 |
|---|---|---|
| 模型 / 迁移 | `tests/automation/test_models.py` / `test_migration.py` | 三表存在；CHECK 接受合法值、拒绝非法值；`0024↔0023` 往返；枚举还原 |
| 枚举修正 | `tests/automation/test_clear_reason_enum.py` | 6 类枚举；存量映射；前端文案；单一出处；既有测试零改动 |
| 扫描器 | `tests/automation/test_scanner.py` | 路径越界；绝对路径；`..` 放行；规则匹配；置信度；跳过目录；上限 |
| 执行器 | `tests/automation/test_runner.py` | **超时即 kill**；**大输出不死锁**；输出解析；退出码语义 |
| 资产 | `tests/automation/test_assets.py` | 入库重扫；同名冲突；关联 / 解绑；越权关联；审计 |
| 执行 | `tests/automation/test_run_flow.py` | Playwright 拒绝；空输入；逐资产落库；stats 口径；报告追溯链；删用例后报告仍可读 |
| 权限 / 归档 | `tests/automation/test_permissions.py` | 矩阵；403 / 404 / 409 顺序 |
| 待办 | `tests/automation/test_todos.py` | 三项计数；项目隔离；非成员 403 |
| e2e | `tests/e2e/test_automation_ui.py` | `test_ac_194_*_ui`：扫描 → 入库 → 关联 → 执行 → 报告 |

测试函数统一命名 `test_ac_<AC号>_<场景>`（验证约定 §4.2）。

**执行器测试的三个要点**：

1. **用 `tmp_path` 造样例文件**，不碰平台自身的 `tests/` 目录——
   绝不能出现「跑 pytest 时把整个平台测试套件跑一遍」的情况。
2. **超时测试用小超时值**（2s）而不是真的等 300s——超时值是配置项，测试里 monkeypatch。
3. **大输出测试**：样例文件打印 1MB 内容，断言执行**在有限时间内返回**
   （PIPE 死锁的回归防线）。这条例子的价值最高——它是唯一能抓住
   「有人把 `capture_output=True` 改成 `PIPE` + `read()`」的测试。

## 11. 复用清单（不重写）

| 能力 | 出处 | 用法 |
|---|---|---|
| `ensure_readable` / `ensure_writable_project` / `ensure_admin` | `app/common/permissions.py` | 原样 |
| `write_audit` | `app/common/audit.py` | 原样（只 add + flush，不 commit） |
| `Page` 分页信封 | 08 的 `app/test_cases/schemas.py` | 照抄形态 |
| `TestCase` 只读查询 | `app/models/test_case.py` | `select(TestCase)`，**不 import 08 的业务函数** |
| `BaselineRevision` / `TestPoint` 只读查询 | 04 / 07 的模型 | `select(...)` 计数 |
| 前端 Tab / 抽屉 / 空态 | `ProjectTestCasesTab.tsx` / `TestCaseDrawer.tsx` | 同构实现 |
| 错误码中文映射 | `web/src/api/client.ts` | 追加 8 条 |
| 配置项写法 | `app/common/config.py` 的 `upload_dir` | 照抄形态（相对路径 + resolve） |

## 12. 风险与规避

| 风险 | 规避 |
|---|---|
| **PIPE 死锁**：子进程输出塞满管道缓冲区，父进程阻塞等退出 → 请求永久挂起 | 只用 `subprocess.run(capture_output=True)`（内部 communicate）；**禁止** `PIPE` + `read()`；AC-186 用 1MB 输出做回归防线 |
| **执行无超时** → 请求挂起 | `timeout=` 强制；超时值可配置（默认 300s）；AC-185 |
| **超时后残留进程** → 占用 CPU / 端口 | `subprocess.run` 超时即 `kill()` + `wait()`；AC-185 断言进程已死 |
| **目录穿越**：`POST /scan` 变成任意文件读取漏洞 | `resolve()` + `is_relative_to(root)` 双检 + 显式拒绝对路径 + 跳过目录硬编码；AC-182 |
| **shell 注入**：文件名含 `;` / `$` | `shell=False`（默认）+ 参数用列表传；AC-183 的文件名用含特殊字符的样例 |
| **外键阻塞 08 删用例**（IntegrityError → 500） | `linked_case_id` **不建 FK**；用快照 + `source_case_deleted` 标记；AC-191 显式回归 08 的删除接口 |
| **执行平台自身的 `tests/` 目录** | 执行的相对路径必须在 `AUTOMATION_ROOT` 内；测试用 `tmp_path` |
| **误扫整个磁盘** | 文件数上限 2000；跳过 `SKIP_DIRS`；只读前 64KB |
| **置信度被前端伪造** | 入库时服务端**重扫重算**；AC-184 |
| **统计口径混淆**（函数级 vs 资产级） | `stats` 统一按**资产**维度，与明细行数一致；函数级计数只进 `log` |
| **`TimeoutExpired.stdout` 为 None** | `_safe_text()` 兜底，不直接 `.decode()` |
| **枚举修正漏改某处** | 枚举只有一处定义（schemas 从 service 导入）；前端类型 + 文案 + 测试三处同步；AC-181 |
| **枚举还原不彻底** → 降级后 04 报 `INVALID_CLEAR_REASON` | `downgrade` 必做反向 UPDATE；往返后 `SELECT DISTINCT clear_reason` 断言 |
| e2e 数据残留 | `tests/e2e/support.py` 清理列表按外键倒序补三表 |
| 04 / 05 / 07 / 08 回归 | T111 只改枚举值与导入关系，**不动任何判定流程**；定向回归必跑 |

## 13. 实施顺序

1. **T110.5** 工作台待办计数（独立小任务，先做掉，解除 07 / 08 的历史欠账）。
2. **T111** 数据层：`0024` 迁移（三表 + 枚举修正）+ 模型 + 错误码 + 配置项。
3. **T112** 扫描器（纯函数）+ 入库服务（服务端重扫）。
4. **T113** 执行器（subprocess + 三条安全线）+ 输出解析。
5. **T114** 服务层 + 接口 + 审计。
6. **T115** 前端 Tab + 报告抽屉 + e2e。
7. **T116** 全量回归 + 迁移往返 + 文档回填。
