"""Playwright 前台验收夹具（见 `specs/验证约定.md`）。

这些用例不在全量 pytest 里跑（`addopts` 默认 `-m "not e2e"`），
需要先起后端 :8000 与前端 :5173，再显式执行：

    .\\.venv\\Scripts\\python.exe -m pytest tests/e2e -m e2e

账号可用环境变量覆盖：`E2E_ADMIN_USERNAME` / `E2E_ADMIN_PASSWORD`。
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.e2e.support import (
    ADMIN_PASSWORD as SUPPORT_ADMIN_PASSWORD,
    ADMIN_USERNAME as SUPPORT_ADMIN_USERNAME,
    Api,
    BACKEND_URL,
    USER_PASSWORD,
    create_user,
    storage_state,
    token_for,
)

SCREENSHOT_ROOT = Path(
    os.getenv("E2E_SCREENSHOT_DIR", r"D:\学习\AI辅助测试平台\.screenshots")
)
ADMIN_USERNAME = os.getenv("E2E_ADMIN_USERNAME", SUPPORT_ADMIN_USERNAME)
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", SUPPORT_ADMIN_PASSWORD)


def _assert_backend_is_isolated(playwright) -> None:
    """确认 e2e 后端连的是 `_e2e` 库，而不是开发库。

    前台用例会真实创建项目、成员、申请与审计记录。跑在开发库上会污染数据，
    还会把后端全量 pytest 的全局断言打红。端口被旧进程占住时最容易踩这个坑
    （端口上跑着连开发库的后端，前台看起来是通的，数据却写错库），
    所以开跑前先验一次。

    做法是拿后端 API 造一个探针项目，再去两个库里找它落在哪——
    只看后端「能不能连上」不够，得看它到底写的哪个库。
    """
    import uuid

    from sqlalchemy import text

    from tests.e2e.support import BACKEND_URL, _dev_dsn, _e2e_dsn

    probe_name = f"e2e-probe-{uuid.uuid4().hex[:8]}"
    ctx = playwright.request.new_context(base_url=BACKEND_URL)
    try:
        response = ctx.post(
            "/api/projects",
            data={"name": probe_name},
            headers={
                "Authorization": (
                    f"Bearer {token_for(ctx, ADMIN_USERNAME, ADMIN_PASSWORD)}"
                )
            },
        )
    finally:
        ctx.dispose()
    if response.status not in (200, 201):
        raise RuntimeError(
            f"e2e 后端 {BACKEND_URL} 不可用：{response.status} {response.text()}"
        )

    found = {}
    for label, dsn in (("e2e", _e2e_dsn()), ("dev", _dev_dsn())):
        engine = create_engine(dsn, pool_pre_ping=True, future=True)
        probe_session = Session(engine, expire_on_commit=False)
        try:
            rows = probe_session.execute(
                text("SELECT id FROM projects WHERE name = :name"),
                {"name": probe_name},
            ).all()
            if rows:
                found[label] = rows[0][0]
        finally:
            probe_session.close()
            engine.dispose()

    if "dev" in found:
        raise RuntimeError(
            f"e2e 后端把探针项目 {probe_name} 写进了开发库（项目 {found['dev']}），"
            "前台用例会污染开发库并打红后端全量断言。先停掉占用 8001 的后端。"
        )
    if "e2e" not in found:
        raise RuntimeError(
            f"探针项目 {probe_name} 没落在隔离库 {_e2e_dsn()}，"
            f"却出现在 {sorted(found)}。先确认 e2e 后端用的是 `_e2e` 库。"
        )


@pytest.fixture(scope="session", autouse=True)
def _e2e_backend_isolation(playwright) -> None:
    """session 级守卫：后端没连隔离库就不许开跑。"""
    _assert_backend_is_isolated(playwright)


@pytest.fixture(scope="session")
def admin_storage_state(browser: Browser, base_url: str) -> dict:
    """登录一次，把 localStorage 里的令牌存下来给所有用例复用。"""
    context = browser.new_context(base_url=base_url)
    page = context.new_page()
    page.goto("/login")
    page.get_by_test_id("login-username").fill(ADMIN_USERNAME)
    page.get_by_test_id("login-password").fill(ADMIN_PASSWORD)
    page.get_by_test_id("login-submit").click()
    page.wait_for_url("**/projects")
    state = context.storage_state()
    context.close()
    return state


@pytest.fixture
def admin_page(
    browser: Browser, base_url: str, admin_storage_state: dict
) -> Iterator[Page]:
    """已登录系统管理员的页面。"""
    context = browser.new_context(base_url=base_url, storage_state=admin_storage_state)
    page = context.new_page()
    page.goto("/projects")
    yield page
    context.close()


@pytest.fixture
def shot(request: pytest.FixtureRequest) -> Callable[..., Path]:
    """截图落到 `.screenshots/<任务号>/<用例名>-<标签>.png`。"""

    def _shot(page: Page, label: str = "final") -> Path:
        marker = request.node.get_closest_marker("task")
        folder = str(marker.args[0]) if marker and marker.args else "misc"
        target = SCREENSHOT_ROOT / folder
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{request.node.name}-{label}.png"
        page.screenshot(path=str(path), full_page=True)
        return path

    return _shot


@pytest.fixture
def api(playwright) -> Iterator[Api]:
    """造数用的后端客户端（默认系统管理员身份）。"""
    ctx = playwright.request.new_context(base_url=BACKEND_URL)
    yield Api(ctx)
    ctx.dispose()


@pytest.fixture
def make_user() -> Callable[..., dict]:
    """按需造普通用户；返回 {id, username, password}。"""

    def _make_user(global_role: str = "user") -> dict:
        return create_user(global_role)

    return _make_user


@pytest.fixture
def page_as(browser: Browser, base_url: str, api: Api) -> Iterator[Callable[..., Page]]:
    """以任意用户身份打开页面，省去登录表单。"""
    contexts: list = []

    def _open(username: str, password: str = USER_PASSWORD, path: str = "/projects") -> Page:
        token = token_for(api.ctx, username, password)
        context = browser.new_context(
            base_url=base_url, storage_state=storage_state(base_url, token)
        )
        contexts.append(context)
        page = context.new_page()
        page.goto(path)
        return page

    yield _open
    for context in contexts:
        context.close()
