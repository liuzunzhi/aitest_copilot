"""分析记录生命周期（T69 实现）。

固定校验顺序（spec §5）：项目 → 归档 → 角色 → 模板 → 快照 → 文档版本。
第 4–6 步失败不建行，因此不会留下「脏记录」。

第一遍同步执行：

    insert(status='running') → 跑第一遍 → 回填 stats/status/finished_at

失败处理：引擎抛出的异常在这里统一落成 `status='failed'` + `error_code` +
`error_message` + `finished_at`，**立刻返回/抛出**，不进入下一章、不做重试。
已落库的结论保留，便于排查模型返回了什么。

审计：`incremental.analysis.create`，遵循「改数据 → flush → write_audit → commit」，
`write_audit` 内部不 commit。
"""
