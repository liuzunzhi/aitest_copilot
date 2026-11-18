"""AC-121 · L1 自动化端到端：真实需求文档 → 解析 → 落库 → 分析 → 结论。

覆盖两件事，一条用例同时验证：

- **AC-119**：真实 `.pdf` / `.docx` 走上传解析，章节树正确落库；
- **AC-120**：模型返回**带 Markdown 围栏的 JSON** 时，结论照样落库。

模型侧用 `OpenAICompatProvider` + `httpx.MockTransport`：
走的是真实的 OpenAI 兼容请求路径（URL / Header / Body / 响应解析），
但**零真实 socket**，断网可跑。

样本来自 `测试用的需求文档_不提交git/`（已被 `.gitignore` 覆盖），
缺失时 skip——CI 上没有这份样本不应算失败。
"""

import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.openai_compat import OpenAICompatProvider
from app.llm.provider import get_provider
from app.main import app as fastapi_app
from app.models.document import DocumentChapter, DocumentVersion
from app.models.incremental import IncrementalAnalysis, IncrementalConclusion
from app.models.llm import LLMRunLog
from tests.incremental import helpers as H

SAMPLES = Path(__file__).resolve().parents[2] / "测试用的需求文档_不提交git"
PDF_SAMPLE = SAMPLES / "Matrix系统说明书_基础需求文档.pdf"
DOCX_SAMPLE = SAMPLES / "Matrix系统需求变更说明书V1.1.docx"

UPLOAD = "/api/projects/{project_id}/documents"
ACTIVATE = "/api/projects/{project_id}/documents/{document_id}/versions/{version_id}/activate"


def _fenced(payload: dict) -> str:
    """真实模型最常见的返回形态：带 json 语言标记的围栏。"""
    return f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


def _transport_returning(conclusions: list[dict]) -> httpx.MockTransport:
    """构造一个假的 DeepSeek：固定返回带围栏的 conclusions。"""
    content = _fenced({"conclusions": conclusions})

    def handler(request: httpx.Request) -> httpx.Response:
        # 走的是真实兼容路径，顺手确认请求形状没跑偏
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            },
        )

    return httpx.MockTransport(handler)


def _upload_and_activate(client: TestClient, headers, project_id: int, path: Path) -> dict:
    """真实文件走上传接口 → 激活版本，返回上传响应。"""
    content_type = "application/pdf" if path.suffix == ".pdf" else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    response = client.post(
        UPLOAD.format(project_id=project_id),
        files={"file": (path.name, path.read_bytes(), content_type)},
        headers=headers,
    )
    assert response.status_code in (200, 201), response.text
    payload = response.json()

    activated = client.post(
        ACTIVATE.format(
            project_id=project_id,
            document_id=payload["document"]["id"],
            version_id=payload["version"]["id"],
        ),
        headers=headers,
    )
    assert activated.status_code in (200, 201), activated.text
    return payload


@pytest.mark.parametrize(
    ("sample", "expect_multilevel_heading"),
    [(PDF_SAMPLE, True), (DOCX_SAMPLE, False)],
    ids=["pdf", "docx"],
)
def test_ac_121_l1_real_document_full_chain(
    client: TestClient,
    db: Session,
    sample: Path,
    expect_multilevel_heading: bool,
):
    """真实文档：上传 → 解析 → 章节落库 → 发起分析 → 结论落库 → 运行留痕。"""
    if not sample.exists():
        pytest.skip(f"样本缺失（不入库）：{sample.name}")

    chain = H.build_chain(db)
    project_id = chain["project"].id
    function_id = chain["structure"]["function"].id
    headers = H.login(client, chain["admin"])

    # ---------- 1. 真实文件上传 + 解析 + 激活 ----------
    payload = _upload_and_activate(client, headers, project_id, sample)
    version_id = payload["version"]["id"]

    chapters = db.scalars(
        select(DocumentChapter)
        .where(DocumentChapter.version_id == version_id)
        .order_by(DocumentChapter.seq)
    ).all()
    assert len(chapters) >= 3, f"{sample.name} 应切出多级章节，实际 {len(chapters)} 节"
    assert all(chapter.title.strip() for chapter in chapters), "章节标题不能为空"
    # 父章节只做归组，正文为空是正常形态；有正文的章节必须够多
    assert sum(1 for chapter in chapters if chapter.content.strip()) >= 2

    if expect_multilevel_heading:
        assert any(
            re.search(r"\d+\.\d+", chapter.title) for chapter in chapters
        ), "PDF 的多级编号标题应被识别"

    version = db.get(DocumentVersion, version_id)
    assert version is not None
    assert version.chapter_count == len(chapters)

    # ---------- 2. 真实 Provider 路径 + 假网络 ----------
    provider = OpenAICompatProvider(
        base_url="https://api.deepseek.com/v1",
        api_key="sk-l1-fake-key-1234",
        model="deepseek-chat",
        timeout_seconds=5,
        transport=_transport_returning(
            [H.conclusion_payload(target_id=function_id, label_type="changed")]
        ),
    )
    fastapi_app.dependency_overrides[get_provider] = lambda: provider

    # ---------- 3. 带围栏的 JSON → 结论照样落库 ----------
    response = client.post(
        H.ANALYSES.format(project_id=project_id),
        json=H.analysis_payload(
            template_id=chain["template"].id,
            baseline_revision_id=chain["revision"].id,
            document_version_id=version_id,
        ),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["stats"]["chapter_count"] == len(chapters)
    # 引擎只对「有正文」的章节发起比对，父章节不送模型——以实际调用次数为准
    analyzed = len(provider.calls)
    assert analyzed > 0
    assert body["stats"]["conclusion_count"] == analyzed

    conclusions = db.scalars(
        select(IncrementalConclusion).where(
            IncrementalConclusion.analysis_id == body["id"]
        )
    ).all()
    assert len(conclusions) == analyzed
    assert {item.label_type for item in conclusions} == {"changed"}
    assert {item.target_id for item in conclusions} == {function_id}

    # ---------- 4. 运行留痕（T86）也确实写了 ----------
    log = db.scalar(
        select(LLMRunLog)
        .where(LLMRunLog.project_id == project_id, LLMRunLog.task_type == "incremental_first")
        .order_by(LLMRunLog.id.desc())
    )
    assert log is not None
    assert log.status == "succeeded"
    assert log.analysis_id == body["id"]
    assert log.call_count == analyzed
    assert log.model == "deepseek-chat"

    analysis = db.get(IncrementalAnalysis, body["id"])
    assert analysis is not None
    assert analysis.status == "succeeded"
