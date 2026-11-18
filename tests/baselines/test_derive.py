"""从文档推导基线（AC-122~131）。

覆盖：推导记录状态、跨章节合并、空章节跳过、坏 JSON 整次失败、
候选删除、采纳（create / reuse / skip）、同名不覆盖、层级递归、
权限与归档、审计落库。
"""

import json

import pytest
from sqlalchemy import select

from app.llm.mock import MockProvider
from app.llm.provider import get_provider
from app.main import app as fastapi_app
from app.models.baseline import (
    BaselineFeaturePoint,
    BaselineFunction,
    BaselineModule,
)
from app.models.baseline_derive import BaselineDerive, BaselineDeriveCandidate
from app.models.incremental import PromptTemplate
from app.models.project import Project
from app.models.system import AuditLog
from tests.baselines.helpers import add_member, create_module, make_user
from tests.incremental.helpers import make_document_version

BASE = "/api/projects/{project_id}/baselines/derive"


@pytest.fixture
def provider() -> MockProvider:
    """测试专用 Mock；`client` 夹具收尾时清空所有依赖覆盖。"""
    mock = MockProvider()
    fastapi_app.dependency_overrides[get_provider] = lambda: mock
    return mock


def derive_template(db) -> PromptTemplate:
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "document_parse")
    )
    assert template is not None, "迁移 0020 应播种一条 document_parse 模板"
    return template


def payload(template: PromptTemplate, document, version) -> dict:
    return {
        "document_id": document.id,
        "document_version_id": version.id,
        "template_id": template.id,
    }


def modules_json(*modules: dict) -> str:
    return json.dumps({"modules": list(modules)}, ensure_ascii=False)


def module_node(name: str, *functions: dict) -> dict:
    return {"name": name, "description": f"{name}描述", "functions": list(functions)}


def function_node(name: str, *points: dict) -> dict:
    return {
        "name": name,
        "description": f"{name}描述",
        "feature_points": list(points),
    }


def point_node(name: str) -> dict:
    return {"name": name, "description": f"{name}描述"}


def latest_derive(db) -> BaselineDerive:
    return db.scalar(select(BaselineDerive).order_by(BaselineDerive.id.desc()))


def detail_candidates(db, derive_id: int) -> list[BaselineDeriveCandidate]:
    return list(
        db.scalars(
            select(BaselineDeriveCandidate)
            .where(BaselineDeriveCandidate.derive_id == derive_id)
            .order_by(BaselineDeriveCandidate.id)
        ).all()
    )


# ---------------------------------------------------------------- AC-122


def test_ac_122_run_derive_success_persists_candidates(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, chapters = make_document_version(
        db,
        project,
        admin,
        chapters=[("登录", "账号密码登录与验证码"), ("背景", "")],
        document_name="需求说明书",
    )
    provider.queue = [
        modules_json(module_node("用户登录", function_node("账号密码登录", point_node("错误次数限制"))))
    ]

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["stats"]["chapter_count"] == 2
    assert body["stats"]["processed_count"] == 1
    assert body["stats"]["module_count"] == 1
    assert body["stats"]["function_count"] == 1
    assert body["stats"]["feature_point_count"] == 1
    assert body["stats"]["candidate_count"] == 3
    assert body["stats"]["skipped_chapters"] == [
        {"chapter_id": chapters[1].id, "reason": "empty_content"}
    ]

    derive = latest_derive(db)
    assert derive.status == "succeeded"
    assert derive.document_id == document.id
    assert derive.template_version == template.version_no
    assert derive.provider == "mock"
    assert derive.started_at is not None and derive.finished_at is not None
    assert len(detail_candidates(db, derive.id)) == 3
    # 空章节不调模型
    assert len(provider.calls) == 1


def test_ac_122_bad_json_marks_derive_failed(client, db, project, admin, headers, provider):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    provider.queue = ["这不是 JSON"]

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert response.status_code == 502, response.text
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"

    derive = latest_derive(db)
    assert derive.status == "failed"
    assert derive.error_code == "LLM_OUTPUT_INVALID"
    assert derive.finished_at is not None
    assert detail_candidates(db, derive.id) == []


def test_ac_122_wrong_root_structure_fails(client, db, project, admin, headers, provider):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    provider.queue = ['{"conclusions": []}']

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert response.status_code == 502, response.text
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"
    assert latest_derive(db).status == "failed"


def test_ac_122_non_active_version_rejected(client, db, project, admin, headers, provider):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")], status="pending"
    )

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "DOCUMENT_VERSION_NOT_ANALYZABLE"
    assert db.scalar(select(BaselineDerive).where(BaselineDerive.project_id == project.id)) is None


def test_ac_122_invalid_template_rejected(client, db, project, admin, headers, provider):
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    other = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "incremental")
    )

    response = client.post(
        BASE.format(project_id=project.id),
        json={
            "document_id": document.id,
            "document_version_id": version.id,
            "template_id": other.id,
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROMPT_TEMPLATE_INVALID"


# ---------------------------------------------------------------- AC-123


def test_ac_123_same_module_across_chapters_is_merged(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, chapters = make_document_version(
        db,
        project,
        admin,
        chapters=[("登录-账号", "账号密码登录"), ("登录-短信", "短信验证码登录")],
    )
    provider.queue = [
        modules_json(module_node("用户登录", function_node("账号密码登录"))),
        modules_json(module_node("用户登录", function_node("短信登录"), function_node("账号密码登录"))),
    ]

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["stats"]["module_count"] == 1
    assert response.json()["stats"]["function_count"] == 2

    rows = detail_candidates(db, response.json()["id"])
    root = [row for row in rows if row.parent_id is None]
    assert len(root) == 1
    # 章节出处取第一次出现的章节
    assert root[0].source_chapter_id == chapters[0].id
    assert root[0].source_chapter_title == chapters[0].title


def test_ac_123_blank_chapters_are_skipped_without_calls(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, chapters = make_document_version(
        db, project, admin, chapters=[("背景", ""), ("术语", "   ")]
    )

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["stats"]["processed_count"] == 0
    assert body["stats"]["candidate_count"] == 0
    assert {item["chapter_id"] for item in body["stats"]["skipped_chapters"]} == {
        chapters[0].id,
        chapters[1].id,
    }
    assert provider.calls == []


def test_ac_123_no_structured_content_is_not_failure(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, chapters = make_document_version(
        db, project, admin, chapters=[("背景", "这是一段背景介绍")]
    )
    provider.queue = [modules_json()]

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "succeeded"
    assert response.json()["stats"]["skipped_chapters"] == [
        {"chapter_id": chapters[0].id, "reason": "no_structured_content"}
    ]


def test_ac_123_invalid_candidate_name_is_dropped(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    provider.queue = [
        modules_json(
            module_node("", function_node("空模块下的功能")),
            module_node("用户登录", function_node(" "), function_node("账号密码登录")),
        )
    ]

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["stats"]["module_count"] == 1
    assert response.json()["stats"]["function_count"] == 1


# ---------------------------------------------------------------- AC-124


def test_ac_124_prompt_contains_document_chapter_and_existing_structure(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db,
        project,
        admin,
        chapters=[("登录", "账号密码登录")],
        document_name="需求说明书",
    )
    create_module(client, headers, project.id, "支付模块")
    provider.queue = [modules_json()]

    client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert len(provider.calls) == 1
    user_prompt = provider.calls[0].user
    assert "需求说明书" in user_prompt
    assert f"v{version.version_no}" in user_prompt
    assert "支付模块" in user_prompt
    assert "## 章节：登录" in user_prompt
    assert "账号密码登录" in user_prompt
    assert provider.calls[0].system.startswith("[DERIVE_SYSTEM]")


# ---------------------------------------------------------------- AC-125


def test_ac_125_delete_candidate_removes_subtree(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    provider.queue = [
        modules_json(module_node("用户登录", function_node("账号密码登录", point_node("错误次数限制"))))
    ]
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()

    response = client.delete(
        BASE.format(project_id=project.id)
        + f"/{created['id']}/candidates/{created['candidates'][0]['id']}",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
    detail = client.get(
        BASE.format(project_id=project.id) + f"/{created['id']}",
        headers=headers,
    ).json()
    assert detail["candidates"] == []


def test_ac_125_delete_decided_candidate_rejected(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    provider.queue = [modules_json(module_node("用户登录"))]
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()
    module_id = created["candidates"][0]["id"]
    client.post(
        BASE.format(project_id=project.id) + f"/{created['id']}/adopt",
        json={"candidates": [{"candidate_id": module_id, "action": "skip"}]},
        headers=headers,
    )

    response = client.delete(
        BASE.format(project_id=project.id) + f"/{created['id']}/candidates/{module_id}",
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ADOPT_ALREADY_DECIDED"


# ---------------------------------------------------------------- AC-126~128


def test_ac_126_adopt_create_writes_trace_fields(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, chapters = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    provider.queue = [
        modules_json(module_node("用户登录", function_node("账号密码登录", point_node("错误次数限制"))))
    ]
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()

    response = client.post(
        BASE.format(project_id=project.id) + f"/{created['id']}/adopt",
        json={"candidates": [{"candidate_id": created["candidates"][0]["id"], "action": "create"}]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == {"modules": 1, "functions": 1, "feature_points": 1}
    assert body["adopted_count"] == 3

    module = db.scalar(
        select(BaselineModule).where(BaselineModule.project_id == project.id)
    )
    assert module.name == "用户登录"
    # 模块行只有 source_type（结构表没有逐章节追溯列）
    assert module.source_type == "document_derived"

    function = db.scalar(
        select(BaselineFunction).where(BaselineFunction.module_id == module.id)
    )
    assert function.name == "账号密码登录"
    assert function.source_type == "document_derived"
    assert function.source_document_id == document.id
    assert function.source_version_id == version.id
    assert function.source_chapter_id == chapters[0].id
    assert function.source_chapter_title == "登录"
    assert function.source_method == "baseline_reverse"
    assert function.source_analysis_id is None

    point = db.scalar(
        select(BaselineFeaturePoint).where(
            BaselineFeaturePoint.function_id == function.id
        )
    )
    assert point.name == "错误次数限制"
    assert point.source_type == "document_derived"
    assert point.source_document_id == document.id
    assert point.source_chapter_id == chapters[0].id
    assert point.source_method == "baseline_reverse"
    assert point.source_analysis_id is None

    rows = detail_candidates(db, created["id"])
    assert {row.status for row in rows} == {"adopted"}
    assert all(row.adopted_entity_id is not None for row in rows)


def test_ac_127_same_name_create_never_overwrites(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    existing = create_module(client, headers, project.id, "用户登录")
    provider.queue = [modules_json(module_node("用户登录", function_node("账号密码登录")))]
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()

    response = client.post(
        BASE.format(project_id=project.id) + f"/{created['id']}/adopt",
        json={"candidates": [{"candidate_id": created["candidates"][0]["id"], "action": "create"}]},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "DUPLICATE_MODULE_NAME"
    # 已有行原样保留，没有被改名 / 改描述
    db.refresh(db.get(BaselineModule, existing["id"]))
    assert db.get(BaselineModule, existing["id"]).name == "用户登录"
    # 候选仍是待决策
    assert detail_candidates(db, created["id"])[0].status == "pending"


def test_ac_127_adopt_reuse_existing_module(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    existing = create_module(client, headers, project.id, "用户登录")
    provider.queue = [
        modules_json(module_node("用户登录", function_node("账号密码登录", point_node("错误次数限制"))))
    ]
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()

    response = client.post(
        BASE.format(project_id=project.id) + f"/{created['id']}/adopt",
        json={
            "candidates": [
                {
                    "candidate_id": created["candidates"][0]["id"],
                    "action": "reuse",
                    "existing_entity_id": existing["id"],
                }
            ]
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == {"modules": 0, "functions": 1, "feature_points": 1}
    assert body["reused"] == {"modules": 1, "functions": 0, "feature_points": 0}

    # 复用的已有模块原样保留（手工建的仍是 manual）
    module = db.get(BaselineModule, existing["id"])
    assert module.source_type == "manual"
    # 新功能 / 功能点挂到已有模块下并带追溯
    function = db.scalar(
        select(BaselineFunction).where(BaselineFunction.module_id == existing["id"])
    )
    assert function.source_type == "document_derived"


def test_ac_127_adopt_skip_writes_nothing(client, db, project, admin, headers, provider):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    provider.queue = [modules_json(module_node("用户登录", function_node("账号密码登录")))]
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()

    response = client.post(
        BASE.format(project_id=project.id) + f"/{created['id']}/adopt",
        json={"candidates": [{"candidate_id": created["candidates"][0]["id"], "action": "skip"}]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == {
        "modules": 1,
        "functions": 1,
        "feature_points": 0,
    }
    assert db.scalar(
        select(BaselineModule).where(BaselineModule.project_id == project.id)
    ) is None


def test_ac_127_reuse_target_must_be_same_project_module(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    other_project = Project(name="另一个项目")
    db.add(other_project)
    db.flush()
    foreign_admin = make_user(db)
    add_member(db, other_project, foreign_admin, "project_admin")
    foreign_module = create_module(
        client, headers_for(client, foreign_admin), other_project.id, "外部模块"
    )
    provider.queue = [modules_json(module_node("用户登录"))]
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()

    response = client.post(
        BASE.format(project_id=project.id) + f"/{created['id']}/adopt",
        json={
            "candidates": [
                {
                    "candidate_id": created["candidates"][0]["id"],
                    "action": "reuse",
                    "existing_entity_id": foreign_module["id"],
                }
            ]
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "ADOPT_TARGET_INVALID"


def test_ac_127_child_candidate_cannot_be_adopted_directly(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    provider.queue = [modules_json(module_node("用户登录", function_node("账号密码登录")))]
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()
    function_id = created["candidates"][0]["children"][0]["id"]

    response = client.post(
        BASE.format(project_id=project.id) + f"/{created['id']}/adopt",
        json={"candidates": [{"candidate_id": function_id, "action": "create"}]},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "ADOPT_TARGET_INVALID"


# ---------------------------------------------------------------- AC-129


def test_ac_129_member_cannot_run_derive(
    client, db, project, admin, member, member_headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=member_headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"
    assert provider.calls == []


def test_ac_129_member_can_read_outsider_cannot(
    client, db, project, admin, member, member_headers, outsider_headers, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()

    ok = client.get(
        BASE.format(project_id=project.id) + f"/{created['id']}",
        headers=member_headers,
    )
    assert ok.status_code == 200, ok.text

    denied = client.get(
        BASE.format(project_id=project.id) + f"/{created['id']}",
        headers=outsider_headers,
    )
    assert denied.status_code == 403, denied.text


def test_ac_129_archived_project_cannot_derive(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    project.status = "archived"
    db.flush()

    response = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROJECT_ARCHIVED"


# ---------------------------------------------------------------- AC-130


def test_ac_130_audit_written_for_run_and_adopt(
    client, db, project, admin, headers, provider
):
    template = derive_template(db)
    document, version, _ = make_document_version(
        db, project, admin, chapters=[("登录", "账号密码登录")]
    )
    provider.queue = [modules_json(module_node("用户登录"))]
    created = client.post(
        BASE.format(project_id=project.id),
        json=payload(template, document, version),
        headers=headers,
    ).json()
    client.post(
        BASE.format(project_id=project.id) + f"/{created['id']}/adopt",
        json={"candidates": [{"candidate_id": created["candidates"][0]["id"], "action": "create"}]},
        headers=headers,
    )

    actions = set(
        db.scalars(
            select(AuditLog.action).where(
                AuditLog.project_id == project.id,
                AuditLog.action.in_(["baseline.derive.run", "baseline.derive.adopt"]),
            )
        ).all()
    )
    assert actions == {"baseline.derive.run", "baseline.derive.adopt"}


def headers_for(client, user) -> dict[str, str]:
    from tests.baselines.helpers import login

    return login(client, user)
