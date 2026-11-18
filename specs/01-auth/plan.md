# 01-auth · 实现方案（plan）

> 对应 spec：`specs/01-auth/spec.md`（AC-01 ~ AC-30）
> PRD：v1.8
> 状态：待评审
> 数据库：MySQL 8.0.46（Docker 容器 `aitest-mysql`，已实测）
> 目标库：`aitest_copilot_v2`（新建，已创建）
> 代码根目录：`D:\aitest_copilot`（尚未创建，由 T01 建立）

## 0. 与现有库的关系

本机 MySQL 里已有一个 `aitest_copilot` 库（alembic 停在 `0023`，41 张表，含真实数据）。**本次采用新品重建，不动它、不复用其表结构、不迁移其数据。**

| 库 | 用途 | 本次是否改动 |
|---|---|---|
| `aitest_copilot` | 旧实现，保留备查 | 否，只读 |
| `aitest_copilot_v2` | 按本 plan 新建 | 是 |

如果后续需要把旧库的历史数据（14 个项目、973 条测试点）迁过来，单独写数据迁移脚本，不混在 alembic 结构迁移里。

## 0.1 技术选型

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11+ | |
| Web | FastAPI + Pydantic v2 | |
| ORM | SQLAlchemy 2.0 + Alembic | 驱动用 `pymysql`；CHECK 约束需手写迁移 |
| 数据库 | MySQL 8.0.46 | InnoDB，`utf8mb4_0900_ai_ci` |
| 缓存 | Redis 7 | 容器 `busy_blackwell`，6379 |
| 密码哈希 | bcrypt（cost=12） | |
| 测试 | pytest + httpx + testcontainers | 镜像 `mysql:8.0` |

环境实测值（后续所有设计以此为准）：

| 项 | 值 | 说明 |
|---|---|---|
| 版本 | `8.0.46` | CHECK 约束生效（需 ≥ 8.0.16） |
| `character_set_server` | `utf8mb4` | |
| `collation_server` | `utf8mb4_0900_ai_ci` | 大小写不敏感，正好符合 2.1 的需求 |
| `transaction_isolation` | `REPEATABLE-READ` | 保持默认，见 7 节 |
| `sql_mode` | 含 `STRICT_TRANS_TABLES` | 超长/非法值直接报错，不静默截断 |
| 容器系统时区 | `UTC` | `NOW()` == `UTC_TIMESTAMP()` |

> 注意：旧库 `system_configs` 里存着 `system.timezone = "Asia/Shanghai"`，那是旧实现的约定。**新库不使用该配置，时间一律 UTC**，理由见 2.0。


## 1. 模块划分

```
app/
  auth/
    router.py        # /api/auth/*
    service.py       # 注册、登录、登出、密码重置
    tokens.py        # 签发 / 校验 / 吊销
    security.py      # bcrypt、验证码
  users/
    router.py        # /api/admin/users/*（启用/禁用、重置密码）
  projects/
    router.py        # /api/projects/*、/api/projects/available
    apply_service.py # 申请 / 撤回 / 审批
    member_service.py
  common/
    settings.py      # system_settings 读写 + 进程内缓存
    audit.py         # write_audit（同一事务）
    deps.py          # current_user / require_system_admin / require_project_role
    scoped_repo.py   # 项目数据隔离基类
    clock.py         # 可注入时钟，测试用
```

分层约束：`router` 只做参数校验与权限声明，业务全部在 `service`；`service` 不接触 `Request`。

## 2. 数据模型

### 2.0 全局约定

```sql
-- 所有表统一
ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```

两条硬约束，后续所有 SQL 都依赖它们：

1. **时间一律 UTC**。`DATETIME(3)` 不带时区，因此必须两端同时固定：

```python
# 连接串
mysql+pymysql://...?charset=utf8mb4
# 每个连接建立后执行一次
SET time_zone = '+00:00';
```

应用侧统一 `datetime.now(timezone.utc)`，不使用 `datetime.now()`，不读任何时区配置项。

> 容器系统时区恰好是 UTC，所以 `NOW(3)` 与 `UTC_TIMESTAMP()` 相等——但这是巧合，不能依赖。一旦有人给容器加 `TZ=Asia/Shanghai`，所有 `NOW()` 写入的时间会整体偏移 8 小时，且不会报错。所以显式 `SET time_zone` 是必需的，不是可选的。
>
> 旧库的 `system.timezone = "Asia/Shanghai"` 属于旧实现，新库不读取。

2. **大小写不敏感靠排序规则**。`utf8mb4_0900_ai_ci` 下 `'Admin' = 'admin'`，因此 `UNIQUE(username)` 天然区分大小写重复。不建 `lower()` 函数索引。

### 2.1 users

```sql
CREATE TABLE users (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username            VARCHAR(64)     NOT NULL,
    password_hash       VARCHAR(100)    NOT NULL COMMENT 'bcrypt',
    email               VARCHAR(255)    NULL,
    phone               VARCHAR(32)     NULL,
    status              VARCHAR(16)     NOT NULL DEFAULT 'active',
    global_role         VARCHAR(16)     NOT NULL DEFAULT 'user',
    failed_login_count  INT             NOT NULL DEFAULT 0,
    locked_until        DATETIME(3)     NULL,
    password_changed_at DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    created_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                                        ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_users_username (username),
    UNIQUE KEY uk_users_email (email),
    UNIQUE KEY uk_users_phone (phone),
    CONSTRAINT ck_users_status CHECK (status IN ('active','disabled')),
    CONSTRAINT ck_users_role   CHECK (global_role IN ('user','system_admin'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

说明：
- MySQL 唯一索引允许多个 `NULL`，所以 `email` / `phone` 可空唯一，不需要 PG 那种 `WHERE ... IS NOT NULL` 条件索引。
- 只有 `active` / `disabled` 两态（PRD v1.8 取消注册审批）。
- `global_role` 承载系统管理员；项目内角色在 `project_members`，两者分离。
- 「未归属用户」不落库，由「无 `project_members` 记录」推导。

### 2.2 access_tokens

```sql
CREATE TABLE access_tokens (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id    BIGINT UNSIGNED NOT NULL,
    token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
               COMMENT 'sha256 十六进制',
    issued_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    expires_at DATETIME(3)     NOT NULL,
    revoked_at DATETIME(3)     NULL,
    user_agent VARCHAR(255)    NULL,
    ip         VARCHAR(45)     NULL COMMENT 'IPv4/IPv6',
    PRIMARY KEY (id),
    UNIQUE KEY uk_tokens_hash (token_hash),
    KEY idx_tokens_user (user_id, revoked_at),
    KEY idx_tokens_exp  (expires_at),
    CONSTRAINT fk_tokens_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

`token_hash` 用 `ascii_bin`：十六进制只占 64 字节，且比较区分大小写、不进校对规则。

### 2.3 projects / project_members

```sql
CREATE TABLE projects (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name       VARCHAR(128)    NOT NULL,
    status     VARCHAR(16)     NOT NULL DEFAULT 'active',
    created_at DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    CONSTRAINT ck_projects_status CHECK (status IN ('active','archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE project_members (
    project_id BIGINT UNSIGNED NOT NULL,
    user_id    BIGINT UNSIGNED NOT NULL,
    role       VARCHAR(16)     NOT NULL,
    joined_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (project_id, user_id),
    KEY idx_members_user (user_id),
    CONSTRAINT ck_members_role CHECK (role IN ('project_admin','member','guest')),
    CONSTRAINT fk_members_project FOREIGN KEY (project_id) REFERENCES projects(id),
    CONSTRAINT fk_members_user    FOREIGN KEY (user_id)    REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

### 2.4 project_applications（MySQL 关键适配）

PG 用条件唯一索引保证「同一项目仅一条 pending」，MySQL 不支持。改用**生成列 + 唯一索引**：非 pending 时生成列为 `NULL`，MySQL 唯一索引允许多个 `NULL`，因此只有 pending 记录会互斥。

```sql
CREATE TABLE project_applications (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    project_id    BIGINT UNSIGNED NOT NULL,
    applicant_id  BIGINT UNSIGNED NOT NULL,
    reason        TEXT            NOT NULL,
    desired_role  VARCHAR(16)     NOT NULL,
    status        VARCHAR(16)     NOT NULL DEFAULT 'pending',
    reviewer_id   BIGINT UNSIGNED NULL,
    reviewed_at   DATETIME(3)     NULL,
    reject_reason TEXT            NULL,
    closed_reason VARCHAR(32)     NULL,
    created_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    pending_key   VARCHAR(64) GENERATED ALWAYS AS (
                      IF(status = 'pending',
                         CONCAT(project_id, ':', applicant_id),
                         NULL)
                  ) STORED,
    PRIMARY KEY (id),
    UNIQUE KEY uk_app_pending (pending_key),
    KEY idx_app_project   (project_id, status),
    KEY idx_app_applicant (applicant_id, created_at),
    CONSTRAINT ck_app_status CHECK (status IN
        ('pending','approved','rejected','withdrawn','closed')),
    CONSTRAINT ck_app_role   CHECK (desired_role IN ('member','guest')),
    CONSTRAINT fk_app_project FOREIGN KEY (project_id)   REFERENCES projects(id),
    CONSTRAINT fk_app_user    FOREIGN KEY (applicant_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

要点：
- `desired_role` 的 CHECK 已在 DB 层排除 `project_admin`，AC-15 有双重保障。
- `pending_key` 是 STORED 生成列，`status` 变更时自动重算，无需应用层维护。
- 申请被驳回后用户重新申请 → 新建一条记录，旧的 `rejected` 记录 `pending_key` 为 `NULL`，不冲突。

### 2.5 system_settings / audit_logs

```sql
CREATE TABLE system_settings (
    `key`      VARCHAR(64)     NOT NULL,
    `value`    JSON            NOT NULL,
    updated_by BIGINT UNSIGNED NULL,
    updated_at DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                               ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO system_settings (`key`, `value`) VALUES
 ('enable_project_apply',  'true'),
 ('token_ttl_seconds',     '28800'),
 ('remember_ttl_seconds',  '2592000'),
 ('max_login_failures',    '5'),
 ('lock_duration_minutes', '30'),
 ('apply_cooldown_hours',  '24');
```

```sql
CREATE TABLE audit_logs (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    action      VARCHAR(64)     NOT NULL,
    actor_id    BIGINT UNSIGNED NULL,
    actor_role  VARCHAR(32)     NULL,
    project_id  BIGINT UNSIGNED NULL,
    target_type VARCHAR(32)     NULL,
    target_id   VARCHAR(64)     NULL,
    before_data JSON            NULL,
    after_data  JSON            NULL,
    reason      TEXT            NULL,
    created_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_audit_project (project_id, created_at),
    KEY idx_audit_actor   (actor_id, created_at),
    KEY idx_audit_action  (action, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

`before` / `after` 是 MySQL 保留字，字段名改为 `before_data` / `after_data`。

### 2.6 Redis（不落库）

| Key | TTL | 用途 |
|---|---|---|
| `captcha:{captcha_id}` | 300s | 图形验证码 |
| `pwdreset:code:{contact}` | 600s | 密码重置验证码 |
| `pwdreset:rate:{contact}` | 60s | 发送频率限制 |

## 3. 状态机

**用户**

```
注册 ──→ active ⇄ disabled
                     ↑ 仅 system_admin 可切换
```

**项目申请**

```
                    ┌── approve ──→ approved   (终态)
                    ├── reject  ──→ rejected   (终态，冷却后新建记录再申请)
pending ────────────┼── withdraw ─→ withdrawn  (终态)
                    └── 项目归档 ──→ closed     (终态)

所有终态记录不可修改；再次申请一律新建一条记录。
```

**访问令牌**

```
issued ──超时──→ expired（不更新字段，靠 expires_at 判定）
       └─logout / 密码重置 / 禁用账号──→ revoked（写 revoked_at）
```

## 4. 接口清单

| 方法 | 路径 | 权限 | 对应 AC |
|---|---|---|---|
| POST | `/api/auth/register` | 匿名 | 08, 09, 10, 11 |
| POST | `/api/auth/login` | 匿名 | 01 ~ 05 |
| POST | `/api/auth/logout` | 登录 | 07 |
| POST | `/api/auth/password/send-code` | 匿名 | 12 |
| POST | `/api/auth/password/reset` | 匿名 | 12 |
| GET | `/api/users/me` | 登录 | — |
| GET | `/api/admin/users` | system_admin | — |
| PATCH | `/api/admin/users/{uid}/status` | system_admin | 03 |
| PATCH | `/api/admin/settings` | system_admin | 18 |
| GET | `/api/projects` | 登录 | 26, 28 |
| GET | `/api/projects/available` | 登录 | 29, 30 |
| POST | `/api/projects/{pid}/applications` | 登录 | 13 ~ 19 |
| GET | `/api/projects/{pid}/applications` | project_admin / system_admin | — |
| POST | `/api/projects/{pid}/applications/{aid}/approve` | project_admin / system_admin | 21, 23 |
| POST | `/api/projects/{pid}/applications/{aid}/reject` | project_admin / system_admin | 22, 23 |
| POST | `/api/projects/{pid}/applications/{aid}/withdraw` | applicant 本人 | 20 |
| GET | `/api/applications/mine` | 登录 | — |

## 5. 关键实现决策

**5.1 Token 用不透明随机串，不用 JWT**

AC-07 要求登出立即失效，AC-12 要求密码重置后全部失效，AC-03 要求禁用账号立即不可用。JWT 无状态特性反而需要额外黑名单表，复杂度更高。

实现：`secrets.token_urlsafe(32)` → 明文返回客户端，DB 存 `sha256` 十六进制。

**5.2 登录失败要防时序侧信道**

AC-02 要求三种失败响应完全一致。若"用户不存在"直接返回，"密码错误"要跑一次 bcrypt（约 100ms），攻击者仍能用耗时区分。

```python
DUMMY_HASH = bcrypt.hash("dummy-password-for-timing")

user = repo.find_by_username(username)
if user is None:
    bcrypt.verify(password, DUMMY_HASH)   # 空跑，对齐耗时
    raise InvalidCredentials
if not bcrypt.verify(password, user.password_hash):
    repo.bump_failed_login(user.id)       # 仅这条分支 +1
    raise InvalidCredentials
```

**5.3 锁定计数用单条原子 UPDATE（MySQL 无 RETURNING）**

MySQL 不支持 `UPDATE ... RETURNING`，改为「UPDATE + SELECT」在同一事务内完成，靠行锁保证读到的就是自己写的值。

```python
new_unlock_at = datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)

session.execute(text("""
    UPDATE users
    SET failed_login_count = failed_login_count + 1,
        locked_until = CASE
            WHEN failed_login_count + 1 >= :max_failures THEN :new_unlock_at
            ELSE locked_until
        END,
        updated_at = NOW(3)
    WHERE id = :uid
"""), {...})

row = session.execute(text(
    "SELECT failed_login_count, locked_until FROM users WHERE id = :uid"
), {...}).one()
```

不要在 SQL 里写 `INTERVAL :n MINUTE`——部分驱动对占位符做绑定时会报语法错。时间在 Python 侧算好再传入。

> 实测补充：MySQL 的 `SET` 子句从左到右求值。若把 `failed_login_count = failed_login_count + 1` 写在 `locked_until` 的 `CASE` 之前，`CASE` 读到的是已经 +1 的值，会在第 4 次失败（阈值 5）就锁定。**`locked_until` 必须写在自增之前。**

**5.4 审批幂等靠条件更新 + rowcount**

```python
result = session.execute(text("""
    UPDATE project_applications
    SET status = 'approved', reviewer_id = :reviewer, reviewed_at = NOW(3)
    WHERE id = :aid AND project_id = :pid AND status = 'pending'
"""), {...})

if result.rowcount == 0:
    raise InvalidApplicationState   # → 409
```

不先 SELECT 再 UPDATE，避免并发双批。影响行数是唯一可靠的判据。

**5.5 注册唯一性靠 DB 约束，不靠先查后插**

```python
try:
    repo.insert_user(...)
except IntegrityError as e:
    code = e.orig.args[0]
    msg  = str(e.orig.args[1])
    if code == 1062:                       # ER_DUP_ENTRY
        if 'uk_users_username' in msg: raise UsernameTaken
        if 'uk_users_email'    in msg: raise ContactTaken
        if 'uk_users_phone'    in msg: raise ContactTaken
    raise
```

先查后插在并发下必然漏。判断依据是错误信息里的索引名，不是字段名。

**5.6 审计与业务同事务**

```python
with session.begin():
    apply.status = 'approved'
    audit.write(session, action='project.apply.approve', ...)
```

AC-25 要求全链路可追溯，审计丢失比业务失败更严重。事务回滚时两者一起丢弃，符合预期。一期不引入 outbox。

**5.7 项目数据隔离在 repository 层强制**

```python
class ProjectScopedRepo:
    def __init__(self, session, project_id, user_id):
        self.p, self.u = project_id, user_id
        if not self._is_member():
            raise NotProjectMember()      # → 403，对应 AC-27

    def query(self, stmt):
        return stmt.where(self.model.project_id == self.p)
```

项目内表只允许通过该类访问，禁止在 service 里直接用裸 `session.query`。一期靠 code review，后续加 lint 规则。

**5.8 冷却判定**

```sql
SELECT reviewed_at FROM project_applications
WHERE project_id = :pid AND applicant_id = :uid AND status = 'rejected'
ORDER BY reviewed_at DESC LIMIT 1;
```

`next_available_at = reviewed_at + timedelta(hours=apply_cooldown_hours)`，未到 → `429 APPLY_COOLDOWN`，响应体带 `next_available_at`。按「用户 × 项目」计算（spec 待确认 3）。

**5.9 密码重置要吊销全部 token**

```python
with session.begin():
    user.password_hash = new_hash
    user.password_changed_at = now
    session.execute(update(AccessToken)
        .where(AccessToken.user_id == user.id,
               AccessToken.revoked_at.is_(None))
        .values(revoked_at=now))
    audit.write(session, action='password.reset', ...)
```

否则被盗 token 在密码改完后依然有效。

**5.10 令牌校验一次性完成四件事**

`token_hash` 命中 → `revoked_at IS NULL` → `expires_at > NOW(3)` → 关联 user `status = 'active'`。第四条保证禁用账号的旧 token 立即失效（AC-03）。

## 6. AC → 实现映射

| AC 范围 | 实现位置 | 测试文件 |
|---|---|---|
| AC-01 ~ 05 登录 | `auth/service.py::login` | `tests/auth/test_login.py` |
| AC-06 token 过期 / 未登录 | `common/deps.py::current_user` | `tests/auth/test_guard.py` |
| AC-07 登出 | `auth/tokens.py::revoke` | `tests/auth/test_logout.py` |
| AC-08 ~ 11 注册 | `auth/service.py::register` | `tests/auth/test_register.py` |
| AC-12 密码找回 | `auth/service.py::reset_password` | `tests/auth/test_password_reset.py` |
| AC-13 ~ 20 申请与撤回 | `projects/apply_service.py` | `tests/projects/test_apply.py` |
| AC-21 ~ 22 审批 | `projects/apply_service.py` | `tests/projects/test_approve.py` |
| AC-23 审批权限 | `common/deps.py::require_project_role` | `tests/projects/test_permission.py` |
| AC-24 归档关闭 | `projects/service.py::archive_project` | `tests/projects/test_archive.py` |
| AC-25 审计 | `common/audit.py` | `tests/common/test_audit.py` |
| AC-26 ~ 30 隔离与引导 | `common/scoped_repo.py` | `tests/projects/test_isolation.py` |

## 7. 测试策略

- **一个 AC 一个用例**，命名 `test_ac_01_login_success`，便于回溯 spec。
- **时间**（锁定、冷却、token 过期）统一走 `common/clock.py`，测试注入固定时间，不 `sleep`。
- **并发**（AC-17 重复申请、AC-21 双批）用线程池打两条并发请求，断言一条成功一条 409。
- **数据隔离**（AC-27）每个项目内接口都跑一组"非成员访问"用例，参数化覆盖，避免漏接口。
- **DB**：testcontainers 起 `mysql:8.0`，不用 SQLite（生成列、CHECK、JSON 行为都不同）。
- **清理**：MySQL 的 DDL 会隐式提交，不能靠事务回滚隔离用例。用 `TRUNCATE` + 临时关闭外键检查，或在 session 级重建 schema。
- **隔离级别**：保持默认 `REPEATABLE READ`。本方案的并发控制全部依赖原子 UPDATE 和唯一索引，不依赖隔离级别，**不要改成 SERIALIZABLE**，否则条件更新会出现大量锁等待。

## 8. PostgreSQL → MySQL 差异清单

改动集中在这 8 处，评审时重点关注：

| # | PG 写法 | MySQL 替代 | 影响 |
|---|---|---|---|
| 1 | 条件唯一索引 `WHERE status='pending'` | 生成列 `pending_key` + 唯一索引 | 2.4 |
| 2 | `lower(username)` 函数唯一索引 | 排序规则 `utf8mb4_0900_ai_ci` | 2.1，需建表时指定 |
| 3 | `UPDATE ... RETURNING` | UPDATE 后同事务 SELECT / 用 `rowcount` | 5.3、5.4 |
| 4 | `TIMESTAMPTZ` | `DATETIME(3)` + 强制 UTC + 连接 `time_zone='+00:00'` | 全局，最易出错 |
| 5 | `JSONB` | `JSON` | 2.5 |
| 6 | `INET` | `VARCHAR(45)` | 2.2 |
| 7 | `make_interval / interval` | Python 侧算好时间再绑定 | 5.3、5.8 |
| 8 | 错误类型 `UniqueViolation` | `IntegrityError` + 错误码 `1062` | 5.5 |

另外：`before` / `after` 是 MySQL 保留字，审计表字段已改为 `before_data` / `after_data`。

## 9. 未决问题

| # | 问题 | 影响 |
|---|---|---|
| 1 | spec 待确认 1：非成员访问 403 还是 404 | 影响 `NotProjectMember` 的状态码 |
| 2 | spec 待确认 2：注册后是否自动登录 | 影响 AC-08 返回体 |
| 3 | spec 待确认 4：管理员重置密码是否走强度校验 | 影响 `PATCH /api/admin/users/{uid}/password` |
| 4 | spec 待确认 5：连续驳回是否熔断 | 影响 AC-22 判定逻辑 |
| 5 | 审计日志是否需要表级归档 | PRD 未定义保留策略，长期会膨胀 |

已确认：代码根目录 `D:\aitest_copilot`；旧库数据不迁移；新库名保留 `aitest_copilot_v2`。
