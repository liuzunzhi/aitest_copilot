"""迁移 `0025` 的数据库层断言（10-process-baseline T117 / AC-197）。

覆盖四件事：四表及其索引 / CHECK 真的建出来了；`prompt_templates` 的 CHECK
扩了 `'process_baseline'` 但没放开非法值；播种的模板恰好一条且前缀可被 Mock 识别；
`llm_run_logs` 的 CHECK **没有**被扩（本期反推不写运行留痕）。

`0025 → 0024 → 0025` 的往返不在这里跑——迁移在独立事务里执行，
与 `db` 夹具的嵌套事务会互相干扰；往返由 T117 的验证命令在两库上实跑。
"""

import uuid

import pytest
from sqlalchemy import func, inspect, select, text
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


def test_ac_197_four_tables_exist(engine: Engine):
    """四张表都存在。"""
    names = set(inspect(engine).get_table_names())
    assert {
        "process_baselines",
        "process_baseline_steps",
        "process_baseline_links",
        "process_baseline_revisions",
    } <= names


@pytest.mark.parametrize(
    ("table", "indexes"),
    [
        (
            "process_baselines",
            {
                "uk_pbaselines_project_name",
                "idx_pbaselines_project",
                "idx_pbaselines_source",
                "idx_pbaselines_status",
            },
        ),
        ("process_baseline_steps", {"uk_pbsteps_baseline_no", "idx_pbsteps_baseline"}),
        (
            "process_baseline_links",
            {"uk_pblinks_baseline_target", "idx_pblinks_target"},
        ),
        (
            "process_baseline_revisions",
            {
                "uk_pbrevisions_project_no",
                "idx_pbrevisions_project",
                "idx_pbrevisions_project_status",
            },
        ),
    ],
)
def test_ac_197_indexes_exist(engine: Engine, table: str, indexes: set[str]):
    """索引 / 唯一键与 spec §4 一致（漏建索引会在大项目上直接拖慢列表页）。"""
    names = {item["name"] for item in inspect(engine).get_indexes(table)}
    assert indexes <= names


@pytest.mark.parametrize(
    ("table", "checks"),
    [
        ("process_baselines", {"ck_pbaselines_source", "ck_pbaselines_status"}),
        ("process_baseline_steps", {"ck_pbsteps_no_positive"}),
        ("process_baseline_links", {"ck_pblinks_target_type"}),
        ("process_baseline_revisions", {"ck_pbrevisions_status"}),
    ],
)
def test_ac_197_check_constraints_exist(engine: Engine, table: str, checks: set[str]):
    """CHECK 约束真的落到了库里（不是只写在 ORM 元数据里）。"""
    names = {
        item["name"] for item in inspect(engine).get_check_constraints(table)
    }
    assert checks <= names


def test_ac_197_links_have_no_foreign_key_to_baseline_targets(engine: Engine):
    """关联表**只有** baseline_id 一个外键，target_id 不指向功能基线。

    这是 04 物理删功能不变成 500 的前提（spec §3.4）。
    """
    fks = inspect(engine).get_foreign_keys("process_baseline_links")
    referred = {fk["referred_table"] for fk in fks}
    assert referred == {"process_baselines"}
    assert "baseline_functions" not in referred
    assert "baseline_feature_points" not in referred


def test_ac_197_seed_template_is_unique(db: Session):
    """`task_type='process_baseline'` 的模板有且只有一条 active。"""
    total = db.scalar(
        select(func.count())
        .select_from(PromptTemplate)
        .where(PromptTemplate.task_type == "process_baseline")
    )
    assert total == 1

    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "process_baseline"
        )
    )
    assert template.status == "active"


def test_ac_197_seed_template_prefix_is_mockable(db: Session):
    """模板的 system 前缀可被 Mock 识别（分流靠前缀）。"""
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "process_baseline"
        )
    )
    assert template.system_prompt.startswith("[PROCESS_BASELINE_SYSTEM]")


def test_ac_197_seed_template_declares_scenarios_contract(db: Session):
    """模板写清了输出契约：**场景列表**（不是三级树），且链接只能取清单里的 id。"""
    template = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "process_baseline"
        )
    )
    assert '"scenarios"' in template.system_prompt
    # 三级树的根结构不能出现——流程基线没有层级
    assert '"modules"' not in template.system_prompt
    # 必须说明 target_id 只能取自清单（06 期「模型瞎猜 id」的教训）
    assert "可关联的功能基线目标" in template.system_prompt
    assert "target_id" in template.system_prompt


def test_ac_197_prompt_template_accepts_process_baseline_task_type(db: Session):
    """模板表接受 `task_type='process_baseline'`（0025 扩了 CHECK 枚举）。"""
    project = Project(name=f"模板项目-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()

    template = PromptTemplate(
        name=f"临时模板-{uuid.uuid4().hex[:6]}",
        task_type="process_baseline",
        description="临时",
        system_prompt="[PROCESS_BASELINE_SYSTEM] 临时",
        user_prompt="临时",
        version_no=1,
        status="active",
    )
    db.add(template)
    db.flush()

    assert template.id is not None
    assert template.task_type == "process_baseline"


def test_ac_197_prompt_template_rejects_unknown_task_type(db: Session):
    """扩枚举不是放开口子：非法 `task_type` 仍被 CHECK 拒绝（3819）。"""
    db.add(
        PromptTemplate(
            name=f"非法模板-{uuid.uuid4().hex[:6]}",
            task_type="bogus_task",
            description="临时",
            system_prompt="临时",
            user_prompt="临时",
            version_no=1,
            status="active",
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_ptemplates_task_type" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_197_llm_run_log_check_is_not_extended(db: Session):
    """**`llm_run_logs.task_type` 的 CHECK 没有被扩**。

    04 的文档推导不写运行留痕（`run_document_derive` 里没有
    `run_log.record_run`），本期的反推同构 → 不写留痕 → 不需要扩它的 CHECK。
    扩了就是一处多余的上游改动。
    """
    db.add(
        LLMRunLog(
            task_type="process_baseline",
            provider_name="mock",
            model="mock",
            call_count=1,
            latency_ms=10,
            status="succeeded",
        )
    )
    with pytest.raises(OperationalError) as exc:
        db.flush()
    assert exc.value.orig.args[0] == 3819
    assert "ck_llmlogs_task_type" in str(exc.value.orig.args[1])
    db.rollback()


def test_ac_197_migration_head_is_0027(db: Session):
    """迁移 head 是 `0027`（0026 数据层 + 0027 模板层，12 期推进）。"""
    row = db.execute(text("SELECT version_num FROM alembic_version")).first()
    assert row is not None
    assert row[0] == "0027"


def test_ac_211_projects_table_has_no_new_column(engine: Engine):
    """**`projects` 表没有新增列**（AC-211：本期不做保留策略）。

    04 的 `baseline_snapshot_max_count` 仍是唯一的快照上限列——
    两套基线共用一列会混算，要独立就得新增项目列（整套功能，超出本期）。
    """
    columns = {item["name"] for item in inspect(engine).get_columns("projects")}
    assert "baseline_snapshot_max_count" in columns
    assert not any("process" in name for name in columns)


def test_ac_210_no_process_baseline_label_table(engine: Engine):
    """**不存在流程基线的标签表**（AC-210：本期不做标签）。

    04 的 `baseline_labels` 保持原样——它的 `target_type` CHECK
    写死两个层级名，扩它就是改上游表结构。
    """
    names = set(inspect(engine).get_table_names())
    assert not any("label" in name and "process" in name for name in names)


def test_ac_210_baseline_labels_check_is_unchanged(engine: Engine):
    """`baseline_labels.target_type` 的 CHECK 仍是两个层级名（04 零改动）。"""
    checks = {
        item["name"]: item["sqltext"]
        for item in inspect(engine).get_check_constraints("baseline_labels")
    }
    assert "ck_blabels_target_type" in checks
    sqltext = str(checks["ck_blabels_target_type"]).lower()
    assert "function" in sqltext
    assert "feature_point" in sqltext
    # 不该出现流程基线相关的层级名
    assert "scenario" not in sqltext
    assert "process_baseline" not in sqltext
