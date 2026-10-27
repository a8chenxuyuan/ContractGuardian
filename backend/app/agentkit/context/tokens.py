"""
文件：app/agentkit/context/tokens.py
作用：token 计数抽象（协议 docs/protocols/context_assembly.md §1）。

调用方只依赖 TokenCounter 协议；接入第二模型时替换实现即可，
预算与装配逻辑零改动。
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable


@runtime_checkable
class TokenCounter(Protocol):
    """token 计数协议。"""

    def count(self, text: str) -> int: ...


class CharEstimator:
    """字符估算器（首发实现）。

    估算规则：ASCII 字符按 4 字符≈1 token（业界经验值）；
    非 ASCII（中文等）按 2 单位≈1 token——Qwen/GPT 系中文分词
    大致 1~1.5 字/token，取 0.5 token/字 略偏保守以避免低估超窗。
    """

    def count(self, text: str) -> int:
        if not text:
            return 0
        ascii_units = sum(1 for ch in text if ord(ch) < 128)
        other_units = (len(text) - ascii_units) * 2
        return math.ceil((ascii_units + other_units) / 4)


def get_token_counter() -> TokenCounter:
    """当前唯一计数实现；换真 tokenizer 时只改这里。"""
    return CharEstimator()
