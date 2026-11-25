# 12 · 章节引用图 AI 分析 · 规格

> 对齐需求：用户实测反馈「文档 → 版本 → 引用图」体验极差——纯手工填源/类型/目标，
> 且没有 AI 分析入口，只有「按规则重抽」。
> 上游依赖：05-incremental（`document_chapter_links` 表、`/links` 路由前缀、规则抽取）、
> 06-real-llm（`LLMProvider` / `get_provider` / `parse_llm_json` / `MockProvider` 前缀分支）、
> 10-process-baseline（「纯函数引擎 + 服务层编排 + 带 id 清单防模型编造」范式）。
> 本期口径（用户 2026-11-25 拍板）：
> - **不新建表**，复用 `document_chapter_links`，用 `source` 字段区分来源（新增 `'ai'`）；
> - **分块映射法**调模型：全篇 ≤ 30000 字走整篇单次调用，超过则走两阶段（并发分块摘要 → 全局目录比对）；
> - **一并补齐删除能力**（提示语承诺「可删除」，必须能删）。
> 本文是待 review 的规格，未写任何业务代码。评审通过后才拆任务落地。

## 0. 一句话结论（先看这个）

| 问题 | 结论 |
|---|---|
| 本期做什么 | 把「文档 → 版本 → 引用图」从「纯手工 + 正则重抽」升级为「AI 一键分析 + 人工可改可删可补」 |
| 数据落哪 | **复用 `document_chapter_links`**，**不新建表**；`source` 新增 `'ai'`（与 `'rule'` / `'manual'` 并列），迁移 `0026` |
| AI 怎么调 | 真实大模型（复用 `get_provider`）；全篇 ≤ 30000 字**整篇一次调用**，超过则**两阶段**（并发分块提取摘要/实体 → 全局目录比对） |
| Prompt 从哪来 | **入库可编辑**（`prompt_templates.task_type='chapter_link_analyze'`），不硬编码 |
| AI 结果怎么落库 | `POST .../links/analyze`：先删 `source='ai'` 旧行再插新行（幂等），人工边与规则边**不受影响** |
| 越界 id 怎么办 | **越界即丢**（模型编造的 `from/to_chapter_id` 一律丢弃，不静默写脏数据） |
| 删除能力 | 新增 `DELETE .../links/{link_id}` → 204；三种来源的边**都可删**，删 `rule` 边时前端提示「重抽会重新生成」 |
| 前端 | 抽屉右上角【✨ AI 一键分析引用】按钮 + 手工表单引导文案 + 顶部浅色提示 + 表格删除按钮 |

---

## 1. 背景与目标

05 期第二期（T71）落地了「章节引用图」的最小闭环：规则抽取（正则认「见第 2 章」）+
人工补链 + 列表。但用户实测后反馈体验极差，两个根因：

1. **纯手工**：补链表单只有「源章节 / 类型 / 目标章节」三个裸下拉，没有任何业务说明，
   用户不知道「类型」填什么、「实体名」是什么格式。
2. **没有 AI 入口**：原计划是「AI 自动分析文档生成引用关系，人工审核」，
   但落地时只有「按规则重抽」——而规则抽取只能认**显式带序号**的引用
   （「见第 2 章」），文档里「参考登录流程」「本节依赖上一节」一律识别不到。

本期目标：

- 接入**真实大模型**，一键分析章节间的引用关系，落库为 `source='ai'` 的边；
- 保留**手工补链**与**按规则重抽**，三种来源（`ai` / `manual` / `rule`）**互不覆盖**；
- 补齐**删除**能力，让「AI 结果错了能删」成为现实；
- 优化手工表单的**引导文案**与抽屉顶部的**浅色提示语**。

## 2. 范围

### 2.1 本期做

| 能力 | 说明 |
|---|---|
| AI 分析引用 | `POST .../links/analyze`：真实 LLM 分析章节，落库 `source='ai'` 的边 |
| 分块映射 | 全篇 ≤ 30000 字整篇一次调用；超过走两阶段（并发分块 → 全局比对） |
| 删除引用边 | `DELETE .../links/{link_id}` → 204，含审计 |
| 手工补链引导 | 源/目标章节 placeholder、类型选项说明、实体名格式示例 |
| 抽屉头部 | 右上角【✨ AI 一键分析引用】按钮（含 loading）+ 顶部浅色提示语 |
| 来源展示 | 表格「来源」列区分 规则 / 人工 / AI（新增 `ai` 显示为「AI」） |
| 章节下拉缩进 | 章节下拉按层级全角空格缩进（对齐 `ProjectTestPointsTab`） |
| 审计 + 留痕 | AI 分析写 `document.chapter_link.analyze` 审计 + `llm_run_logs` 留痕；删除写审计 |

### 2.2 本期不做（红线，违反即返工）

| 不做 | 为什么 |
|---|---|
| **不新建 `document_chapter_references` 表** | 用户拍板复用现有表；拆两张表意味着规则/人工/AI 三套逻辑维护两份，数据割裂 |
| **AI 不产出实体边（`entity`）** | 实体名无 id 可校验，越界无法判定；实体边仍由人工补链负责 |
| **不改 `source='rule'` 的命名** | `'rule'` 语义已等价正则抽取，改它会破坏 05 期既有数据与断言；只**新增** `'ai'` |
| **不内置兜底 Prompt** | 模板入库可编辑；模板缺失明确报错（`TEMPLATE_NOT_FOUND`），不静默降级 |
| **不做引用图的过滤 UI** | 后端 `list_links` 已支持 `link_type` / `source` 过滤，但前端本期不暴露（非用户诉求） |
| **不做实体边的编辑** | 实体边只「补」与「删」，不做改（改=删旧补新，用户诉求里没有） |
| **不改 05 的规则抽取判定逻辑** | `extract_links` / `_collect` / 正则**一个字节不动** |
| **不改既有测试的期望值** | 既有 1444 条 pytest + 64 条 e2e 一条不删、不改断言 |
| **不引入任何新前端依赖** | `web/package.json` 不动 |

### 2.3 与上游的兼容约束

1. **`source` 三种来源各自独立重算**：AI 分析只重算 `source='ai'`，
   规则重抽只重算 `source='rule'`，互不覆盖；人工边永远不受任何重算影响。
2. **上游 schema 改动仅两处**：① `document_chapter_links.source` 的 CHECK 扩 `'ai'`；
   ② `prompt_templates.task_type` + `llm_run_logs.task_type` 的 CHECK 扩 `'chapter_link_analyze'`。
   `app/llm/mock.py` 加一个前缀分支（既有六个分支行为一个字节不变）。
3. **零真实 socket**：本期不引入任何网络客户端。AI 分析只调注入的 `LLMProvider`，
   测试用 `MockProvider`；其余全是本地文件与数据库操作。
4. **模板输出契约独立**：`chapter_link_analyze` 的根结构是 `{"references": [...]}`，
   与 `incremental`（`{"conclusions"}`）、`process_baseline`（`{"scenarios"}`）互不解析。

---

## 3. 业务语义裁决

### 3.1 不新建表，复用 `document_chapter_links`

用户原话「绝对不要新建表，复用现有表，用 source 字段区分来源」。落地为
`CHAPTER_LINK_SOURCES = ("rule", "manual", "ai")`。三种来源并列，唯一键
（`uk_chlinks_to_chapter` / `uk_chlinks_entity`）继续兜底「同源同类型同目标只留一条」。

### 3.2 AI 分析只产出「章节 → 章节」边

AI 分析的输出契约里 `from_chapter_id` / `to_chapter_id` 都必须来自「章节清单」
（带 id），服务端按 `chapter_ids` 校验，越界即丢。**实体边不产出**——实体名没有
id 可校验，越界无法判定。实体边仍由人工补链负责（前端「实体名」输入框保留）。

### 3.3 分块映射法（用户拍板的口径）

```
总正文字符数 = sum(len(chapter.content))
├── ≤ 30000 字  → 【整篇一次调用】
└── > 30000 字  → 【两阶段】
      阶段一（并发）：按每 20 章一块切分 → max_workers=4 并发调模型
                     → 每块产出 [{chapter_id, title, summary, entities[]}]
      阶段二（全局比对）：Prompt = 模板 + 全局章节目录清单
                        （每章一行：id + 标题 + 摘要 + 实体）
                     → 一次 LLM 调用，产出引用边
```

阈值 30000 字、块大小 20 章、并发 4 是**模块常量**，便于调。两条路径共用一套
输出契约 `{"references": [...]}`。

### 3.4 越界即丢，不静默写脏数据

模型返回的每条边逐条校验：`from/to_chapter_id` 不在 `chapter_ids` 内 → 丢弃；
`from == to`（自引用）→ 丢弃；`link_type` 不在枚举内 → 丢弃；`confidence` 收敛到
`[0,1]` 并转 `Decimal("0.00")`。**坏条目只丢该条，不整次失败**（与 10 期「坏候选只丢该候选」同一哲学）。

### 3.5 落库幂等

AI 分析落库照抄 `extract_links` 的口径：先删 `(version_id, source='ai')` 旧行 → 再插新行。
**AI 边命中人工边同一条（同源+同类型+同目标）时跳过**，避免撞 `uk_chlinks_to_chapter`
唯一键（05 期 `extract_links` 已踩过、已有 `manual_keys` 去重先例）。

### 3.6 删除语义：三种来源都可删

| 删谁 | 允许 | 前端提示 |
|---|---|---|
| `source='ai'` | ✅ | 无特殊提示 |
| `source='manual'` | ✅ | 无特殊提示 |
| `source='rule'` | ✅ | 「删除后再次「按规则重抽」会重新生成这条关系」 |

不限制删 `rule` 边——用户诉求是「可以修改或删除错误结果」，规则边也是「结果」。
限制它会让提示语变成半真。

### 3.7 「没有引用关系」不是错误

模型返回 `{"references": []}` → 写 0 行，`analyzed_count=0`，**不抛异常**。
与「返回了但全被丢弃」区分：后者 `discarded_count > 0`，响应里体现。

---

## 4. 数据模型（复用 `document_chapter_links`，迁移 `0026`）

### 4.1 `document_chapter_links` 的 `source` 扩枚举

现有列、索引、唯一键**一个不动**，只扩 `ck_chlinks_source`：

```
CHECK (source IN ('rule','manual'))  →  CHECK (source IN ('rule','manual','ai'))
```

ORM 侧同步改 `app/models/chapter_link.py` 的 `CHAPTER_LINK_SOURCES` 与 `ck_chlinks_source`。

### 4.2 `prompt_templates` / `llm_run_logs` 的 `task_type` 扩枚举

`prompt_templates.task_type` 扩 `'chapter_link_analyze'`，播种一条模板；
`llm_run_logs.task_type` 扩 `'chapter_link_analyze'`（AI 分析写留痕）。

ORM 侧同步改 `app/models/incremental.py`（`TASK_TYPES` + `ck_ptemplates_task_type`）
与 `app/models/llm.py`（`RUN_LOG_TASK_TYPES` + `ck_llmlogs_task_type`）。

### 4.3 迁移 `0026`

`revision="0026"`、`down_revision="0025"`。四条顺序约束（都是踩过坑的）：
1. 先扩 `ck_chlinks_source`；
2. 先扩 `ck_ptemplates_task_type` 再播种模板（反了插行被旧 CHECK 拒 3819）；
3. 先扩 `ck_llmlogs_task_type` 再写留痕；
4. downgrade 先删 `source='ai'` 边、`chapter_link_analyze` 模板行与留痕行，再重建旧 CHECK。

---

## 5. 业务语义

### 5.1 AI 分析流程

```
POST .../links/analyze
  1. ensure_writable_admin（404 → 409 → 403 固定顺序）
  2. _load_version（文档/版本不存在 → 404）
  3. 取模板：task_type='chapter_link_analyze' + status='active'（没有 → 400 TEMPLATE_NOT_FOUND）
  4. documents_service.list_chapters(...) 取章节树（含 content）
  5. 调引擎 analyze(...)（纯函数，无 session）
  6. 落库：删 source='ai' 旧行 → 插新行（跳过与人工边冲突的）
  7. write_audit("document.chapter_link.analyze")
  8. 写 llm_run_logs 留痕（task_type='chapter_link_analyze'）
  9. commit
```

### 5.2 删除流程

```
DELETE .../links/{link_id}
  1. ensure_writable_admin
  2. 查边：id == link_id AND version_id == version_id（校验归属，防跨版本删）
  3. session.delete + flush
  4. write_audit("document.chapter_link.delete")
  5. commit
```

边不存在 / 不属于该版本 → 404 `CHAPTER_LINK_NOT_FOUND`。

### 5.3 权限矩阵

| 操作 | 项目管理员 | 普通成员 | 访客 | 系统管理员 |
|---|---|---|---|---|
| 查看引用图（GET /links） | ✅ | ✅ | ✅ | ✅ |
| 手工补链（POST /links） | ✅ | ❌ | ❌ | ✅ |
| 按规则重抽（POST /links/extract） | ✅ | ❌ | ❌ | ✅ |
| AI 分析（POST /links/analyze） | ✅ | ❌ | ❌ | ✅ |
| 删除边（DELETE /links/{id}） | ✅ | ❌ | ❌ | ✅ |

> 权限口径修正（既有坑）：前端 `ProjectDocumentsTab` 的 `canWrite` 含普通 member
> （`canManage || role === 'member'`），但后端 `ensure_writable_admin` 只认 `project_admin`。
> 本期把引用图抽屉的写权限**单独收紧为 `canManage`**，不复用 `canWrite`。

---

## 6. 接口

### 6.1 `POST /links/analyze`（AI 分析）

请求：无 body。响应 `200 ChapterLinkAnalyzeOut`：

```json
{
  "links": [ ...ChapterLinkOut... ],
  "analyzed_count": 12,
  "discarded_count": 3,
  "chapter_count": 29,
  "provider": "openai_compat",
  "mode": "full" | "chunked"
}
```

**为什么不是裸 list**：前端要显示「分析了 29 章，发现 12 条，丢弃 3 条越界」，
且要区分「模型没返回」与「返回了但全被丢弃」。裸 list 表达不了；`mode` 让用户知道走的整篇还是分块。

### 6.2 `DELETE /links/{link_id}`（删除边）

响应 `204 No Content`。

### 6.3 错误码（新增 3 个）

| 错误类 | HTTP | code |
|---|---|---|
| `ChapterLinkNotFound` | 404 | `CHAPTER_LINK_NOT_FOUND` |
| `ChapterLinkAnalyzeFailed` | 502 | `CHAPTER_LINK_ANALYZE_FAILED` |
| `ChapterLinkAnalyzeEmpty` | 400 | `CHAPTER_LINK_ANALYZE_EMPTY` |

### 6.4 审计

| 操作 | action | target_type |
|---|---|---|
| AI 分析 | `document.chapter_link.analyze` | `document_chapter_link` |
| 删除边 | `document.chapter_link.delete` | `document_chapter_link` |

---

## 7. 前端

### 7.1 抽屉头部

- `Drawer` 的 `extra` 放右上角【✨ AI 一键分析引用】按钮（`type="primary"`，`loading={analyzing}`）；
- `title` 下方加 `Alert type="info"` 浅色提示语：
  「系统已通过 AI 自动识别章节间的引用关系，您可以修改或删除错误结果，也可以手动补充。」

### 7.2 手工表单引导

| 项 | 现状 | 改为 |
|---|---|---|
| 源章节 | placeholder「选择源章节」 | 「请选择源章节」+ `showSearch` |
| 类型 | 无说明 | 三项带说明：引用 —— A 提到「见 B」/ 依赖 —— A 实现依赖 B / 相关 —— A 提到功能点或术语 |
| 目标章节 | placeholder「选择目标章节」 | 「请选择目标章节」+ `showSearch` |
| 实体名 | placeholder「功能点或术语名」 | 「格式：功能:用户登录，如 功能:退款审核 / 术语:订单锁定」 |

### 7.3 表格

- 来源列改为 `linkSourceTag()`：规则(default) / 人工(green) / AI(cyan)。
- 新增「操作」列删除按钮（`Popconfirm` 二次确认；删 `rule` 边时 description 提示「重抽会重新生成」）。
- 章节下拉全角空格层级缩进（对齐 `ProjectTestPointsTab`）。

### 7.4 `data-testid` 命名（沿用「区域-动作-目标」，统一前缀 `chapter-link-`）

`chapter-link-ai-analyze-btn` / `chapter-link-ai-hint` / `chapter-link-analyzing-tip` /
`chapter-link-delete-btn-{id}` / 既有 `chapter-link-*-select` / `-input` / `-btn` 不动。

---

## 8. 验收标准

### AC-220 AI 一键分析入口与 loading

抽屉右上角有【✨ AI 一键分析引用】按钮；点击后按钮进入 loading 态，完成或失败后恢复。
（e2e：按钮可见、可点、点击后有 `loading` 态）

### AC-221 抽屉顶部浅色提示语

抽屉顶部展示浅色提示语「系统已通过 AI 自动识别章节间的引用关系，您可以修改或删除错误结果，也可以手动补充。」（`Alert type="info"`）

### AC-222 手工表单引导文案

「源章节」「目标章节」placeholder 为「请选择…」；「类型」下拉展开后有三项带说明（引用/依赖/相关）。

### AC-223 实体名格式提示

「实体名」输入框 placeholder 含格式示例「功能:用户登录」。

### AC-224 AI 边来源展示为「AI」

AI 分析后，表格「来源」列显示「AI」标签（**不是「人工」**），`source='ai'` 的边置信度可见。

### AC-225 删除能力

点删除 → `Popconfirm` 二次确认 → 边消失；删 `rule` 边时确认框提示「重抽会重新生成」；删不存在的边 → 404 `CHAPTER_LINK_NOT_FOUND`。

### AC-226 AI 分析不破坏人工边与规则边

分析前已有 `manual` / `rule` 边，分析后二者仍存在；AI 边命中人工同一条时跳过（不撞唯一键）。

### AC-227 权限矩阵

非项目管理员（普通成员 / 访客）看不到 AI 按钮与删除按钮；后端 `analyze` / `delete` 对非管理员返回 403 `NOT_PROJECT_ADMIN`；归档项目返回 409 `PROJECT_ARCHIVED`。

### AC-228 零回归与红线

既有 1444 条 pytest + 64 条 e2e 全绿；`document_chapter_links` 表结构零改动（仅 CHECK 扩枚举）；`extract_links` / `create_link` / `list_links` 行为不变；`app/llm/mock.py` 既有六个前缀分支行为一个字节不变。

---

## 9. 非功能

- **性能**：整篇单次调用 1 次模型请求；大文档两阶段并发（max_workers=4），前端提示「可能需要 1–2 分钟…」。
- **幂等**：AI 分析重复调用，`source='ai'` 行数不累加。
- **可追溯**：AI 分析写审计 + `llm_run_logs` 留痕（provider / model / call_count / 状态 / 错误）。
- **零真实 socket**：测试不产生任何网络请求（`MockProvider` + `httpx.MockTransport`）。

---

## 10. 依赖与影响

### 上游 schema 改动声明（本期仅三处）

| 位置 | 改动 | 为什么 |
|---|---|---|
| `app/models/chapter_link.py` | `CHAPTER_LINK_SOURCES` 加 `'ai'` + CHECK 扩枚举 | 承载 AI 边 |
| `app/models/incremental.py` | `TASK_TYPES` + `ck_ptemplates_task_type` 加 `'chapter_link_analyze'` | 独立 task_type，根结构 `{"references"}` 不复用任何现有类型 |
| `app/models/llm.py` | `RUN_LOG_TASK_TYPES` + `ck_llmlogs_task_type` 加 `'chapter_link_analyze'` | AI 分析写留痕 |
| `app/llm/mock.py` | 加 `CHAPTER_LINK_SYSTEM_PREFIX` 分支 | 否则 Mock 落到兜底 `{"conclusions":[]}` 根结构校验失败 |

---

## 11. 风险与规避

| 风险 | 影响 | 规避 |
|---|---|---|
| 模型编造 chapter_id | 脏数据落库 | Prompt 必给带 id 的章节清单 + 服务层按 `chapter_ids` 校验 + 越界即丢 |
| 大文档耗时过长 | 前端长时间转圈 | 两阶段并发 + 前端提示 + `mode` 回传 |
| 0026 迁移往返撞 3819 | 迁移失败 | downgrade 先删 `source='ai'` 边、模板行、留痕行再重建旧 CHECK |
| Mock 落到兜底响应 | 测试全红 | `mock.py` 加前缀分支；`git diff --stat` 实测既有分支零改动 |
| `source='ai'` 显示成「人工」 | 误导用户 | `linkSourceTag()` 映射表；表格来源列必改 |
| `canWrite` 口径差 | 普通 member 点按钮吃 403 | 引用图写权限改用 `canManage` |
| e2e 残留 `llm_run_logs` | 迁移往返失败 | 清理清单加 `llm_run_logs` |
| 并发下 `MockProvider.calls` 竞态 | 断言不稳定 | 只断言 `len(calls)` 与内容，不断言 `raw["index"]` |

---

## 12. 后续期（明确不在本期）

| 能力 | 说明 |
|---|---|
| 引用图可视化（图而非表格） | 当前是表格展示，真正的「图」（力导向图）留待后续 |
| AI 产出实体边 | 需要先解决「实体名的规范与校验」问题 |
| 引用边置信度阈值筛选 | 前端暴露 `link_type` / `source` / `confidence` 过滤 |
| 批量审核 AI 边（勾选采纳而非直接落库） | 当前直接落库 + 可删；「候选待确认」两段式留待后续 |
