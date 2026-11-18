# 02 · 项目与成员管理

> 对应 PRD：2.2 项目管理、2.3.1 工作台待办（申请队列）、2.3.3 成员管理
> PRD 版本：v1.8
> 状态：待评审
> 承接：`specs/01-auth/`（AC-01 ~ AC-30）

## 背景

01 已把「谁能进哪个项目」的入口做完：项目列表、可申请列表、申请提交 / 撤回 / 审批、归档关闭 pending。
但项目生命周期本身还没有出口——系统管理员无法在平台内创建项目，项目管理员无法维护成员，审批人看不到本项目的申请队列，系统管理员也无法查看全局申请记录。本模块补齐这些管理面。

## 范围

**做**

- 项目创建、编辑、归档（=删除）、概览
- 项目成员列表、添加、修改角色、移除
- 本项目申请队列、我的申请、系统管理员全局申请记录与代审批
- 系统管理员全局角色分配（提升 / 降级 `system_admin`）

**不做**

- 项目物理删除（归档即删除，见 AC-33）
- 成员主动退出项目（自己移除自己）
- 邀请制入组、批量导入成员
- 项目级「是否开放申请」开关（01 已明确不做）
- 邮件 / 短信通知通道（沿用 01 缺口，由列表接口承担站内待办）

## 验收标准

### 一、项目生命周期

**AC-31 创建项目**

```
Given 系统管理员 S
When  POST /api/projects {"name":"支付中台","description":"支付相关需求"}
Then  201 {"id","name","description","status":"active"}
And   同一事务内写入 project_members(project_id=P, user_id=S, role=project_admin)
And   审计 action=project.create, actor_id=S.id, project_id=P
And   S 立即可以按 AC-23 审批 P 的加入申请

Given name 缺失或全为空白字符
Then  400 {"code":"PROJECT_NAME_REQUIRED"}
Given name 长度 > 128
Then  400 {"code":"INVALID_PROJECT_NAME"}
Given description 长度 > 500
Then  400 {"code":"INVALID_PROJECT_DESCRIPTION"}
Given 调用者 global_role != system_admin
Then  403 {"code":"FORBIDDEN"}
```

**AC-32 编辑项目**

```
Given 项目 P status=active，调用者是 P 的 project_admin 或系统管理员
When  PATCH /api/projects/{pid} {"name":"新名称","description":"新简介"}
Then  200，返回更新后的项目
And   审计 action=project.update，before_data / after_data 各含 name、description
And   只传 name 时 description 保持不变
And   显式传 description=null 时清空简介

Given P status=archived
Then  409 {"code":"PROJECT_ARCHIVED"}
Given 调用者是 P 的 member / guest
Then  403 {"code":"NOT_PROJECT_ADMIN"}
Given 调用者不是 P 的成员
Then  403 {"code":"NOT_PROJECT_ADMIN"}（不区分项目是否存在）
```

**AC-33 归档项目（即删除）**

```
Given 系统管理员，P status=active，P 有 2 条 status=pending 的申请
When  POST /api/projects/{pid}/archive
Then  200 {"status":"archived"}
And   P.status=archived
And   2 条申请 status=closed，closed_reason=project_archived（复用 01 AC-24）
And   审计 action=project.archive，并为每条申请写 project.apply.close

Given P 已归档
When  再次归档
Then  200 {"status":"archived"}，不新增审计记录

Given 调用者不是系统管理员
Then  403 {"code":"FORBIDDEN"}
Given P 不存在
Then  404 {"code":"PROJECT_NOT_FOUND"}
```

> PRD 2.2 的「删除」通过归档实现，平台不提供物理删除接口（PRD 1.4 原则四：不物理删除追溯链）。

**AC-34 归档项目只读**

```
Given P status=archived
When  PATCH /api/projects/{pid}
      或 POST /api/projects/{pid}/members
      或 PATCH /api/projects/{pid}/members/{uid}
      或 DELETE /api/projects/{pid}/members/{uid}
Then  409 {"code":"PROJECT_ARCHIVED"}

Given P status=archived
When  GET  members / overview / applications
Then  200，仍可查看历史
And   P 不出现在 /api/projects/available（01 已实现）
```

### 二、成员管理

**AC-35 成员列表**

```
Given 调用者是 P 的成员（project_admin / member / guest）或系统管理员
When  GET /api/projects/{pid}/members
Then  200 [{"user_id","username","role","joined_at"}]
And   按 joined_at、user_id 升序
And   不返回 password_hash、令牌等敏感字段

Given 调用者既不是 P 成员也不是系统管理员
Then  403 {"code":"NOT_PROJECT_MEMBER"}
```

**AC-36 添加成员**

```
Given 调用者是 P 的 project_admin 或系统管理员，P status=active
When  POST /api/projects/{pid}/members {"user_id":U,"role":"member"}
Then  201 {"user_id","username","role","joined_at"}
And   审计 action=project.member.add，target_type=project_member，target_id=U

Given role 不在 {project_admin, member, guest}
Then  400 {"code":"INVALID_ROLE_ASSIGNMENT"}
Given U 不存在
Then  404 {"code":"USER_NOT_FOUND"}
Given U 已是 P 成员
Then  409 {"code":"ALREADY_PROJECT_MEMBER"}
And   并发重复添加同样返回 409（靠主键冲突 1062 映射，不靠先查后插）
```

**AC-37 修改成员角色**

```
Given 调用者是 P 的 project_admin 或系统管理员，P status=active
When  PATCH /api/projects/{pid}/members/{uid} {"role":"guest"}
Then  200 {"user_id","username","role","joined_at"}
And   审计 action=project.member.role，before/after 均为 {"role": ...}

Given role 不在 {project_admin, member, guest}（含 system_admin）
Then  400 {"code":"INVALID_ROLE_ASSIGNMENT"}
Given U 不是 P 的成员
Then  404 {"code":"MEMBER_NOT_FOUND"}
Given U 是 P 内唯一一名 project_admin，且新角色不是 project_admin
Then  409 {"code":"LAST_PROJECT_ADMIN"}
```

**AC-38 移除成员**

```
Given 调用者是 P 的 project_admin 或系统管理员，P status=active
When  DELETE /api/projects/{pid}/members/{uid}
Then  200 {"status":"removed"}
And   审计 action=project.member.remove，before_data={"role":...}
And   U 的下一次项目内请求返回 403（不需要重新登录）
And   GET /api/projects 对 U 不再返回 P

Given uid == 调用者自己
Then  400 {"code":"CANNOT_REMOVE_SELF"}
Given 调用者是 project_admin，目标成员 global_role=system_admin
Then  403 {"code":"FORBIDDEN"}
Given U 是 P 内唯一一名 project_admin
Then  409 {"code":"LAST_PROJECT_ADMIN"}
Given U 不是 P 的成员
Then  404 {"code":"MEMBER_NOT_FOUND"}
```

> PRD 2.3.3「不能移除自己以外的系统管理员」按以下口径落地：项目管理员不能移除系统管理员成员；任何人不能移除自己；系统管理员可移除其他任意成员。

**AC-39 项目与成员变更审计**

```
When  创建 / 编辑 / 归档 / 添加成员 / 修改角色 / 移除成员 / 修改全局角色
Then  audit_logs 至少记录：action、actor_id、actor_role、project_id（项目相关操作）、
      target_type、target_id、before_data、after_data、created_at
And   可按 project_id 检索到该项目的全部成员变更
And   审计与业务同事务：业务失败时不留审计记录
```

### 三、项目概览

**AC-40 项目概览**

```
Given 调用者是 P 的成员或系统管理员
When  GET /api/projects/{pid}/overview
Then  200 {"member_count":N,"document_count":0,"baseline_count":0,"latest_execution":null}
And   member_count 为 project_members 实际行数
And   文档 / 基线 / 执行模块上线前，后三个字段为固定占位值（0 / 0 / null）

Given 调用者既不是 P 成员也不是系统管理员
Then  403 {"code":"NOT_PROJECT_MEMBER"}
```

### 四、申请队列与全局申请记录

**AC-41 本项目申请列表**

```
Given 调用者是 P 的 project_admin 或系统管理员
When  GET /api/projects/{pid}/applications?status=pending&page=1&page_size=20
Then  200 {"items":[...],"total":N,"page":1,"page_size":20}
And   item 含 id、applicant{id,username}、reason、desired_role、status、created_at、
      reviewer{id,username}|null、reviewed_at、reject_reason、closed_reason
And   按 created_at 降序
And   status 缺省时返回全部状态
Given status 不在 {pending,approved,rejected,withdrawn,closed}
Then  400 {"code":"INVALID_APPLICATION_STATUS"}
Given 调用者是成员但不是 project_admin，也不是系统管理员
Then  403 {"code":"NOT_PROJECT_ADMIN"}
```

**AC-42 我的申请**

```
Given 登录用户 U
When  GET /api/applications/mine?status=
Then  200 分页结构同上，仅含 applicant_id=U.id 的记录
And   item 含 project{id,name}、reason、desired_role、status、created_at、
      reviewed_at、reject_reason、closed_reason

Given 未登录
Then  401 {"code":"UNAUTHENTICATED"}
```

**AC-43 系统管理员全局申请记录**

```
Given 系统管理员
When  GET /api/admin/applications?project_id=&status=&applicant_id=&page=&page_size=
Then  200 分页结构同上，按 created_at 降序
And   project_id / status / applicant_id 可任意组合筛选
And   每条含 project{id,name}、applicant{id,username}、reviewer{id,username}|null

Given 调用者不是系统管理员
Then  403 {"code":"FORBIDDEN"}
```

**AC-44 系统管理员代审批**

```
Given 系统管理员 S（可以不是 P 的成员），P 有一条 status=pending 的申请
When  POST /api/projects/{pid}/applications/{aid}/approve {"role":"member"}
Then  200
And   审计 actor_role=system_admin
And   GET /api/admin/applications 中该记录 status=approved
And   被审批用户立即获得 P 的访问权限
```

### 五、全局角色分配

**AC-45 提升 / 降级系统管理员**

```
Given 系统管理员 S
When  PATCH /api/admin/users/{uid}/role {"global_role":"system_admin"}
Then  200 {"id","username","global_role"}
And   审计 action=user.role.change，before/after 均为 {"global_role": ...}

Given global_role 不在 {user, system_admin}
Then  400 {"code":"INVALID_GLOBAL_ROLE"}
Given uid 不存在
Then  404 {"code":"USER_NOT_FOUND"}
Given uid == S.id
Then  400 {"code":"CANNOT_CHANGE_OWN_ROLE"}
```

> 禁止修改自己的全局角色，从机制上保证系统至少保留一名系统管理员；因此不设「最后一名管理员」判定。

**AC-46 全局角色变更即时生效**

```
Given 用户 U 已登录且 global_role=user
When  系统管理员把 U 提升为 system_admin
Then  U 用原令牌访问 GET /api/admin/users → 200

When  再把 U 降级为 user
Then  U 用原令牌访问 GET /api/admin/users → 403 {"code":"FORBIDDEN"}
And   不需要重新登录，也不需要吊销令牌
```

### 六、访问控制

**AC-47 项目内管理接口的成员边界**

```
Given U 不是 P 的成员
When  GET /api/projects/{pid}/members、/overview、/applications
Then  403 {"code":"NOT_PROJECT_MEMBER"}
When  POST / PATCH / DELETE /api/projects/{pid}/members...
Then  403（NOT_PROJECT_MEMBER 或 NOT_PROJECT_ADMIN）

Given U 是 P 的 member 或 guest
When  调用成员写接口
Then  403 {"code":"NOT_PROJECT_ADMIN"}
```

**AC-48 全局接口的系统管理员边界**

```
Given global_role=user
When  GET /api/admin/applications
      或 PATCH /api/admin/users/{uid}/role
Then  403 {"code":"FORBIDDEN"}

Given 未携带令牌
Then  401 {"code":"UNAUTHENTICATED"}
```

## 规则

- 时间一律 UTC 存储、ISO8601 输出。
- 权限判定每请求读库（`global_role` 与成员关系），不把角色写进令牌或进程缓存。
- 分页统一：`page >= 1`，`1 <= page_size <= 100`，缺省 `page=1`、`page_size=20`。
- 审计与业务同一事务，业务回滚时审计一起回滚。
- 归档是唯一的删除方式；归档不可逆，一期不提供恢复。
- 项目内角色只允许 `project_admin / member / guest`；`system_admin` 只存在于 `users.global_role`。
- 项目至少保留一名 `project_admin`：最后一名不能被降级或移除。
- 项目管理员不能移除系统管理员成员；任何人不能移除自己。

## 权限矩阵

| 操作 | system_admin | project_admin | member | guest | 非成员 |
|---|---|---|---|---|---|
| 创建项目 | ✓ | ✗ | ✗ | ✗ | ✗ |
| 编辑项目 | ✓ | ✓ | ✗ | ✗ | ✗ |
| 归档项目 | ✓ | ✗ | ✗ | ✗ | ✗ |
| 查看成员 / 概览 | ✓ | ✓ | ✓ | ✓ | ✗ |
| 添加 / 改角色 / 移除成员 | ✓ | ✓ | ✗ | ✗ | ✗ |
| 查看本项目申请队列 | ✓ | ✓ | ✗ | ✗ | ✗ |
| 查看全局申请记录 | ✓ | ✗ | ✗ | ✗ | ✗ |
| 代审批 | ✓ | 仅本项目 | ✗ | ✗ | ✗ |
| 修改全局角色 | ✓ | ✗ | ✗ | ✗ | ✗ |

## 待确认（已在 2026-11-15 与用户确认）

1. **「删除」语义**：不物理删除，删除即归档（AC-33）。
2. **创建人归属**：创建人自动成为该项目 `project_admin`（AC-31）。
3. **全局角色分配**：纳入本模块（AC-45 / 46）。
4. **项目元信息**：新增 `description`，创建 / 编辑接口可写（AC-31 / 32）。
5. **创建 / 归档权限**：仅系统管理员；编辑与成员维护由项目管理员负责。
6. **PRD「不能移除自己以外的系统管理员」**：按 AC-38 的口径解释。
7. **概览的文档 / 基线 / 执行字段**：对应模块未上线前固定返回 `0 / 0 / null`，不删字段。

## 依赖

| 依赖 | 用途 |
|---|---|
| `projects` / `project_members` / `project_applications`（01 已建） | 生命周期、成员、申请队列 |
| `users.global_role`（01 已建） | 全局角色分配 |
| `audit_logs`（01 已建） | 本模块全部写操作留痕 |
| `0008` 新增的 `audit_logs.applicant_id` | 「我的申请」与全局申请记录的审计检索 |
