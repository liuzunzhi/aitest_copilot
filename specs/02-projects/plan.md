# 02-projects · 实现方案（plan）

> 对应 spec：`specs/02-projects/spec.md`（AC-31 ~ AC-48）
> 前置：`specs/01-auth/` 全部完成（186 passed，迁移 0009）
> 代码根目录：`D:\aitest_copilot`

## 0. 与 01 的关系

不新建业务表，只在 `projects` 上加一列 `description`；其余全部复用 01 已定稿的表与约束。

| 表 | 本模块动作 |
|---|---|
| `projects` | 新增 `description VARCHAR(500) NULL` |
| `project_members` | 复用，复合主键保证同一用户唯一成员记录 |
| `project_applications` | 复用，`pending_key` 唯一索引继续兜并发 |
| `users` | 复用，读写 `global_role` |
| `audit_logs` | 复用，新增 7 个 action 常量 |

不动的既有行为：申请提交 / 撤回 / 审批逻辑、`pending_key`、驳回冷却、token 与鉴权、`ProjectScopedRepo`。

## 1. 模块划分

```
app/projects/
  router.py          # /api/projects/*（新增 CRUD、成员、申请队列）
  service.py         # 项目生命周期 + 概览 + 成员操作
  apply_service.py   # 01 已有，本模块只新增查询函数
  query_service.py   # 本项目申请 / 我的申请 / 全局申请记录的分页查询
app/applications/
  router.py          # /api/applications/mine
app/admin/
  applications_router.py  # /api/admin/applications
app/users/
  router.py          # 追加 PATCH /api/admin/users/{uid}/role
app/common/
  deps.py            # 新增 require_project_member_or_system_admin
  errors.py          # 新增本模块错误码
migrations/versions/
  0010_add_project_description.py
```

分层不变：router 只做参数与权限声明，业务在 service，service 不接触 `Request`。

## 2. 数据模型变更

```sql
ALTER TABLE projects
    ADD COLUMN description VARCHAR(500) NULL COMMENT '项目简介' AFTER name;
```

- 与 01 的「时间一律 UTC」「`utf8mb4_0900_ai_ci`」保持一致。
- 不加 `updated_at`：编辑时间由审计记录回答，避免为一个字段改表。
- 不加 `created_by`：创建人已落 `project_members(project_admin)`，审计也有 `actor_id`。

## 3. 状态机

**项目**

```
active ──archive（仅 system_admin）──→ archived   (终态，不可恢复)
```

**项目内角色**

```
project_admin ⇄ member ⇄ guest
约束：任一时刻项目内至少 1 名 project_admin
```

**全局角色**

```
user ⇄ system_admin
约束：system_admin 不能修改自己的 global_role
```

## 4. 接口清单

| 方法 | 路径 | 权限 | AC |
|---|---|---|---|
| POST | `/api/projects` | system_admin | 31 |
| PATCH | `/api/projects/{pid}` | project_admin / system_admin | 32, 34 |
| POST | `/api/projects/{pid}/archive` | system_admin | 33 |
| GET | `/api/projects/{pid}/overview` | 成员 / system_admin | 40, 47 |
| GET | `/api/projects/{pid}/members` | 成员 / system_admin | 35, 47 |
| POST | `/api/projects/{pid}/members` | project_admin / system_admin | 36, 47 |
| PATCH | `/api/projects/{pid}/members/{uid}` | project_admin / system_admin | 37, 47 |
| DELETE | `/api/projects/{pid}/members/{uid}` | project_admin / system_admin | 38, 47 |
| GET | `/api/projects/{pid}/applications` | project_admin / system_admin | 41, 47 |
| GET | `/api/applications/mine` | 登录 | 42 |
| GET | `/api/admin/applications` | system_admin | 43, 48 |
| PATCH | `/api/admin/users/{uid}/role` | system_admin | 45, 46, 48 |

沿用 01 的 `POST .../approve`、`POST .../reject` 作为代审批入口，不新增重复接口。

## 5. 关键实现决策

**5.1 读接口新增「成员或系统管理员」依赖**

现有 `require_project_role(*roles)` 没有系统管理员旁路；写接口用已有的 `require_project_admin_or_system_admin` 正好合适。
读接口新增：

```python
def require_project_member_or_system_admin(
    project_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> User:
    if user.global_role == SYSTEM_ADMIN:
        return user
    if session.get(ProjectMember, (project_id, user.id)) is None:
        raise NotProjectMember("不是该项目成员")
    return user
```

**5.2 成员变更用项目行锁串行化**

「最后一名 project_admin」是跨行约束，先 SELECT COUNT 再 UPDATE 在并发下会两人同时通过。
所有成员写操作先锁项目行：

```python
project = session.execute(
    select(Project).where(Project.id == project_id).with_for_update()
).scalar_one_or_none()
if project is None:
    raise ProjectNotFound("项目不存在")
if project.status != "active":
    raise ProjectArchived("项目已归档")
```

锁后计数：

```python
admin_count = session.execute(
    select(func.count()).select_from(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.role == "project_admin",
    )
).scalar_one()
if target.role == "project_admin" and admin_count == 1 and new_role != "project_admin":
    raise LastProjectAdmin("项目至少保留一名项目管理员")
```

加成员（`role=project_admin`）不受该约束；改角色与移除才判定。

**5.3 添加成员的并发去重**

不先查后插：

```python
member = ProjectMember(project_id=pid, user_id=uid, role=role)
session.add(member)
try:
    session.flush()
except IntegrityError as exc:
    session.rollback()
    if "PRIMARY" in str(exc.orig) or exc.orig.args[0] == 1062:
        raise AlreadyProjectMember("该用户已是项目成员") from exc
    raise
```

`project_members` 是复合主键，重复插入触发 1062 / `PRIMARY`。

**5.4 归档幂等 + 审计**

`archive_project` 已幂等（01 T24 的用例守着）。本模块只补两件事：

```python
if project.status == "archived":
    session.commit()
    return
```

- 已归档：直接返回，不新增审计；
- 首次归档：`project.archive` 一条 + 每条 pending 的 `project.apply.close`（01 已有）。
- 归档路由只挂 `require_system_admin`。

**5.5 项目编辑的局部更新**

用 Pydantic 的 `model_fields_set` 区分「未传」与「显式 null」：

```python
data = payload.model_dump(exclude_unset=True)
if "name" in data: ...
if "description" in data: project.description = data["description"]
```

名称：`strip()` 后为空 → `PROJECT_NAME_REQUIRED`；长度 > 128 → `INVALID_PROJECT_NAME`。
简介：长度 > 500 → `INVALID_PROJECT_DESCRIPTION`。

**5.6 分页查询统一形状**

三个列表接口返回同一结构，不建公共基类：

```json
{"items": [...], "total": 42, "page": 1, "page_size": 20}
```

- `page`、`page_size` 用 FastAPI `Query(ge=1, le=100)`；
- `total` 用同条件的 `SELECT COUNT(*)`；
- 排序一律 `created_at DESC, id DESC`，避免同毫秒重排；
- `status` 非法 → `INVALID_APPLICATION_STATUS`（不要交给 422，保持稳定 code 约定）。

**5.7 关联用户名的查询方式**

列表返回 `applicant` / `reviewer` 的 `{id, username}`，不返回邮箱手机号。
用两次 join（`User` 分别别名 applicant / reviewer），一次查询取完，避免 N+1：

```python
Applicant = aliased(User)
Reviewer = aliased(User)
stmt = (
    select(ProjectApplication, Applicant, Reviewer)
    .join(Applicant, Applicant.id == ProjectApplication.applicant_id)
    .outerjoin(Reviewer, Reviewer.id == ProjectApplication.reviewer_id)
)
```

**5.8 全局角色变更即时生效**

`require_system_admin` 每请求从库读 `user.global_role`，所以只需改库 + 审计，不碰令牌：

```python
if uid == admin.id:
    raise CannotChangeOwnRole("不能修改自己的全局角色")
if payload.global_role not in ("user", "system_admin"):
    raise InvalidGlobalRole(...)
user.global_role = payload.global_role
```

提升后原令牌立即有权限，降级后立即 403（AC-46）。

**5.9 概览的占位字段**

```python
{"member_count": count, "document_count": 0, "baseline_count": 0, "latest_execution": None}
```

文档 / 基线 / 执行模块上线时再替换为真实查询，响应结构不变。

## 6. 错误码

| code | HTTP | 触发 |
|---|---|---|
| `PROJECT_NAME_REQUIRED` | 400 | 名称为空 / 全空白 |
| `INVALID_PROJECT_NAME` | 400 | 名称 > 128 |
| `INVALID_PROJECT_DESCRIPTION` | 400 | 简介 > 500 |
| `PROJECT_ARCHIVED` | 409 | 对归档项目做写操作 |
| `MEMBER_NOT_FOUND` | 404 | 目标用户不是项目成员 |
| `LAST_PROJECT_ADMIN` | 409 | 降级 / 移除最后一名项目管理员 |
| `CANNOT_REMOVE_SELF` | 400 | 移除自己 |
| `INVALID_APPLICATION_STATUS` | 400 | 申请列表 status 非法 |
| `INVALID_GLOBAL_ROLE` | 400 | 全局角色不是 user / system_admin |
| `CANNOT_CHANGE_OWN_ROLE` | 400 | 修改自己的全局角色 |

复用既有：`FORBIDDEN`(403)、`NOT_PROJECT_MEMBER`(403)、`NOT_PROJECT_ADMIN`(403)、`PROJECT_NOT_FOUND`(404)、`USER_NOT_FOUND`(404)、`ALREADY_PROJECT_MEMBER`(409)、`INVALID_ROLE_ASSIGNMENT`(400)。

## 7. AC → 实现映射

| AC | 实现 | 测试 |
|---|---|---|
| 31 创建项目 | `projects/service.py::create_project` | `tests/projects/test_projects.py` |
| 32 编辑项目 | `projects/service.py::update_project` | 同上 |
| 33 归档 | `projects/service.py::archive_project` + router | `tests/projects/test_archive.py` |
| 34 归档只读 | `projects/service.py::_locked_active_project` | `tests/projects/test_projects.py` |
| 35 成员列表 | `projects/service.py::list_members` | `tests/projects/test_members.py` |
| 36 添加成员 | `projects/service.py::add_member` | 同上 |
| 37 改角色 | `projects/service.py::update_member_role` | 同上 |
| 38 移除成员 | `projects/service.py::remove_member` | 同上 |
| 39 审计 | `common/audit.py` 调用点 | `tests/common/test_audit_coverage.py` |
| 40 概览 | `projects/service.py::get_overview` | `tests/projects/test_overview.py` |
| 41 本项目申请 | `projects/query_service.py` | `tests/projects/test_application_lists.py` |
| 42 我的申请 | `projects/query_service.py` | 同上 |
| 43 全局记录 | `projects/query_service.py` | 同上 |
| 44 代审批 | 01 `apply_service.approve` + 全局列表 | `tests/projects/test_application_lists.py` |
| 45 全局角色 | `users/router.py::update_role` | `tests/users/test_roles.py` |
| 46 即时生效 | 每请求读库（已有） | 同上 |
| 47 项目内边界 | `common/deps.py` | `tests/projects/test_member_access.py` |
| 48 全局边界 | `require_system_admin` | `tests/users/test_roles.py` |

## 8. 测试策略

- 沿用 `tests/conftest.py` 的 savepoint 会话，不新建 fixture。
- 权限类用例参数化：同一组路径跑「非成员 / member / guest」三类身份，避免漏接口。
- 并发用例只保留两条：重复添加成员、双人同时降级最后一名 project_admin（用线程池打真实请求）。
- 归档相关回归必须跑 `tests/projects/test_archive.py`，确认 01 的 AC-24 不被破坏。
- 测试数据用 `uuid4().hex` 生成用户名 / 项目名，避免与开发库已有数据冲突。

## 9. 未决问题

| # | 问题 | 现状 |
|---|---|---|
| 1 | PRD 2.3.3「不能移除自己以外的系统管理员」表述有歧义 | 按 spec AC-38 口径落地，已在 spec 记录 |
| 2 | 项目概览的「最近执行情况」 | 执行模块未建，固定 `null` |
| 3 | 归档项目是否允许恢复 | 一期不做，归档不可逆 |
