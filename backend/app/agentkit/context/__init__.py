"""
文件：app/agentkit/context/__init__.py
作用：装配层（架构 L2）公共出口。

协议：docs/protocols/context_assembly.md（冻结）
所有上下文组装经 ContextManager.assemble()，禁止业务代码手工拼接+截断。
"""

from app.agentkit.context.budget import Budget
from app.agentkit.context.manager import (
    AssembledContext,
    ContextManager,
    ContextReport,
    Layer,
    LayerStat,
    Priority,
)
from app.agentkit.context.strategy import (
    STRATEGIES,
    ContextStrategy,
    LayerResult,
    TruncateStrategy,
)
from app.agentkit.context.tokens import CharEstimator, TokenCounter, get_token_counter

__all__ = [
    "AssembledContext",
    "Budget",
    "CharEstimator",
    "ContextManager",
    "ContextReport",
    "ContextStrategy",
    "Layer",
    "LayerResult",
    "LayerStat",
    "Priority",
    "STRATEGIES",
    "TokenCounter",
    "TruncateStrategy",
    "get_token_counter",
]
