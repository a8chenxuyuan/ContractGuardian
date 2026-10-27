"""
工具：output_finding
作用：在 SessionGraph 中新增风险节点，并建立 Clause -> HAS_RISK 边。

输入示例：
{
    "clause_id": "Clause_xxx",
    "risk_type": "试用期超长",
    "level": "high",
    "confidence": 0.95,
    "reason": "两年期合同试用期不得超过两个月",
    "suggestion": {
        "original_text": "试用期为六个月",
        "revised_text": "试用期为二个月",
        "rationale": "符合劳动合同法第19条"
    }
}

输出示例：
{
    "status": "success",
    "risk_id": "Risk_xxx"
}
"""

from typing import Any

from app.agentkit.tool_registry import register_tool


@register_tool("output_finding")
async def output_finding(input: dict, context: dict) -> dict[str, Any]:
    """把发现的风险写入 SessionGraph。"""
    session_graph = context.get("session_graph")
    if not session_graph:
        return {"status": "error", "message": "缺少 session_graph", "risk_id": None}

    clause_id = input.get("clause_id")

    # 如果指定了 clause_id，尝试从 Clause 节点继承位置信息
    page = input.get("page")
    bbox = input.get("bbox")
    if clause_id and session_graph.get_node(clause_id):
        clause_props = session_graph.get_node(clause_id).get("properties", {})
        if page is None:
            page = clause_props.get("page", 1)
        if bbox is None:
            bbox = clause_props.get("bbox")

    risk_props = {
        "risk_type": input.get("risk_type", "未分类"),
        "level": input.get("level", "low"),
        "confidence": input.get("confidence", 0.5),
        "reason": input.get("reason", ""),
        "suggestion": input.get("suggestion", {}),
        "law_refs": input.get("law_refs", []),
        "clause_text": input.get("clause_text", ""),
        "source_chunk_id": clause_id,
        "page": page,
        "bbox": bbox,
    }

    risk_id = session_graph.add_node(
        node_type="Risk",
        properties=risk_props,
    )

    # 如果指定了 clause_id 且存在，建立 Clause -> HAS_RISK -> Risk 边
    if clause_id and session_graph.get_node(clause_id):
        session_graph.add_edge(
            source_id=clause_id,
            target_id=risk_id,
            edge_type="HAS_RISK",
        )

    return {"status": "success", "risk_id": risk_id}
