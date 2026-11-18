"""模型输出的 JSON 解析容错。

真实模型（DeepSeek / 通义千问等）**必然**会返回带 Markdown 代码块的 JSON：

    ```json
    {"conclusions": [...]}
    ```

裸 `json.loads` 遇到这种输入会抛 `JSONDecodeError`，整次分析直接 502。
所以这里提供一个**纯函数**做入口加固。

容错的边界很窄——**只放宽「怎么把响应读成 JSON」，不放宽「什么算合法结论」**：

- 只做三件事：剥围栏、兜底取平衡括号区间、失败就报错；
- **不做「智能修复」**（补引号、截断补全、JSON5 容错）：
  那些会掩盖模型输出的真实问题，让「模型返回了坏 JSON」变成「平台悄悄改对了」，
  排查时更难定位。围栏与前置说明是**格式噪声**，去掉它是还原原文；
  补引号是**猜测**，不做。

错误消息**不含原始响应正文**——模型输出里可能夹带不该进日志的内容。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.common.errors import LLMOutputInvalid

# Markdown 围栏：```json ... ``` 或 ``` ... ```。
# `json` 大小写不敏感；`re.S` 让 `.` 能跨行（围栏内常带换行）。
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def strip_code_fence(content: str) -> str:
    """去掉 Markdown 围栏。

    只剥**最外层**的一层围栏：模型偶尔会在 JSON 字符串里写 ```，
    但那在 JSON 内部，不在围栏边界上，所以剥最外层是安全的。
    """
    match = _FENCE_RE.search(content)
    if match is None:
        return content
    return match.group(1).strip()


def extract_json_block(content: str) -> str | None:
    """取第一个 `{` 到最后一个 `}` 的区间。

    应对「前面带一句说明文字」的情况（如「好的，结果如下：{...}」）。
    只取**最外层**区间，不做括号配对——模型输出里的 `{` `}` 配对关系
    不可靠，硬配对反而容易取错。取不到返回 None。
    """
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return content[start : end + 1]


def parse_llm_json(content: str) -> Any:
    """把模型输出读成 JSON。

    解析顺序（**只做这几步**）：

    1. `strip()`；
    2. 剥 Markdown 围栏；
    3. 仍失败 → 取第一个 `{` 到最后一个 `}` 的区间再试一次；
    4. 仍失败 → 抛 `LLMOutputInvalid`，**消息不含原始响应正文**。

    纯函数、无 IO，可脱离数据库单测。
    """
    if not isinstance(content, str):
        raise LLMOutputInvalid("模型返回不是合法 JSON")

    candidate = content.strip()
    for text in _candidates(candidate):
        try:
            return json.loads(text)
        except ValueError:
            continue

    raise LLMOutputInvalid("模型返回不是合法 JSON")


def _candidates(candidate: str) -> list[str]:
    """按顺序给出待尝试的解析文本。"""
    attempts = [candidate]

    unfenced = strip_code_fence(candidate)
    if unfenced != candidate:
        attempts.append(unfenced)

    # 围栏里也可能带前缀说明（```json 好的，结果如下：{...} ```）
    block = extract_json_block(unfenced)
    if block is not None and block != unfenced:
        attempts.append(block)

    # 兜底：直接从原文里取区间
    block = extract_json_block(candidate)
    if block is not None and block not in attempts:
        attempts.append(block)

    return attempts


__all__ = ["extract_json_block", "parse_llm_json", "strip_code_fence"]
