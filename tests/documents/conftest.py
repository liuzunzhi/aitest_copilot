"""文档模块测试夹具。"""

import pytest

from app.common.config import get_settings


@pytest.fixture
def upload_root(tmp_path, monkeypatch):
    """把原文目录指向临时目录，避免测试往仓库 `var/uploads` 写文件。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    return tmp_path
