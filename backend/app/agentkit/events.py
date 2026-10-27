"""
文件：app/agentkit/events.py
作用：事件协议（docs/protocols/event_protocol.md）的代码侧唯一事实源。

提供三样东西：
- EventType    : 全部事件类型常量，业务代码禁止散写字符串字面量
- review_channel: Redis 频道命名单一事实源（AgentBus / SSEManager 共用）
- emit         : 带类型校验的发布入口，未知类型只告警不拦截（协议演进期兼容）

新增事件类型：先在协议文档登记 + 此处加常量，再在发布方使用。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventType:
    """事件类型注册表（与 docs/protocols/event_protocol.md §2 保持一致）。"""

    # 生命周期
    PHASE_CHANGED = "phase_changed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"

    # Agent 执行
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"

    # 风险产出
    FINDING_ADDED = "finding_added"
    RISK_ESCALATED = "risk_escalated"
    EVIDENCE_FOUND = "evidence_found"
    CONTRADICTION_DETECTED = "contradiction_detected"

    # 上下文装配（M2' 装配层发布）
    CONTEXT_ASSEMBLED = "context_assembled"
    SKILLS_MATCHED = "skills_matched"
    MEMORY_LOADED = "memory_loaded"

    # 工具治理（M3' 权限钩子发布）
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    TOOL_PERMISSION_PENDING = "tool_permission_pending"
    # HITL 审批裁决（HITL_ENABLED 开启时发出，协议已登记）
    TOOL_PERMISSION_APPROVED = "tool_permission_approved"
    TOOL_PERMISSION_REJECTED = "tool_permission_rejected"

    # 面向前端
    PROGRESS = "progress"


# 全量注册表：emit() 用它校验类型；import 它做穷举检查
EVENT_TYPES: frozenset[str] = frozenset(
    value
    for name in dir(EventType)
    if not name.startswith("_")
    for value in [getattr(EventType, name)]
    if isinstance(value, str)
)


def review_channel(session_id: int | str) -> str:
    """审查会话 Redis 频道名（单一事实源，禁止各处硬编码）。"""
    return f"review:{session_id}:events"


async def emit(bus: Any, event_type: str, payload: dict[str, Any]) -> None:
    """经事件总线发布事件；类型不在注册表时告警（协议文档未登记）。"""
    if event_type not in EVENT_TYPES:
        logger.warning(
            "emit 未注册的事件类型 %r（先在 docs/protocols/event_protocol.md 登记）",
            event_type,
        )
    await bus.publish(event_type, payload)
