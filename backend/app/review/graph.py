"""
文件：app/review/graph.py
作用：M3 —— 用 LangGraph StateGraph 重写审查编排层（只换壳，不换 Agent）。

设计动机（为什么）：
- 旧 run_review 是手写顺序管线：阶段写死、无法条件路由、无法暂停恢复；
- LangGraph 把每个阶段变成图节点，获得：条件边（跳过无风险章节的整段审查）、
  回环（未来 legal_verify 失败可回到 legal_research）、checkpoint/interrupt（人工介入暂停）；
- 13 个 Agent 与全部业务逻辑零改动——节点只是「发 phase 事件 + 调原方法 + 计时」的薄包装。

与旧实现的关系：ReviewCoordinator.run_review 调用 build_review_graph().ainvoke()，
SSE 事件（phase_changed/completed/error）的时序与旧管线一致，前端无感知。
"""

from __future__ import annotations

import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class ReviewCancelledError(RuntimeError):
    """用户中途取消审查时抛出，用于软中断 LangGraph 剩余阶段。"""


async def _abort_if_cancelled(review_session_id: int | None) -> None:
    """阶段边界检查会话状态：用户已取消则抛出软中断异常，停止后续阶段。"""
    if not review_session_id:
        return
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.review import ReviewSession

    async with AsyncSessionLocal() as db:
        status = (
            await db.execute(
                select(ReviewSession.status).where(ReviewSession.id == review_session_id)
            )
        ).scalar_one_or_none()
    if status == "cancelled":
        raise ReviewCancelledError(f"审查会话 #{review_session_id} 已被用户取消")


class ReviewState(TypedDict, total=False):
    # 输入
    contract_id: int
    chunks: list[dict[str, Any]]
    section_tree: dict[str, Any]
    contract_type: str
    review_session_id: int | None
    # 运行时对象（不序列化，仅进程内传递）
    coordinator: Any
    session_graph: Any
    agent_bus: Any
    context: dict[str, Any]
    # 阶段产物
    assignments: list[Any]
    research: dict[str, Any]
    findings: list[dict[str, Any]]
    human_review_items: list[dict[str, Any]]
    costs: dict[str, float]


def build_review_graph(coordinator: Any) -> Any:
    """构建审查状态图。coordinator 提供 _route/_preload/_execute/... 原方法。"""

    async def _phase(state: ReviewState, name: str, message: str) -> None:
        """发布阶段开始事件（与旧管线相同的 SSE 协议）。"""
        bus = state["agent_bus"]
        from app.agentkit.events import EventType

        await bus.publish(EventType.PHASE_CHANGED, {"phase": name, "message": message})

    # ---------- 节点定义：每个节点 = 事件 + 原方法 + 计时 ----------

    async def route_node(state: ReviewState) -> dict[str, Any]:
        await _abort_if_cancelled(state.get("review_session_id"))
        await _phase(state, "route", "正在分配审查任务...")
        t0 = time.time()
        assignments = await coordinator._route(
            state["session_graph"], state["chunks"]
        )
        return {"assignments": assignments, "costs": {**state.get("costs", {}), "route": time.time() - t0}}

    async def preload_node(state: ReviewState) -> dict[str, Any]:
        await _abort_if_cancelled(state.get("review_session_id"))
        await _phase(state, "preload", "正在预加载合同上下文...")
        t0 = time.time()
        await coordinator._preload(
            state["session_graph"], state["chunks"], state["section_tree"]
        )
        return {"costs": {**state.get("costs", {}), "preload": time.time() - t0}}

    async def legal_research_node(state: ReviewState) -> dict[str, Any]:
        await _abort_if_cancelled(state.get("review_session_id"))
        await _phase(state, "legal_research", "正在动态推断适用法律...")
        t0 = time.time()
        agent = coordinator.agents["legal_research"]
        result = await agent.run(state["session_graph"], state["context"])
        context = state["context"]
        context["discovered_laws"] = result.get("discovered_laws", [])
        context["review_checklist"] = result.get("review_checklist", [])
        context["risk_signals"] = result.get("risk_signals", [])
        return {
            "research": result,
            "costs": {**state.get("costs", {}), "legal_research": time.time() - t0},
        }

    async def execute_node(state: ReviewState) -> dict[str, Any]:
        await _abort_if_cancelled(state.get("review_session_id"))
        await _phase(state, "execute", "Agent 正在并行审查...")
        t0 = time.time()
        await coordinator._execute(
            state["session_graph"], state["assignments"], state["context"]
        )
        return {"costs": {**state.get("costs", {}), "execute": time.time() - t0}}

    async def merge_link_node(state: ReviewState) -> dict[str, Any]:
        await _abort_if_cancelled(state.get("review_session_id"))
        await _phase(state, "merge_link", "正在合并风险并发现组合风险...")
        t0 = time.time()
        await coordinator._merge_and_link(state["session_graph"])
        return {"costs": {**state.get("costs", {}), "merge_link": time.time() - t0}}

    async def legal_verify_node(state: ReviewState) -> dict[str, Any]:
        await _abort_if_cancelled(state.get("review_session_id"))
        await _phase(state, "legal_verify", "正在验证法律依据...")
        t0 = time.time()
        await coordinator._legal_verify(state["session_graph"], state["context"])
        return {"costs": {**state.get("costs", {}), "legal_verify": time.time() - t0}}

    async def debate_node(state: ReviewState) -> dict[str, Any]:
        await _abort_if_cancelled(state.get("review_session_id"))
        await _phase(state, "debate", "正在对高风险项进行辩论...")
        t0 = time.time()
        await coordinator._debate(state["session_graph"], state["context"])
        return {"costs": {**state.get("costs", {}), "debate": time.time() - t0}}

    async def triage_node(state: ReviewState) -> dict[str, Any]:
        await _abort_if_cancelled(state.get("review_session_id"))
        await _phase(state, "triage", "正在整理最终结果...")
        t0 = time.time()
        findings, human_review_items = await coordinator._triage(
            state["session_graph"]
        )
        return {
            "findings": findings,
            "human_review_items": human_review_items,
            "costs": {**state.get("costs", {}), "triage": time.time() - t0},
        }

    graph = StateGraph(ReviewState)
    graph.add_node("route", route_node)
    graph.add_node("preload", preload_node)
    graph.add_node("legal_research", legal_research_node)
    graph.add_node("execute", execute_node)
    graph.add_node("merge_link", merge_link_node)
    graph.add_node("legal_verify", legal_verify_node)
    graph.add_node("debate", debate_node)
    graph.add_node("triage", triage_node)

    graph.add_edge(START, "route")
    graph.add_edge("route", "preload")
    graph.add_edge("preload", "legal_research")
    graph.add_edge("legal_research", "execute")
    graph.add_edge("execute", "merge_link")
    graph.add_edge("merge_link", "legal_verify")
    graph.add_edge("legal_verify", "debate")
    graph.add_edge("debate", "triage")
    graph.add_edge("triage", END)

    return graph.compile()
