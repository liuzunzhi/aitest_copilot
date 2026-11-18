# 04 · 功能基线管理 · 方案

> 规格 [spec.md](./spec.md) ｜ 任务 [tasks.md](./tasks.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)

## 1. 总体思路

03 已经把「文档 → 版本 → 章节」这条链做完了，缺的是「章节落到被测对象上」这一步。
本期不引入 LLM，也不做文档推导，只把**手工路径**做扎实：

```
结构层：baseline_modules ── baseline_functions ── baseline_feature_points
                          （source_type + 追溯字段）
标签层：baseline_labels ──▶ (target_type, target_id) + revision_id
审核层：baseline_revisions ── 冻结 structure_json + 版本号 v1.n
策略层：projects.baseline_snapshot_max_count（空 = 不启用）
```

关键取舍：

1. **审核记录与快照合表**。`baseline_revisions` 一行既是「一次审核」也是「一份快照」。
   拆两张表会让「审核通过后冻结结构」需要跨表拼装，合表后
   `status='approved'` 即快照，`structure_json` 只在通过时写入、之后只读。
2. **标签挂快照而不是挂结构行**。PRD 写「标签作用于对应快照」。
   挂快照的好处是「旧快照清除标签不影响新快照」天然成立：
   生成新快照时把当时生效的标签**复制成新行**（新 `revision_id`），
   旧行的清除只动旧行。
3. **`active_key` 生成列**复用 03 的手法（`IF(status='active', ..., NULL)` + 唯一索引），
   用数据库保证「同实体同快照同类型只允许一条生效标签」，应用层不写该列。
4. **标签行不物理删除**。清除 = `status='cleared'` + 记清除人/时间/原因。
   PRD 明确要求「标签清除后默认不再展示，审计可查」，物理删除会丢痕迹。
5. **保留上限放 `projects` 列**而不是 `system_settings`：PRD 要求项目级、空值即不启用。
6. **快照「被引用即保护」本期只查标签引用**。PRD 列举了标签、增量分析记录、测试点、用例、报告，
   后四者尚未上线，引用检查在对应模块落地时补。

## 2. 数据层

### 2.1 迁移

`migrations/versions/0012_baseline.py`，`down_revision = "0011"`。

upgrade 顺序（外键依赖）：
`baseline_modules` → `baseline_functions` → `baseline_feature_points`
→ `baseline_revisions` → `baseline_labels` → `projects.baseline_snapshot_max_count`。

downgrade 反序：先删 `projects` 新列，再按 `labels → revisions → feature_points → functions → modules` 删表。

`baseline_labels.active_key` 用 MySQL STORED 生成列：

```sql
active_key VARCHAR(160) GENERATED ALWAYS AS (
  IF(status = 'active',
     CONCAT(revision_id, ':', target_type, ':', target_id, ':', label_type),
     NULL)
) STORED,
UNIQUE KEY uk_labels_active (active_key)
```

MySQL 唯一索引允许多个 NULL，已清除的行不占位。

### 2.2 模型

`app/models/baseline.py`，5 个模型，注册到 `app/models/__init__.py`。

`Project` 模型补 `baseline_snapshot_max_count: Mapped[int | None]`。

## 3. 服务层

新建包 `app/baselines/`，与 `app/documents/` 同构：

```
app/baselines/
  __init__.py
  schemas.py    请求/响应模型
  service.py    业务逻辑
  router.py     路由
```

### 3.1 复用 03 的既有件

- `app/common/deps.py` 的 `require_project_member_or_system_admin`（读）与
  `require_project_admin_or_system_admin`（写）直接用。
- 归档判断沿用 `app/projects/service.py` 的写法：先判 409 `PROJECT_ARCHIVED`，再判角色。
- `app/common/audit.py` 的 `write_audit` 直接用。

### 3.2 关键实现点

**模块删除**：
```
count = 功能数
if count > 0:
    raise ModuleNotEmpty(extra={"available_actions": ["migrate_functions", "delete_functions"]})
删模块 → 级联删其功能点 → 级联删相关标签（标签是软状态，改为 cleared）
```
PRD 说「模块下有功能 → 弹窗提供迁移/删除功能两个入口」，即删除模块本身不是唯一路径，
功能可以先迁移走或先删掉，模块空了再删。

**功能迁移**：
```
目标模块校验：存在、同项目、不等于当前模块 → 否则 INVALID_MIGRATE_TARGET
逐个功能更新 module_id，并把旧 module_id 写进 moved_from_module_id
```
`moved_from_module_id` 落在 `baseline_functions` 上（保留最近一次迁移来源，追溯用）。

**标签 `active_key` 唯一冲突**：
写入前不查库，直接插入，让数据库唯一索引报冲突 → 映射成 409 `DUPLICATE_LABEL`。
并发下也不会出现两条生效标签。

**快照生成**：
```
approve:
  1. 结构冻结：查当前 active 模块/功能/功能点 → 组树 → json.dumps → structure_json
  2. version_no = 项目内已 approved 的最大 version_no + 1
  3. 计数写 module_count / function_count / feature_point_count / label_count
  4. 复制标签：查上一 approved 快照的 active 标签 → 逐条 insert 新行（revision_id 换新，active_key 自然不同）
```

**标签清除**：
```
入参 clear_reason 必填且在 6 类枚举内；reason == 'other' 时 clear_note 必填
更新：status='cleared'，cleared_by/cleared_at/clear_reason/clear_note
```
6 类原因取自 PRD 2.4.2「人工清除」：需求已实现、需求已取消、判断错误、优先级变化、
重复标签、其他。枚举常量放 `app/baselines/service.py` 的 `CLEAR_REASONS`。

**被引用即保护**：
```
被引用 = 存在 label.revision_id == 该快照且 label.status == 'active' 的行
删除快照：被引用 → 409 SNAPSHOT_REFERENCED + extra.refs（来源明细）
```

**保留策略**：
```
max_count 为空 → 候选空
max_count = N，approved 快照数 > N → 超出的最旧 (count - N) 份进候选
候选里被引用的不自动删，只在告警里列出
```
`GET /retention` 返回：`max_count`、快照总数、候选列表（含每份的被引用计数）、告警文案。

## 4. 接口层

路由挂在 `app/baselines/router.py`，前缀 `/api/projects/{project_id}/baselines`，
在 `app/main.py` 注册 `baselines_router`。

写接口统一：
1. 解析 `project_id`（404 `PROJECT_NOT_FOUND`）
2. 归档检查（409 `PROJECT_ARCHIVED`）——只对写接口
3. 角色检查（403 `NOT_PROJECT_ADMIN`）
4. 资源归属检查（404 `*_NOT_FOUND`）

读接口：项目成员 + 访客 + system_admin 兜底；非成员 403 `NOT_PROJECT_MEMBER`。

列表接口统一支持分页参数 `page`（默认 1）/ `page_size`（默认 50，上限 200），
返回 `{items, total, page, page_size}`。

## 5. 前端

`web/src/pages/` 新增：

- `ProjectBaselineTree.tsx` —— 模块/功能/功能点三级树 + 打标 + 清除标签 + 筛选
- `ProjectBaselineSnapshots.tsx` —— 快照列表、提交审核、审核通过/驳回、保留策略、清理候选

`ProjectDetailPage.tsx` 插入「基线管理」Tab；原「基线」Tab（文档基线快照）改名「版本快照」。

`web/src/api/index.ts` 增类型与函数；`web/src/client.ts` 补错误码中文映射。

## 6. 任务拆分

见 [tasks.md](./tasks.md)：T55–T66。

依赖关系：
```
T55 模型与迁移 ─┬─▶ T56 模块管理 ─▶ T57 功能与功能点 ─▶ T58 功能迁移
                ├─▶ T59 标签与清除 ─▶ T60 标签随快照
                └─▶ T61 审核与快照 ─▶ T62 保留策略与被引用保护 ─▶ T63 检索
                                                                     T64 概览计数
                                                          T65 前端 ─▶ T66 全量回归
```
T59 打标依赖 T61 的快照概念，故实际顺序里 T60 合并到 T61 之后；
先做 T55–T58（结构），再做 T59–T62（标签+审核），最后 T63–T66。
