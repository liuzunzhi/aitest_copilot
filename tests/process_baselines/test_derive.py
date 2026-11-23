"""文档反推引擎 + 候选采纳（10-process-baseline T119 / AC-202、AC-203）。

覆盖点：

**AC-202 反推引擎是纯函数**

- 反推后 `process_baselines` / `process_baseline_steps` /
  `process_baseline_links` **三张表行数全部不变**（不写表）；
- 引擎函数的签名里**没有 `session`**（结构化断言，不靠肉眼）；
- 输出根结构是 `{"scenarios": [...]}`（**列表**，不是三级树）；
- 模型返回坏 JSON → 整次失败 `LLMOutputInvalid`；
- 模型返回 `{"scenarios": []}` → **不算失败**，记 `no_structured_content`；
- 某候选 `name` 为空 → **只丢该候选**，其余正常返回；
- 某候选的 `target_id` **不在**可关联清单里 → **只丢该条关联**，
  该候选与其步骤仍返回；
- 步骤 `action` 为空 → **只丢该步骤**；
- `char_count == 0` 的章节**不调模型**（记 `empty_content`）；
- Prompt 里同时含「已有流程基线场景清单」与「可关联的功能基线清单（带 id）」；
- 同名场景跨章节合并，**步骤保留首次出现**；
- 既有五个 Mock 分支的输出**一个字节不变**。

**AC-203 反推候选采纳**

- 勾选 2 个 → `POST /scenarios` → `created=2`，追溯三元组与请求一致；
- 同名冲突 → **整批拒**（409），`process_baselines` 行数不变；
- 候选带 `links` → 链接行按**服务端重查**的名称写入；
- 审计 `process_baseline.scenario.create` 含 `created` 计数。

**零真实 socket**：本文件不引入任何网络客户端，
请求全部走 `fastapi.testclient.TestClient`（进程内 ASGI）。
"""

import inspect
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.common.config import get_settings
from app.llm.mock import (
    DEFAULT_RESPONSE,
    DERIVE_DEFAULT_RESPONSE,
    PROCESS_BASELINE_DEFAULT_RESPONSE,
    SECOND_PASS_DEFAULT_RESPONSE,
    TEST_CASE_DEFAULT_RESPONSE,
    TEST_POINT_DEFAULT_RESPONSE,
    MockProvider,
)
from app.llm.provider import get_provider
from app.main import app as fastapi_app
from app.models.document import Document, DocumentChapter, DocumentVersion
from app.models.incremental import PromptTemplate
from app.models.process_baseline import (
    ProcessBaseline,
    ProcessBaselineLink,
    ProcessBaselineStep,
)
from app.models.system import AuditLog

from app.process_baselines import derive as derive_engine
from tests.process_baselines.helpers import (
    SCENARIOS,
    login,
    make_chain,
    make_feature_point,
    make_function,
)

DERIVE = "/api/projects/{project_id}/process-baselines/derive"


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


def _make_document(
    db,
    project,
    user,
    *,
    chapters: list[tuple[str, str]] | None = None,
    status: str = "active",
) -> tuple[Document, DocumentVersion, list[DocumentChapter]]:
    """建文档 + 版本 + 章节（支持多章节与空正文章节）。"""
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
        status=status,
        file_name="需求.md",
        file_path=f"var/uploads/{project.id}/{uuid.uuid4().hex}.md",
        file_size=128,
        sha256="d" * 64,
        chapter_count=len(chapters or []),
        uploaded_by=user.id,
    )
    db.add(version)
    db.flush()

    rows: list[DocumentChapter] = []
    for seq, (title, content) in enumerate(
        chapters or [("4.2 登录失败次数限制", "账号连续输错密码 5 次后锁定")], start=1
    ):
        chapter = DocumentChapter(
            version_id=version.id,
            parent_id=None,
            seq=seq,
            level=1,
            title=title,
            content=content,
            char_count=len(content),
        )
        db.add(chapter)
        rows.append(chapter)
    db.flush()
    return document, version, rows


def _scenarios_json(*scenarios: dict) -> str:
    return json.dumps({"scenarios": list(scenarios)}, ensure_ascii=False)


def _scenario_node(name: str, **overrides) -> dict:
    node = {
        "name": name,
        "description": f"{name}描述",
        "precondition": f"{name}前置条件",
        "confidence": 0.9,
        "rationale": "正文明确写了",
        "steps": [
            {"action": "第一步", "expected": "结果一"},
            {"action": "第二步", "expected": "结果二"},
        ],
        "links": [],
    }
    node.update(overrides)
    return node


def _post_derive(client, chain: dict, headers: dict, template, document, version):
    return client.post(
        DERIVE.format(project_id=chain["project"].id),
        json={
            "document_id": document.id,
            "document_version_id": version.id,
            "template_id": template.id,
        },
        headers=headers,
    )


def _counts(db) -> tuple[int, int, int]:
    """三张业务表的行数（反推前后必须完全相同）。"""
    return (
        db.scalar(select(func.count()).select_from(ProcessBaseline)),
        db.scalar(select(func.count()).select_from(ProcessBaselineStep)),
        db.scalar(select(func.count()).select_from(ProcessBaselineLink)),
    )


def _audits(db, project_id: int, action: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id, AuditLog.action == action
            )
        ).all()
    )


# ============================================================= AC-202


def test_ac_202_engine_signature_has_no_session():
    """引擎签名里**没有 `session`**——「不写表」是结构上的保证。

    结构化断言（`inspect.signature`），不靠肉眼。
    """
    params = inspect.signature(derive_engine.run_derive).parameters
    assert "session" not in params
    assert "db" not in params
    # 引擎只吃「输入」，不吃「会话」——查库、落库都在服务层。
    assert set(params) == {
        "provider",
        "template",
        "document_name",
        "version_no",
        "chapters",
        "existing_scenarios",
        "linkable_targets",
        "max_chars",
    }


def test_ac_202_derive_does_not_write_any_table(db, client, provider, template):
    """反推后三张表**行数全部不变**（反推只出草案不写表）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(
        db, chain["project"], chain["user"], chapters=[("登录", "账号连续输错密码后锁定")]
    )
    provider.queue = [_scenarios_json(_scenario_node("扫码登录失败锁定"))]

    before = _counts(db)
    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    assert response.json()["candidate_count"] == 1
    assert _counts(db) == before
    # 本项目一条场景都没落库
    assert (
        db.scalar(
            select(func.count())
            .select_from(ProcessBaseline)
            .where(ProcessBaseline.project_id == chain["project"].id)
        )
        == 0
    )


def test_ac_202_output_root_is_scenarios_list(db, client, provider, template):
    """输出的根结构是 `{"scenarios": [...]}`——**列表**，不是三级树。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [_scenarios_json(_scenario_node("扫码登录失败锁定"))]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["scenarios"], list)
    assert len(body["scenarios"]) == 1
    scenario = body["scenarios"][0]
    assert scenario["name"] == "扫码登录失败锁定"
    # 场景是**平铺**的：没有 children / modules / functions 之类的层级包装
    assert "children" not in scenario
    assert "modules" not in body


def test_ac_202_bad_json_fails_whole_run(db, client, provider, template):
    """模型返回坏 JSON → **整次失败** `LLMOutputInvalid`（502）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = ["这不是 JSON"]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 502, response.text
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"
    # 失败操作不写审计
    assert _audits(db, chain["project"].id, "process_baseline.derive.run") == []


def test_ac_202_wrong_root_structure_fails_whole_run(db, client, provider, template):
    """根结构不是 `{"scenarios": [...]}` → 整次失败。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [json.dumps({"modules": [{"name": "示例模块"}]}, ensure_ascii=False)]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 502, response.text
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"


def test_ac_202_empty_scenarios_is_not_a_failure(db, client, provider, template):
    """`{"scenarios": []}` → **不算失败**，记 `no_structured_content`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, chapters = _make_document(
        db, chain["project"], chain["user"], chapters=[("背景介绍", "本章没有场景")]
    )
    provider.queue = [_scenarios_json()]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scenarios"] == []
    assert body["candidate_count"] == 0
    assert body["processed_count"] == 1
    assert body["skipped_chapters"] == [
        {"chapter_id": chapters[0].id, "reason": "no_structured_content"}
    ]


def test_ac_202_blank_name_drops_only_that_candidate(db, client, provider, template):
    """某候选 `name` 为空 → **只丢该候选**，其余正常返回。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [
        _scenarios_json(
            _scenario_node("   "),
            _scenario_node("扫码登录失败锁定"),
        )
    ]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["name"] for row in body["scenarios"]] == ["扫码登录失败锁定"]
    assert body["candidate_count"] == 1


def test_ac_202_too_long_name_drops_only_that_candidate(db, client, provider, template):
    """候选名超长（> 128）→ **只丢该候选**。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [
        _scenarios_json(
            _scenario_node("超" * 200),
            _scenario_node("扫码登录失败锁定"),
        )
    ]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["name"] for row in body["scenarios"]] == ["扫码登录失败锁定"]


def test_ac_202_out_of_range_target_id_drops_only_that_link(
    db, client, provider, template
):
    """`target_id` 不在可关联清单里 → **只丢该条关联**，候选与其步骤仍返回。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    function = make_function(db, chain["project"], chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [
        _scenarios_json(
            _scenario_node(
                "扫码登录失败锁定",
                links=[
                    {"target_type": "function", "target_id": 999999},
                    {
                        "target_type": "function",
                        "target_id": function.id,
                        "target_name": "前端乱传的名字",
                    },
                ],
            )
        )
    ]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate_count"] == 1
    scenario = body["scenarios"][0]
    # 候选与其步骤都还在
    assert len(scenario["steps"]) == 2
    # 越界的那条关联被丢掉，剩下的按**清单里的真名**返回
    assert len(scenario["links"]) == 1
    assert scenario["links"][0]["target_id"] == function.id
    assert scenario["links"][0]["target_name"] == "用户扫码登录"


def test_ac_202_blank_step_action_drops_only_that_step(db, client, provider, template):
    """步骤 `action` 为空 → **只丢该步骤**，候选与其余步骤保留。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [
        _scenarios_json(
            _scenario_node(
                "扫码登录失败锁定",
                steps=[
                    {"action": "打开登录页", "expected": "展示登录页"},
                    {"action": "   ", "expected": "不该出现"},
                    {"action": "连续输错密码", "expected": "提示已锁定"},
                ],
            )
        )
    ]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    scenario = response.json()["scenarios"][0]
    assert [step["action"] for step in scenario["steps"]] == [
        "打开登录页",
        "连续输错密码",
    ]


def test_ac_202_empty_chapter_does_not_call_model(db, client, provider, template):
    """`char_count == 0` 的章节**不调模型**（记 `empty_content`）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, chapters = _make_document(
        db,
        chain["project"],
        chain["user"],
        chapters=[("背景介绍", ""), ("登录", "账号连续输错密码后锁定")],
    )
    provider.queue = [_scenarios_json(_scenario_node("扫码登录失败锁定"))]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["chapter_count"] == 2
    assert body["processed_count"] == 1
    assert body["skipped_chapters"] == [
        {"chapter_id": chapters[0].id, "reason": "empty_content"}
    ]
    # 空章节没调模型 → 只有一次调用
    assert len(provider.calls) == 1


def test_ac_202_prompt_contains_both_briefs(db, client, provider, template):
    """Prompt 里**同时**含「已有场景清单」与「可关联目标清单（带 id）」。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    function = make_function(db, chain["project"], chain["user"], name="用户扫码登录")
    point = make_feature_point(db, chain["project"], chain["user"], function)
    # 先建一个已有场景——它要出现在「已有流程基线场景」那一段
    client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={
            "scenarios": [
                {
                    "name": "已存在的场景",
                    "source_type": "manual",
                    "steps": [{"action": "第一步", "expected": "结果一"}],
                }
            ]
        },
        headers=headers,
    )
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [_scenarios_json(_scenario_node("扫码登录失败锁定"))]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    prompt = provider.calls[0].user
    # ① 已有流程基线场景清单
    assert "## 已有流程基线场景（避免重复抽取）" in prompt
    assert "已存在的场景" in prompt
    # ② 可关联的功能基线清单（**带 id**）
    assert "## 可关联的功能基线目标（target_id 取自这里）" in prompt
    assert f"功能#{function.id} 用户扫码登录" in prompt
    assert f"功能点#{point.id} 展示扫码二维码" in prompt
    # 四段顺序固定
    assert (
        prompt.index("## 文档信息")
        < prompt.index("## 已有流程基线场景（避免重复抽取）")
        < prompt.index("## 可关联的功能基线目标（target_id 取自这里）")
        < prompt.index("## 章节：")
    )


def test_ac_202_prompt_groups_linkable_targets_by_module(db, client, provider, template):
    """可关联清单按**模块分组**渲染——模块头只出现一次。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    first = make_function(db, chain["project"], chain["user"], name="用户扫码登录")
    second = make_function(db, chain["project"], chain["user"], name="提交订单")
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [_scenarios_json(_scenario_node("扫码登录失败锁定"))]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    prompt = provider.calls[0].user
    assert prompt.count("- 模块：") == 2
    assert f"功能#{first.id} 用户扫码登录" in prompt
    assert f"功能#{second.id} 提交订单" in prompt


def test_ac_202_prompt_is_byte_identical_for_same_document(
    db, client, provider, template
):
    """同一份文档 → 渲染出**逐字节相同**的 Prompt（可复现）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    make_function(db, chain["project"], chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [
        _scenarios_json(_scenario_node("扫码登录失败锁定")),
        _scenarios_json(_scenario_node("扫码登录失败锁定")),
    ]

    assert _post_derive(client, chain, headers, template, document, version).status_code == 200
    assert _post_derive(client, chain, headers, template, document, version).status_code == 200

    assert len(provider.calls) == 2
    assert provider.calls[0].user == provider.calls[1].user


def test_ac_202_long_brief_is_truncated_at_the_tail_only(
    db, client, provider, template, monkeypatch
):
    """清单超长 → **只砍清单段尾部**，模板正文与章节正文不动。

    砍掉多少要**告诉模型**（追加省略说明）——否则它会以为「清单就这么多」。
    """
    # 把输入预算调小，让清单必然超预算（不改配置文件的默认值）
    settings = get_settings()
    monkeypatch.setattr(
        settings, "incremental_max_input_chars", 1200, raising=False
    )

    chain = make_chain(db)
    headers = login(client, chain["user"])
    long_name = "很长的功能基线名称用来把清单预算撑满以便触发截断"
    for index in range(20):
        make_function(
            db, chain["project"], chain["user"], name=f"{long_name}{index:02d}"
        )
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [_scenarios_json(_scenario_node("扫码登录失败锁定"))]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    prompt = provider.calls[0].user
    # 清单被砍了，且**告诉模型砍了多少**
    assert "已省略" in prompt
    # 砍的是**尾部**：前面的留着，最后一个没了
    assert f"{long_name}00" in prompt
    assert f"{long_name}19" not in prompt
    # 章节正文**没被砍**（章节只有一句短正文，砍它就该没内容了）
    assert "账号连续输错密码 5 次后锁定" in prompt


def test_ac_202_same_name_scenarios_are_merged(db, client, provider, template):
    """同名场景跨章节合并，**步骤保留首次出现**（不追加）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, chapters = _make_document(
        db,
        chain["project"],
        chain["user"],
        chapters=[("登录", "账号连续输错密码后锁定"), ("风控", "账号锁定规则补充")],
    )
    provider.queue = [
        _scenarios_json(
            _scenario_node(
                "扫码登录失败锁定",
                steps=[{"action": "第一步", "expected": "结果一"}],
            )
        ),
        _scenarios_json(
            _scenario_node(
                "扫码登录失败锁定",
                steps=[{"action": "后来章节的步骤", "expected": "不该出现"}],
            )
        ),
    ]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate_count"] == 1
    scenario = body["scenarios"][0]
    # 步骤保留**首次出现**的那一份
    assert [step["action"] for step in scenario["steps"]] == ["第一步"]
    # 来源章节取第一次出现
    assert scenario["source_chapter_id"] == chapters[0].id
    assert scenario["source_chapter_title"] == chapters[0].title


def test_ac_202_mock_existing_branches_are_byte_identical():
    """既有五个 Mock 分支的输出**一个字节不变**。

    这是「本期一个字都不许改 `app/llm/mock.py`」的**可执行断言**：
    常量的字面量与分支的返回值都逐字节比对。
    """
    # ① 五个既有分支的常量逐字节不变
    assert DEFAULT_RESPONSE == '{"conclusions": []}'
    assert SECOND_PASS_DEFAULT_RESPONSE == (
        '{"decision": "unchanged", "confidence": 0.5, '
        '"rationale": "mock 默认结论", "new_points": []}'
    )
    assert DERIVE_DEFAULT_RESPONSE == json.dumps(
        {
            "modules": [
                {
                    "name": "示例模块",
                    "description": "mock 推导出的示例模块",
                    "functions": [
                        {
                            "name": "示例功能",
                            "description": "mock 推导出的示例功能",
                            "feature_points": [
                                {
                                    "name": "示例功能点",
                                    "description": "mock 推导出的示例功能点",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )
    assert TEST_POINT_DEFAULT_RESPONSE == json.dumps(
        {
            "test_points": [
                {
                    "name": "mock 测试点",
                    "target_type": "function",
                    "target_id": 123,
                    "priority": "medium",
                    "precondition": "mock 前置条件",
                    "verification": "mock 验证要点",
                }
            ]
        },
        ensure_ascii=False,
    )
    assert TEST_CASE_DEFAULT_RESPONSE == json.dumps(
        {
            "cases": [
                {
                    "title": "mock 生成用例",
                    "case_type": "functional",
                    "priority": "medium",
                    "precondition": "mock 前置条件",
                    "steps": [
                        {"action": "mock 第一步", "expected": "mock 预期一"},
                        {"action": "mock 第二步", "expected": "mock 预期二"},
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )

    # ② 每个既有分支返回的就是它自己的常量（逐字节相等）
    from app.llm.schemas import LLMRequest

    mock = MockProvider()
    cases = [
        ("[INCREMENTAL_2B_SYSTEM] x", SECOND_PASS_DEFAULT_RESPONSE),
        ("[DERIVE_SYSTEM] x", DERIVE_DEFAULT_RESPONSE),
        ("[TEST_POINT_SYSTEM] x", TEST_POINT_DEFAULT_RESPONSE),
        ("[TEST_CASE_SYSTEM] x", TEST_CASE_DEFAULT_RESPONSE),
        ("[PROCESS_BASELINE_SYSTEM] x", PROCESS_BASELINE_DEFAULT_RESPONSE),
    ]
    for system, expected in cases:
        mock = MockProvider()
        response = mock.chat(LLMRequest(system=system, user="u"))
        assert response.content == expected


def test_ac_202_derive_requires_admin(db, client, provider, template):
    """普通成员发起反推 → 403 `NOT_PROJECT_ADMIN`。"""
    chain = make_chain(db, role="member")
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "NOT_PROJECT_ADMIN"


def test_ac_202_archived_project_is_rejected_before_role(db, client, provider, template):
    """归档项目 → 409 `PROJECT_ARCHIVED`（**先判归档，后判角色**）。"""
    chain = make_chain(db, role="member", status="archived")
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PROJECT_ARCHIVED"


def test_ac_202_non_active_version_is_rejected(db, client, provider, template):
    """版本不是生效版本 → 400 `DOCUMENT_VERSION_NOT_ANALYZABLE`。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(
        db, chain["project"], chain["user"], status="pending"
    )

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "DOCUMENT_VERSION_NOT_ANALYZABLE"


def test_ac_202_wrong_template_type_is_rejected(db, client, provider, template):
    """模板类型不是 `process_baseline` → 400（选错模板会静默产出错误结构）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    wrong = db.scalar(
        select(PromptTemplate).where(PromptTemplate.task_type == "document_parse")
    )
    assert wrong is not None

    response = client.post(
        DERIVE.format(project_id=chain["project"].id),
        json={
            "document_id": document.id,
            "document_version_id": version.id,
            "template_id": wrong.id,
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROMPT_TEMPLATE_INVALID"


def test_ac_202_derive_writes_audit(db, client, provider, template):
    """审计 `process_baseline.derive.run` 落库，`after_data` 带统计。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [_scenarios_json(_scenario_node("扫码登录失败锁定"))]

    response = _post_derive(client, chain, headers, template, document, version)

    assert response.status_code == 200, response.text
    rows = _audits(db, chain["project"].id, "process_baseline.derive.run")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_id == chain["user"].id
    assert row.project_id == chain["project"].id
    assert row.target_type == "process_baseline_derive"
    assert row.after_data["document_id"] == document.id
    assert row.after_data["document_version_id"] == version.id
    assert row.after_data["template_id"] == template.id
    assert row.after_data["provider"] == "mock"
    assert row.after_data["stats"]["candidate_count"] == 1


def test_ac_202_derive_request_rejects_unknown_fields(db, client, provider, template):
    """请求带多余字段 → 400 `PROCESS_BASELINE_INVALID`（不静默丢弃）。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])

    response = client.post(
        DERIVE.format(project_id=chain["project"].id),
        json={
            "document_id": document.id,
            "document_version_id": version.id,
            "template_id": template.id,
            "source_method": "前端乱传的字段",
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PROCESS_BASELINE_INVALID"
    # 请求没被受理 → 一次模型调用都没有
    assert provider.calls == []


# ============================================================= AC-203


def _adopt(
    client,
    chain: dict,
    headers: dict,
    candidates: list[dict],
    document,
    version,
) -> dict:
    """把候选按「勾选 → 采纳」的形态提交给 `POST /scenarios`。"""
    items = []
    for candidate in candidates:
        items.append(
            {
                "name": candidate["name"],
                "description": candidate.get("description"),
                "precondition": candidate.get("precondition"),
                "source_type": "document_derived",
                "source_document_id": document.id,
                "source_version_id": version.id,
                "source_chapter_id": candidate["source_chapter_id"],
                "source_chapter_title": candidate.get("source_chapter_title"),
                "source_method": "baseline_reverse",
                "steps": candidate.get("steps") or [],
                "links": [
                    {"target_type": link["target_type"], "target_id": link["target_id"]}
                    for link in (candidate.get("links") or [])
                ],
            }
        )
    return client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={"scenarios": items},
        headers=headers,
    )


def test_ac_203_adopt_two_candidates_creates_two_scenarios(
    db, client, provider, template
):
    """勾选 2 个 → `created=2`，追溯三元组与请求一致。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, chapters = _make_document(
        db,
        chain["project"],
        chain["user"],
        chapters=[("登录", "账号连续输错密码后锁定"), ("支付", "下单后支付失败重试")],
    )
    provider.queue = [
        _scenarios_json(_scenario_node("扫码登录失败锁定")),
        _scenarios_json(_scenario_node("支付失败自动重试")),
    ]

    response = _post_derive(client, chain, headers, template, document, version)
    assert response.status_code == 200, response.text
    candidates = response.json()["scenarios"]
    assert len(candidates) == 2

    adopted = _adopt(client, chain, headers, candidates, document, version)

    assert adopted.status_code == 201, adopted.text
    body = adopted.json()
    assert body["created"] == 2
    assert len(body["items"]) == 2

    rows = list(
        db.scalars(
            select(ProcessBaseline)
            .where(ProcessBaseline.project_id == chain["project"].id)
            .order_by(ProcessBaseline.id)
        ).all()
    )
    assert len(rows) == 2
    for row in rows:
        assert row.source_type == "document_derived"
        assert row.source_document_id == document.id
        assert row.source_version_id == version.id
        assert row.source_chapter_id in [chapter.id for chapter in chapters]
        assert row.source_method == "baseline_reverse"
        assert row.source_chapter_title is not None


def test_ac_203_duplicate_name_rejects_whole_batch(db, client, provider, template):
    """候选里有**同名**已存在场景 → **整批拒**（409），行数不变。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    # 先建一个同名场景
    client.post(
        SCENARIOS.format(project_id=chain["project"].id),
        json={
            "scenarios": [
                {
                    "name": "扫码登录失败锁定",
                    "source_type": "manual",
                    "steps": [{"action": "第一步", "expected": "结果一"}],
                }
            ]
        },
        headers=headers,
    )
    provider.queue = [
        _scenarios_json(
            _scenario_node("扫码登录失败锁定"),
            _scenario_node("支付失败自动重试"),
        )
    ]
    response = _post_derive(client, chain, headers, template, document, version)
    candidates = response.json()["scenarios"]

    before = _counts(db)
    adopted = _adopt(client, chain, headers, candidates, document, version)

    assert adopted.status_code == 409, adopted.text
    assert adopted.json()["code"] == "PROCESS_BASELINE_DUPLICATE_NAME"
    # **整批拒**：一条都没落库
    assert _counts(db) == before


def test_ac_203_adopted_links_use_server_requeried_name(db, client, provider, template):
    """采纳的候选带 `links` → 链接行按**服务端重查**的名称写入。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    function = make_function(
        db, chain["project"], chain["user"], name="用户扫码登录"
    )
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [
        _scenarios_json(
            _scenario_node(
                "扫码登录失败锁定",
                links=[
                    {
                        "target_type": "function",
                        "target_id": function.id,
                        "target_name": "前端乱传的名字",
                    }
                ],
            )
        )
    ]
    response = _post_derive(client, chain, headers, template, document, version)
    candidates = response.json()["scenarios"]

    adopted = _adopt(client, chain, headers, candidates, document, version)

    assert adopted.status_code == 201, adopted.text
    links = list(db.scalars(select(ProcessBaselineLink)).all())
    assert len(links) == 1
    assert links[0].target_id == function.id
    # 服务端重查的真名，不是模型给的、也不是客户端传的
    assert links[0].target_name == "用户扫码登录"


def test_ac_203_adopt_audit_contains_created_count(db, client, provider, template):
    """审计 `process_baseline.scenario.create` 含 `created` 计数。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [
        _scenarios_json(
            _scenario_node("扫码登录失败锁定"),
            _scenario_node("支付失败自动重试"),
        )
    ]
    response = _post_derive(client, chain, headers, template, document, version)
    candidates = response.json()["scenarios"]

    adopted = _adopt(client, chain, headers, candidates, document, version)

    assert adopted.status_code == 201, adopted.text
    rows = _audits(db, chain["project"].id, "process_baseline.scenario.create")
    assert len(rows) == 1
    assert rows[0].after_data["created"] == 2


def test_ac_203_adopt_with_links_and_steps_writes_both_tables(
    db, client, provider, template
):
    """采纳的候选带步骤与关联 → 步骤行与链接行都落库。"""
    chain = make_chain(db)
    headers = login(client, chain["user"])
    function = make_function(db, chain["project"], chain["user"])
    document, version, _ = _make_document(db, chain["project"], chain["user"])
    provider.queue = [
        _scenarios_json(
            _scenario_node(
                "扫码登录失败锁定",
                links=[
                    {
                        "target_type": "function",
                        "target_id": function.id,
                        "target_name": "用户扫码登录",
                    }
                ],
            )
        )
    ]
    response = _post_derive(client, chain, headers, template, document, version)
    candidates = response.json()["scenarios"]

    adopted = _adopt(client, chain, headers, candidates, document, version)

    assert adopted.status_code == 201, adopted.text
    steps = list(
        db.scalars(
            select(ProcessBaselineStep).order_by(ProcessBaselineStep.step_no)
        ).all()
    )
    assert [row.step_no for row in steps] == [1, 2]
    assert [row.action for row in steps] == ["第一步", "第二步"]
    assert db.scalar(select(func.count()).select_from(ProcessBaselineLink)) == 1
