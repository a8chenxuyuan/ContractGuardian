"""
工具：read_section
作用：根据 section_path 从 SessionGraph 中读取对应条款文本。

输入示例：
{
    "section_path": "1.1"
}

输出示例：
{
    "text": "本合同试用期为六个月...",
    "section": "1.1"
}
"""

from typing import Any

from app.agentkit.tool_registry import register_tool


@register_tool("read_section")
async def read_section(input: dict, context: dict) -> dict[str, Any]:
    """根据 section_path 读取条款内容。"""
    section_path = input.get("section_path") or input.get("section")
    session_graph = context.get("session_graph")

    if not session_graph or not section_path:
        return {"text": "", "section": section_path}

    # 在 SessionGraph 中查找 Clause 节点，匹配 section_path
    clauses = session_graph.find_nodes(
        node_type="Clause",
        filters={"section_path": section_path},
    )

    if not clauses:
        # 兼容 chunk_id 直接查询
        node = session_graph.get_node(section_path)
        if node and node.get("type") == "Clause":
            clauses = [node]

    if clauses:
        # 合并同一 section_path 下的文本（通常只有一个）
        texts = [c["properties"].get("text", "") for c in clauses]
        return {"text": "\n".join(t for t in texts if t), "section": section_path}

    return {"text": "", "section": section_path}
