"""权限矩阵与校验顺序（10-process-baseline T121 / AC-207、AC-208、AC-209）。

**固定校验顺序**（spec §6 / §7，全平台唯一出处 `app/common/permissions.py`）：

    项目 404 → 归档 409 → 角色 403 → 资源 404 → 业务校验 400 → 执行

本文件把这条顺序逐个接口钉死：

**AC-207 权限矩阵**

- 读接口（场景列表 / 详情 / 快照列表 / 快照详情）：member / guest / 项目管理员 /
  系统管理员 → 200；
- 写接口（新建 / 改 / 删 / 覆盖步骤 / 覆盖关联 / 反推 / 提交 / 通过 / 驳回）：
  member / guest → **403 `NOT_PROJECT_ADMIN`**；项目管理员 / 系统管理员 → 通过；
- 非项目成员读 → **403 `NOT_PROJECT_MEMBER`**（不是 404）；
- 项目不存在 → **404 `PROJECT_NOT_FOUND`**（读和写都是）。

**AC-208 归档项目**

- 归档项目：写接口 → **409 `PROJECT_ARCHIVED`**；读接口 → **200**；
- **归档项目里的普通成员调写接口 → 409（不是 403）**——
  归档先于角色判（tasks.md 明确点名的用例）。

**AC-209 审计**

- 9 个 `process_baseline.*` action 各有落库；
- 审计条目带 `project_id` / `actor_id` / `target_type` / `target_id`；
- `review.approve` 的 `after_data` 含 `self_approved`；
- **失败操作不产生任何 `process_baseline.*` 审计**。

**零真实 socket**：本文件不引入任何网络客户端，
请求全部走 `fastapi.testclient.TestClient`（进程内 ASGI）。
"""

import uuid

import pytest
from sqlalchemy import select

from app.llm.mock import MockProvider
from app.llm.provider import get_provider
from app.main import app as fastapi_app
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import PromptTemplate
from app.models.system import AuditLog

from tests.process_baselines.helpers import (
    BASE,
    SCENARIOS,
    add_member,
    create_scenario,
    login,
    make_chain,
    make_user,
    scenario_body,
)

REVIEWS = BASE + "/reviews"
REVISIONS = BASE + "/revisions"
DERIVE = BASE + "/derive"

# 9 个写操作的审计 action（spec §7.6 / plan §8）
WRITE_ACTIONS = (
    "process_baseline.scenario.create",
    "process_baseline.scenario.update",
    "process_baseline.scenario.delete",
    "process_baseline.steps.update",
    "process_baseline.links.update",
    "process_baseline.derive.run",
    "process_baseline.review.submit",
    "process_baseline.review.approve",
    "process_baseline.review.reject",
)

# 9 个写接口在**项目管理员**下的期望状态码（spec §7）
_EXPECTED_WRITE_STATUS = {
    "新建场景": 201,
    "改场景": 200,
    "覆盖步骤": 200,
    "覆盖关联": 200,
    "删场景": 204,
    "发起反推": 200,
    "提交审核": 201,
    "审核通过": 200,
    "审核驳回": 200,
}


# ---------------------------------------------------------------- 夹具


@pytest.fixture
def provider(client) -> MockProvider:
    """测试专用 Mock；`client` 夹具收尾时清空所有依赖覆盖。"""
    mock = MockProvider()
    fastapi_app.dependency_overrides[get_provider] = lambda: mock
    return mock


@pytest.fixture
def template(db) -> PromptTemplate:
    """迁移 0025 播种的流程基线推导模板。"""
    row = db.scalar(
        select(PromptTemplate).where(
            PromptTemplate.task_type == "process_baseline",
            PromptTemplate.status == "active",
        )
    )
    assert row is not None, "迁移 0025 应播种一条 process_baseline 模板"
    return row


# ---------------------------------------------------------------- 造数


def _document(db, project, user):
    """建文档 + 生效版本 + 章节（反推的上下文）。"""
    document = Document(
        project_id=project.id,
        name=f"需求-{uuid.uuid4().hex[:6]}",
        created_by=user.id,
    )
    db.add(document)
    db.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        status="active",
        file_name="需求.md",
        file_path=f"var/uploads/{project.id}/{uuid.uuid4().hex}.md",
        file_size=128,
        sha256="d" * 64,
        chapter_count=1,
        uploaded_by=user.id,
    )
    db.add(version)
    db.flush()
    chapter = DocumentChapter(
        version_id=version.id,
        parent_id=None,
        seq=1,
        level=1,
        title="4.2 登录失败次数限制",
        content="账号连续输错密码 5 次后锁定",
        char_count=12,
    )
    db.add(chapter)
    db.flush()
    return document, version


def _admin(db, client, chain: dict) -> tuple:
    """另建一个**项目管理员**专供造数——被测账号的角色另行设置。

    造数不能靠被测账号：归档 / 降权之后它自己就写不动了。
    """
    admin = make_user(db)
    add_member(db, chain["project"], admin, "project_admin")
    return admin, login(client, admin)


def _seed_scenarios(client, chain: dict, admin_headers: dict[str, str], count: int = 4):
    """建若干场景（写接口各用一个——免得前一个删掉后，后一个只撞 404）。"""
    ids = []
    for index in range(count):
        body = create_scenario(
            client,
            chain,
            admin_headers,
            name=f"权限矩阵场景-{index}-{uuid.uuid4().hex[:6]}",
        )
        ids.append(body["items"][0]["id"])
    return ids


def _seed_revision(client, chain: dict, admin_headers: dict[str, str]) -> int:
    """提交一份审核中的快照，返回 revision id（读接口要用）。"""
    response = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _write_calls(
    client,
    chain: dict,
    headers: dict[str, str],
    template,
    prepared: dict,
) -> list:
    """把 9 个写接口各调一遍，返回 `(说明, 响应)` 列表。

    **调用顺序固定**，且每一步都留出成功路径：
    提交 → 通过 → 再提交 → 驳回（已通过的快照驳回是 409，
    那样 `review.reject` 就永远没有成功落库的机会）。
    """
    project_id = chain["project"].id
    scenario_ids = prepared["scenario_ids"]
    document = prepared["document"]
    version = prepared["version"]
    responses: list[tuple[str, object]] = []

    created = client.post(
        SCENARIOS.format(project_id=project_id),
        json={
            "scenarios": [scenario_body(name=f"权限矩阵新建-{uuid.uuid4().hex[:6]}")]
        },
        headers=headers,
    )
    responses.append(("新建场景", created))
    responses.append(
        (
            "改场景",
            client.patch(
                SCENARIOS.format(project_id=project_id) + f"/{scenario_ids[0]}",
                json={"description": "权限矩阵改描述"},
                headers=headers,
            ),
        )
    )
    responses.append(
        (
            "覆盖步骤",
            client.put(
                SCENARIOS.format(project_id=project_id) + f"/{scenario_ids[2]}/steps",
                json={"steps": [{"action": "第一步", "expected": "结果一"}]},
                headers=headers,
            ),
        )
    )
    responses.append(
        (
            "覆盖关联",
            client.put(
                SCENARIOS.format(project_id=project_id) + f"/{scenario_ids[3]}/links",
                json={"links": []},
                headers=headers,
            ),
        )
    )
    responses.append(
        (
            "删场景",
            client.delete(
                SCENARIOS.format(project_id=project_id) + f"/{scenario_ids[1]}",
                headers=headers,
            ),
        )
    )
    responses.append(
        (
            "发起反推",
            client.post(
                DERIVE.format(project_id=project_id),
                json={
                    "document_id": document.id,
                    "document_version_id": version.id,
                    "template_id": template.id,
                },
                headers=headers,
            ),
        )
    )

    submitted = client.post(
        REVIEWS.format(project_id=project_id) + "/submit",
        json={},
        headers=headers,
    )
    responses.append(("提交审核", submitted))
    first_id = submitted.json().get("id") if submitted.status_code == 201 else 999999

    responses.append(
        (
            "审核通过",
            client.post(
                REVIEWS.format(project_id=project_id) + f"/{first_id}/approve",
                json={},
                headers=headers,
            ),
        )
    )

    resubmitted = client.post(
        REVIEWS.format(project_id=project_id) + "/submit",
        json={},
        headers=headers,
    )
    second_id = (
        resubmitted.json().get("id") if resubmitted.status_code == 201 else 999999
    )

    responses.append(
        (
            "审核驳回",
            client.post(
                REVIEWS.format(project_id=project_id) + f"/{second_id}/reject",
                json={"comment": "步骤写漏了"},
                headers=headers,
            ),
        )
    )
    return responses


def _read_calls(client, chain: dict, headers: dict[str, str], prepared: dict) -> list:
    """把 4 个读接口各调一遍，返回 `(说明, 响应)` 列表。"""
    project_id = chain["project"].id
    scenario_id = prepared["scenario_ids"][0]
    revision_id = prepared["revision_id"]

    return [
        (
            "场景列表",
            client.get(SCENARIOS.format(project_id=project_id), headers=headers),
        ),
        (
            "场景详情",
            client.get(
                SCENARIOS.format(project_id=project_id) + f"/{scenario_id}",
                headers=headers,
            ),
        ),
        (
            "快照列表",
            client.get(REVISIONS.format(project_id=project_id), headers=headers),
        ),
        (
            "快照详情",
            client.get(
                REVISIONS.format(project_id=project_id) + f"/{revision_id}",
                headers=headers,
            ),
        ),
    ]


def _audits(db, project_id: int, action: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id, AuditLog.action == action
            )
        ).all()
    )


def _archive(db, chain: dict) -> None:
    """把项目改成归档（直接改库——归档接口要系统管理员，这里不需要那一层）。"""
    chain["project"].status = "archived"
    db.flush()


def _prepared(db, client, chain: dict, template, *, revision: bool):
    """造出读 / 写接口各自需要的前置数据。

    **造数用另建的项目管理员**——被测账号的角色随时会变
    （member / guest / 归档），靠它造数会自己把自己挡住。
    """
    admin, admin_headers = _admin(db, client, chain)
    scenario_ids = _seed_scenarios(client, chain, admin_headers)
    document, version = _document(db, chain["project"], admin)
    prepared = {
        "scenario_ids": scenario_ids,
        "document": document,
        "version": version,
        "revision_id": None,
    }
    if revision:
        prepared["revision_id"] = _seed_revision(client, chain, admin_headers)
    return prepared


# ============================================================= AC-207


def test_ac_207_read_interfaces_allow_member_and_guest(db, client, template):
    """member / guest 读接口 → 200（成员可读，含访客）。"""
    chain = make_chain(db, role="member")
    prepared = _prepared(db, client, chain, template, revision=True)

    member = make_user(db)
    guest = make_user(db)
    add_member(db, chain["project"], member, "member")
    add_member(db, chain["project"], guest, "guest")

    for user in (member, guest):
        headers = login(client, user)
        for label, response in _read_calls(client, chain, headers, prepared):
            assert response.status_code == 200, (user.username, label, response.text)


def test_ac_207_write_interfaces_reject_member_and_guest(db, client, template):
    """member / guest 调 9 个写接口 → 403 `NOT_PROJECT_ADMIN`。"""
    chain = make_chain(db, role="member")
    prepared = _prepared(db, client, chain, template, revision=False)

    member = make_user(db)
    guest = make_user(db)
    add_member(db, chain["project"], member, "member")
    add_member(db, chain["project"], guest, "guest")

    for user in (member, guest):
        headers = login(client, user)
        for label, response in _write_calls(
            client, chain, headers, template, prepared
        ):
            assert response.status_code == 403, (user.username, label, response.text)
            assert response.json()["code"] == "NOT_PROJECT_ADMIN", (
                user.username,
                label,
                response.text,
            )


def test_ac_207_project_admin_can_write(db, client, template):
    """项目管理员 → 9 个写接口全部走通。"""
    chain = make_chain(db, role="project_admin")
    headers = login(client, chain["user"])
    prepared = _prepared(db, client, chain, template, revision=False)

    responses = _write_calls(client, chain, headers, template, prepared)

    for label, response in responses:
        assert response.status_code == _EXPECTED_WRITE_STATUS[label], (
            label,
            response.text,
        )


def test_ac_207_system_admin_can_write(db, client, template):
    """系统管理员兜底 → 写接口全部放行（不是项目成员也能写）。"""
    chain = make_chain(db, role="project_admin")
    prepared = _prepared(db, client, chain, template, revision=False)

    system_admin = make_user(db, global_role="system_admin")
    headers = login(client, system_admin)

    responses = _write_calls(client, chain, headers, template, prepared)

    for label, response in responses:
        assert response.status_code == _EXPECTED_WRITE_STATUS[label], (
            label,
            response.text,
        )


def test_ac_207_outsider_cannot_read(db, client, template):
    """非项目成员读 → 403 `NOT_PROJECT_MEMBER`（**不是** 404）。"""
    chain = make_chain(db)
    prepared = _prepared(db, client, chain, template, revision=True)

    outsider = make_user(db)
    headers = login(client, outsider)

    for label, response in _read_calls(client, chain, headers, prepared):
        assert response.status_code == 403, (label, response.text)
        assert response.json()["code"] == "NOT_PROJECT_MEMBER", (label, response.text)


def test_ac_207_outsider_cannot_write(db, client, template):
    """非项目成员写 → 403 `NOT_PROJECT_ADMIN`（与读接口的码不同）。

    与读接口区分开：区分「非成员」与「角色不符」会泄露项目是否存在。
    """
    chain = make_chain(db)
    prepared = _prepared(db, client, chain, template, revision=False)

    outsider = make_user(db)
    headers = login(client, outsider)

    for label, response in _write_calls(client, chain, headers, template, prepared):
        assert response.status_code == 403, (label, response.text)
        assert response.json()["code"] == "NOT_PROJECT_ADMIN", (label, response.text)


def test_ac_207_missing_project_returns_404(db, client):
    """项目不存在 → 404 `PROJECT_NOT_FOUND`（读与写都是）。

    先判 404 是为了不泄露「项目是否存在」——
    项目根本不存在时，报 404 是唯一诚实的答案。
    """
    chain = make_chain(db)
    headers = login(client, chain["user"])
    missing = 99_999_999

    read_probes = [
        (
            "场景列表",
            client.get(SCENARIOS.format(project_id=missing), headers=headers),
        ),
        (
            "场景详情",
            client.get(
                SCENARIOS.format(project_id=missing) + "/1",
                headers=headers,
            ),
        ),
        (
            "快照列表",
            client.get(REVISIONS.format(project_id=missing), headers=headers),
        ),
        (
            "快照详情",
            client.get(REVISIONS.format(project_id=missing) + "/1", headers=headers),
        ),
    ]
    for label, response in read_probes:
        assert response.status_code == 404, (label, response.text)
        assert response.json()["code"] == "PROJECT_NOT_FOUND", (label, response.text)

    write_probes = [
        (
            "新建场景",
            client.post(
                SCENARIOS.format(project_id=missing),
                json={"scenarios": [scenario_body()]},
                headers=headers,
            ),
        ),
        (
            "改场景",
            client.patch(
                SCENARIOS.format(project_id=missing) + "/1",
                json={"description": "改描述"},
                headers=headers,
            ),
        ),
        (
            "删场景",
            client.delete(
                SCENARIOS.format(project_id=missing) + "/1",
                headers=headers,
            ),
        ),
        (
            "覆盖步骤",
            client.put(
                SCENARIOS.format(project_id=missing) + "/1/steps",
                json={"steps": [{"action": "第一步", "expected": "结果一"}]},
                headers=headers,
            ),
        ),
        (
            "覆盖关联",
            client.put(
                SCENARIOS.format(project_id=missing) + "/1/links",
                json={"links": []},
                headers=headers,
            ),
        ),
        (
            "发起反推",
            client.post(
                DERIVE.format(project_id=missing),
                json={
                    "document_id": 1,
                    "document_version_id": 1,
                    "template_id": 1,
                },
                headers=headers,
            ),
        ),
        (
            "提交审核",
            client.post(
                REVIEWS.format(project_id=missing) + "/submit",
                json={},
                headers=headers,
            ),
        ),
        (
            "审核通过",
            client.post(
                REVIEWS.format(project_id=missing) + "/999999/approve",
                json={},
                headers=headers,
            ),
        ),
        (
            "审核驳回",
            client.post(
                REVIEWS.format(project_id=missing) + "/999999/reject",
                json={"comment": "步骤写漏了"},
                headers=headers,
            ),
        ),
    ]
    for label, response in write_probes:
        assert response.status_code == 404, (label, response.text)
        assert response.json()["code"] == "PROJECT_NOT_FOUND", (label, response.text)


# ============================================================= AC-208


def test_ac_208_archived_project_reads_still_work(db, client, template):
    """归档项目：读接口 → **200**（归档只挡写，不挡读）。"""
    chain = make_chain(db, role="member")
    prepared = _prepared(db, client, chain, template, revision=True)
    _archive(db, chain)

    headers = login(client, chain["user"])
    for label, response in _read_calls(client, chain, headers, prepared):
        assert response.status_code == 200, (label, response.text)


def test_ac_208_archived_project_blocks_write(db, client, template):
    """归档项目：写接口 → 409 `PROJECT_ARCHIVED`。"""
    chain = make_chain(db, role="project_admin")
    headers = login(client, chain["user"])
    prepared = _prepared(db, client, chain, template, revision=False)
    _archive(db, chain)

    for label, response in _write_calls(client, chain, headers, template, prepared):
        assert response.status_code == 409, (label, response.text)
        assert response.json()["code"] == "PROJECT_ARCHIVED", (label, response.text)


def test_ac_208_archived_beats_role_check(db, client, template):
    """**归档项目里的普通成员调写接口 → 409（不是 403）**。

    「先判归档再判角色」是全平台约定，顺序只有一个出处
    （`app/common/permissions.py`）——用权限错误掩盖归档状态是不诚实的。
    """
    chain = make_chain(db, role="member")
    prepared = _prepared(db, client, chain, template, revision=False)
    _archive(db, chain)

    headers = login(client, chain["user"])
    for label, response in _write_calls(client, chain, headers, template, prepared):
        assert response.status_code == 409, (label, response.text)
        assert response.json()["code"] == "PROJECT_ARCHIVED", (label, response.text)


def test_ac_208_missing_project_beats_role_check(db, client):
    """**项目不存在优先于角色**：非成员访问不存在的项目 → 404，不是 403。"""
    chain = make_chain(db)
    outsider = make_user(db)
    headers = login(client, outsider)

    response = client.post(
        SCENARIOS.format(project_id=99_999_999),
        json={"scenarios": [scenario_body()]},
        headers=headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


def test_ac_208_role_check_beats_business_validation(db, client):
    """**角色优先于业务校验**：member + 空步骤 → 403，不是 400。

    顺序是 404 → 409 → 403 → 400：角色在业务校验前面。
    """
    chain = make_chain(db, role="project_admin")
    admin_headers = login(client, chain["user"])
    scenario_id = create_scenario(
        client,
        chain,
        admin_headers,
        name=f"权限矩阵顺序-{uuid.uuid4().hex[:6]}",
    )["items"][0]["id"]

    member = make_user(db)
    add_member(db, chain["project"], member, "member")
    headers = login(client, member)

    response = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={"steps": []},
        headers=headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


# ============================================================= AC-209


def test_ac_209_all_nine_actions_are_audited(db, client, template):
    """9 个 `process_baseline.*` action 各有落库。"""
    chain = make_chain(db, role="project_admin")
    headers = login(client, chain["user"])
    prepared = _prepared(db, client, chain, template, revision=False)
    _write_calls(client, chain, headers, template, prepared)

    for action in WRITE_ACTIONS:
        logs = _audits(db, chain["project"].id, action)
        assert len(logs) >= 1, f"{action} 没有产生审计记录"


def test_ac_209_audit_entries_carry_scope(db, client, template):
    """审计条目带 `project_id` / `actor_id` / `target_type` / `target_id`。"""
    chain = make_chain(db, role="project_admin")
    headers = login(client, chain["user"])
    prepared = _prepared(db, client, chain, template, revision=False)
    _write_calls(client, chain, headers, template, prepared)

    rows = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == chain["project"].id,
                AuditLog.action.in_(WRITE_ACTIONS),
                AuditLog.actor_id == chain["user"].id,
            )
        ).all()
    )
    assert rows

    for row in rows:
        assert row.project_id == chain["project"].id
        assert row.actor_role == "user"
        assert row.target_type is not None
        assert row.target_type.startswith("process_baseline")
        # `derive.run` 没有具体目标行 → target_id 为空是允许的
        if row.action != "process_baseline.derive.run":
            assert row.target_id is not None, row.action


def test_ac_209_approve_audit_contains_self_approved(db, client, template):
    """`review.approve` 的 `after_data` 含 `self_approved`。"""
    chain = make_chain(db, role="project_admin")
    headers = login(client, chain["user"])
    prepared = _prepared(db, client, chain, template, revision=False)
    _write_calls(client, chain, headers, template, prepared)

    logs = _audits(db, chain["project"].id, "process_baseline.review.approve")
    assert len(logs) == 1
    assert "self_approved" in logs[0].after_data
    assert logs[0].after_data["self_approved"] is True


def test_ac_209_failed_operation_writes_no_audit(db, client, template):
    """**失败操作不产生任何 `process_baseline.*` 审计**。

    三个失败点各占一类：步骤校验失败（400）、审核中再提交（409）、
    对已通过的快照再审核（409）。
    """
    chain = make_chain(db, role="project_admin")
    headers = login(client, chain["user"])
    scenario_id = create_scenario(
        client,
        chain,
        headers,
        name=f"审计失败用例-{uuid.uuid4().hex[:6]}",
    )["items"][0]["id"]

    # ① 步骤校验失败 → 400
    failed = client.put(
        SCENARIOS.format(project_id=chain["project"].id) + f"/{scenario_id}/steps",
        json={"steps": []},
        headers=headers,
    )
    assert failed.status_code == 400, failed.text

    # ② 审核中再提交 → 409
    submitted = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={},
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    duplicate = client.post(
        REVIEWS.format(project_id=chain["project"].id) + "/submit",
        json={},
        headers=headers,
    )
    assert duplicate.status_code == 409, duplicate.text

    # ③ 对已通过的快照再通过 → 409
    approved = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted.json()['id']}/approve",
        json={},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    again = client.post(
        REVIEWS.format(project_id=chain["project"].id)
        + f"/{submitted.json()['id']}/approve",
        json={},
        headers=headers,
    )
    assert again.status_code == 409, again.text

    # 失败的那几次**没有**留下审计
    assert _audits(db, chain["project"].id, "process_baseline.steps.update") == []
    assert _audits(db, chain["project"].id, "process_baseline.links.update") == []
    assert _audits(db, chain["project"].id, "process_baseline.scenario.update") == []
    assert _audits(db, chain["project"].id, "process_baseline.scenario.delete") == []
    assert _audits(db, chain["project"].id, "process_baseline.derive.run") == []
    assert _audits(db, chain["project"].id, "process_baseline.review.reject") == []
    # 提交 / 通过各只有**成功**的那一次
    assert len(_audits(db, chain["project"].id, "process_baseline.review.submit")) == 1
    assert len(_audits(db, chain["project"].id, "process_baseline.review.approve")) == 1
