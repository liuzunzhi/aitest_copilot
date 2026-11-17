"""增量分析（05-incremental 第一期）。

本期只做第一遍：章节 → MockProvider 比对 → 局部结论落库。

模块划分：

- `context.py` Prompt 组装 + 基线索引（T69）
- `engine.py` 第一遍引擎，只产出不写库（T69）
- `service.py` 记录生命周期、落库、丢弃留痕（T69）
- `router.py` 四个接口（T69）

红线：不写真实网络请求、不做模板管理 UI、不做第二遍、不写产出段。
"""
