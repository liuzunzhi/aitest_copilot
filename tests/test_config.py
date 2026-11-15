"""配置加载测试（T02）。

核心断言：缺 DB_DSN 时必须构造失败，不能带空配置启动。
"""

import pytest
from pydantic import ValidationError

from app.common.config import Settings, get_settings

DSN = "mysql+pymysql://u:p@127.0.0.1:3306/db"


def test_missing_db_dsn_raises(monkeypatch, tmp_path):
    """缺 DB_DSN 时抛 ValidationError，而不是用空串跑起来。"""
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.chdir(tmp_path)  # 确保读不到项目根目录的 .env

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    assert "db_dsn" in str(exc.value)


def test_empty_db_dsn_raises():
    """空串等同缺失。"""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_dsn="")


def test_defaults():
    s = Settings(_env_file=None, db_dsn=DSN)

    assert s.redis_url == "redis://127.0.0.1:6379/0"
    assert s.bcrypt_cost == 12


def test_reads_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        f"DB_DSN={DSN}\n"
        "REDIS_URL=redis://127.0.0.1:6379/3\n"
        "BCRYPT_COST=10\n",
        encoding="utf-8",
    )

    s = Settings(_env_file=env)

    assert s.db_dsn == DSN
    assert s.redis_url == "redis://127.0.0.1:6379/3"
    assert s.bcrypt_cost == 10


@pytest.mark.parametrize("cost", [3, 17])
def test_bcrypt_cost_out_of_range(cost):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_dsn=DSN, bcrypt_cost=cost)


def test_get_settings_is_cached(monkeypatch):
    monkeypatch.setenv("DB_DSN", DSN)
    get_settings.cache_clear()

    assert get_settings() is get_settings()

    get_settings.cache_clear()
