"""
工具：query_knowledge_graph
作用：查询 SessionGraph 中某节点的关联信息（邻居节点）。

输入示例：
{
    "node_id": "Clause_xxx",
    "edge_type": "HAS_RISK",
    "direction": "out"
}

输出示例：
{
    "nodes": [...],
    "edges": [...]
}
"""

from typing import Any

from app.agentkit.tool_registry import register_tool


@register_tool("query_knowledge_graph")
async def query_knowledge_graph(input: dict, context: dict) -> dict[str, Any]:
    """查询图中的节点邻居。"""
    node_id = input.get("node_id")
    edge_type = input.get("edge_type")
    direction = input.get("direction", "out")
    depth = input.get("depth", 1)
    session_graph = context.get("session_graph")

    if not session_graph or not node_id:
        return {"nodes": [], "edges": []}

    visited_nodes = {node_id}
    visited_edges = set()
    current_level = {node_id}

    for _ in range(depth):
        next_level = set()
        for nid in current_level:
            neighbors = session_graph.get_neighbors(
                node_id=nid,
                edge_type=edge_type,
                direction=direction,
            )
            for item in neighbors:
                neighbor = item["node"]
                edge = item["edge"]
                visited_nodes.add(neighbor["id"])
                visited_edges.add(edge["id"])
                next_level.add(neighbor["id"])
        current_level = next_level

    nodes = [session_graph.get_node(nid) for nid in visited_nodes]
    edges = [session_graph._edges.get(eid) for eid in visited_edges]

    return {
        "nodes": [n for n in nodes if n],
        "edges": [e for e in edges if e],
    }
