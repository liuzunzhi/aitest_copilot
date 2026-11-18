# 03 · 文档解析与基线（解析段）· 任务清单

> 规格 [spec.md](./spec.md) ｜ 方案 [plan.md](./plan.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)

## 执行约定

1. 每个任务开始前重读 `spec.md` 对应 AC 与 `plan.md` 对应小节，不凭记忆写代码。
2. 先写用例再写实现；用例名带 AC 编号（`test_ac_49_upload_new_document`）。
3. 任务收尾跑：`-k ac_XX` → 全量 `.\.venv\Scripts\python.exe -m pytest`（数量只增不减）。
4. 前端可用后补 Playwright 前台核对，按 [../验证约定.md](../验证约定.md) 第 2 节落截图；
   前端未就绪时在任务行标「前台待补」，T54 统一补跑。
5. 提交信息用 `feat(documents): …` / `test(documents): …`，一个任务一个提交。

## 前置条件

| 项 | 状态 |
|---|---|
| 01-auth / 02-projects 已完成 | T1–T44 已验收 |
| 后端基线 | 316 passed（2026-11-15） |
| 前端 | `D:\aitest_copilot\web`，项目详情页含「概览 / 成员 / 文档 / 基线 / 申请」Tab（T54 补齐后两项） |
| 数据库迁移 head | `0010`（03 从 `0011` 起） |
| e2e 环境 | 8001 / 5174 + `aitest_copilot_e2e`，见验证约定 §3 |

## 任务

- [x] **T45 · 数据模型与迁移** ✓ 2026-11-15
  - 内容：`app/models/document.py` 四个模型（`Document` / `DocumentVersion` / `DocumentChapter` / `BaselineSnapshot`），
    字段与索引严格对齐 spec §4；迁移 `migrations/versions/0011_documents.py`；注册到 `app/models/__init__.py`。
  - 产出：4 张表可 upgrade / downgrade / upgrade；`active_key` 用 STORED 生成列，应用层只改 `status`。
  - 验证：`tests/documents/test_models.py` 6 条通过（回写、同名唯一、版本号唯一、active_key、状态 CHECK、快照唯一）；
    全量 `322 passed`；开发库与 e2e 库均已 `upgrade head`，e2e 库完成 downgrade/upgrade 往返。
  - 前台：本期无页面入口，随 T54 一并核对。

- [x] **T46 · 章节解析器** ✓ 2026-11-15
  - 内容：`app/documents/parser.py` 的 `ChapterNode` 与 `parse()`；md（含代码块跳过）、docx（Heading 样式）、
    txt / 无标题整文单章；异常类型改用 `app/common/errors.py` 里的 `UnsupportedDocType` /
    `EmptyDocument` / `DocumentParseFailed`（与全局错误处理器一致）。
  - 产出：纯函数解析器，不碰 DB；测试用 `python-docx` 动态造 docx，`python-docx>=1.1` 进依赖。
  - 验证：`-k ac_52` 12 条通过（三级成树、代码块跳过、层级跳跃、前言、txt 单章、docx 标题与表格、
    docx 无标题、5 组非法输入）；全量 `334 passed`。
  - 前台：本期无页面入口，随 T54 一并核对。

- [x] **T47 · 上传接口** ✓ 2026-11-15
  - 内容：`POST /api/projects/{pid}/documents`，multipart `file` + 可选 `document_id`；
    大小/类型/空文件/同名校验；落盘 UUID 文件；解析成功后同事务写文档、版本、章节；
    guest 403 `FORBIDDEN`、非成员 403 `NOT_PROJECT_MEMBER`、归档项目 409。
  - 产出：`app/documents/{schemas,service,router}.py`；`config.py` 增 `upload_dir` / `doc_max_bytes`；
    `python-docx`、`python-multipart` 进依赖；`.gitignore` 增 `var/uploads/`。
  - 验证：`-k "ac_49 or ac_50 or ac_51"` 11 条通过（成功、类型、超限、空文件、同名、访客、非成员、
    追加版本、文档不存在、跨项目越权、归档拦截）；失败用例断言表里没有新增行、目录无残留；全量 `345 passed`。
  - 前台：本期无页面入口，随 T54 一并核对。

- [x] **T48 · 文档 / 版本 / 章节读取** ✓ 2026-11-15
  - 内容：`GET /documents`（版本数、待确认数、生效版本摘要，一次查询避免 N+1）、
    `GET /documents/{did}/versions`（倒序）、`GET .../chapters`（内存组树）；
    响应不含 `file_path`；成员可读、非成员 403、system_admin 兜底。
  - 产出：`service.list_documents` / `list_versions` / `list_chapters` + 三个 GET 路由；
    读接口统一复用 `require_project_member_or_system_admin`（访客可读）。
  - 验证：`-k ac_53` 10 条通过（列表、版本倒序、章节树、访客可读、非成员 403、系统管理员、
    文档/版本 404、跨项目不可见、归档仍可读）；全量 `355 passed`。
  - 前台：文档 Tab 在 T54 实现，届时核对列表与章节树渲染。

- [x] **T49 · 确认生效 + 基线快照** ✓ 2026-11-16
  - 内容：`POST .../activate`；项目行锁 `SELECT … FOR UPDATE`；旧 active → archived（先 flush 再激活，
    避免两个 active 撞 `uk_versions_active`）；写入 `baseline_snapshots`（项目内 `version_no` 递增）；
    审计 `document.version.activate` + `baseline.snapshot.create`；重复确认 / 非 pending → 409。
  - 产出：`service.activate_version` / `list_baselines` / `_ensure_can_operate`；额外补
    `GET /api/projects/{pid}/baselines`（原计划漏排，前端基线 Tab 需要）。
  - 验证：`-k "ac_54 or ac_56 or ac_57 or ac_59"` 11 条通过（首次确认、旧版归档、重复确认 409、
    序号按项目递增、列表倒序与访客/非成员边界、成员仅本人、管理员任意、访客 403、归档 409、版本 404）；
    全量 `366 passed`。并发取号由「项目行锁 + `UNIQUE(project_id, version_no)`」双重保障，
    未写多线程用例（现有单与会话夹具无法制造真实并发）。

- [x] **T50 · 作废与版本操作权限** ✓ 2026-11-16
  - 内容：`POST .../void`（仅 pending）；权限矩阵：project_admin / system_admin 任意，member 仅本人上传，
    guest 403；归档项目先判 409 `PROJECT_ARCHIVED` 再判角色；审计 `document.version.void`。
  - 产出：`service.void_version`，与确认共用 `_ensure_can_operate`，避免两条路径权限漂移。
  - 验证：`-k "ac_55 or ac_56 or ac_59"` 9 条通过（本人作废 + 作废后不能生效、已生效不可作废、
    重复作废 409、成员不可动他人、管理员任意、访客 403、非成员 403、归档 409、版本 404）；
    全量 `375 passed`。权限矩阵未做参数化，按「操作 × 角色」逐条写，失败时定位更直接。

- [x] **T51 · 原文下载** ✓ 2026-11-16
  - 内容：`GET .../download`，`FileResponse` + `Content-Disposition: attachment`；成员（含访客）可读，
    非成员 403；下载字节 sha256 与原文件一致；文件被误删返回 404 而不是 500。
  - 产出：`service.get_source_file` 拼 `upload_dir` 后才暴露磁盘路径；传输层不出现 `file_path`。
  - 验证：`-k ac_58` 5 条通过（字节摘要一致、中文文件名 RFC 5987、访客可下 / 非成员 403、
    文档与版本 404、磁盘文件缺失 404、归档仍可下载）；全量 `380 passed`。

- [x] **T52 · 概览真实计数** ✓ 2026-11-16
  - 内容：`app/projects/service.py::get_overview` 改为真实 `COUNT`（文档数按文档、基线数按快照），
    响应结构不变；`latest_execution` 仍为 `None`（执行模块未上线）。已归档项目读数不受影响。
  - 验证：新增 `tests/documents/test_overview_counts.py` 3 条（文档数不等于版本数、跨项目不串、
    作废不产生基线）+ 原 `test_overview.py` 7 条；全量 `383 passed`。

- [x] **T53 · 审计覆盖** ✓ 2026-11-16
  - 内容：`tests/common/test_audit_coverage.py` 清单补 `document.upload`、`document.version.activate`、
    `document.version.void`、`baseline.snapshot.create`；另加一条专门断言 `project_id` / `actor_id` /
    `target_type` / `target_id` 的用例。
  - 实现差异：上传与确认的 `target_type` 都是 `document_version`（目标是被操作的那一版），
    文档 id 放在 `after_data.document_id`；`target_id` 列是字符串。
  - 验证：该文件 28 条通过；全量 `388 passed`。

- [x] **T54 · 前端文档 / 基线页 + 全量回归** ✓ 2026-11-16
  - 内容：`ProjectDetailPage` 插入「文档」「基线」Tab；`ProjectDocumentsTab`（上传、版本历史弹窗、
    章节树预览、确认生效 / 作废 / 下载）、`ProjectBaselinesTab`（快照列表）；`api/index.ts` 增类型与 8 个函数；
    `client.ts` 补 9 个文档错误码的中文映射。
  - 实现细节：文档名是「文件名去扩展名」（后端 `Document.name`），列表与基线显示 `支付需求` 而不是 `.md`；
    下载走 XHR 取 blob 再从 `Content-Disposition` 解 `filename*`，普通链接带不上 Bearer 头。
  - 验证：`tests/e2e/test_documents_ui.py` 6 条通过（上传+章节树、确认生成基线、作废、下载文件名、
    同名 409 中文提示、PDF 中文报错），截图 `.screenshots/T54/`；e2e 全量 `19 passed`；
    `npm run build` 通过；后端全量 `388 passed`。
  - 前台核对：AC-49/50/52/54/55/58 已覆盖；AC-51 的大小与空文件、AC-56/57 的成员/访客越权仍以后端用例为准
    （前端不做上传前校验，边界全靠后端返回中文提示）。
  - 补丁（2026-11-16 交互检查后）：版本弹窗增「上传新版本」（`document_id` 追加版本，打通多版本→多基线）；
    版本状态补 `archived → 已归档`；基线 Tab 随文档变更自动重载（`refreshKey`）。
    e2e 新增 AC-54 V2 链路用例；另修复 2 处 Popconfirm 竞态（归档 / 移除成员确认按钮改用
    `.ant-popover:visible` 限定，列表上百行时 `.last` 会误点行内按钮）。e2e 全量 `20 passed`。
