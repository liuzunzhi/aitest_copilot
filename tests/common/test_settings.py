"""配置读取与缓存（T11）。

必须真连库跑：要守的是「缓存命中不读库」与「写后立即失效」，
mock 掉数据库就失去了验证意义。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common import settings as settings_service
from app.common.settings import CACHE_TTL_SECONDS, get_setting, invalidate, set_setting

KEY = "max_login_failures"


@pytest.fixture(autouse=True)
def clean_cache():
    """用例之间不共享缓存。"""
    settings_service.cache_clear()
    yield
    settings_service.cache_clear()


def _db_update(db: Session, value: str) -> None:
    """绕过服务层直接改库，用来证明读的是缓存还是数据库。"""
    db.execute(
        text("UPDATE system_settings SET `value` = :v WHERE `key` = :k"),
        {"v": value, "k": KEY},
    )


def test_returns_seeded_value(db: Session):
    assert get_setting(KEY, db) == 5
    assert get_setting("token_ttl_seconds", db) == 28800
    assert get_setting("enable_project_apply", db) is True


def test_missing_key_raises(db: Session):
    with pytest.raises(KeyError):
        get_setting("no_such_setting", db)


def test_cache_hit_until_invalidated(db: Session):
    """TTL 内的重复读取不碰库；invalidate 后拿到新值。"""
    assert get_setting(KEY, db) == 5

    _db_update(db, "9")
    assert get_setting(KEY, db) == 5

    invalidate(KEY)
    assert get_setting(KEY, db) == 9


def test_cache_expires_after_ttl(db: Session, monkeypatch):
    """超过 60s 后缓存自然失效。"""
    fake = {"now": 0.0}
    monkeypatch.setattr(settings_service.time, "monotonic", lambda: fake["now"])

    assert get_setting(KEY, db) == 5
    _db_update(db, "9")

    fake["now"] = CACHE_TTL_SECONDS - 1
    assert get_setting(KEY, db) == 5

    fake["now"] = CACHE_TTL_SECONDS + 1
    assert get_setting(KEY, db) == 9


def test_set_setting_invalidates_cache(db: Session):
    """写入后无需等待 TTL，下一次读取即为新值。"""
    assert get_setting(KEY, db) == 5

    set_setting(db, KEY, 7)

    assert get_setting(KEY, db) == 7


def test_set_setting_upserts_unknown_key(db: Session):
    set_setting(db, "t11_tmp_key", "v")

    assert get_setting("t11_tmp_key", db) == "v"
