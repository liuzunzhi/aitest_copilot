"""导出 Excel（T108 / AC-177）。

覆盖点：

- 返回 `.xlsx`，Content-Type 与文件名符合 spec §6.6；
- 3 步骤的用例占 3 行，`步骤序号` 为 1 / 2 / 3，元数据在每行重复；
- 列名与中文状态 / 类型 / 优先级 / 来源正确；
- 筛选参数（状态 / 测试点 / 批次）对导出生效；
- member 可导出，非成员 403。
"""

from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.test_cases.labels import (
    CASE_PRIORITY_LABELS,
    CASE_SOURCE_LABELS,
    CASE_STATUS_LABELS,
    CASE_TYPE_LABELS,
)

from tests.test_cases.helpers import (
    ANALYSES,
    CASES,
    add_member,
    case_response,
    login,
    make_case,
    make_chapter,
    make_point,
    make_project,
    make_user,
    seed_template,
)

EXPORT_URL = CASES.format(project_id=0) + "/export"

COLUMNS = (
    "用例ID",
    "用例名称",
    "用例类型",
    "优先级",
    "所属测试点ID",
    "所属测试点",
    "功能或功能点",
    "前置条件",
    "步骤序号",
    "操作步骤",
    "预期结果",
    "状态",
    "来源",
    "创建时间",
)


def _chain(db) -> dict:
    admin = make_user(db)
    project = make_project(db)
    add_member(db, project, admin, "project_admin")
    template = seed_template(db)
    chapter = make_chapter(db, project, admin)
    point = make_point(db, project, admin, chapter=chapter)
    return {
        "admin": admin,
        "project": project,
        "template": template,
        "chapter": chapter,
        "point": point,
    }


def _export(client, chain: dict, headers: dict, query: str = "") -> dict:
    """调导出并把 xlsx 读回表格。"""
    url = f"{CASES.format(project_id=chain['project'].id)}/export{query}"
    response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    workbook = load_workbook(BytesIO(response.content))
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    return {
        "response": response,
        "header": rows[0] if rows else (),
        "rows": rows[1:],
    }


def _create_case(client, chain: dict, headers: dict, **overrides) -> dict:
    body = {
        "test_point_id": chain["point"].id,
        "title": "导出的用例",
        "case_type": "functional",
        "priority": "high",
        "precondition": "账号已存在",
        "steps": [
            {"action": "第一步", "expected": "预期一"},
            {"action": "第二步", "expected": "预期二"},
            {"action": "第三步", "expected": "预期三"},
        ],
    }
    body.update(overrides)
    response = client.post(
        CASES.format(project_id=chain["project"].id), json=body, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ac_177_content_type_and_filename(db, client):
    """Content-Type 与文件名符合 spec §6.6。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    _create_case(client, chain, headers)

    result = _export(client, chain, headers)
    response = result["response"]

    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    disposition = response.headers["content-disposition"]
    assert "test-cases-" in disposition
    assert f"{chain['project'].id}" in disposition
    assert ".xlsx" in disposition


def test_ac_177_header_columns_match_spec(db, client):
    """表头列名与 spec §6.6 一致（顺序也一致）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    _create_case(client, chain, headers)

    result = _export(client, chain, headers)

    assert tuple(result["header"]) == COLUMNS


def test_ac_177_one_row_per_step(db, client):
    """3 个步骤 → 3 行，`步骤序号` 为 1 / 2 / 3，元数据每行重复。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    created = _create_case(client, chain, headers)

    result = _export(client, chain, headers)

    assert len(result["rows"]) == 3
    step_nos = [row[8] for row in result["rows"]]
    assert step_nos == [1, 2, 3]
    actions = [row[9] for row in result["rows"]]
    assert actions == ["第一步", "第二步", "第三步"]
    expected = [row[10] for row in result["rows"]]
    assert expected == ["预期一", "预期二", "预期三"]
    # 元数据在每行重复
    assert {row[0] for row in result["rows"]} == {created["id"]}
    assert {row[1] for row in result["rows"]} == {"导出的用例"}
    assert {row[5] for row in result["rows"]} == {chain["point"].name}


def test_ac_177_labels_are_chinese(db, client):
    """状态 / 类型 / 优先级 / 来源输出中文。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    _create_case(client, chain, headers, case_type="api", priority="low")

    result = _export(client, chain, headers)

    assert result["rows"][0][2] == CASE_TYPE_LABELS["api"]
    assert result["rows"][0][3] == CASE_PRIORITY_LABELS["low"]
    assert result["rows"][0][11] == CASE_STATUS_LABELS["pending"]
    assert result["rows"][0][12] == CASE_SOURCE_LABELS["manual"]


def test_ac_177_status_filter_applies(db, client):
    """状态筛选对导出生效。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    case_id = _create_case(client, chain, headers)["id"]
    client.post(
        f"{CASES.format(project_id=chain['project'].id)}/{case_id}/review",
        json={"action": "approve"},
        headers=headers,
    )

    pending = _export(client, chain, headers, "?status=pending")
    approved = _export(client, chain, headers, "?status=approved")

    assert len(pending["rows"]) == 0
    assert len(approved["rows"]) == 3
    assert approved["rows"][0][11] == CASE_STATUS_LABELS["approved"]


def test_ac_177_test_point_filter_applies(db, client):
    """测试点筛选对导出生效。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    _create_case(client, chain, headers)
    other = make_point(
        db, chain["project"], chain["admin"], target_id=10097, name="别的点"
    )

    matched = _export(client, chain, headers, f"?test_point_id={chain['point'].id}")
    unmatched = _export(client, chain, headers, f"?test_point_id={other.id}")

    assert len(matched["rows"]) == 3
    assert len(unmatched["rows"]) == 0


def test_ac_177_analysis_filter_applies(db, client, provider):
    """批次筛选对导出生效：手工用例（`analysis_id=NULL`）不随批次导出。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])
    provider.queue = [case_response(make_case())]
    generated = client.post(
        ANALYSES.format(project_id=chain["project"].id),
        json={"template_id": chain["template"].id},
        headers=headers,
    )
    assert generated.status_code == 201, generated.text
    analysis_id = generated.json()["id"]
    _create_case(client, chain, headers)

    by_analysis = _export(client, chain, headers, f"?analysis_id={analysis_id}")
    without_filter = _export(client, chain, headers)

    assert len(by_analysis["rows"]) == 2  # 生成的用例有 2 个步骤
    # 手工用例的 3 步 + 生成的 2 步
    assert len(without_filter["rows"]) == 5


def test_ac_177_member_can_export(db, client):
    """member 可导出（读权限）。"""
    chain = _chain(db)
    admin_headers = login(client, chain["admin"])
    _create_case(client, chain, admin_headers)

    member = make_user(db)
    add_member(db, chain["project"], member, "member")
    result = _export(client, chain, login(client, member))

    assert result["response"].status_code == 200
    assert len(result["rows"]) == 3


def test_ac_177_non_member_gets_403(db, client):
    """非成员导出 → 403。"""
    chain = _chain(db)
    outsider = make_user(db)
    headers = login(client, outsider)

    response = client.get(
        f"{CASES.format(project_id=chain['project'].id)}/export", headers=headers
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_PROJECT_MEMBER"


def test_ac_177_export_of_empty_project_has_only_header(db, client):
    """没有用例时导出只有表头（不报错）。"""
    chain = _chain(db)
    headers = login(client, chain["admin"])

    result = _export(client, chain, headers)

    assert result["rows"] == []
    assert tuple(result["header"]) == COLUMNS


@pytest.mark.parametrize("value", sorted(CASE_STATUS_LABELS))
def test_label_mapping_is_total(value: str):
    """状态枚举每个都有中文（前端会手抄一份，两边不能漂移）。"""
    assert CASE_STATUS_LABELS[value]
    assert CASE_TYPE_LABELS["functional"]
    assert CASE_SOURCE_LABELS["llm"]
