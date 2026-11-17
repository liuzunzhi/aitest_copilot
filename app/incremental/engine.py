"""第一遍引擎（T69 实现）。

只负责产出结论，不写库——丢弃判定因此可以纯函数级测试，不必起 HTTP。

执行策略（本期同步）：

- 逐章节调用 `LLMProvider.chat`，章节按 `seq` 升序、跳过 `char_count == 0`；
- **单章失败即整体失败**：Provider 抛错或返回非 JSON 时立即中止循环，
  抛出对应业务错误（`LLM_CALL_FAILED` / `LLM_OUTPUT_INVALID`），
  不继续跑后续章节、不静默吞掉异常。同步请求下这是唯一能让前端
  立刻拿到 `failed` 而不干等的做法；第二期接真实模型、引入后台队列后
  再改成异步重试。
- 单条结论分类：越界 → `INCREMENTAL_TARGET_OUT_OF_BASELINE`；
  `label_type='new'` → `INCREMENTAL_LABEL_NEW_DROPPED`；其余待落库。
"""
