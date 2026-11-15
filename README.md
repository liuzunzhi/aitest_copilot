# AI 辅助测试平台 · 后端

按 Spec Coding 流程实现。规范文档在 `D:\学习\AI辅助测试平台\specs\`。

## 能力模块

| 模块 | spec | 状态 |
|---|---|---|
| 01-auth 登录、注册与项目申请 | `specs/01-auth/` | 进行中 |

## 环境要求

- Python 3.11+
- MySQL 8.0.46（Docker 容器 `aitest-mysql`，库 `aitest_copilot_v2`）
- Redis 7（Docker 容器 `busy_blackwell`）

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

健康检查：

```powershell
curl http://localhost:8000/health
# {"status":"ok"}
```

## 开发约定

- 时间一律 UTC。数据库连接建立后强制 `SET time_zone = '+00:00'`。
- 一个任务一次提交，任务清单见 `specs/01-auth/tasks.md`。
- 测试命名 `test_ac_XX_*`，与 spec 的验收标准编号一一对应。
