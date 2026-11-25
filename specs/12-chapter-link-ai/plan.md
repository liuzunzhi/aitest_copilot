# 12 · 章节引用图 AI 分析 · 技术方案

> 配套 [spec.md](./spec.md)（AC-220 ~ AC-228）与 [tasks.md](./tasks.md)（T129 ~ T136）。
> 定位：**补丁任务**——在 05 期「章节引用图」上接入真实大模型 + 补齐删除能力 +
> 优化手工表单引导。复用现有表与 LLM 基础设施，不重写。

## 1. 总体思路

```
ChapterLinkDrawer（前端抽屉）
      │  POST /links/analyze            DELETE /links/{id}
      ▼
links_router.analyze_links             links_router.delete_link
      │
      ▼
links.analyze_links（服务层编排：权限 → 模板 → 章节 → 引擎 → 落库 → 审计 → 留痕）
      │
      ▼
link_analyze.analyze（纯函数引擎，签名里没有 session）
      ├─ 整篇 ≤ 30000 字 → 一次调用
      └─ > 30000 字 → 两阶段（并发分块摘要 → 全局目录比对）
```

四条关键设计：

1. **不新建表** —— 复用 `document_chapter_links`，`source` 扩 `'ai'`，
   三种来源（`ai` / `manual` / `rule`）各自独立重算、互不覆盖。
2. **引擎是纯函数** —— `analyze()` 签名里**没有 `session`**，
   「引擎不碰数据库」从「靠自觉」变成「结构上做不到」（对齐 10 期 `derive.py`）。
3. **越界即丢** —— Prompt 必给带 id 的章节清单，服务层按 `chapter_ids` 校验，
   模型编造的 id 一律丢弃（06 期 L2 联调翻车的教训）。
4. **分块映射法** —— 整篇一次调用有 token 上限，大文档走「并发分块摘要 → 全局比对」，
   既控 token 又不丢跨章上下文。

## 2. 目录与文件

```
app/incremental/
├── link_analyze.py      # AI 分析引擎（纯函数，无 session）—— 新增
├── links.py             # 服务层：+ analyze_links() / delete_link()
├── links_router.py      # 路由：+ POST /analyze、DELETE /{link_id}
└── schemas.py           # + ChapterLinkAnalyzeOut

app/models/chapter_link.py             # CHAPTER_LINK_SOURCES 加 'ai'
app/models/incremental.py              # TASK_TYPES 加 'chapter_link_analyze'
app/models/llm.py                      # RUN_LOG_TASK_TYPES 加 'chapter_link_analyze'
app/common/errors.py                   # + 3 个错误类
migrations/versions/0026_chapter_link_ai.py   # 扩 3 个 CHECK + 播种模板
app/llm/mock.py                        # + CHAPTER_LINK_SYSTEM_PREFIX 分支

web/src/api/index.ts                   # + analyzeChapterLinks / deleteChapterLink
web/src/api/client.ts                  # CODE_TEXT + 3 个错误码
web/src/pages/ChapterLinkDrawer.tsx    # 抽屉重构
web/src/pages/incrementalMeta.tsx      # + LINK_SOURCE_META / linkSourceTag
web/src/pages/settings/PromptTemplatePanel.tsx  # + TASK_TYPE_LABELS
web/src/pages/ProjectDocumentsTab.tsx  # 引用图写权限改用 canManage
web/src/pages/ProjectDetailPage.tsx    # 传 canManage 给 ProjectDocumentsTab

tests/incremental/…  tests/e2e/…  specs/验证约定.md  PROGRESS.md
```

## 3. 数据层

### 3.1 迁移 `0026`

三个 CHECK 各扩一个枚举值 + 播种一条模板，**downgrade 成对**：

```python
revision = "0026"; down_revision = "0025"

def upgrade():
    # 1) ck_chlinks_source: ('rule','manual') → ('rule','manual','ai')
    # 2) ck_ptemplates_task_type: 加 'chapter_link_analyze'
    # 3) ck_llmlogs_task_type: 加 'chapter_link_analyze'
    # 4) 播种「章节引用图·AI 引用分析」模板

def downgrade():
    # 反序：先删模板行 / 留痕行 / source='ai' 边，再重建三个旧 CHECK
```

### 3.2 播种的 Prompt 模板

`task_type='chapter_link_analyze'`，system 前缀 `[CHAPTER_LINK_ANALYZE_SYSTEM]`。
system prompt 必须写死三条（都是踩过坑的）：① `link_type` 只能三值；②
`from/to_chapter_id` 只能取自「章节清单」；③ 只输出 JSON。输出契约：

```json
{"references":[{"from_chapter_id":1,"to_chapter_id":2,"link_type":"references","confidence":0.85,"rationale":"..."}]}
```

### 3.3 Mock 分支

`app/llm/mock.py` 加 `CHAPTER_LINK_SYSTEM_PREFIX = "[CHAPTER_LINK_ANALYZE_SYSTEM]"`，
默认响应 `{"references": []}`（**空列表**，不编 id——Mock 不知道真实章节 id，
编了必越界被丢）。既有六个分支一个字节不改。

## 4. 引擎（`app/incremental/link_analyze.py`）

### 4.1 签名

```python
def analyze(
    *,
    provider: LLMProvider,
    template: PromptTemplate,
    document_name: str,
    version_no: int,
    chapters: list[dict],           # 章节树（含 content）
    max_chars: int | None = None,   # 单次 Prompt 字符预算
    full_doc_threshold: int = 30000,
    chunk_size: int = 20,
    max_workers: int = 4,
) -> AnalyzeResult
```

### 4.2 两条路径

```
总正文字符数 = sum(len(chapter.content))
├── ≤ full_doc_threshold  → 整篇一次调用
│     Prompt = 模板 + 文档信息 + 章节清单 + 全文
└── > full_doc_threshold  → 两阶段
      阶段一：按 chunk_size 切块 → ThreadPoolExecutor(max_workers) 并发调模型
              → 每块 [{chapter_id, title, summary, entities[]}]
              → 某块失败只跳过该块；全部失败抛 LLMCallFailed
      阶段二：全局目录清单（每章一行：id + 标题 + 摘要 + 实体）
              → 一次调用产出引用边
```

### 4.3 输出解析 `parse_references(content, *, chapter_ids) -> list[dict]`

- `parse_llm_json` → 根结构 `{"references": [...]}`，否则抛 `LLMOutputInvalid`；
- 逐条校验：越界 id / 自引用 / 非法 link_type → 丢该条；`confidence` 收敛 `[0,1]`
  转 `Decimal("0.00")`；`rationale` 截断 500。

### 4.4 Prompt 组装

四段固定顺序（`template.user_prompt` + `## 文档信息` + `## 章节清单` + `## 章节正文`）。
超长时**只截断正文尾部**，前缀不变（对齐 `context.py:96-103`，保证 Prompt 可复现）。

## 5. 服务层（`app/incremental/links.py`）

### 5.1 `analyze_links()`

编排顺序照抄 `process_baselines/service.py::run_derive`：
权限 → 版本 → 模板 → 章节 → 引擎 → 落库 → 审计 → 留痕 → commit。

落库幂等（照抄 `extract_links`）：先删 `(version_id, source='ai')` → 再插；
AI 边命中人工边同一条时跳过（`manual_keys` 去重）。

### 5.2 `delete_link()`

权限 → 查边（`id == link_id AND version_id == version_id`）→ 删 → 审计 → commit。
边不存在 / 跨版本 → 404 `CHAPTER_LINK_NOT_FOUND`。

## 6. 路由（`app/incremental/links_router.py`）

```python
@router.post("/analyze", response_model=ChapterLinkAnalyzeOut)
def analyze_links(...): ...

@router.delete("/{link_id}", status_code=204)
def delete_link(...): ...
```

## 7. 前端

### 7.1 API 客户端（`web/src/api/index.ts` / `client.ts`）

`ChapterLink.source` 加 `'ai'`；新增 `analyzeChapterLinks()` / `deleteChapterLink()`；
`CODE_TEXT` 补 3 个错误码。

### 7.2 抽屉重构（`web/src/pages/ChapterLinkDrawer.tsx`）

- 头部 `extra` 放【✨ AI 一键分析引用】按钮（`analyzing` loading 独立 state）；
- 顶部 `Alert type="info"` 提示语；
- 手工表单引导文案 + 章节下拉层级缩进；
- 表格来源列 `linkSourceTag()` + 操作列删除按钮；
- `submitting` 拆成 `analyzing` / `extracting` / `submitting` / `deletingId` 四个 state。

### 7.3 权限口径修正

`ProjectDocumentsTab` 新增 `canManage` prop，引用图抽屉写权限用 `canManage`（不再用含 member 的 `canWrite`）。

## 8. 测试

| 层 | 文件 | 覆盖 |
|---|---|---|
| 数据层 | `tests/incremental/test_chapter_link_models.py` | `source='ai'` 可插 / 非法被拒 / `ck_chlinks_target` 二选一 / 迁移 head=0026 / 模板播种 / task_type 扩枚举 |
| 引擎 | `tests/incremental/test_link_analyze.py` / `test_link_analyze_prompt.py` / `test_link_analyze_mock.py` | 解析越界/自引用/非法类型 / Prompt 可复现 / 两条路径 |
| 接口 | `tests/incremental/test_link_analyze_api.py` | 成功 / 幂等 / 人工边不受影响 / 模板缺失 / 越界 / 权限 / 审计 / 留痕 |
| 删除 | `tests/incremental/test_chapter_link_delete.py` | 删除 / 404 / 权限 / 审计 |
| Mock | `tests/llm/test_mock_branch.py` | 新前缀命中 / 既有六分支零改动 |
| e2e | `tests/e2e/test_chapter_link_ai_ui.py` | AC-220~AC-227 前台核对 |

## 9. 验证命令

```powershell
.\.venv\Scripts\python.exe scripts\dev_check.py          # 开跑前自检
.\.venv\Scripts\python.exe -m pytest -m "not e2e"        # 全量（只增不减）
.\.venv\Scripts\python.exe scripts\run_e2e.py            # e2e 全量
cd web; npm run build; npm run lint                      # 前端构建
# 迁移往返（两库都跑）：alembic upgrade head → downgrade -1 → upgrade head
```
