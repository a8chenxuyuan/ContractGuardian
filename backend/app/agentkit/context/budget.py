"""
文件：app/agentkit/context/budget.py
作用：装配层分层预算模型（协议 docs/protocols/context_assembly.md §1）。

每个 prompt 层有独立 token 配额，总预算由 settings 配置；
换模型/调预算只改配置，不改业务代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 代码侧默认配额（settings 里可用 CONTEXT_LAYER_LIMITS 覆盖同名层）
DEFAULT_LAYER_LIMITS: dict[str, int] = {
    "system": 4000,
    "skills": 3000,
    "memory": 2000,
    "history": 16000,
    "tool": 8000,
}


@dataclass
class Budget:
    """分层预算：总 token 上限 + 各层 token 上限。"""

    max_total_tokens: int = 32000
    layer_limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LAYER_LIMITS))

    @classmethod
    def from_config(cls) -> "Budget":
        """读项目配置构建预算；未配置的层回落到代码默认值。"""
        from app.core.config import get_settings

        settings: Any = get_settings()
        # 覆盖式合并：配置里写空 dict（pydantic 默认值）时全部用代码默认
        overrides = dict(getattr(settings, "CONTEXT_LAYER_LIMITS", None) or {})
        return cls(
            max_total_tokens=int(getattr(settings, "CONTEXT_MAX_TOKENS", 32000)),
            layer_limits={**DEFAULT_LAYER_LIMITS, **overrides},
        )
