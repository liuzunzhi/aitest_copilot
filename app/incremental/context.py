"""Prompt 组装与基线索引（T69 实现）。

组装规则（AC-78）：

    system = template.system_prompt
    user   = f"{template.user_prompt}\n\n## 章节：{chapter.title}\n{chapter.content}"

基线索引：从比对基准快照对应的**当前**结构表取功能 / 功能点 id → name，
排除归档模块及其下属。目标不在索引里即越界（AC-79）。
"""
