"""e2e 数据准备。

前台用例必须与开发库隔离：e2e 后端连 `<开发库>_e2e`（见 `specs/验证约定.md`），
否则会往开发库里塞项目、申请与审计记录，把后端全量 pytest 的全局断言打红。

用户没有开放注册接口（验证码在 Redis 里），所以用户直接写库；
项目、成员、申请一律走真实 API。UI 只用来验证被检查的那一步。
"""

import os
import json
import shutil
import uuid
from pathlib import Path

from playwright.sync_api import APIRequestContext
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.common.security import hash_password
from app.models.user import User

BACKEND_URL = os.getenv("E2E_BACKEND_URL", "http://127.0.0.1:8001")
ADMIN_USERNAME = os.getenv("E2E_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "Admin12345")
USER_PASSWORD = "E2ePassw0rd1"

# 自动化资产的根目录（09 期 T115）。
#
# **e2e 后端的 cwd 是仓库根**（`scripts/run_e2e.py` 用 `cwd=ROOT` 起 uvicorn），
# 而后端把 `AUTOMATION_ROOT`（默认 `var/automation`）按 cwd 解析成绝对路径——
# 所以扫描扫的就是仓库里的这个目录。不往这儿写样例文件，扫描永远返回空清单。
AUTOMATION_ROOT = Path(__file__).resolve().parents[2] / "var" / "automation"

_engine: Engine | None = None


def write_automation_samples(directory: str, files: dict[str, str]) -> Path:
    """往自动化根目录写样例资产文件，返回该子目录的绝对路径。

    `files` 每项：`{相对文件名: 文件内容}`。

    **样例文件不该留在版本库里**——`var/automation/` 已加进 `.gitignore`，
    用例收尾时再把子目录删掉（见 `remove_automation_samples`）。
    """
    target = AUTOMATION_ROOT / directory
    target.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return target


def remove_automation_samples(directory: str) -> None:
    """删掉样例子目录（含 pytest 跑出来的 `__pycache__`）。"""
    shutil.rmtree(AUTOMATION_ROOT / directory, ignore_errors=True)


def _e2e_dsn() -> str:
    """优先用 E2E_DB_DSN；否则读 .env 的开发 DSN，把库名换成 `_e2e`。

    只在本模块内部用，不改 os.environ：全量 pytest 会一并 import 本模块，
    改全局 DB_DSN 会让后端用例读到 e2e 库。
    """
    explicit = os.getenv("E2E_DB_DSN")
    if explicit:
        return explicit
    env_file = Path(__file__).resolve().parents[2] / '.env'
    for line in env_file.read_text(encoding='utf-8').splitlines():
        if line.startswith('DB_DSN='):
            parts = line.split('=', 1)[1].split('/')
            parts[-1] = 'aitest_copilot_e2e?charset=utf8mb4'
            return '/'.join(parts)
    raise RuntimeError('.env 里没有 DB_DSN，无法定位 e2e 库')


def _dev_dsn() -> str:
    """开发库 DSN（`.env` 里的原始值）。

    只给「隔离守卫」用：确认 e2e 后端没有把数据写进开发库。
    """
    env_file = Path(__file__).resolve().parents[2] / '.env'
    for line in env_file.read_text(encoding='utf-8').splitlines():
        if line.startswith('DB_DSN='):
            return line.split('=', 1)[1]
    raise RuntimeError('.env 里没有 DB_DSN，无法定位开发库')


def _session() -> Session:
    global _engine
    if _engine is None:
        _engine = create_engine(_e2e_dsn(), pool_pre_ping=True, future=True)
    return Session(_engine, expire_on_commit=False)


def cleanup_e2e_data(name_prefix: str = "e2e-") -> dict[str, int]:
    """删掉前台用例造的数据（项目名以 `e2e-` 开头，用例统一用这个前缀）。

    不清理的代价：e2e 库会越跑越大（T65 时已积到 200+ 个项目），用例变慢，
    而且 `dev_check.py` 用「admin 参与的项目集合」认库，历史数据会让判定失真。
    用户只删 `e2e-` 前缀的，`admin` 与手工造的数据不动。

    子表按外键依赖顺序删（文档章节 → 版本/标签/快照 → 结构 → 项目），
    删完把会话的外键检查恢复，不影响同连接的后续语句。
    """
    session = _session()
    counts: dict[str, int] = {}
    in_projects = "SELECT id FROM projects WHERE name LIKE :prefix"
    in_documents = (
        "SELECT d.id FROM documents d JOIN projects p ON p.id = d.project_id "
        "WHERE p.name LIKE :prefix"
    )
    statements = [
        # 10 期流程基线四表：按外键依赖倒序（快照 → 步骤 / 关联 → 场景）
        # `process_baseline_revisions` 有 project_id 直接删；
        # `process_baseline_links` / `process_baseline_steps` 有 baseline_id，
        # **要先删子表再删父表**——顺序反了会撞外键。
        (
            "process_baseline_revisions",
            f"DELETE FROM process_baseline_revisions WHERE project_id IN ({in_projects})",
        ),
        (
            "process_baseline_links",
            "DELETE FROM process_baseline_links WHERE baseline_id IN ("
            "SELECT id FROM process_baselines WHERE project_id IN ("
            f"{in_projects}))",
        ),
        (
            "process_baseline_steps",
            "DELETE FROM process_baseline_steps WHERE baseline_id IN ("
            "SELECT id FROM process_baselines WHERE project_id IN ("
            f"{in_projects}))",
        ),
        (
            "process_baselines",
            f"DELETE FROM process_baselines WHERE project_id IN ({in_projects})",
        ),
        # 09 期自动化执行三表：按外键依赖倒序（明细 → 记录 → 资产）
        (
            "automation_run_items",
            f"DELETE FROM automation_run_items WHERE project_id IN ({in_projects})",
        ),
        (
            "automation_runs",
            f"DELETE FROM automation_runs WHERE project_id IN ({in_projects})",
        ),
        (
            "automation_assets",
            f"DELETE FROM automation_assets WHERE project_id IN ({in_projects})",
        ),
        (
            "test_case_steps",
            "DELETE FROM test_case_steps WHERE case_id IN ("
            "SELECT id FROM test_cases WHERE project_id IN (" + in_projects + "))",
        ),
        (
            "test_cases",
            f"DELETE FROM test_cases WHERE project_id IN ({in_projects})",
        ),
        (
            "test_case_analyses",
            f"DELETE FROM test_case_analyses WHERE project_id IN ({in_projects})",
        ),
        (
            "test_points",
            f"DELETE FROM test_points WHERE project_id IN ({in_projects})",
        ),
        (
            "test_point_analyses",
            f"DELETE FROM test_point_analyses WHERE project_id IN ({in_projects})",
        ),
        (
            # 留痕带 project_id；不清会让 `task_type='test_point'` / `'test_case'`
            # 的数据挡住 `0022` / `0023` 降级时重建旧 CHECK（迁移往返实测）。
            "llm_run_logs",
            f"DELETE FROM llm_run_logs WHERE project_id IN ({in_projects})",
        ),
        (
            "incremental_conflicts",
            "DELETE FROM incremental_conflicts WHERE analysis_id IN ("
            "SELECT id FROM incremental_analyses WHERE project_id IN ("
            f"{in_projects}))",
        ),
        (
            "incremental_decisions",
            "DELETE FROM incremental_decisions WHERE analysis_id IN ("
            "SELECT id FROM incremental_analyses WHERE project_id IN ("
            f"{in_projects}))",
        ),
        (
            "incremental_conclusions",
            "DELETE FROM incremental_conclusions WHERE analysis_id IN ("
            "SELECT id FROM incremental_analyses WHERE project_id IN ("
            f"{in_projects}))",
        ),
        (
            "incremental_analyses",
            f"DELETE FROM incremental_analyses WHERE project_id IN ({in_projects})",
        ),
        (
            "document_chapter_links",
            "DELETE FROM document_chapter_links WHERE version_id IN ("
            "SELECT dv.id FROM document_versions dv WHERE dv.document_id IN ("
            f"{in_documents}))",
        ),
        (
            "document_chapters",
            "DELETE FROM document_chapters WHERE version_id IN ("
            "SELECT dv.id FROM document_versions dv WHERE dv.document_id IN ("
            f"{in_documents}))",
        ),
        ("baseline_labels", f"DELETE FROM baseline_labels WHERE project_id IN ({in_projects})"),
        ("baseline_revisions", f"DELETE FROM baseline_revisions WHERE project_id IN ({in_projects})"),
        ("baseline_snapshots", f"DELETE FROM baseline_snapshots WHERE project_id IN ({in_projects})"),
        (
            "baseline_derive_candidates",
            f"DELETE FROM baseline_derive_candidates WHERE project_id IN ({in_projects})",
        ),
        ("baseline_derives", f"DELETE FROM baseline_derives WHERE project_id IN ({in_projects})"),
        (
            "document_versions",
            f"DELETE FROM document_versions WHERE document_id IN ({in_documents})",
        ),
        (
            "baseline_feature_points",
            f"DELETE FROM baseline_feature_points WHERE project_id IN ({in_projects})",
        ),
        ("baseline_functions", f"DELETE FROM baseline_functions WHERE project_id IN ({in_projects})"),
        ("baseline_modules", f"DELETE FROM baseline_modules WHERE project_id IN ({in_projects})"),
        ("documents", f"DELETE FROM documents WHERE project_id IN ({in_projects})"),
        (
            "project_applications",
            f"DELETE FROM project_applications WHERE project_id IN ({in_projects})",
        ),
        ("project_members", f"DELETE FROM project_members WHERE project_id IN ({in_projects})"),
        ("audit_logs", f"DELETE FROM audit_logs WHERE project_id IN ({in_projects})"),
        ("projects", "DELETE FROM projects WHERE name LIKE :prefix"),
    ]
    try:
        session.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table, sql in statements:
            affected = session.execute(text(sql), {"prefix": f"{name_prefix}%"}).rowcount or 0
            if affected:
                counts[table] = affected
        session.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        session.commit()
    finally:
        session.close()
    return counts


def seed_analysis_conclusions(analysis_id: int, targets: list[dict]) -> None:
    """给一次增量分析补写「局部结论」与「丢弃明细」。

    本期模型侧只有 `MockProvider`（默认返回空结论），发起分析跑不出真实结论；
    前台用例又要核对结论表 / 丢弃表的展示，所以按真实表结构直接写 e2e 库。
    只造数，不绕过任何被验证的接口——结论仍由详情 / 结论接口读出。

    `targets` 每项：
        {target_type, target_id, label_type, rationale}
        discard=True 时改成写进 `stats.discarded`，用 `code` 指定丢弃标识。
    """
    session = _session()
    try:
        analysis = session.execute(
            text(
                "SELECT document_version_id, stats FROM incremental_analyses "
                "WHERE id = :id"
            ),
            {"id": analysis_id},
        ).first()
        assert analysis is not None, f"分析记录 {analysis_id} 不存在"
        version_id, raw_stats = analysis
        chapters = session.execute(
            text(
                "SELECT id, title FROM document_chapters "
                "WHERE version_id = :version_id AND char_count > 0 ORDER BY seq"
            ),
            {"version_id": version_id},
        ).all()
        assert chapters, "生效版本没有可分析的章节"

        stats = raw_stats
        if isinstance(stats, str):
            stats = json.loads(stats or "{}")
        stats = dict(stats or {})
        conclusions: list[dict] = []
        discarded: list[dict] = []

        for index, target in enumerate(targets):
            chapter_id, chapter_title = chapters[index % len(chapters)]
            if target.get("discard"):
                discarded.append(
                    {
                        "chapter_id": chapter_id,
                        "chapter_title": chapter_title,
                        "target_type": target["target_type"],
                        "target_id": target["target_id"],
                        "label_type": target["label_type"],
                        "code": target.get("code", "INCREMENTAL_LABEL_NEW_DROPPED"),
                    }
                )
                continue
            session.execute(
                text(
                    "INSERT INTO incremental_conclusions (analysis_id, chapter_id,"
                    " chapter_title, target_type, target_id, label_type, confidence,"
                    " rationale, created_at) VALUES (:analysis_id, :chapter_id,"
                    " :chapter_title, :target_type, :target_id, :label_type,"
                    " :confidence, :rationale, NOW(3))"
                ),
                {
                    "analysis_id": analysis_id,
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "target_type": target["target_type"],
                    "target_id": target["target_id"],
                    "label_type": target["label_type"],
                    "confidence": target.get("confidence", 0.9),
                    "rationale": target.get("rationale"),
                },
            )
            conclusions.append(target)

        stats["conclusion_count"] = len(conclusions)
        stats["discarded_count"] = len(discarded)
        stats["dropped_new_count"] = sum(
            1 for item in discarded if item["code"] == "INCREMENTAL_LABEL_NEW_DROPPED"
        )
        stats["discarded"] = discarded
        session.execute(
            text("UPDATE incremental_analyses SET stats = :stats WHERE id = :id"),
            {"stats": json.dumps(stats, ensure_ascii=False), "id": analysis_id},
        )
        session.commit()
    finally:
        session.close()


def seed_chapter_links(version_id: int, links: list[dict]) -> None:
    """给一个文档版本补写章节引用边。

    `links` 每项：
    `{from_chapter_id, link_type, to_chapter_id?, entity?, source?, status?, rationale?, confidence?}`

    - `source` 默认 `manual`（人工补链）；`rule` = 规则抽取；`ai` = AI 分析产出；
    - `status` 默认 `approved`（人工边 / 规则边天然已生效）；
      要造「待评审」的 AI 边显式传 `status="pending"`；
    - `rationale` 默认 None（只有 AI 边才有分析理由）。
    """
    session = _session()
    try:
        for link in links:
            session.execute(
                text(
                    "INSERT INTO document_chapter_links (version_id, from_chapter_id,"
                    " to_chapter_id, link_type, entity, confidence, source, status,"
                    " rationale, created_by, created_at) VALUES (:version_id,"
                    " :from_chapter_id, :to_chapter_id, :link_type, :entity,"
                    " :confidence, :source, :status, :rationale, :created_by, NOW(3))"
                ),
                {
                    "version_id": version_id,
                    "from_chapter_id": link["from_chapter_id"],
                    "to_chapter_id": link.get("to_chapter_id"),
                    "link_type": link.get("link_type", "references"),
                    "entity": link.get("entity"),
                    "confidence": link.get("confidence"),
                    "source": link.get("source", "manual"),
                    "status": link.get("status", "approved"),
                    "rationale": link.get("rationale"),
                    "created_by": link.get("created_by", 1),
                },
            )
        session.commit()
    finally:
        session.close()


def seed_test_points(
    analysis_id: int | None,
    project_id: int,
    rows: list[dict],
    *,
    created_by: int = 1,
) -> list[int]:
    """给一次测试点生成记录补写测试点。

    MockProvider 返回的占位 `target_id` 一定越界（不在基线清单内），
    发起生成只会得到 `succeeded` + 0 条测试点；
    前台用例又要核对「生成 → 列表 → 评审通过」的展示与操作，
    所以按真实表结构直接写 e2e 库。只造数——评审仍走真实 `review` 接口。

    `analysis_id` 传 `None` 表示「没有来源批次」——该列有外键，
    塞 0 会直接撞 1452。

    `rows` 每项：{name, target_type, target_id, target_name, priority?,
    precondition?, verification?, chapter_id?, chapter_title?, status?}
    """
    session = _session()
    inserted: list[int] = []
    try:
        for item in rows:
            result = session.execute(
                text(
                    "INSERT INTO test_points (project_id, analysis_id, name, target_type,"
                    " target_id, target_name, priority, precondition, verification,"
                    " chapter_id, chapter_title, status, source_type, created_by,"
                    " created_at, updated_at) VALUES (:project_id, :analysis_id, :name,"
                    " :target_type, :target_id, :target_name, :priority, :precondition,"
                    " :verification, :chapter_id, :chapter_title, :status, 'llm',"
                    " :created_by, NOW(3), NOW(3))"
                ),
                {
                    "project_id": project_id,
                    "analysis_id": analysis_id,
                    "name": item["name"],
                    "target_type": item["target_type"],
                    "target_id": item["target_id"],
                    "target_name": item["target_name"],
                    "priority": item.get("priority", "medium"),
                    "precondition": item.get("precondition"),
                    "verification": item.get("verification"),
                    "chapter_id": item.get("chapter_id"),
                    "chapter_title": item.get("chapter_title"),
                    "status": item.get("status", "pending"),
                    "created_by": created_by,
                },
            )
            inserted.append(int(result.lastrowid))
        session.commit()
    finally:
        session.close()
    return inserted


def seed_second_pass_rows(
    analysis_id: int,
    *,
    decisions: list[dict] | None = None,
    conflicts: list[dict] | None = None,
) -> None:
    """给一次分析补写第二遍的裁决与冲突。

    Mock 第二遍默认返回 `unchanged`，能跑出裁决，但冲突 / 新增要展示就得造数。
    只造数，不绕过被验证的接口——裁决动作仍走真实 `resolve` 接口。

    `decisions` 每项：{target_type, target_id, target_name, decision, confidence?, rationale?}
    `conflicts` 每项：{target_type, target_id, target_name, conflict_type, candidates}
    """
    session = _session()
    try:
        for item in decisions or []:
            session.execute(
                text(
                    "INSERT INTO incremental_decisions (analysis_id, target_type,"
                    " target_id, target_name, decision, confidence, rationale, evidence,"
                    " created_at) VALUES (:analysis_id, :target_type, :target_id,"
                    " :target_name, :decision, :confidence, :rationale, :evidence,"
                    " NOW(3))"
                ),
                {
                    "analysis_id": analysis_id,
                    "target_type": item["target_type"],
                    "target_id": item["target_id"],
                    "target_name": item["target_name"],
                    "decision": item.get("decision", "changed"),
                    "confidence": item.get("confidence", 0.8),
                    "rationale": item.get("rationale"),
                    "evidence": json.dumps(item.get("evidence", {}), ensure_ascii=False),
                },
            )
        for item in conflicts or []:
            session.execute(
                text(
                    "INSERT INTO incremental_conflicts (analysis_id, target_type,"
                    " target_id, target_name, conflict_type, candidates, status,"
                    " created_at) VALUES (:analysis_id, :target_type, :target_id,"
                    " :target_name, :conflict_type, :candidates, 'pending', NOW(3))"
                ),
                {
                    "analysis_id": analysis_id,
                    "target_type": item["target_type"],
                    "target_id": item.get("target_id"),
                    "target_name": item["target_name"],
                    "conflict_type": item.get("conflict_type", "conflict"),
                    "candidates": json.dumps(
                        item.get("candidates", []), ensure_ascii=False
                    ),
                },
            )
        session.commit()
    finally:
        session.close()


def seed_todo_counts(
    project_id: int,
    *,
    baseline_reviews: int = 0,
    test_points: int = 0,
    test_cases: int = 0,
    created_by: int = 1,
) -> None:
    """给工作台待办计数造数（T110.5 · AC-193）。

    三项待办的行结构各不相同，且各有必填列（审核记录要 `status`、
    测试点要 `target_*`、用例要 `test_point_name` 与 `target_*`），
    所以分三段 INSERT 而不是拼一条通用语句。

    只造数——三项的状态变更仍走真实接口。
    """
    session = _session()
    try:
        for _ in range(baseline_reviews):
            session.execute(
                text(
                    "INSERT INTO baseline_revisions (project_id, status, structure_json,"
                    " module_count, function_count, feature_point_count, label_count,"
                    " created_at) VALUES (:project_id, 'submitted', NULL, 0, 0, 0, 0, NOW(3))"
                ),
                {"project_id": project_id},
            )
        for index in range(test_points):
            session.execute(
                text(
                    "INSERT INTO test_points (project_id, analysis_id, name, target_type,"
                    " target_id, target_name, priority, status, source_type, created_by,"
                    " created_at, updated_at) VALUES (:project_id, NULL, :name, 'function',"
                    " 1, '功能', 'medium', 'pending', 'llm', :created_by, NOW(3), NOW(3))"
                ),
                {
                    "project_id": project_id,
                    "name": f"待评审测试点-{index}",
                    "created_by": created_by,
                },
            )
        for index in range(test_cases):
            session.execute(
                text(
                    "INSERT INTO test_cases (project_id, analysis_id, test_point_id,"
                    " test_point_name, title, case_type, priority, target_type, target_id,"
                    " target_name, status, source_type, created_by, created_at, updated_at)"
                    " VALUES (:project_id, NULL, 1, '待评审测试点', :title, 'functional',"
                    " 'medium', 'function', 1, '功能', 'pending', 'llm', :created_by,"
                    " NOW(3), NOW(3))"
                ),
                {
                    "project_id": project_id,
                    "title": f"待评审用例-{index}",
                    "created_by": created_by,
                },
            )
        session.commit()
    finally:
        session.close()


def create_user(global_role: str = "user") -> dict:
    """直接在 e2e 库里造一个可登录用户（用户名带 uuid，不撞已有数据）。"""
    payload = {
        "username": f"e2e-{uuid.uuid4().hex[:10]}",
        "password": USER_PASSWORD,
    }
    session = _session()
    try:
        user = User(
            username=payload["username"],
            password_hash=hash_password(USER_PASSWORD),
            global_role=global_role,
        )
        session.add(user)
        session.commit()
        payload["id"] = user.id
    finally:
        session.close()
    return payload


def token_for(ctx: APIRequestContext, username: str, password: str) -> str:
    response = ctx.post(
        "/api/auth/login", data={"username": username, "password": password}
    )
    assert response.ok, response.text()
    return response.json()["access_token"]


def storage_state(base_url: str, token: str) -> dict:
    """把令牌塞进 localStorage，省掉每个用例都走一遍登录表单。"""
    return {
        "cookies": [],
        "origins": [
            {
                "origin": base_url.rstrip("/"),
                "localStorage": [{"name": "aitest.token", "value": token}],
            }
        ],
    }


class Api:
    """以系统管理员身份造数；需要别的身份时用 `token_for` 换令牌。"""

    def __init__(self, ctx: APIRequestContext):
        self.ctx = ctx
        self.admin_token = token_for(ctx, ADMIN_USERNAME, ADMIN_PASSWORD)

    def _headers(self, token: str | None = None) -> dict:
        return {"Authorization": f"Bearer {token or self.admin_token}"}

    def create_project(self, name: str, description: str | None = None, token: str | None = None) -> dict:
        response = self.ctx.post(
            "/api/projects",
            data={"name": name, "description": description},
            headers=self._headers(token),
        )
        assert response.status in (200, 201), response.text()
        return response.json()

    def archive_project(self, project_id: int) -> None:
        response = self.ctx.post(
            f"/api/projects/{project_id}/archive", headers=self._headers()
        )
        assert response.ok, response.text()

    def add_member(self, project_id: int, user_id: int, role: str) -> None:
        response = self.ctx.post(
            f"/api/projects/{project_id}/members",
            data={"user_id": user_id, "role": role},
            headers=self._headers(),
        )
        assert response.status in (200, 201), response.text()

    def submit_application(
        self, project_id: int, token: str, reason: str = "e2e 前台核对"
    ) -> None:
        response = self.ctx.post(
            f"/api/projects/{project_id}/applications",
            data={"reason": reason, "desired_role": "member"},
            headers=self._headers(token),
        )
        assert response.status in (200, 201), response.text()

    def set_role(self, user_id: int, global_role: str) -> None:
        """改全局角色，用管理员令牌（AC-45 的后台动作，前台只负责展示结果）。"""
        response = self.ctx.patch(
            f"/api/admin/users/{user_id}/role",
            data={"global_role": global_role},
            headers=self._headers(),
        )
        assert response.ok, response.text()
