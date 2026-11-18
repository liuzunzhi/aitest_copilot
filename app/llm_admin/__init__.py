"""06-real-llm · 配置管理与模板管理（T85）。

两个管理面：

- **大模型配置**（`/api/admin/llm-providers`）：全局唯一默认，
  API Key 只存密文、只出掩码；
- **提示词模板**（`/api/admin/prompt-templates`）：只做列表 + 编辑，
  **不做新建 / 删除**。

外加一个只读面（`/api/prompt-templates`）：登录用户可见的可用模板列表，
供 05 项目页动态渲染模板下拉。

**明文边界**（spec §5.3，硬约束）：响应 / 审计 / 日志 / 异常 / 运行日志里
一律不出现 API Key 明文，也**不出现密文**——响应只给 `api_key_masked`。
"""

__all__: list[str] = []
