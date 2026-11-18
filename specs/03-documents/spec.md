# 03 · 文档解析与基线（解析段）· 规格

> 对齐需求：PRD 2.4.1 文档管理、2.4.2 基线管理；需求文档 v2.2（工作区 `新建 文本文档.md`）§2 解析段、§5 数据模型。
> 本期只做解析段：**上传 → 拆章节 → 生成不可变基线快照**。比对段、产出段不在本期。

## 1. 背景与目标

平台当前只有项目与成员（01 / 02），概览接口的 `document_count` / `baseline_count` 是固定占位 0（AC-40）。

本期目标：用户能把需求文档传进项目，系统拆出章节树并可视化预览；确认生效后形成**不可变基线快照**，
供下一期比对与用例生成消费。做完后概览的两个计数变成真实数据，文档/基线 Tab 可用。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| 文档 / 版本 | 一个项目多个文档，一个文档多个版本；版本号文档内从 1 递增 |
| 上传 | 单文件 `docx` / `md` / `txt` / `pdf`，≤ 10MB；磁盘按 UUID 存，库内存相对路径 + sha256 |
| 解析 | md 标题层级、docx Heading 样式 → 章节树；pdf 按字号 + 编号 → 章节树；txt 整文单章；无标题同样整文单章 |
| 读取 | 文档列表、版本列表、章节树预览、原文下载 |
| 版本流转 | `pending` → `active`（确认生效）或 `void`（作废）；新版本生效时旧 `active` 自动 `archived` |
| 基线快照 | 确认生效时**同事务**写入，项目内版本号单调递增，不提供修改/删除 |
| 概览 | `document_count` / `baseline_count` 取真实值，`latest_execution` 仍为 `null` |
| 审计 | 上传、确认、作废、快照生成四条 |

### 2.2 本期不做

- **批量上传 / 压缩包**：一次一个文件。
- **人工修正章节边界**：v2.2 §5 提到，但会引入「快照需冻结章节副本」；本期章节随版本不可变，故快照只引用版本。
- **文档删除 / 重命名**：删除会让基线悬空，改名影响同名判重，均不做。
- **比对段、产出段、LLM 调用**：零外部模型依赖。

> **2026-11-17 更新（T84-PDF，06 期）**：PDF 解析**已支持**。
> `pdfplumber` 纯文本提取 + 字号/加粗/编号规则切章节 + 表格还原成 `a | b`；
> 扫描件（无文字层）降级成整文单章「全文」，不报错。
> 详见 [specs/06-real-llm/spec.md §2.4](../06-real-llm/spec.md)。
> 因此 `UNSUPPORTED_DOC_TYPE` 的语义回归「**未知扩展名**」（如 `.xlsx`）。

### 2.3 待确认（先按此实现，可评审时改）

1. 同项目上传同名文档 → `409 DOCUMENT_NAME_TAKEN`，不自动加后缀。
2. 基线快照版本号按**项目**递增（不是按文档）。
3. `guest` 可读不可上传；`member` 可上传，但只能确认/作废**自己上传**的版本。
4. 上传即同步解析；解析失败整体回滚（不留半成品文档/版本），用户重传即可。

## 3. 角色与权限

| 操作 | guest | member | project_admin | system_admin |
|---|---|---|---|---|
| 文档/版本/章节/下载 | 可 | 可 | 可 | 可（兜底） |
| 上传（新建文档 / 追加版本） | 403 `FORBIDDEN` | 可 | 可 | 可 |
| 确认生效 / 作废 | 403 `NOT_PROJECT_ADMIN` | 仅自己上传的 | 任意版本 | 可 |
| 归档项目内的写操作 | 409 `PROJECT_ARCHIVED` | 同左 | 同左 | 同左（概览只读不受影响） |

非项目成员访问读接口 → 403 `NOT_PROJECT_MEMBER`；项目不存在 → 404 `PROJECT_NOT_FOUND`。
所有列表/详情响应**不返回磁盘路径**，只返回文件名与大小。

## 4. 数据模型（4 张表，迁移 0011）

### 4.1 `documents`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `project_id` | BIGINT UNSIGNED | FK → projects.id |
| `name` | VARCHAR(128) | 非空，默认取文件名去扩展名 |
| `created_by` | BIGINT UNSIGNED | FK → users.id |
| `created_at` | DATETIME(3) | 默认 CURRENT_TIMESTAMP(3) |

索引：`UNIQUE(project_id, name)`（同名判重，也覆盖按项目查询）。

### 4.2 `document_versions`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `document_id` | BIGINT UNSIGNED | FK → documents.id |
| `version_no` | INT UNSIGNED | 非空，文档内从 1 递增 |
| `status` | VARCHAR(16) | `pending` / `active` / `archived` / `void` |
| `file_name` | VARCHAR(255) | 原始文件名 |
| `file_path` | VARCHAR(500) | 相对 `UPLOAD_DIR` 的 `<project_id>/<uuid>.<ext>`，不外泄 |
| `file_size` | BIGINT UNSIGNED | 字节 |
| `sha256` | CHAR(64) | 内容摘要 |
| `chapter_count` | INT UNSIGNED | 解析出的章节数，默认 0 |
| `uploaded_by` | BIGINT UNSIGNED | FK → users.id |
| `active_key` | BIGINT UNSIGNED NULL | STORED 生成列 `IF(status='active', document_id, NULL)`，应用层不写 |
| `created_at` | DATETIME(3) | 默认 CURRENT_TIMESTAMP(3) |

索引：`UNIQUE(document_id, version_no)`、`UNIQUE(active_key)`（同文档只能一个 active，并发兜底）。

### 4.3 `document_chapters`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `version_id` | BIGINT UNSIGNED | FK → document_versions.id |
| `parent_id` | BIGINT UNSIGNED NULL | 自引用 FK |
| `seq` | INT UNSIGNED | 版本内文档顺序，从 1 开始（同级先后由 seq 大小体现） |
| `level` | TINYINT UNSIGNED | 1–6 |
| `title` | VARCHAR(255) | 章节标题；整文单章时为「全文」 |
| `content` | MEDIUMTEXT | 该标题下**直属正文**（不含子章节正文） |
| `char_count` | INT UNSIGNED | `content` 字符数 |

索引：`UNIQUE(version_id, seq)`、`INDEX(parent_id)`。

### 4.4 `baseline_snapshots`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `project_id` | BIGINT UNSIGNED | FK → projects.id |
| `version_id` | BIGINT UNSIGNED | FK → document_versions.id |
| `version_no` | INT UNSIGNED | 项目内基线序号，从 1 递增 |
| `chapter_count` | INT UNSIGNED | 冻结时的章节数 |
| `created_by` | BIGINT UNSIGNED | FK → users.id |
| `created_at` | DATETIME(3) | 默认 CURRENT_TIMESTAMP(3) |

索引：`UNIQUE(version_id)`（一个版本只生成一次）、`UNIQUE(project_id, version_no)`。
只提供读接口，无更新/删除。

## 5. 接口

前缀 `/api`，全部需要 Bearer 令牌。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/projects/{pid}/documents` | member+ | multipart：`file` 必填，`document_id` 可选（追加版本） |
| GET | `/projects/{pid}/documents` | 成员 | 文档列表，含生效版本摘要、版本数、待确认数 |
| GET | `/projects/{pid}/documents/{did}/versions` | 成员 | 版本列表，按 `version_no` 倒序 |
| GET | `/projects/{pid}/documents/{did}/versions/{vid}/chapters` | 成员 | 章节树（`children` 嵌套） |
| POST | `/projects/{pid}/documents/{did}/versions/{vid}/activate` | 管理员或上传者 | 确认生效，同事务生成基线快照 |
| POST | `/projects/{pid}/documents/{did}/versions/{vid}/void` | 管理员或上传者 | 作废，仅 `pending` 可作废 |
| GET | `/projects/{pid}/documents/{did}/versions/{vid}/download` | 成员 | 下载原文，`Content-Disposition: attachment` |
| GET | `/projects/{pid}/baselines` | 成员 | 基线快照列表，按 `version_no` 倒序 |

上传响应示例：

```json
{
  "document": {"id": 3, "name": "支付需求", "version_count": 1},
  "version": {"id": 7, "version_no": 1, "status": "pending", "chapter_count": 12}
}
```

## 6. 验收标准

### AC-49 上传新文档
- **Given** 项目 `active`，我是 `member`
- **When** `POST /documents` 传 `支付需求.md`（不传 `document_id`）
- **Then** 201；项目下新增文档「支付需求」；版本 `version_no=1`、`status=pending`、`chapter_count>0`

### AC-50 上传校验
- `.pdf` → 400 `UNSUPPORTED_DOC_TYPE`
- 11MB 文件 → 400 `DOC_TOO_LARGE`
- 0 字节 → 400 `EMPTY_DOCUMENT`
- 同项目同名文档 → 409 `DOCUMENT_NAME_TAKEN`
- 非成员 → 403 `NOT_PROJECT_MEMBER`；`guest` → 403 `FORBIDDEN`
- 任一失败均不落文档、版本、章节与审计记录

### AC-51 追加新版本
- **Given** 文档已有 `v1`
- **When** 带 `document_id` 上传第二份
- **Then** 201，`version_no=2`、`status=pending`；`v1` 状态不变；文档 `version_count=2`
- `document_id` 不存在或不属于该项目 → 404 `DOCUMENT_NOT_FOUND`

### AC-52 章节解析
- md：`#` / `##` / `###` 三级标题成树，`level` 与 `seq` 正确；代码块（``` 包裹）内的 `#` 不当标题
- docx：`Heading 1` / `Heading 2` 段落成树，正文段落归入最近标题
- 无任何标题：生成单章「全文」，`level=1`，`content` 为全文
- 有标题但首个标题前有正文：该段正文单独成「前言」章节（`level=1`），不丢内容
- `level` 跳跃（h1 直接到 h3）时挂到最近的更高级祖先
- 章节 `content` 不含子章节正文；`char_count` 与 `content` 长度一致

### AC-53 章节树读取
- **When** 成员 `GET .../chapters`
- **Then** 200，返回嵌套树，同级按 `seq` 升序；节点含 `title` / `level` / `char_count` / `children`
- 非成员 → 403 `NOT_PROJECT_MEMBER`；system_admin 可读任意项目

### AC-54 确认生效
- **Given** 文档 `v2` 为 `pending`，`v1` 为 `active`
- **When** 管理员确认 `v2`
- **Then** `v2` → `active`、`v1` → `archived`；同一事务内生成基线快照（AC-57）
- 重复确认 `v2` → 409 `INVALID_VERSION_STATUS`；确认 `void` / `archived` → 409

### AC-55 版本作废
- `pending` → 作废后 `status=void`，200
- `active` / `archived` → 409 `INVALID_VERSION_STATUS`
- `void` 版本不能确认，也不进文档列表的「生效版本」

### AC-56 版本操作权限
- `project_admin` 可确认/作废本项目的任意版本
- `member` 只能操作**自己上传**的版本；操作他人版本 → 403 `NOT_PROJECT_ADMIN`
- `guest` → 403 `NOT_PROJECT_ADMIN`
- 归档项目内确认/作废 → 409 `PROJECT_ARCHIVED`（先判归档，再判角色）

### AC-57 基线快照
- 确认生效成功后，`baseline_snapshots` 新增一条：`project_id` 正确、`version_id` 指向该版本、
  `version_no` 等于该项目当前最大值 + 1、`chapter_count` 与章节数一致
- 同一版本不会生成第二条（`UNIQUE(version_id)`）
- 两个不同版本并发确认，快照 `version_no` 不重复（项目行锁）
- 快照无更新/删除接口（404）

### AC-58 原文下载
- 成员下载 → 200，响应头 `Content-Disposition: attachment`，字节与原文件一致（sha256 相同）
- 非成员 → 403 `NOT_PROJECT_MEMBER`
- 文档列表 / 版本列表响应中不出现 `file_path` 字段

### AC-59 归档项目只读
- 归档项目内上传、确认、作废 → 409 `PROJECT_ARCHIVED`
- 文档列表、版本、章节、下载、基线列表仍可正常读取

### AC-60 概览真实计数
- 项目内 2 个文档、1 个已确认版本 → `GET /projects/{id}/overview`
  返回 `document_count=2`、`baseline_count=1`、`member_count` 不变、`latest_execution=null`

### AC-61 审计
- 成功上传写 `document.upload`；确认写 `document.version.activate`；作废写 `document.version.void`；
  快照写 `baseline.snapshot.create`
- 每条审计含 `project_id`、`actor_id`、`target_type` 与 `target_id`；失败操作不写审计
- `tests/common/test_audit_coverage.py` 的清单同步更新

## 7. 错误码

| code | HTTP | 触发 |
|---|---|---|
| `UNSUPPORTED_DOC_TYPE` | 400 | 非 docx / md / txt |
| `DOC_TOO_LARGE` | 400 | 超过 10MB |
| `EMPTY_DOCUMENT` | 400 | 0 字节或解析后无正文 |
| `DOCUMENT_PARSE_FAILED` | 400 | docx 结构损坏、无法解码 |
| `DOCUMENT_NAME_TAKEN` | 409 | 同项目同名 |
| `DOCUMENT_NOT_FOUND` | 404 | 文档不存在或不属于该项目 |
| `DOCUMENT_VERSION_NOT_FOUND` | 404 | 版本不存在或不属于该文档 |
| `INVALID_VERSION_STATUS` | 409 | 重复确认、作废非 pending |

## 8. 非功能

- 解析在请求内同步完成，单文件 10MB 上限；超时风险由大小限制兜底。
- 磁盘目录 `var/uploads/`，按 `project_id` 分目录；配置项 `UPLOAD_DIR`、`DOC_MAX_BYTES`。
- 新增依赖：`python-docx>=1.1`（仅解析 docx）；md 解析手写，不引第三方。

## 9. 依赖与影响

- **AC-40 概览**：`get_overview` 由占位改真实，需同步更新 `tests/projects/test_overview.py` 的断言。
- **审计清单**：`test_audit_coverage.py` 增加 4 个 action。
- **前端**：项目详情页新增「文档」「基线」两个 Tab，对应 `tests/e2e/test_documents_ui.py`。
- **验证约定**：每个任务按 `specs/验证约定.md` 第 2 节走「任务 pytest + 全量 pytest + 前台核对 + 截图」。
