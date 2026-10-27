"""
文件：app/agentkit/approval.py
作用：HITL 审批的挂起/等待/裁决（协议 plugin_registry.md §2 approve 态的终态实现）。

流程（HITL_ENABLED 开启时）：
    _call_tool 遇 approve
      → create_request 登记 pending（Redis 键 tool:approval:{id}）
      → wait_for_decision 每秒轮询，直到被裁决或超时
      → 审批方经 routers/approvals.py 调 decide 写 approved/denied
      → 等待方拿到终态交回 _call_tool 发事件

边界约定：
- 超时按拒绝处理（宁可拒绝不放行）；
- Redis 不可用 = 该工具调用直接拒绝（不静默放行）；
- 裁决只允许 pending → approved/denied 一次流转，防重复裁决。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from app.core.config import get_settings

# 裁决后的终态记录保留时长（wait 轮询拿到即可，无需长留）
_DECIDED_TTL_SECONDS = 60


def _key(approval_id: str) -> str:
    return f"tool:approval:{approval_id}"


def _client():
    import redis

    return redis.Redis.from_url(get_settings().REDIS_URL)


def create_request(tool_name: str, agent_name: str, tool_input: dict[str, Any]) -> str:
    """登记一条待审批请求，返回 approval_id（Redis 不可用时抛错，由调用方按拒绝处理）。"""
    approval_id = uuid.uuid4().hex[:12]
    payload = {
        "status": "pending",
        "tool": tool_name,
        "agent_name": agent_name,
        # 输入摘要供审批人判断，截断防超大 payload
        "input_preview": json.dumps(tool_input, ensure_ascii=False, default=str)[:500],
        "created_at": time.time(),
    }
    timeout = get_settings().APPROVAL_TIMEOUT
    _client().set(
        _key(approval_id),
        json.dumps(payload, ensure_ascii=False),
        ex=timeout + 60,  # 超时宽限：保证等待方超时前键一定还在
    )
    return approval_id


def get_request(approval_id: str) -> dict[str, Any] | None:
    raw = _client().get(_key(approval_id))
    return json.loads(raw) if raw else None


def list_pending() -> list[dict[str, Any]]:
    """待审批列表（审批页面/接口用），按创建时间倒序。"""
    client = _client()
    pending: list[dict[str, Any]] = []
    for key in client.scan_iter(match="tool:approval:*"):
        raw = client.get(key)
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if item.get("status") == "pending":
            ks = key.decode() if isinstance(key, bytes) else str(key)
            item["approval_id"] = ks.rsplit(":", 1)[-1]
            pending.append(item)
    pending.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return pending


def decide(approval_id: str, decision: str, decided_by: str = "") -> dict[str, Any] | None:
    """裁决：pending → approved/denied。已裁决或不存在返回 None（幂等防重）。"""
    if decision not in ("approved", "denied"):
        raise ValueError(f"非法裁决 {decision!r}，可选：approved/denied")
    client = _client()
    req = get_request(approval_id)
    if not req or req.get("status") != "pending":
        return None
    req["status"] = decision
    req["decided_by"] = decided_by
    req["decided_at"] = time.time()
    client.set(
        _key(approval_id),
        json.dumps(req, ensure_ascii=False),
        ex=_DECIDED_TTL_SECONDS,
    )
    return req


async def wait_for_decision(
    approval_id: str, timeout: int | None = None, interval: float = 1.0
) -> str:
    """等待裁决，返回 approved / denied / timeout / unavailable。

    Redis 不可用返回 unavailable（调用方按拒绝处理）；超时返回 timeout（同样按拒绝）。
    """
    settings = get_settings()
    limit = settings.APPROVAL_TIMEOUT if timeout is None else timeout
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit

    while loop.time() < deadline:
        try:
            req = await asyncio.to_thread(get_request, approval_id)
        except Exception:  # noqa: BLE001 —— Redis 不可用 = 拒绝，不静默放行
            return "unavailable"
        if req is None:
            # 键不存在（被清理）= 无从裁决，按拒绝
            return "unavailable"
        if req.get("status") != "pending":
            return str(req["status"])
        await asyncio.sleep(interval)
    return "timeout"
