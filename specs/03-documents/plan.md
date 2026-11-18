# 03 · 文档解析与基线（解析段）· 技术方案

> 规格见 [spec.md](./spec.md)，任务清单见 [tasks.md](./tasks.md)。
> 遵循 01 / 02 已落地的分层：`models` → `service` → `router`，依赖注入复用 `app/common/deps.py`。

## 1. 模块落点

后端在 `D:\aitest_copilot`：

```
app/
  documents/
    __init__.py
    parser.py        # md / docx / txt → 章节节点树（纯函数，无 DB）
    service.py       # 上传、版本流转、快照、读取
    schemas.py       # Pydantic 出入参
    router.py        # /api/projects/{pid}/documents、/baselines
  models/document.py # Document / DocumentVersion / DocumentChapter / BaselineSnapshot
  common/config.py   # + UPLOAD_DIR、DOC_MAX_BYTES
migrations/versions/00xx_documents.py
tests/
  documents/
    conftest.py      # 造文档的 fixture（写盘用 tmp_path 覆盖 UPLOAD_DIR）
    test_upload.py
    test_parser.py
    test_read.py
    test_version_flow.py
    test_baseline.py
    test_download.py
  e2e/test_documents_ui.py
```

前端在 `D:\aitest_copilot\web`：

```
src/pages/ProjectDetailPage.tsx      # 增加两个 Tab
src/components/DocumentPanel.tsx     # 上传 + 文档/版本列表 + 章节树预览
src/components/BaselinePanel.tsx     # 快照列表
src/api/index.ts                     # + 文档相关类型与函数
```

## 2. 数据模型与迁移

4 张表字段见 spec §4，统一沿用 `app/models/project.py` 的写法：

- `BIGINT(unsigned=True)` 主键、自增；时间列 `DATETIME(fsp=3)` + `server_default=text("CURRENT_TIMESTAMP(3)")`。
- `_TABLE_OPTS`（InnoDB / utf8mb4 / utf8mb4_0900_ai_ci）。
- `CheckConstraint("status IN ('pending','active','archived','void')", name="ck_document_versions_status")`。
- `active_key` 解决「同文档唯一 active」：定义为 STORED 生成列
  `IF(status = 'active', document_id, NULL)`，配合 `UNIQUE(active_key)`；MySQL 允许多个 NULL。
  生成列由数据库维护，应用层只改 `status`，不会出现「状态改了、键没改」的脏数据。
  （01 / 02 的 `pending_key` 也是同一手法。）
- 迁移文件 `migrations/versions/0011_documents.py`，`down_revision` 指向当前 head（`0010_*`），
  建表顺序：`documents` → `document_versions` → `document_chapters` → `baseline_snapshots`；
  `downgrade` 反序删表。

## 3. 解析器（`app/documents/parser.py`）

对外只暴露：

```python
@dataclass
class ChapterNode:
    title: str
    level: int
    content: str
    children: list["ChapterNode"]

def parse(file_name: str, data: bytes) -> list[ChapterNode]: ...
```

- 按扩展名分派：`.md` / `.txt` / `.docx`；其余抛 `UnsupportedDocType`。
- **markdown**：逐行扫描，用 ``` 开关标记代码块；代码块内不识别 `#`。
  命中 `^(#{1,6})\s+(.*)$` 时生成节点，`level=len(#)`；正文行累加到「当前节点」。
  根节点栈按 level 比较：弹出所有 `level >= 新 level` 的节点，栈顶即父节点。
- **docx**：`python-docx` 读 `Document(io.BytesIO(data))`；段落 `style.name` 匹配 `Heading (\d)` 或 `标题 (\d)`
  视为标题，其余非空段落累加到当前节点正文。表格文本按行拼接后并入当前节点（不建子节点）。
- **兜底**：没有任何标题时返回 `[ChapterNode(title="全文", level=1, content=全文)]`；
  正文全空抛 `EmptyDocument`。
- 解析异常统一包成 `DocumentParseFailed`，由 service 转 400，**不落库**。

## 4. 存储

- 目录：`settings.upload_dir`（默认 `var/uploads`），按 `project_id` 分子目录，文件名 `uuid4().hex + ext`。
- 入库只存相对 `upload_dir` 的路径（`3/ab12….md`），读取时拼 `settings.upload_dir`；
  测试用 `tmp_path` 覆盖配置，避免污染仓库。
- 写入顺序：先落盘 → 解析 → 解析成功再开事务写 DB；DB 失败时删除已落盘文件（`try/except` 清理）。
- 下载用 `FileResponse(path, filename=file_name, media_type="application/octet-stream")`，
  不暴露绝对路径；列表响应显式不含 `file_path`。

## 5. 服务层关键逻辑

### 5.1 上传（`service.upload_document`）

```python
def upload_document(session, *, project_id, user, file_name, data,
                    document_id: int | None = None) -> tuple[Document, DocumentVersion]:
```

1. 校验扩展名 / 大小 / 非空（错误码见 spec §7）。
2. 解析得到章节树（解析失败直接抛，未落任何数据）。
3. `document_id` 为空：以 `Path(file_name).stem` 建 `Document`，同名先查 → `DocumentNameTaken`。
   非空：`SELECT ... WHERE id=? AND project_id=?`，查不到 `DocumentNotFound`。
4. 取版本号：`SELECT MAX(version_no) FROM document_versions WHERE document_id=?` 后 +1；
   `UNIQUE(document_id, version_no)` 兜并发，冲突时抛 `InvalidVersionStatus` 之外的重试不展开（单用户场景）。
5. 写 `document_versions`（`status='pending'`、`chapter_count=len(flat(chapters))`）与 `document_chapters`。
6. 写审计 `document.upload`（`target_type="document_version"`，`after_data` 含 `version_no`/`chapter_count`）。
7. 返回文档与版本；router 组响应。

### 5.2 确认生效（`service.activate_version`）

1. 校验项目 `active` → 否则 `ProjectArchived`。
2. 校验版本属于该文档、属于该项目；状态必须 `pending`，否则 `InvalidVersionStatus`。
3. 权限：`project_admin` / `system_admin` 放行；`member` 仅当 `version.uploaded_by == user.id`；其余 `NotProjectAdmin`。
4. `SELECT ... FROM projects WHERE id=? FOR UPDATE` 拿项目行锁（保证基线 `version_no` 单调）。
5. 旧 `active` → `archived`（生成列 `active_key` 自动变 NULL）；本版本 → `active`。
6. 插 `baseline_snapshots`：`version_no = COALESCE(MAX(version_no),0)+1`、`chapter_count=version.chapter_count`。
7. 审计 `document.version.activate` + `baseline.snapshot.create`，同一事务提交。

### 5.3 作废（`service.void_version`）

状态必须 `pending`；改 `status='void'`；审计 `document.version.void`。权限同 5.2 第 3 步。

### 5.4 读取

- `list_documents`：一次 `GROUP BY` 拿版本数、待确认数、生效版本（`status='active'`）摘要，避免 N+1。
- `list_chapters`：按 `version_id` 取全量（`ORDER BY seq`），内存里按 `parent_id` 组树。
- `list_baselines`：按 `project_id` 取，`ORDER BY version_no DESC`。

### 5.5 概览改造

`app/projects/service.py::get_overview` 把两个常量换成长度统计：

```python
document_count = session.scalar(select(func.count()).select_from(Document)
                                .where(Document.project_id == project_id))
baseline_count = session.scalar(select(func.count()).select_from(BaselineSnapshot)
                                .where(BaselineSnapshot.project_id == project_id))
```

响应结构不变；同步更新 `tests/projects/test_overview.py`（原断言 0 的用例改为「无文档时仍为 0」，
新增有文档场景由 03 的用例覆盖）。

## 6. 依赖与配置

- `pyproject.toml` 依赖加 `python-docx>=1.1`。
- `app/common/config.py` 增加：

```python
upload_dir: str = "var/uploads"
doc_max_bytes: int = 10 * 1024 * 1024
```

- `app/main.py` 注册 `documents.router`。
- `.gitignore` 增 `var/uploads/`。
- 审计 action 常量沿用 `app/common/audit.py` 的字符串写法，不新增枚举。

## 7. 测试策略

### 7.1 后端

| 文件 | 覆盖 |
|---|---|
| `tests/documents/test_parser.py` | md 层级/代码块、docx Heading、无标题整文、空文档、跳跃层级 |
| `tests/documents/test_upload.py` | AC-49 / 50 / 51：成功、类型/大小/空/同名/权限、失败不落库 |
| `tests/documents/test_read.py` | AC-53 / 58：章节树结构、列表字段无 `file_path`、非成员 403 |
| `tests/documents/test_version_flow.py` | AC-54 / 55 / 56 / 59：确认、作废、权限矩阵、归档拦截 |
| `tests/documents/test_baseline.py` | AC-57 / 60：快照字段、版本号递增、概览计数 |
| `tests/common/test_audit_coverage.py` | AC-61：4 个 action |

- 复用现有 `client` / `db` / `admin` / `make_user` 夹具；文件用 `io.BytesIO` 造，
  docx 用 `python-docx` 在测试里动态生成（不提交二进制夹具）。
- `tests/documents/conftest.py` 用 `monkeypatch` 把 `settings.upload_dir` 指到 `tmp_path`，
  并在用例结束清理，避免 `var/uploads` 堆积。

### 7.2 前台（Playwright）

`tests/e2e/test_documents_ui.py`，按任务打 `@pytest.mark.task("T54")`：

1. 登录 → 进项目 → 「文档」Tab 上传 md → 列表出现文档，状态「待确认」。
2. 展开章节 → 树形标题与层级正确；点「确认生效」→ 状态变「已生效」，概览文档/基线数 +1。
3. 「基线」Tab 出现快照记录。
4. 上传 `.pdf` → 页面出现「不支持的文件类型」中文提示。

截图落 `.screenshots/T54/`；造数复用 `tests/e2e/support.py`。

## 8. 风险与取舍

| 风险 | 处理 |
|---|---|
| docx 标题样式不统一（自定义样式名） | 只认 `Heading N` / `标题 N`；识别不到就整文单章，不猜 |
| 章节 `content` 归属歧义 | 只收直属正文，子章节正文归子节点；预览时按树展开，符合直觉 |
| 文件与 DB 不一致 | 先落盘后写库，DB 失败删文件；解析失败不落盘直接返回 |
| 并发确认 | 项目行锁 + `UNIQUE(active_key)` / `UNIQUE(project_id,version_no)` 双保险 |
| 迁移回滚 | `downgrade` 严格反序；先在 e2e 库验证 upgrade/downgrade/upgrade |

## 9. 实施顺序

`T45 模型` → `T46 解析器` → `T47 上传` → `T48 读取` → `T49 确认+快照` → `T50 作废+权限`
→ `T51 下载` → `T52 概览` → `T53 审计` → `T54 前端 + 全量回归`。

T45 / T46 可并行；T47 依赖两者；T48 起依赖 T47。每个任务结束跑「任务 pytest + 全量 pytest」，
T54 收尾跑 e2e 与 `npm run build`。
