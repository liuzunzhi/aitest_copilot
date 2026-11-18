"""06 期两张新表（T84）· 数据库层保障。

断言 spec §4.1 / §4.2 的结构约束：

- `llm_providers`：生成列 `default_key` + 唯一索引 `uk_llmprov_default`
  保证全局只有一个默认；`uk_llmprov_name` 保证配置名唯一；
  三个 CheckConstraint 限制类型 / 状态 / 超时范围；
- `llm_run_logs`：`task_type` / `status` 两个 CheckConstraint；
  `analysis_id` / `provider_id` **不建外键**（记录要能留存）。
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.llm.crypto import encrypt
from app.models.llm import LLMProviderConfig, LLMRunLog

from tests.llm.conftest import FAKE_KEY


def _provider(db: Session, **overrides) -> LLMProviderConfig:
    row = LLMProviderConfig(
        name=overrides.pop("name", "配置"),
        provider_type=overrides.pop("provider_type", "openai_compat"),
        base_url=overrides.pop("base_url", "https://api.deepseek.com/v1"),
        api_key_ciphertext=overrides.pop("api_key_ciphertext", encrypt(FAKE_KEY)),
        api_key_last4=overrides.pop("api_key_last4", FAKE_KEY[-4:]),
        model=overrides.pop("model", "deepseek-chat"),
        timeout_seconds=overrides.pop("timeout_seconds", 60),
        status=overrides.pop("status", "active"),
        is_default=overrides.pop("is_default", 0),
        created_by=overrides.pop("created_by", 1),
    )
    db.add(row)
    db.flush()
    return row


# ------------------------------------------------------------ llm_providers


def test_provider_defaults(db: Session):
    """建行后默认值为空时能正常落库。"""
    row = _provider(db)

    assert row.id is not None
    assert row.provider_type == "openai_compat"
    assert row.status == "active"
    assert row.is_default == 0
    assert row.timeout_seconds == 60
    assert row.created_at is not None
    assert row.updated_at is not None


def test_default_key_generated_column(db: Session):
    """`default_key` 是生成列：默认行取 1，其余取 NULL（应用层不写它）。"""
    default_row = _provider(db, name="默认", is_default=1)
    normal_row = _provider(db, name="普通", is_default=0)

    db.refresh(default_row)
    db.refresh(normal_row)

    assert default_row.default_key == 1
    assert normal_row.default_key is None


def test_provider_name_is_unique(db: Session):
    """配置名唯一。"""
    _provider(db, name="重复名")

    with pytest.raises(IntegrityError) as exc:
        _provider(db, name="重复名")

    assert "uk_llmprov_name" in str(exc.value.orig.args[1])
    db.rollback()


def test_default_key_unique_index_blocks_two_defaults(db: Session):
    """唯一索引挂在生成列上 → 两个默认行不可能共存。"""
    _provider(db, name="默认一", is_default=1)

    with pytest.raises(IntegrityError) as exc:
        _provider(db, name="默认二", is_default=1)

    assert "uk_llmprov_default" in str(exc.value.orig.args[1])
    db.rollback()


def test_non_default_rows_do_not_conflict(db: Session):
    """多个非默认行不占位——MySQL 唯一索引允许多个 NULL。"""
    _provider(db, name="一", is_default=0)
    _provider(db, name="二", is_default=0)
    _provider(db, name="三", is_default=0)

    rows = db.scalars(select(LLMProviderConfig)).all()
    assert len(rows) == 3
    assert all(row.default_key is None for row in rows)


def test_provider_type_check_constraint(db: Session):
    """provider_type 只允许 openai_compat。"""
    with pytest.raises(OperationalError) as exc:
        _provider(db, provider_type="anthropic")

    assert "ck_llmprov_type" in str(exc.value.orig.args[1])
    db.rollback()


def test_provider_status_check_constraint(db: Session):
    """status 只允许 active / disabled。"""
    with pytest.raises(OperationalError) as exc:
        _provider(db, status="paused")

    assert "ck_llmprov_status" in str(exc.value.orig.args[1])
    db.rollback()


@pytest.mark.parametrize("timeout", [0, 301])
def test_provider_timeout_check_constraint(db: Session, timeout: int):
    """超时范围 1 ~ 300。"""
    with pytest.raises(OperationalError) as exc:
        _provider(db, timeout_seconds=timeout)

    assert "ck_llmprov_timeout" in str(exc.value.orig.args[1])
    db.rollback()


def test_provider_ciphertext_column_never_stores_plaintext(db: Session):
    """AC-105 库层：整行所有列拼起来都不含明文。"""
    row = _provider(db, name="明文检查")

    db.refresh(row)
    blob = "|".join(
        str(value)
        for column in row.__table__.columns
        for value in (getattr(row, column.name),)
    )

    assert FAKE_KEY not in blob
    assert row.api_key_ciphertext != FAKE_KEY
    assert row.api_key_last4 == FAKE_KEY[-4:]


# ------------------------------------------------------------ llm_run_logs


def _log(db: Session, **overrides) -> LLMRunLog:
    row = LLMRunLog(
        task_type=overrides.pop("task_type", "incremental_first"),
        project_id=overrides.pop("project_id", None),
        analysis_id=overrides.pop("analysis_id", None),
        provider_id=overrides.pop("provider_id", None),
        provider_name=overrides.pop("provider_name", "测试配置"),
        model=overrides.pop("model", "deepseek-chat"),
        template_id=overrides.pop("template_id", None),
        template_version=overrides.pop("template_version", None),
        call_count=overrides.pop("call_count", 1),
        latency_ms=overrides.pop("latency_ms", 120),
        status=overrides.pop("status", "succeeded"),
        error_code=overrides.pop("error_code", None),
        error_message=overrides.pop("error_message", None),
    )
    db.add(row)
    db.flush()
    return row


def test_run_log_defaults(db: Session):
    """运行留痕可写入，默认值符合预期。"""
    row = _log(db)

    assert row.id is not None
    assert row.task_type == "incremental_first"
    assert row.status == "succeeded"
    assert row.call_count == 1
    assert row.created_at is not None


def test_run_log_accepts_null_foreign_keys(db: Session):
    """analysis_id / provider_id **不建外键**——配置停用、记录删除都不该让日志丢失。"""
    row = _log(db, analysis_id=None, provider_id=None, project_id=None)

    assert row.analysis_id is None
    assert row.provider_id is None


def test_run_log_accepts_dangling_snapshot_ids(db: Session):
    """填了不存在的 id 也能写（没有外键约束）。"""
    row = _log(db, analysis_id=999999, provider_id=888888)

    assert row.analysis_id == 999999
    assert row.provider_id == 888888


def test_run_log_task_type_check_constraint(db: Session):
    """task_type 只允许三个枚举值。"""
    with pytest.raises(OperationalError) as exc:
        _log(db, task_type="whatever")

    assert "ck_llmlogs_task_type" in str(exc.value.orig.args[1])
    db.rollback()


def test_run_log_status_check_constraint(db: Session):
    """status 只允许 succeeded / failed。"""
    with pytest.raises(OperationalError) as exc:
        _log(db, status="running")

    assert "ck_llmlogs_status" in str(exc.value.orig.args[1])
    db.rollback()


def test_run_log_has_no_token_or_prompt_columns(db: Session):
    """运行留痕**不记** token 金额、不记 Prompt 正文——表里根本没有这些列。"""
    column_names = {column.name for column in LLMRunLog.__table__.columns}

    assert "prompt" not in " ".join(column_names).lower()
    assert "token" not in " ".join(column_names).lower()
    assert "usage" not in " ".join(column_names).lower()
    assert "content" not in " ".join(column_names).lower()
