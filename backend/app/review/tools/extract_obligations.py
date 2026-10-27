"""
工具：extract_obligations
作用：从条款文本中提取甲乙双方的权利义务。

输入示例：
{
    "section_path": "1.1"
}

输出示例：
{
    "obligations": [
        {"party": "甲方", "type": "义务", "content": "按时足额支付工资"},
        {"party": "乙方", "type": "义务", "content": "遵守公司规章制度"}
    ]
}
"""

import re
from typing import Any

from app.agentkit.tool_registry import register_tool


@register_tool("extract_obligations")
async def extract_obligations(input: dict, context: dict) -> dict[str, Any]:
    """从条款中提取甲乙双方义务。"""
    section_path = input.get("section_path")
    text = input.get("text", "")
    session_graph = context.get("session_graph")

    # 如果没有直接传文本，尝试从 session_graph 读取
    if not text and session_graph and section_path:
        from app.review.tools.read_section import read_section

        result = await read_section({"section_path": section_path}, context)
        text = result.get("text", "")

    if not text:
        return {"obligations": []}

    obligations = []

    # 简单规则匹配：包含"应当""必须""不得"的句子
    sentences = re.split(r"[。；]", text)
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        party = None
        if sentence.startswith("甲方") or "甲方" in sentence[:10]:
            party = "甲方"
        elif sentence.startswith("乙方") or "乙方" in sentence[:10]:
            party = "乙方"

        obligation_type = "义务"
        if "不得" in sentence or "禁止" in sentence:
            obligation_type = "禁止性义务"
        elif "享有" in sentence or "有权" in sentence:
            obligation_type = "权利"

        if party and ("应当" in sentence or "必须" in sentence or "不得" in sentence or "有权" in sentence):
            obligations.append(
                {
                    "party": party,
                    "type": obligation_type,
                    "content": sentence,
                }
            )

    return {"obligations": obligations}
