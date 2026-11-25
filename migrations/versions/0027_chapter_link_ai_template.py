"""章节引用图 AI 分析 · 提示词模板与留痕枚举（12-chapter-link-ai T130）

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-25

给「章节引用图的 AI 分析」准备两样东西：

1. `prompt_templates.task_type` 的 CHECK 扩一个 `'chapter_link_analyze'`，
   并播种一条「章节引用图·AI 引用分析」模板。
2. `llm_run_logs.task_type` 的 CHECK 扩一个 `'chapter_link_analyze'`——
   AI 分析**写运行留痕**：真实模型调用耗时长且可能失败，
   没有留痕就无法排查「上次那次分析为什么失败」。

**为什么 `task_type` 必须独立成一个类型**：
引用分析的输出契约是 `{"references": [...]}`，与增量分析的
`{"conclusions": [...]}`、流程基线的 `{"scenarios": [...]}` 根结构都不同。
复用任何一个都会让根结构校验失败，而报错信息完全指不到真因
（与 10 期 `process_baseline` 独立的原因一模一样，见
`app/models/incremental.py` 里 `TASK_TYPES` 的注释）。

**为什么 `llm_run_logs` 也扩**：
04 的文档推导不写留痕（所以 0025 没扩它的 CHECK），但本期**要写**——
AI 分析是同步调用真实模型，可能耗时一两分钟、可能失败，
排查「为什么这次分析没产出」只能靠留痕。

**upgrade / downgrade 的三条顺序约束**（都是踩过坑的）：

1. **先扩 CHECK 再播种模板**：反了的话插入 `task_type='chapter_link_analyze'`
   的行会被旧 CHECK 拒（3819）。见 `0025_process_baselines.py` 的同款说明。
2. **MySQL 不允许直接改 CHECK**，必须先 `drop_constraint` 再
   `create_check_constraint`（08 期在 `llm_run_logs` 上踩过同一件事，
   见 `0023_test_cases.py:279-285`）。
3. **downgrade 必须先删残留行再重建旧 CHECK**：残留的
   `task_type='chapter_link_analyze'` 模板行与留痕行都会让旧 CHECK
   重建失败（3819）。这正是 08 期在 `llm_run_logs` 上踩过的坑
   （`0023_test_cases.py:321-322` 的注释写明了原因）。

**0026 与 0027 为什么分成两个迁移**：
0026 只做 `document_chapter_links.source` 扩 `'ai'`（数据层），
0027 做模板与留痕枚举（提示词层）。一个迁移只做一件事，
两库往返时哪一步出问题一目了然。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `prompt_templates.task_type` 的 CHECK：旧五值 → 新六值。
OLD_TEMPLATE_TASK_TYPES = (
    "document_parse",
    "incremental",
    "test_point",
    "test_case",
    "process_baseline",
)
NEW_TEMPLATE_TASK_TYPES = (*OLD_TEMPLATE_TASK_TYPES, "chapter_link_analyze")

# `llm_run_logs.task_type` 的 CHECK：旧五值 → 新六值。
OLD_RUN_LOG_TASK_TYPES = (
    "incremental_first",
    "incremental_second",
    "provider_test",
    "test_point",
    "test_case",
)
NEW_RUN_LOG_TASK_TYPES = (*OLD_RUN_LOG_TASK_TYPES, "chapter_link_analyze")


def _enum_sql(values: tuple[str, ...]) -> str:
    """把枚举拼成 CHECK 约束的 SQL 字面量片段。"""
    joined = ",".join(f"'{value}'" for value in values)
    return f"IN ({joined})"


TEMPLATE_NAME = "章节引用图·AI 引用分析"
TEMPLATE_DESCRIPTION = "从需求文档章节中识别章节之间的引用 / 依赖关系"

SYSTEM_PROMPT = (
    "[CHAPTER_LINK_ANALYZE_SYSTEM] 你是需求文档章节引用关系分析助手。\n"
    "分析给定的章节内容，找出章节与章节之间的引用关系。\n"
    '只输出 JSON：{"references":[{"from_chapter_id":1,"to_chapter_id":2,'
    '"link_type":"references","confidence":0.0,"rationale":"理由"}]}。\n'
    "规则：\n"
    "1. link_type 只能是 references（引用：A 提到「见 B 章节」）、"
    "depends_on（依赖：A 的实现依赖 B 章节）、"
    "mentions_entity（相关：A 提到某个功能点或术语）三者之一；\n"
    "2. from_chapter_id / to_chapter_id **只能取自「章节清单」里的编号**，"
    "不要臆造编号，也不要输出清单之外的章节；\n"
    "3. 章节不能引用自己；\n"
    "4. 没有任何引用关系时输出 {\"references\": []}；\n"
    "5. confidence 取 0 到 1 之间的小数，表示这条关系的把握程度；\n"
    "6. 只输出 JSON，不要输出 JSON 之外的任何内容。"
)

USER_PROMPT = (
    "请分析下面的章节内容，找出章节之间的引用与依赖关系。\n"
    "章节编号（from_chapter_id / to_chapter_id）只能取自「章节清单」，"
    "不要自己编造编号。"
)


def upgrade() -> None:
    # 1) 扩 `prompt_templates.task_type` 的 CHECK（**必须先扩，再播种**）
    op.drop_constraint("ck_ptemplates_task_type", "prompt_templates", type_="check")
    op.create_check_constraint(
        "ck_ptemplates_task_type",
        "prompt_templates",
        f"task_type {_enum_sql(NEW_TEMPLATE_TASK_TYPES)}",
    )

    # 2) 扩 `llm_run_logs.task_type` 的 CHECK（**必须先扩，再写留痕**）
    op.drop_constraint("ck_llmlogs_task_type", "llm_run_logs", type_="check")
    op.create_check_constraint(
        "ck_llmlogs_task_type",
        "llm_run_logs",
        f"task_type {_enum_sql(NEW_RUN_LOG_TASK_TYPES)}",
    )

    # 3) 播种 AI 分析模板。created_at / updated_at 走 server default，不手写时间。
    op.execute(
        sa.text(
            "INSERT INTO prompt_templates "
            "(name, task_type, description, system_prompt, user_prompt, version_no, status) "
            "VALUES (:name, 'chapter_link_analyze', :description, :system_prompt, "
            ":user_prompt, 1, 'active')"
        ).bindparams(
            name=TEMPLATE_NAME,
            description=TEMPLATE_DESCRIPTION,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
        )
    )


def downgrade() -> None:
    # 1) 删模板行（**必须在重建旧 CHECK 之前**——
    #    残留的 task_type='chapter_link_analyze' 会让旧 CHECK 重建失败（3819））
    op.execute(
        sa.text(
            "DELETE FROM prompt_templates WHERE task_type = 'chapter_link_analyze'"
        )
    )

    # 2) 清留痕行（同上：残留会让旧 CHECK 重建失败）
    op.execute(
        sa.text(
            "DELETE FROM llm_run_logs WHERE task_type = 'chapter_link_analyze'"
        )
    )

    # 3) 恢复两个旧 CHECK
    op.drop_constraint("ck_llmlogs_task_type", "llm_run_logs", type_="check")
    op.create_check_constraint(
        "ck_llmlogs_task_type",
        "llm_run_logs",
        f"task_type {_enum_sql(OLD_RUN_LOG_TASK_TYPES)}",
    )

    op.drop_constraint("ck_ptemplates_task_type", "prompt_templates", type_="check")
    op.create_check_constraint(
        "ck_ptemplates_task_type",
        "prompt_templates",
        f"task_type {_enum_sql(OLD_TEMPLATE_TASK_TYPES)}",
    )
