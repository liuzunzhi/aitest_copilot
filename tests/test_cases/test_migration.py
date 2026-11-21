"""迁移 `0023` 的数据库层断言（08-test-case-analysis T105 / AC-159）。

覆盖三件事：三表及其索引 / CHECK 真的建出来了；`llm_run_logs` 的枚举
扩了 `'test_case'` 但没放开非法值；播种的提示词模板恰好一条且前缀可识别。

`0023 → 0022 → 0023` 的往返不在这里跑——迁移在独立事务里执行，
与 `db` 夹具的嵌套事务会互相干扰；往返由 T105 的验证命令在两库上实跑。
"""

import uuid

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.common.db import get_engine
from app.models.incremental import PromptTemplate
from app.models.llm import LLMRunLog
from app.models.project import Project


@pytest.fixture(scope="module")
def engine() -> Engine:
    """只读用的引擎：结构断言不写入，也不吃 `db` 夹具的事务。"""
    return get_engine()


def test_ac_159_three_tables_exist(engine: Engine):
    """三张表都存在。"""
    names = set(inspect(engine).get_table_names())
    assert {"test_case_analyses", "test_cases", "test_case_steps"} <= names


@pytest.mark.parametrize(
    ("table", "indexes"),
    [
        ("test_case_analyses", {"idx_tcanalyses_project", "idx_tcanalyses_template"}),
        (
            "test_cases",
            {"idx_tcases_project", "idx_tcases_test_point", "idx_tcases_status"},
        ),
        ("test_case_steps", {"idx_tcsteps_case", "uk_tcsteps_case_no"}),
    ],
)
def test_ac_159_indexes_exist(engine: Engine, table: str, indexes: set[str]):
    """索引 / 唯一键与 spec §4 一致（漏建索引会在大项目上直接拖慢列表页）。"""
    names = {item["name"] for item in inspect(engine).get_indexes(table)}
    assert indexes <= names


@pytest.mark.parametrize(
    ("table", "checks"),
    [
        ("test_case_analyses", {"ck_tcanalyses_status"}),
        (
            "test_cases",
            {
                "ck_tcases_case_type",
                "ck_tcases_priority",
                "ck_tcases_status",
                "ck_tcases_source_type",
            },
        ),
        ("test_case_steps", {"ck_tcsteps_no_positive"}),
    ],
)
def test_ac_159_check_constraints_exist(engine: Engine, table: str, checks: set[str]):
    """CHECK 约束真的落到了库里（不是只写在 ORM 元数据里）。"""
    names = {
        item["name"] for item in inspect(engine).get_check_constraints(table)
    }
    assert checks <= names


def test_ac_159_seed_template_is_unique(db: Session):
    """`task_type='test_case'` 的模板有且只有一条 active。"""
    total = db.scalar(
        select(func.count())
        .select_from(PromptTemplate)
        .where(PromptTemplate.task_type == "test_case")
    )
    assert total == 1

    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "test_case")
    )
    assert template.status == "active"


def test_ac_159_seed_template_prefixes_and_no_copyable_ids(db: Session):
    """模板前缀可被 Mock 识别；示例里不出现任何「可照抄的 id」。"""
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "test_case")
    )
    assert template.system_prompt.startswith("[TEST_CASE_SYSTEM]")
    assert template.user_prompt.startswith("[TEST_CASE_USER]")
    # 输出契约里没有测试点 id，模板也就不该出现任何 id 字段
    assert "test_point_id" not in template.system_prompt
    assert "target_id" not in template.system_prompt
    # 批次关联由服务端完成，模板必须说清这一点
    assert "追溯到该测试点" in template.system_prompt


def test_ac_159_run_log_accepts_test_case_task_type(db: Session):
    """留痕表接受 `task_type='test_case'`（0023 扩了 CHECK 枚举）。"""
    project = Project(name=f"留痕项目-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()

    log = LLMRunLog(
        task_type="test_case",
        project_id=project.id,
        provider_name="mock",
        model="mock",
        call_count=1,
        latency_ms=10,
        status="succeeded",
    )
    db.add(log)
    db.flush()

    assert log.id is not None
    assert log.task_type == "test_case"


def test_ac_159_run_log_rejects_unknown_task_type(db: Session):
    """扩枚举不是放开口子：非法 `task_type` 仍被 CHECK 拒绝（3819）。"""
    project = Project(name=f"留痕项目-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()

    log = LLMRunLog(
        task_type="bogus_task",
        project_id=project.id,
        provider_name="mock",
        model="mock",
        call_count=1,
        latency_ms=10,
        status="succeeded",
    )
    db.add(log)
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_llmlogs_task_type" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_159_metadata_uses_mysql_engine():
    """三表都是 InnoDB + utf8mb4（迁移里显式声明，不靠服务器默认值）。"""
    from app.models.test_case import TestCase, TestCaseAnalysis, TestCaseStep

    for model in (TestCaseAnalysis, TestCase, TestCaseStep):
        opts = model.__table__.dialect_kwargs
        assert opts["mysql_engine"] == "InnoDB"
        assert opts["mysql_default_charset"] == "utf8mb4"
