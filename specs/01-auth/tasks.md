# 01-auth · 任务清单（tasks）

> 对应 spec：`specs/01-auth/spec.md`（AC-01 ~ AC-30）
> 对应 plan：`specs/01-auth/plan.md`
> 代码根目录：`D:\aitest_copilot`

## 前置条件

| 项 | 要求 |
|---|---|
| Python | 3.11+ |
| MySQL | 容器 `aitest-mysql`，库 `aitest_copilot_v2`（已创建） |
| Redis | 容器 `aitest-redis`，`localhost:6380`（原 `busy_blackwell:6379` 被本机 rediszt3 服务占用） |
| DSN | `mysql+pymysql://aitest:aitestpass123@127.0.0.1:3306/aitest_copilot_v2` |

## 执行约定

1. 一个任务 = 一次会话能写完的范围。任务内的「验证」命令跑通才算完成。
2. 任务之间不并行修改同一文件。T01 ~ T08 顺序执行，T09 之后可按 Phase 内并行。
3. **不做任务范围外的事**。比如做 T14 注册时不要顺手改登录逻辑。
4. 完成一个任务就勾选，并在后面追加 commit 短哈希。
5. 遇到 plan 里没写的细节，先停下来确认，不要自行发挥。

---

## Phase 0 · 脚手架

- [x] **T01 · 仓库骨架** ✓ 2026-11-15（355b92b）
  - 产出：`D:\aitest_copilot\` 目录树、`pyproject.toml`、`app/main.py`、`app/__init__.py`、`.gitignore`、`README.md`
  - 内容：FastAPI 实例 + `GET /health` 返回 `{"status":"ok"}`；依赖 uv 或 pip 安装
  - 验证：`uvicorn app.main:app --port 8000` 后 `curl localhost:8000/health`
  - 完成标准：HTTP 200，body 为 `{"status":"ok"}`

- [x] **T02 · 配置加载** ✓ 2026-11-15（355b92b）
  - 产出：`app/common/config.py`、`.env.example`
  - 内容：`pydantic-settings` 读取 DB DSN、Redis URL、bcrypt cost；缺失即启动失败
  - 验证：`pytest tests/test_config.py`（断言缺 DB DSN 时抛 `ValidationError`）

- [x] **T03 · 数据库引擎与 UTC 强制** ✓ 2026-11-15（355b92b）
  - 产出：`app/common/db.py`
  - 内容：SQLAlchemy `create_engine` + `pool_pre_ping`；用 `event.listens_for(Engine, "connect")` 在**每个连接**建立后执行 `SET time_zone = '+00:00'`
  - 验证：`pytest tests/test_db.py::test_session_timezone`（断言 `SELECT @@session.time_zone` 返回 `+00:00`）
  - 注意：这一条是 AC-04 / AC-22 正确性的前提，必须有测试守住

- [x] **T04 · Alembic 接入** ✓ 2026-11-15（355b92b）
  - 产出：`alembic.ini`、`migrations/env.py`、`migrations/versions/`
  - 内容：连接目标库，`target_metadata` 指向 `app.models`
  - 验证：`alembic upgrade head` 成功 + `alembic current` 显示版本号

## Phase 1 · 数据层

- [x] **T05 · users 表** ✓ 2026-11-15（6a23160）
  - 产出：`app/models/user.py`、`migrations/versions/xxxx_create_users.py`
  - 内容：按 plan 2.1 建表，含 `uk_users_username` / `uk_users_email` / `uk_users_phone` 与两个 CHECK
  - 验证：`alembic upgrade head` 后 `SHOW CREATE TABLE users` 能看到 3 个唯一索引
  - 注意：CHECK 约束 Alembic autogenerate 不识别，迁移需手写

- [x] **T06 · projects / project_members 表** ✓ 2026-11-15（38a3080）
  - 产出：`app/models/project.py`、对应迁移
  - 内容：按 plan 2.3
  - 验证：`alembic upgrade head` + `pytest tests/test_models.py::test_project_tables`

- [x] **T07 · access_tokens / project_applications 表** ✓ 2026-11-15（2026556）
  - 产出：`app/models/token.py`、`app/models/application.py`、对应迁移
  - 内容：按 plan 2.2 / 2.4。`project_applications.pending_key` 为 STORED 生成列
  - 验证：`pytest tests/test_models.py::test_pending_unique`——插入两条 `(p1,u1)` 的 pending 应报 `1062`；把其中一条改为 `rejected` 后，再插 pending 应成功
  - 注意：这条测试是 AC-17 的数据库层保障，必须真跑，不能只读代码

- [x] **T08 · system_settings / audit_logs 表 + 默认配置** ✓ 2026-11-15（a09d563）
  - 产出：`app/models/system.py`、迁移、`migrations/versions/xxxx_seed_settings.py`
  - 内容：按 plan 2.5；种子 6 个配置项
  - 验证：`pytest tests/test_models.py::test_seed_settings`（断言 `token_ttl_seconds` = 28800）

## Phase 2 · 基础设施

- [x] **T09 · 时钟与密码哈希** ✓ 2026-11-15（3af27ee）
  - 产出：`app/common/clock.py`、`app/common/security.py`
  - 内容：可注入 `Clock`（默认 UTC）；`hash_password` / `verify_password`；模块级 `DUMMY_HASH` 常量
  - 验证：`pytest tests/common/test_security.py`（含"不存在的用户也返回 False 且耗时接近"的用例）

- [x] **T10 · 验证码与 Redis** ✓ 2026-11-15（7e7872f）
  - 产出：`app/common/captcha.py`
  - 内容：生成/校验图形验证码（TTL 300s）；密码重置验证码（TTL 600s）+ 60s 发送限流
  - 验证：`pytest tests/common/test_captcha.py`（验证码用后即失效、重复发送触发 429）

- [x] **T11 · 配置读取服务** ✓ 2026-11-15（2a98f66）
  - 产出：`app/common/settings.py`
  - 内容：`get_setting(key)`，进程内缓存 60s，写操作后失效缓存
  - 验证：`pytest tests/common/test_settings.py`（改值后缓存能刷新）

- [x] **T12 · 审计写入服务** ✓ 2026-11-15（fddd7be）
  - 产出：`app/common/audit.py`
  - 内容：`write_audit(session, action, actor_id, ...)`，与业务同事务
  - 验证：`pytest tests/common/test_audit.py::test_rollback`（业务异常时审计一起回滚）

- [x] **T13 · 令牌服务** ✓ 2026-11-15（fa172b6）
  - 产出：`app/auth/tokens.py`
  - 内容：`issue(user_id, ttl) -> 明文token`、`resolve(token) -> (user, token)`、`revoke(token)`、`revoke_all(user_id)`
  - 验证：`pytest tests/auth/test_tokens.py`（明文只返回一次、DB 只存 sha256、revoke 后 resolve 失败）

## Phase 3 · 注册与登录

- [x] **T14 · 注册接口** — AC-08, 09, 10, 11 ✓ 2026-11-15（3553684）
  - 产出：`app/auth/router.py::register`、`app/auth/service.py::register`
  - 内容：唯一性靠捕获 `1062` 映射；密码强度校验；验证码校验；成功返回 201 不含 token
  - 验证：`pytest tests/auth/test_register.py -k "ac_08 or ac_09 or ac_10 or ac_11"`

- [x] **T15 · 登录接口** — AC-01 ~ 05 ✓ 2026-11-15（9b344a0）
  - 产出：`app/auth/service.py::login`
  - 内容：AC-02 三种失败统一响应且空跑 bcrypt；AC-04 单条原子 UPDATE + 同事务 SELECT；AC-05 读 `remember_ttl_seconds`
  - 验证：`pytest tests/auth/test_login.py`
  - 注意：AC-04 的锁定计数必须并发测一遍，不能只测串行

- [x] **T16 · 登出接口** — AC-07 ✓ 2026-11-15（02155b7）
  - 产出：`app/auth/router.py::logout`
  - 内容：写 `revoked_at`，后续同 token 返回 `TOKEN_REVOKED`
  - 验证：`pytest tests/auth/test_logout.py`

- [x] **T17 · 密码找回与重置** — AC-12 ✓ 2026-11-15（9700dd9）
  - 产出：`app/auth/service.py::send_reset_code` / `reset_password`
  - 内容：重置后写 `password_changed_at`，并 `revoke_all` 该用户全部 token
  - 验证：`pytest tests/auth/test_password_reset.py`（重置前签发的 token 全部失效）

- [x] **T18 · 鉴权与权限依赖** — AC-06, AC-03 ✓ 2026-11-15（5520ec4）
  - 产出：`app/common/deps.py`
  - 内容：`current_user` 做四重校验（命中 → 未吊销 → 未过期 → 用户 `active`）；`require_system_admin`、`require_project_role`
  - 验证：`pytest tests/auth/test_guard.py::test_disabled_user_token_rejected`（AC-03 的关键一环）

## Phase 4 · 项目申请

- [x] **T19 · 项目列表与可申请列表** — AC-26, 29, 30, 28（后端部分）✓ 2026-11-15（0fd0223）
  - 产出：`app/projects/router.py`、`app/common/scoped_repo.py`
  - 内容：`/api/projects` 按成员过滤；`/api/projects/available` 返回全部未加入项目；无项目用户返回空数组而非报错
  - 验证：`pytest tests/projects/test_isolation.py -k "list or available"`
  - 说明：AC-28 的前端渲染要求不在本任务范围

- [x] **T20 · 提交申请** — AC-13 ~ 19 ✓ 2026-11-15（fc36b2e）
  - 产出：`app/projects/apply_service.py::submit`
  - 内容：AC-14 理由必填；AC-15 角色白名单（DB CHECK 双重保障）；AC-16 已是成员拒绝；AC-18 开关判断；重复 pending 靠 `1062` 映射为 409
  - 验证：`pytest tests/projects/test_apply.py`

- [x] **T21 · 撤回申请** — AC-20 ✓ 2026-11-15（cf4921c）
  - 产出：`app/projects/apply_service.py::withdraw`
  - 内容：校验 `applicant_id == current_user.id`，非本人 403
  - 验证：`pytest tests/projects/test_apply.py -k withdraw`

- [x] **T22 · 审批通过 / 驳回** — AC-21, 22 ✓ 2026-11-15（2edcc06）
  - 产出：`app/projects/apply_service.py::approve` / `reject`
  - 内容：条件更新 + `rowcount == 0 → 409`；通过时写 `project_members`；驳回写 `rejected_at` 并在下次提交时判定冷却
  - 验证：`pytest tests/projects/test_approve.py`（含双批并发用例、冷却边界用例）

- [x] **T23 · 审批权限边界** — AC-23 ✓ 2026-11-15（ebd432f）
  - 产出：`app/common/deps.py::require_project_admin_or_system_admin`
  - 内容：项目管理员只能审本项目；系统管理员兜底
  - 验证：`pytest tests/projects/test_permission.py`

- [x] **T24 · 项目归档关闭待审批** — AC-24 ✓ 2026-11-15（02081b9）
  - 产出：`app/projects/service.py::archive_project`
  - 内容：同事务把所有 `pending` 申请置为 `closed`，`closed_reason='project_archived'`
  - 验证：`pytest tests/projects/test_archive.py`

## Phase 5 · 收尾

- [x] **T25 · 管理员用户管理** — AC-03 ✓ 2026-11-15（a3944b0）
  - 产出：`app/users/router.py`
  - 内容：用户列表、启用/禁用、重置密码
  - 验证：`pytest tests/users/test_admin.py`（禁用后该用户旧 token 立即失效）

- [x] **T26 · 审计覆盖核对** — AC-25 ✓ 2026-11-15（4df989e）
  - 产出：`tests/common/test_audit_coverage.py`
  - 内容：参数化跑完所有写操作，断言每条都产生预期 `action` 的审计记录
  - 验证：`pytest tests/common/test_audit_coverage.py`
  - 说明：这是唯一防止"漏写审计"的自动化手段，务必覆盖全

- [x] **T27 · 全量回归与覆盖报告** ✓ 2026-11-15（09493fb / 报告见 `reports/coverage.md`）
  - 产出：`tests/`、`reports/coverage.md`
  - 内容：跑全量测试，逐个核对 AC-01 ~ 30 是否都有对应用例，输出缺口清单
  - 验证：`pytest --cov=app --cov-report=term-missing`
  - 完成标准：30 条 AC 全部有用例，无缺口

> 补充（2026-11-15，commit 8ced0ce / b76bcc3）：按 spec「待确认 4」定稿管理员重置密码方案 —— 随机临时密码 + `users.must_change_password` 强制首登改密，新增 `POST /api/auth/password/change`；改密前除该接口外一律 403 `PASSWORD_CHANGE_REQUIRED`；改密成功后吊销该用户其他设备令牌、保留当前会话。回归 186 passed / 98%。

---

## AC 覆盖索引

| AC | 任务 | AC | 任务 |
|---|---|---|---|
| 01 登录成功 | T15 | 16 已是成员不可申请 | T20 |
| 02 失败不区分原因 | T15 | 17 同项目仅一条 pending | T07 + T20 |
| 03 禁用账号拒绝 | T15 + T18 + T25 | 18 全局开关关闭 | T20 |
| 04 失败锁定 | T15 | 19 多项目并行 | T20 |
| 05 记住登录 | T15 | 20 撤回申请 | T21 |
| 06 token 过期 / 未登录 | T18 | 21 审批通过即生效 | T22 |
| 07 登出 | T16 | 22 驳回与冷却 | T22 |
| 08 注册即激活 | T14 | 23 审批权限边界 | T23 |
| 09 唯一性 | T14 | 24 归档关闭申请 | T24 |
| 10 密码强度 | T14 | 25 全链路审计 | T26 |
| 11 验证码 | T14 | 26 项目列表过滤 | T19 |
| 12 密码找回 | T17 | 27 非成员 403 | T19 |
| 13 提交申请 | T20 | 28 无项目引导 | T19 + T27 |
| 14 理由必填 | T20 | 29 可申请列表 | T19 |
| 15 期望角色白名单 | T20 | 30 空态 | T19 |

## 建议的第一批提交

T01 → T02 → T03 → T04 可以合成一个 commit（脚手架 + 能连上库），之后一个任务一个 commit。
