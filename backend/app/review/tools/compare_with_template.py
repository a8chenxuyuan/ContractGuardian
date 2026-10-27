"""
工具：compare_with_template
作用：将合同条款与标准模板进行对比，标出差异。

输入示例：
{
    "section_path": "1.1",
    "template_text": "试用期不得超过两个月。"
}

输出示例：
{
    "differences": [
        {"type": "增加", "content": "试用期为六个月"}
    ]
}
"""

import difflib
from typing import Any

from app.agentkit.tool_registry import register_tool


@register_tool("compare_with_template")
async def compare_with_template(input: dict, context: dict) -> dict[str, Any]:
    """将条款与模板文本对比。"""
    section_path = input.get("section_path")
    template_text = input.get("template_text", "")
    session_graph = context.get("session_graph")

    if not template_text:
        return {"differences": []}

    clause_text = ""
    if session_graph and section_path:
        from app.review.tools.read_section import read_section

        result = await read_section({"section_path": section_path}, context)
        clause_text = result.get("text", "")
    elif "clause_text" in input:
        clause_text = input["clause_text"]

    if not clause_text:
        return {"differences": []}

    # 使用 difflib 简单对比，提取差异行
    differences = []
    for line in difflib.unified_diff(
        template_text.splitlines(),
        clause_text.splitlines(),
        lineterm="",
    ):
        if line.startswith("+") and not line.startswith("+++"):
            differences.append({"type": "增加", "content": line[1:].strip()})
        elif line.startswith("-") and not line.startswith("---"):
            differences.append({"type": "删除", "content": line[1:].strip()})

    return {"differences": differences}
