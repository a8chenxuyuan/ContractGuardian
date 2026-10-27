"""
文件：app/agentkit/context/manager.py
作用：上下文装配唯一入口（协议 docs/protocols/context_assembly.md）。

assemble() 流程：
1. 逐层按 layer_limits 套用策略（默认 truncate）——层内裁剪
2. 总额仍超 max_total_tokens 时：先整层丢弃 LOW 优先级层，
   仍超则按比例截断剩余层（溢出降级顺序 LOW→NORMAL→HIGH）
3. 产出 ContextReport（各层占用/丢弃统计）
4. 给定 bus 时发布 context_assembled 事件（接入事件流可审计）

业务方禁止自行拼接 + 手工截断，一律经本入口。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from app.agentkit.context.budget import Budget
from app.agentkit.context.strategy import LayerResult, get_strategy
from app.agentkit.context.tokens import TokenCounter, get_token_counter


class Priority(IntEnum):
    """层优先级：数值越小越先被裁掉。"""

    LOW = 0
    NORMAL = 1
    HIGH = 2


@dataclass
class Layer:
    """一个 prompt 层。"""

    name: str
    content: str
    priority: Priority = Priority.NORMAL
    strategy: str = "truncate"


@dataclass
class LayerStat:
    """单层装配统计。"""

    original_tokens: int
    kept_tokens: int
    strategy: str
    dropped: bool


@dataclass
class ContextReport:
    """装配报告（随 context_assembled 事件发布）。"""

    layer_stats: dict[str, LayerStat] = field(default_factory=dict)
    total_tokens: int = 0
    dropped_layers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_stats": {
                name: vars(stat) for name, stat in self.layer_stats.items()
            },
            "total_tokens": self.total_tokens,
            "dropped_layers": self.dropped_layers,
        }


@dataclass
class AssembledContext:
    """装配结果：最终文本 + 报告；parts 为各层裁剪后内容（供模板化 prompt 按槽位取用）。"""

    text: str
    report: ContextReport
    parts: dict[str, str] = field(default_factory=dict)


class ContextManager:
    """上下文装配器（唯一入口）。"""

    def __init__(
        self,
        budget: Budget | None = None,
        counter: TokenCounter | None = None,
    ):
        self.budget = budget or Budget.from_config()
        self.counter = counter or get_token_counter()

    def assemble(
        self,
        layers: list[Layer],
        budget: Budget | None = None,
        bus: Any = None,
    ) -> AssembledContext:
        """装配全部层，返回最终文本与报告；给定 bus 时发布装配事件。"""
        budget = budget or self.budget
        report = ContextReport()

        # ---- 第 1 步：逐层按配额套策略（层内裁剪）----
        kept: list[tuple[Layer, LayerResult]] = []
        for layer in layers:
            if not layer.content:
                continue
            limit = budget.layer_limits.get(layer.name, budget.max_total_tokens)
            result = get_strategy(layer.strategy).apply(layer.content, limit, self.counter)
            report.layer_stats[layer.name] = LayerStat(
                original_tokens=result.original_tokens,
                kept_tokens=result.kept_tokens,
                strategy=result.strategy,
                dropped=result.dropped,
            )
            kept.append((layer, result))

        # ---- 第 2 步：总额超预算时按优先级降级 ----
        # 总额含层间分隔符 "\n\n"（按每处 1 token 保守估算），避免恰好卡满时溢出
        total = sum(r.kept_tokens for _, r in kept) + max(0, len(kept) - 1)
        if total > budget.max_total_tokens:
            # 2a. 先整层丢弃 LOW 层（从已装配的最低优先级开始）
            droppable = [
                i for i, (layer, _) in enumerate(kept)
                if layer.priority == Priority.LOW
            ]
            for i in sorted(droppable, key=lambda x: -x):
                layer, _ = kept.pop(i)
                report.dropped_layers.append(layer.name)
                total -= report.layer_stats[layer.name].kept_tokens + 1
                report.layer_stats[layer.name].dropped = True
            # 2b. 仍超：按比例截断剩余层内容，直到装得下
            if total > budget.max_total_tokens and kept:
                ratio = (budget.max_total_tokens / total) * 0.98  # 留 2% 余量
                for i, (layer, result) in enumerate(kept):
                    target = max(1, int(result.kept_tokens * ratio))
                    rescaled = get_strategy(layer.strategy).apply(
                        result.content, target, self.counter
                    )
                    kept[i] = (layer, rescaled)
                    report.layer_stats[layer.name].kept_tokens = rescaled.kept_tokens

        # ---- 第 3 步：拼接 + 报告 ----
        text = "\n\n".join(r.content for _, r in kept)
        report.total_tokens = self.counter.count(text)
        parts = {layer.name: result.content for layer, result in kept}

        # ---- 第 4 步：发布装配事件（事件协议 CONTEXT_ASSEMBLED）----
        if bus is not None:
            from app.agentkit.events import EventType, emit

            try:
                import asyncio

                asyncio.get_running_loop()
                asyncio.ensure_future(
                    emit(bus, EventType.CONTEXT_ASSEMBLED, {"report": report.to_dict()})
                )
            except RuntimeError:
                # 无运行中事件循环（同步调用场景）：跳过事件，不影响装配
                pass

        return AssembledContext(text=text, report=report, parts=parts)
