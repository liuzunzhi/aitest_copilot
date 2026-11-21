"""Playwright 前台验收夹具（见 `specs/验证约定.md`）。

这些用例不在全量 pytest 里跑（`addopts` 默认 `-m "not e2e"`），
常规直接用 `scripts/run_e2e.py`（自检 → 起 8001/5174 → 跑用例 → 收尾）。

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

REPO_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_ROOT = Path(
    os.getenv("E2E_SCREENSHOT_DIR", str(REPO_ROOT / ".screenshots"))
)
ADMIN_USERNAME = os.getenv("E2E_ADMIN_USERNAME", SUPPORT_ADMIN_USERNAME)
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", SUPPORT_ADMIN_PASSWORD)


def _db_fingerprint(session, username: str) -> tuple[int | None, frozenset[int]]:
    """某库里 `username` 的 id + 参与项目集合。"""
    from sqlalchemy import text

    row = session.execute(
        text("SELECT id FROM users WHERE username = :name"), {"name": username}
    ).first()
    if row is None:
        return None, frozenset()
    project_ids = session.execute(
        text("SELECT project_id FROM project_members WHERE user_id = :uid"),
        {"uid": row[0]},
    ).scalars()
    return row[0], frozenset(project_ids.all())


def _assert_backend_is_isolated(playwright) -> None:
    """确认 e2e 后端连的是 `aitest_copilot_e2e`，而不是开发库。

    前台用例会真实创建项目、成员、申请与审计记录。跑在开发库上会污染数据，
    还会把后端全量 pytest 的全局断言打红。端口被旧进程占住时最容易踩这个坑
    （端口上跑着连开发库的后端，前台看起来是通的，数据却写错库），
    所以开跑前先验一次。

    只读校验：拿 `/api/auth/me` 的 admin id 与 `/api/projects` 的项目集合，
    去两个库里比对 admin 的「id + 参与项目」指纹。不造探针数据，
    校验失败也不会留下垃圾；两库数据都为空时靠 admin id 区分。
    """
    from tests.e2e.support import _dev_dsn, _e2e_dsn

    ctx = playwright.request.new_context(base_url=BACKEND_URL)
    try:
        login = ctx.post(
            "/api/auth/login",
            data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        if login.status != 200:
            raise RuntimeError(
                f"e2e 后端 {BACKEND_URL} 不可用：{login.status} {login.text()}"
            )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = ctx.get("/api/auth/me", headers=headers)
        projects = ctx.get("/api/projects", headers=headers)
        if me.status != 200 or projects.status != 200:
            raise RuntimeError(
                f"e2e 后端 {BACKEND_URL} 取身份/项目失败："
                f"me={me.status} projects={projects.status}"
            )
        api_fingerprint = (
            me.json()["id"],
            frozenset(item["id"] for item in projects.json()),
        )
    finally:
        ctx.dispose()

    found: dict[str, tuple[int | None, frozenset[int]]] = {}
    for label, dsn in (("e2e", _e2e_dsn()), ("dev", _dev_dsn())):
        engine = create_engine(dsn, pool_pre_ping=True, future=True)
        session = Session(engine, expire_on_commit=False)
        try:
            found[label] = _db_fingerprint(session, ADMIN_USERNAME)
        finally:
            session.close()
            engine.dispose()

    if found["e2e"] == api_fingerprint and found["dev"] != api_fingerprint:
        return
    if found["dev"] == api_fingerprint and found["e2e"] != api_fingerprint:
        raise RuntimeError(
            f"e2e 后端连的是开发库（admin id={api_fingerprint[0]} 落在 dev），"
            "前台用例会污染开发库并打红后端全量断言。先停掉占用 8001 的后端。"
        )
    raise RuntimeError(
        "无法确认 e2e 后端连的是隔离库："
        f"后端指纹 admin id={api_fingerprint[0]}、项目 {len(api_fingerprint[1])} 个；"
        f"e2e 库 {found['e2e']}，dev 库 {found['dev']}。"
        "确认 8001 上跑的是 `DB_DSN=..._e2e` 的后端。"
    )


@pytest.fixture(scope="session", autouse=True)
def _e2e_backend_isolation(playwright) -> None:
    """session 级守卫：后端没连隔离库就不许开跑。"""
    _assert_backend_is_isolated(playwright)


@pytest.fixture(scope="session", autouse=True)
def _e2e_data_cleanup(pytestconfig: pytest.Config) -> Iterator[None]:
    """会话结束清掉 `e2e-` 前缀的项目，避免 e2e 库越跑越大。

    需要现场排查时设 `E2E_KEEP_DATA=1` 跳过清理（`scripts/run_e2e.py --keep-data`）。
    """
    yield
    if os.getenv("E2E_KEEP_DATA"):
        print("\n[e2e] E2E_KEEP_DATA 已设置，跳过数据清理")
        return

    from tests.e2e.support import cleanup_e2e_data

    counts = cleanup_e2e_data()
    summary = "，".join(f"{table} {rows}" for table, rows in counts.items()) or "没有可清理的数据"
    message = f"\n[e2e] 已清理：{summary}"
    # 会话收尾的 print 会被 pytest 捕获，走 terminal writer 才能直接看到
    writer = getattr(pytestconfig, "get_terminal_writer", None)
    if callable(writer):
        writer().line(message)
    else:
        print(message)


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
    """截图落到 `.screenshots/<任务号>/<用例名>-<标签>.png`。

    `full_page=False` 用于**抽屉 / 弹窗**场景：抽屉是 `position: fixed`，
    整页截图会按文档宽度渲染，固定定位的抽屉会被裁掉一截，
    截图上看不清抽屉内容。
    """

    def _shot(page: Page, label: str = "final", *, full_page: bool = True) -> Path:
        marker = request.node.get_closest_marker("task")
        folder = str(marker.args[0]) if marker and marker.args else "misc"
        target = SCREENSHOT_ROOT / folder
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{request.node.name}-{label}.png"
        page.screenshot(path=str(path), full_page=full_page)
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
