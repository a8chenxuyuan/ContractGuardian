"""
文件：app/agentkit/context/strategy.py
作用：层内裁剪策略（协议 docs/protocols/context_assembly.md §2 策略注册制）。

首发实现 truncate；预留 offload（大结果落盘留占位符）、compress
（LLM 结构化压缩）——实现 ContextStrategy 协议后注册即可，
manager 与业务方零改动。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.agentkit.context.tokens import TokenCounter

TRUNCATION_MARKER = "\n…[超出预算已截断]"


@dataclass
class LayerResult:
    """策略执行结果。"""

    content: str
    original_tokens: int
    kept_tokens: int
    strategy: str
    dropped: bool = False


@runtime_checkable
class ContextStrategy(Protocol):
    """层内裁剪策略协议。"""

    name: str

    def apply(self, content: str, limit_tokens: int, counter: TokenCounter) -> LayerResult: ...


class TruncateStrategy:
    """按 token 上限截断，保留头部 + 截断标记（首发实现）。"""

    name = "truncate"

    def apply(self, content: str, limit_tokens: int, counter: TokenCounter) -> LayerResult:
        original = counter.count(content)
        if original <= limit_tokens or not content:
            return LayerResult(content, original, original, self.name)

        # 二分逼近：估算每 token 字符数，截到标记与内容合计不超过上限
        lo, hi = 0, len(content)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if counter.count(content[:mid] + TRUNCATION_MARKER) <= limit_tokens:
                lo = mid
            else:
                hi = mid - 1
        kept = content[:lo] + TRUNCATION_MARKER
        return LayerResult(kept, original, counter.count(kept), self.name, dropped=True)


# 策略注册表：新策略实现 ContextStrategy 后按名注册
STRATEGIES: dict[str, ContextStrategy] = {
    "truncate": TruncateStrategy(),
    # "offload": OffloadStrategy(),   # 触发条件：出现万字级工具返回
    # "compress": CompressStrategy(), # 触发条件：history 层长期为 top 消耗
}


def get_strategy(name: str) -> ContextStrategy:
    """按名取策略；未知策略回落 truncate（渐进迁移期兼容）。"""
    return STRATEGIES.get(name, STRATEGIES["truncate"])
