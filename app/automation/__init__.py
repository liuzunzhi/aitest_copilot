"""自动化执行与测试报告（09-automation）。

本包分层与 04 / 05 / 07 / 08 一致：

- `scanner.py`：**纯函数**。路径安全校验 + 文件遍历 + 规则匹配，不碰数据库、不碰配置。
- `service.py`：服务层。扫描出清单、**人工确认后**入库、资产 CRUD 与关联用例。
- `schemas.py`：请求 / 响应模型。
- `router.py`：接口层，前缀 `/api/projects/{project_id}/automation`。
- `runner.py`：执行器（T113）。
"""
