# 01 · 登录、注册与项目申请

> 对应 PRD：2.1 登录与注册、2.2 项目管理（申请与审批）、2.3.1 工作台无项目引导
> PRD 版本：v1.7
> 状态：待评审

## 背景

平台数据全部按项目隔离，必须先回答两个问题：你是谁（登录）、你能进哪个项目（项目申请审批）。

注册环节不做审批，注册即激活。项目申请保留审批，因为项目是数据边界，必须有把关人。

## 用户故事

- 作为新用户，我要自助注册，注册完就能登录。
- 作为测试工程师，我要用账号密码登录，并能让登录状态保持一段时间。
- 作为未归属任何项目的用户，我要看到无项目引导页并申请加入项目。
- 作为项目管理员，我要审批他人的加入申请，以便控制谁能看到本项目数据。

## 验收标准

### 一、登录

**AC-01 登录成功**

```
Given 用户 U status=active，密码正确
When  POST /api/auth/login {"username","password","remember":false}
Then  200，返回 access_token，过期时间 = token_ttl_seconds（默认 8h）
And   failed_login_count 归零
And   审计 action=login.success, actor=U.id
```

**AC-02 凭据错误不区分原因**

```
Given 密码错误 / 用户名不存在 / 账号已注销
When  POST /api/auth/login
Then  401，三种情况响应体完全一致 {"code":"INVALID_CREDENTIALS"}
And   不得出现"用户不存在""密码错误"的区分文案
And   （仅密码错误时）该用户 failed_login_count +1
```

**AC-03 已禁用账号拒绝登录**

```
Given 用户 U status=disabled，密码正确
When  POST /api/auth/login
Then  403 {"code":"ACCOUNT_DISABLED"}
And   审计 action=login.blocked.disabled
And   不增加 failed_login_count
```

**AC-04 连续失败锁定**

```
Given 同一账号连续失败达到 max_login_failures（默认 5）
Then  账号锁定 lock_duration_minutes（默认 30）
When  锁定期内用正确密码登录
Then  423 {"code":"ACCOUNT_LOCKED","unlock_at":"<ISO8601>"}
When  锁定期结束后登录
Then  200，failed_login_count 归零
And   审计 action=login.locked / login.unlocked
And   两项阈值均可系统级配置，改动即时生效
```

**AC-05 记住登录延长有效期**

```
Given remember=true  → 过期时间 = remember_ttl_seconds（默认 30 天）
Given remember=false 或缺省 → 过期时间 = token_ttl_seconds（默认 8h）
```

**AC-06 Token 过期与未登录访问**

```
Given access_token 已过有效期
Then  401 {"code":"TOKEN_EXPIRED"}，前端跳登录页

Given 请求不带 token 访问任意受保护接口
Then  401 {"code":"UNAUTHENTICATED"}，前端跳登录页并带 ?redirect=<原路径>
```

**AC-07 登出**

```
When  POST /api/auth/logout
Then  200，该 token 立即失效
When  使用该 token 再次访问
Then  401 {"code":"TOKEN_REVOKED"}
And   审计 action=logout
```

### 二、注册与密码找回

**AC-08 注册即激活**

```
When  POST /api/auth/register {"username","password","email","phone","captcha"}
Then  201 {"status":"active","user_id":...}
And   不返回 access_token，前端跳转登录页
And   可立即使用 AC-01 登录
And   系统中不存在 pending_approval / rejected 这类用户状态
And   审计 action=register.submit
```

**AC-09 用户名与联系方式唯一**

```
When  用户名已存在  → 409 {"code":"USERNAME_TAKEN"}
When  邮箱或手机号已存在 → 409 {"code":"CONTACT_TAKEN"}
```

**AC-10 密码强度**

```
When  密码长度 < 8，或不含字母，或不含数字
Then  400 {"code":"WEAK_PASSWORD"}
And   该规则不适用于管理员重置密码接口（见待确认 4）
```

**AC-11 验证码校验**

```
When  captcha 缺失 → 400 {"code":"CAPTCHA_REQUIRED"}
When  captcha 错误或已过期 → 400 {"code":"CAPTCHA_INVALID"}
```

**AC-12 密码找回与重置**

```
Given 用户已注册且 status=active
When  POST /api/auth/password/send-code {"contact":"..."}
Then  200，发送验证码至邮箱或手机
And   contact 不存在时同样返回 200，不泄露账号是否存在

When  POST /api/auth/password/reset {"contact","code","new_password"}
Then  200，密码更新，该用户全部已签发 token 立即失效
And   新密码需通过 AC-10 强度校验
And   审计 action=password.reset
```

### 三、项目申请与审批

**AC-13 提交项目申请**

```
Given enable_project_apply=true
And   用户 U 不是项目 P 的成员
And   U 对 P 无 status=pending 的申请
When  POST /api/projects/{pid}/applications {"reason":"...","desired_role":"member"}
Then  201 {"status":"pending"}
And   P 的项目管理员待办出现该条
And   审计 action=project.apply.submit
```

**AC-14 申请理由必填**

```
When  reason 为空或全为空白字符
Then  400 {"code":"REASON_REQUIRED"}
```

**AC-15 期望角色白名单**

```
When  desired_role 取值为 project_admin 或 system_admin
Then  400 {"code":"INVALID_DESIRED_ROLE"}
And   合法值仅 member / guest
```

**AC-16 已是成员不可申请**

```
Given 用户 U 已是项目 P 的成员（任意角色）
When  POST /api/projects/{pid}/applications
Then  409 {"code":"ALREADY_PROJECT_MEMBER"}
And   P 不出现在 U 的可申请列表中
```

**AC-17 同一项目仅一条待审批申请**

```
Given U 对 P 已有 status=pending 的申请
When  再次提交对 P 的申请
Then  409 {"code":"DUPLICATE_APPLICATION"}
```

**AC-18 全局开关关闭时拒绝新申请**

```
Given enable_project_apply=false
When  POST /api/projects/{pid}/applications
Then  403 {"code":"APPLY_DISABLED"}
And   已存在的 pending 申请仍可被审批
And   前端申请入口置灰/隐藏，文案提示"当前平台未开放自助申请，请联系系统管理员分配项目"
```

**AC-19 允许多项目并行申请**

```
When  U 对 P1、P2 各提交一条申请
Then  两条独立存在，status 均为 pending
And   审批 P1 不影响 P2 状态
```

**AC-20 撤回申请**

```
Given U 自己提交的 status=pending 申请
When  POST /api/projects/{pid}/applications/{aid}/withdraw
Then  200，status=withdrawn
And   该记录不再占用"同一项目仅一条待审批"名额
And   审计 action=project.apply.withdraw

When  U 撤回不属于自己的申请
Then  403 {"code":"NOT_APPLICATION_OWNER"}
```

**AC-21 审批通过立即生效**

```
Given 项目 P 的项目管理员，申请 status=pending
When  POST /api/projects/{pid}/applications/{aid}/approve {"role":"member"}
Then  200，status=approved
And   用户加入 P，项目内角色为 role
And   同一请求内即可访问 P 的资源（无需重新登录）
And   审计 action=project.apply.approve, before=pending, after=approved
And   通知申请人

When  role=system_admin
Then  400 {"code":"INVALID_ROLE_ASSIGNMENT"}，合法值仅 project_admin / member / guest
```

**AC-22 驳回与冷却**

```
Given 项目管理员，申请 status=pending
When  POST /api/projects/{pid}/applications/{aid}/reject {"reason":"..."}
Then  200，status=rejected，记录 rejected_at
And   reason 必填，为空返回 400 {"code":"REASON_REQUIRED"}
And   审计 action=project.apply.reject
And   通知申请人

Given 该申请于 T 被驳回，apply_cooldown_hours=24（系统级可配）
When  T + 12h 再次对同一项目提交申请
Then  429 {"code":"APPLY_COOLDOWN","next_available_at":"<ISO8601>"}
When  T + 25h 再次提交
Then  201，正常进入 pending
```

**AC-23 审批权限边界**

```
Given A 是 P1 的项目管理员，不是 P2 的成员
When  A 对 P2 的申请执行 approve / reject
Then  403 {"code":"NOT_PROJECT_ADMIN"}

Given 系统管理员（非该项目成员）
When  对任意项目的 pending 申请执行 approve / reject
Then  200，行为与 AC-21 / AC-22 一致
And   审计记录 approver_role=system_admin
```

**AC-24 项目归档时关闭待审批申请**

```
Given 项目 P 存在 status=pending 的申请
When  P 被归档或删除
Then  这些申请 status=closed，关闭原因 project_archived
And   通知每位申请人
```

**AC-25 申请全链路审计**

```
When  发生 submit / approve / reject / withdraw / close
Then  审计表至少记录：action、project_id、applicant_id、actor_id、
      before_status、after_status、reason、timestamp
And   可按 project_id 或 applicant_id 检索
```

### 四、无项目用户与访问控制

**AC-26 项目列表按成员关系过滤**

```
Given 用户 U 属于 P1，不属于 P2
When  GET /api/projects
Then  只返回 P1
And   该过滤在数据访问层统一生效，不依赖各接口自行判断
```

**AC-27 非成员访问项目资源一律 403**

```
Given U 不是项目 P 的成员
When  GET /api/projects/{pid}/documents（或任意项目内资源）
Then  403 {"code":"NOT_PROJECT_MEMBER"}
```

**AC-28 无项目用户进入引导页且不渲染项目信息**

```
Given U 已登录，且不属于任何项目
When  登录成功
Then  前端路由到工作台的无项目引导页
And   页面不渲染任何项目卡片、项目列表或项目元信息（名称、简介等）
And   不出现"无权限"的项目占位
And   GET /api/projects 返回空数组，不报错
And   可访问：个人中心、项目申请、帮助、我的申请
```

**AC-29 可申请列表覆盖全部未加入项目**

```
Given U 是 P1 成员，不是 P2、P3 成员
When  GET /api/projects/available
Then  返回 P2、P3（全部尚未加入的项目）
And   不返回 P1
And   不存在项目级开关影响该列表的返回结果
```

**AC-30 无可申请项目时的空态**

```
Given enable_project_apply=true，且平台上没有 U 尚未加入的项目
When  用户点击「申请加入项目」
Then  进入空态页，展示"暂无可申请的项目，可联系系统管理员分配项目"
And   提供「返回工作台」
And   申请入口本身保持可点击，不隐藏
```

## 规则

- 所有时间按 UTC 存储、ISO8601 输出。
- 开关与阈值的默认值以 PRD 1.4 默认值对齐表为准，本 spec 只在 AC 中引用键名。
- 用户状态仅 `active` / `disabled` 两态，不存在待审批态。
- 登录失败计数按账号统计，不按 IP；锁定与解锁均写审计。
- 密码使用 bcrypt（cost ≥ 10）存储，任何接口不返回密码字段。
- 审批类接口必须幂等：对已处理过的申请重复 approve/reject 返回 409，不重复写入。
- 「我的申请」包含 pending / approved / rejected / withdrawn / closed 全部状态。

## 不做什么

- **不做注册审批**（本期明确取消，注册即激活）。
- **不做项目级「是否开放申请」开关**（所有项目统一开放申请，由项目管理员审批把关）。
- 不做第三方登录（OAuth / SSO / 企业微信）。
- 不做多因素认证（MFA）。
- 不做用户自助注销账号。
- 不做批量审批（一期逐条处理）。
- 不做邀请制入组。
- 密码找回只做邮箱/手机验证码，不做安全问题。

## 依赖

| 依赖 | 用途 |
|---|---|
| 系统配置表 | `enable_project_apply`、`token_ttl_seconds`、`remember_ttl_seconds`、`max_login_failures`、`lock_duration_minutes`、`apply_cooldown_hours` |
| 项目表、项目成员关系表 | 可申请列表、成员判定、审批落库 |
| 审计日志表 | 全部 AC 的留痕，与运行日志分离 |
| 通知模块 | 审批结果通知（未实现时可退化为站内待办） |

## 待确认

1. **非成员访问返回 403 还是 404**：PRD 2.2 写 403，但从安全角度 404 更合理（不泄露项目存在性）。本 spec 暂按 403。
2. **注册成功后是否自动登录**：PRD 写"注册成功后…登录后进入"，读起来是两步。本 spec 暂定为不自动登录、跳转登录页。
3. **冷却时间按「用户 × 项目」还是「用户」计算**：本 spec 按用户 × 项目，换项目不受影响。
4. **密码强度规则是否适用于管理员重置密码**：本 spec 暂定不适用（管理员重置走随机强密码 + 强制首登修改），但 AC-10 未定义"强制首登修改"的字段，需要补。
5. **连续驳回是否需要熔断**：目前无上限，用户每 24h 可申请一次同一项目。是否需要"连续 N 次驳回后禁止申请"。

---

## 备注

本 spec 约 280 行，仍略超单文件 200 行建议。若后续评审确认，可拆为：

```
specs/
  01-auth/spec.md        # 登录 + 注册 + 密码找回（AC-01 ~ AC-12）
  02-project-apply/spec.md   # 项目申请审批 + 访问控制（AC-13 ~ AC-30）
```
