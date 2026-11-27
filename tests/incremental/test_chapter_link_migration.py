"""迁移 `0026` 的数据库层断言（12-chapter-link-ai T129 / AC-224）。

覆盖：`document_chapter_links.source` 的 CHECK 真的扩了 `'ai'`（不是只写在 ORM
元数据里）；迁移 head。

`0026 → 0025 → 0026` 的往返不在这里跑——迁移在独立事务里执行，与 `db` 夹具的
嵌套事务会互相干扰；往返由 T129 的验证命令在两库上实跑。
"""

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.common.db import get_engine
from app.models.incremental import PromptTemplate


@pytest.fixture(scope="module")
def engine() -> Engine:
    """只读用的引擎：结构断言不写入，也不吃 `db` 夹具的事务。"""
    return get_engine()


def test_ac_224_source_check_extended(engine: Engine):
    """`ck_chlinks_source` 的 CHECK 扩了 `'ai'`（真的落到库里）。"""
    checks = {
        item["name"]: str(item["sqltext"]).lower()
        for item in inspect(engine).get_check_constraints("document_chapter_links")
    }
    assert "ck_chlinks_source" in checks
    assert "'ai'" in checks["ck_chlinks_source"]


def test_ac_224_source_check_keeps_rule_and_manual(engine: Engine):
    """扩枚举不是重写：`'rule'` / `'manual'` 仍在 CHECK 里。"""
    checks = {
        item["name"]: str(item["sqltext"]).lower()
        for item in inspect(engine).get_check_constraints("document_chapter_links")
    }
    sqltext = checks["ck_chlinks_source"]
    assert "'rule'" in sqltext
    assert "'manual'" in sqltext


def test_migration_head_is_0028(db: Session):
    """迁移 head 是 `0028`（0026 数据层 + 0027 模板层 + 0028 评审状态层）。"""
    row = db.execute(text("SELECT version_num FROM alembic_version")).first()
    assert row is not None
    assert row[0] == "0028"


def test_chapter_links_table_has_two_new_columns(engine: Engine):
    """12.5 期加两列：`status`（待评审/已生效）与 `rationale`（分析理由）。"""
    columns = {item["name"] for item in inspect(engine).get_columns("document_chapter_links")}
    assert columns == {
        "id",
        "version_id",
        "from_chapter_id",
        "to_chapter_id",
        "link_type",
        "entity",
        "confidence",
        "source",
        "created_by",
        "created_at",
        "status",
        "rationale",
    }


def test_ac_224_prompt_template_task_type_check_extended(engine: Engine):
    """`prompt_templates.task_type` 的 CHECK 扩了 `'chapter_link_analyze'`。"""
    checks = {
        item["name"]: str(item["sqltext"]).lower()
        for item in inspect(engine).get_check_constraints("prompt_templates")
    }
    assert "ck_ptemplates_task_type" in checks
    assert "'chapter_link_analyze'" in checks["ck_ptemplates_task_type"]
    # 既有五值不能被挤掉
    for value in (
        "document_parse",
        "incremental",
        "test_point",
        "test_case",
        "process_baseline",
    ):
        assert f"'{value}'" in checks["ck_ptemplates_task_type"]


def test_ac_224_llm_run_log_task_type_check_extended(engine: Engine):
    """`llm_run_logs.task_type` 的 CHECK 扩了 `'chapter_link_analyze'`。

    AI 分析写运行留痕——没有留痕就无法排查「上次那次分析为什么失败」。
    """
    checks = {
        item["name"]: str(item["sqltext"]).lower()
        for item in inspect(engine).get_check_constraints("llm_run_logs")
    }
    assert "ck_llmlogs_task_type" in checks
    assert "'chapter_link_analyze'" in checks["ck_llmlogs_task_type"]


def test_ac_224_seed_template_is_unique_and_active(db: Session):
    """播种的引用图分析模板**有且只有一条**，且是 active。"""
    rows = list(
        db.scalars(
            select(PromptTemplate).where(
                PromptTemplate.task_type == "chapter_link_analyze"
            )
        ).all()
    )

    assert len(rows) == 1
    assert rows[0].status == "active"
    assert rows[0].version_no == 1


def test_ac_224_seed_template_prefix_is_mockable(db: Session):
    """模板的 system 前缀可被 Mock 识别（分流靠前缀）。"""
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "chapter_link_analyze"
        )
    )

    assert template is not None
    assert template.system_prompt.startswith("[CHAPTER_LINK_ANALYZE_SYSTEM]")


def test_ac_224_seed_template_declares_references_contract(db: Session):
    """模板写清了输出契约：**引用列表**，且章节 id 只能取自清单。

    两条都是踩过坑的：① 根结构错一个字母，服务端解析直接失败；
    ② 不告诉模型 id 从哪来，它会自己编（06 期 L2 联调翻车的根因）。
    """
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "chapter_link_analyze"
        )
    )

    assert '"references"' in template.system_prompt
    # 别的根结构不能出现——引用分析的契约是独立的
    assert '"conclusions"' not in template.system_prompt
    assert '"scenarios"' not in template.system_prompt
    # 必须说明章节 id 只能取自清单
    assert "章节清单" in template.system_prompt
    assert "from_chapter_id" in template.system_prompt
    assert "to_chapter_id" in template.system_prompt
