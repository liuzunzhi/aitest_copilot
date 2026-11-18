# 05 · 增量分析（第二期）· 技术方案

> 规格 [spec-phase2.md](./spec-phase2.md) ｜ 一期 [spec.md](./spec.md) / [plan.md](./plan.md) ｜ 验证约定 [../验证约定.md](../验证约定.md)
> 迁移：0014（引用图）→ 0015（第二遍表与列）；head 从 `0013` 推进到 `0015`。

## 1. 总体结构

一期已经形成「一条主链路 + 三个可复用积木」：

```
router.py → service.py → engine.py（第一遍，逐章节）
             ↘ context.py（Prompt 组装 + 基线索引）
             ↘ app/llm（Provider Protocol + MockProvider）
```

第二期不推翻主链路，只在其后串一段**同构**的第二遍：

```
                ┌─ links.py（规则抽取，独立于 03）
document_chapter_links ─┐
                        ▼
incremental_conclusions → second_pass.py（2b-1 索引 → 2b-2 按点分治 → 2b-3 图传播）
                        │        ↘ context2b.py（第二遍 Prompt 组装）
                        ▼
        incremental_decisions / incremental_conflicts
                        ▼
        service.run_second_pass → router 四个新接口
```

**只新增、不改写一期语义**：`incremental_conclusions` 不动，`analyses.status` 只表达第一遍。

## 2. 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 第二遍状态 | `analyses.second_pass_status` 独立列 | 第一遍成功但第二遍失败是最常见的排查场景；复用 `status` 会互相覆盖 |
| 冲突与裁决分表 | `decisions` 只存无争议结果，`conflicts` 存一切待人工项 | C3 / C4 都要求「不自动写最终标签」，分表后「人工队列」就是一个简单查询 |
| `new` 的落点 | 只进 `conflicts(conflict_type='new')`，`target_id=NULL` | 新增没有基线 id，落 `decisions` 会逼出假 id；也让「新增唯一来源」可断言 |
| 冲突唯一性 | 数据库不加唯一键，服务层去重 | `new` 的 `target_id` 为 NULL 会让唯一键对同分析重复命中失效 |
| 图传播落点 | 只写 `possible_impact` 冲突 | C4 明确「只进待人工裁决队列，不自动确认」 |
| 抽取幂等 | 按 `(version_id, source='rule')` 先删后插 | 重复抽取不累加；人工行 `source='manual'` 不受影响 |
| 第二遍模板 | 按 `name LIKE '增量分析·第二遍%' AND status='active'` 取最新一条 | 一期已有 `prompt_templates`，不为第二遍加新表或新选择接口 |
| 重跑 | 有 pending 冲突 → 409；成功重跑先删后建 | 防止把未裁决的候选冲掉；同时避免结果累加 |
| 同步执行 | 触发接口跑完才返回 | 与一期一致，真实模型接入时再换队列 |
| 引用图权限 | 读随文档（含访客），写限管理员 | 引用图是文档版本的一部分，不额外收紧可见性 |

## 3. 落库与幂等细节

### 3.1 第二遍事务边界

```
run_second_pass:
  1. 校验（§5.2 顺序）；置 second_pass_status='running'，commit
  2. try:
       - 抽取引用图（若无 rule 行且被授权? 见下）
       - 重跑时：DELETE decisions/conflicts WHERE analysis_id=?
       - 2b-1 → 内存索引
       - 2b-2 → 逐点调 Mock，逐点 flush
       - 2b-3 → 传播，写冲突
       - 回填 stats/status/succeeded/finished_at，commit
     except LLMError:
       - 回填 failed + error_code/message + stats.failed_target_*，commit（保留已写入行）
     except Exception:
       - 同上，统一转 LLM_OUTPUT_INVALID / 500 由全局处理器兜底
```

- **引用图自动抽取**：触发第二遍时若该版本没有任何 `source='rule'` 行，用「触发人」身份跑一次
  幂等抽取；已有 rule 行则不再重抽（避免覆盖人工调整后的图）。管理员的显式 `extract` 仍可随时重抽。
- 每次 `flush` 保证「单点失败前的结果可保留」，与一期「单章失败即终止」一致。

### 3.2 2b-1 索引形状

```python
@dataclass
class PointIndex:
    conclusions: dict[tuple[str, int], list[LocalConclusion]]
    function_points: dict[int, list[int]]       # function_id -> point_ids
    chapter_links: dict[int, list[int]]         # from_chapter_id -> to_chapter_ids
    point_names: dict[int, str]
```

- 只收 `baseline_index()` 里存在的目标（一期已保证落库目标合法，这里再兜一次，归档后变更的目标直接忽略）。
- 章节引用图只取当前分析 `document_version_id` 的边。

### 3.3 2b-2 Prompt 形状（AC-89 可断言锚点）

```
system = 第二遍模板.system_prompt                    # 以 [INCREMENTAL_2B_SYSTEM] 开头
user   = f"{第二遍模板.user_prompt}\n\n## {target_label}：{name}\n## 局部结论\n{scoped}\n## 关联章节\n{chapters}"
# target_label ∈ {功能点, 功能}
```

- 参与计算的目标 = 有结论的功能点 + 有结论且无功能点的功能；有功能点的功能不单独算，
  功能级结论并入其下每个点的作用域，因此功能/点不一致会自然暴露为点内冲突。
- **先判证据一致性**：作用域内标签不一致 → 不调模型，直接写 `conflict` 候选；
  一致才调 Mock，模型 `decision` 为准落 `decisions`。Mock 调用数与「证据一致的目标数」相等（AC-89）。
- `scoped` 每条一行：`- [{label_type}] {chapter_title}：{rationale}`，
  **只取该目标（功能点，或无功能点的功能）及其所辖功能的结论**，不带其他功能点 id，不带全量基线；
- 模板 `user_prompt` 之后的第一行固定为 `## 功能点：` 或 `## 功能：`，AC-89 按该锚点断言；
- `chapters` 只带标题与摘要（截断），不带正文全文。

### 3.4 2b-3 传播规则

```
for (from_chapter, to_chapters) in chapter_links:
    strong = {t for t in conclusions_of(from_chapter) if t.label_type in (changed, affected)}
    if not strong: continue
    for to_chapter in to_chapters:
        for target in targets_of(to_chapter):
            if target in strong: continue
            upsert_conflict(target, 'possible_impact',
                            candidates=[{label_type: 'affected', source: f'chapter:{from_chapter}'}])
```

- 传播深度**只做一跳**（本期）；多跳随基准集再定，避免指数级候选。
- `possible_impact` 与 `conflict` 同目标合并时，`conflict` 优先，候选按
  `(label_type, source)` 去重。

## 4. 文件级改动清单

### 后端

| 文件 | 动作 |
|---|---|
| `app/models/chapter_link.py` | 新增 `DocumentChapterLink`；`Core` 检查约束与双唯一键 |
| `app/models/incremental.py` | 追加 `IncrementalDecision` / `IncrementalConflict`，`IncrementalAnalysis` 加第二遍列；同步 `__all__` |
| `app/models/__init__.py` | 注册新模型与 `__all__` |
| `migrations/versions/0014_chapter_links.py` | 建引用图表 |
| `migrations/versions/0015_incremental_second_pass.py` | 建两表、改 analyses、播种第二遍模板 |
| `app/incremental/links.py` | 规则抽取（正则 + 章节序号解析）、补链校验、幂等重抽 |
| `app/incremental/links_router.py` | 引用图三个接口（前缀打到 `/documents/{id}/versions/{vid}/links`） |
| `app/incremental/context2b.py` | 第二遍 Prompt 组装 + 分点作用域 |
| `app/incremental/second_pass.py` | 2b-1 索引、2b-2 按点分治、2b-3 图传播（纯函数，可单测） |
| `app/incremental/schemas.py` | `ChapterLinkOut/Create`、`DecisionOut`、`ConflictOut/Resolve`；`AnalysisOut` 追加第二遍字段 |
| `app/incremental/service.py` | `run_second_pass`、`resolve_conflict`、查询封装；固定校验顺序；审计 |
| `app/incremental/router.py` | 第二遍四个接口 |
| `app/llm/mock.py` | 增加第二遍默认响应（按 `[INCREMENTAL_2B_SYSTEM]` 前缀识别），一期默认响应不变 |
| `app/main.py` | 注册 `links_router` |
| `app/common/errors.py` | 8 个新错误类 + `__all__` |

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/incremental/test_chapter_links.py` | AC-86 / 87 / 95（图部分）/ 96（补链审计） |
| `tests/incremental/test_second_pass_index.py` | AC-89（2b-1 索引形状与作用域） |
| `tests/incremental/test_second_pass_engine.py` | AC-89 / 90 / 91 / 92（Mock 驱动，纯引擎） |
| `tests/incremental/test_second_pass_flow.py` | AC-88 / 93 / 94 / 95 / 96（接口 + 库断言） |
| `tests/incremental/test_second_pass_models.py` | 约束、级联、第二遍模板种子、一期记录 `second_pass_status IS NULL` |
| `tests/common/test_audit_coverage.py` | `SCENARIOS` 补三个 action |
| `tests/e2e/test_incremental_second_pass_ui.py` | 前端：触发第二遍 → 裁决 / 冲突可见 → 确认 / 驳回 |

### 前端

| 文件 | 动作 |
|---|---|
| `web/src/api/index.ts` | 05 分节追加第二期类型与 7 个函数（links 3 + second-pass 4） |
| `web/src/api/client.ts` | 8 个新错误码中文映射 |
| `web/src/pages/ProjectIncrementalDrawer.tsx` | 第二遍区块：状态、触发按钮（admin）、裁决表、冲突队列、裁决弹窗 |
| `web/src/pages/ProjectDocumentsTab.tsx` | 版本行「引用图」入口（抽屉：列表 + 管理员补链） |
| `web/src/pages/ProjectIncrementalTab.tsx` | 列表统计列追加第二遍状态（可选，不新增列count） |

## 5. 测试策略

- **纯引擎优先**：`second_pass.py` 不碰 Session 之外的 IO，用真实 Session + `MockProvider.queue` 驱动；
  AC-89 直接断言 `provider.calls[-1].user` 的作用域。
- **接口层**：复用一期 `tests/incremental/helpers.py` 的造数（项目 / 快照 / 文档版本 / 分析）。
- **离线**：所有用例不配 provider、不发网络；`provider='mock'` 进入 stats。
- **e2e 造数**：第二遍触发走真实接口（`MockProvider` 第二遍默认返回 `unchanged`，
  可产出裁决）；需要冲突 / 新增展示时由 `support.seed_second_pass_rows` 按真实表结构补写，
  裁决动作仍走真实 `resolve` 接口。引用图由 `support.seed_chapter_links` 补写，
  「补链」交互走真实接口。
- **计数**：后端基线 516，预计新增 25–30 条；e2e 31 → 33 左右。

## 6. 前端交互

### 6.1 分析详情抽屉（在 6.x 现有抽屉内追加）

- 「第二遍」区块：
  - 未跑：状态「未执行」+「触发第二遍」按钮（仅 admin，且第一遍 `succeeded`）；
  - running / succeeded / failed：状态 Tag + 统计（点数 / 裁决数 / 新增 / 冲突 / 传播）；
  - failed：红条展示 `second_pass_error_message`。
- 裁决表 `data-testid="incremental-decision-table"`：目标、裁决、置信度、依据。
- 冲突表 `data-testid="incremental-conflict-table"`：目标、类型、候选、状态、操作（确认 / 驳回）。
- 确认弹窗：选择标签（变更 / 受影响 / 未变更）+ 提交；驳回需二次确认。
- 冲突存在时，触发按钮禁用并提示「请先完成本轮冲突裁决」。

### 6.2 文档版本引用图（`ProjectDocumentsTab`）

- 版本行新增「引用图」按钮 `data-testid="chapter-link-btn-{versionId}"`；
- 抽屉内只读列表：源章节、类型、目标（章节标题或实体名）、来源；
- 管理员可补链：源章节 / 类型 / 目标二选一，提交后刷新；重复 / 非法错误走统一错误映射。

## 7. 迁移与回滚

- `0014`：只建表，`downgrade` 直接删表（与一期一致，不先删索引）。
- `0015`：先建两表 → `add_column` 扩展 analyses → 播种模板；
  `downgrade`：删模板行 → 逐个 `drop_column` → 反序删两表。
- 老数据兼容：一期分析记录 `second_pass_status IS NULL`，前端显示「未执行」；接口返回 `null`。
- 迁移可重复执行验证：`upgrade → downgrade → upgrade`。

## 8. 验证命令

```powershell
# 定向
.\.venv\Scripts\python.exe -m pytest -q -k "ac_86 or ac_87 or ac_88 or ac_89 or ac_90 or ac_91 or ac_92 or ac_93 or ac_94 or ac_95 or ac_96 or ac_97"
# 全量（串行；排查偶发失败时不要加 -n）
.\.venv\Scripts\python.exe -m pytest
# 前台
.\.venv\Scripts\python.exe scripts\run_e2e.py -k second_pass
# 构建
cd web; npm run build
```

## 9. 主要风险

| 风险 | 应对 |
|---|---|
| 引用规则误抽（「见第 1 章」指向自身 / 不存在的章节） | 抽取时丢弃 `from == to` 与解析不到的序号；补链接口同样校验 |
| 冲突候选重复累积 | 服务层按 `(target_type,target_id,label_type,source)` 去重；合并规则写在 `second_pass.py` 单测里 |
| 第二遍重跑冲掉已裁决结果 | 有 `pending` 时直接 409；`confirmed/rejected` 允许重跑后被替换，接口文档写明 |
| 前端抽屉继续膨胀 | 第二遍区块抽 `IncrementalSecondPass.tsx`；抽屉主文件控制 400 行内 |
| 一期兼容 | `AnalysisOut` 只追加字段；一期 e2e 断言不受影响（新增列不出现在旧按钮区域） |
