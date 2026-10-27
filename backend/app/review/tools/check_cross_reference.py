"""
工具：check_cross_reference
作用：检查两个条款之间是否存在引用或冲突。

输入示例：
{
    "section_a": "1.1",
    "section_b": "2.1"
}

输出示例：
{
    "consistent": false,
    "issues": ["条款A约定试用期6个月，但条款B合同期限为2年，两者不匹配"]
}
"""

from typing import Any

from app.agentkit.tool_registry import register_tool


@register_tool("check_cross_reference")
async def check_cross_reference(input: dict, context: dict) -> dict[str, Any]:
    """检查两个条款是否一致。"""
    section_a = input.get("section_a") or input.get("section_a_path")
    section_b = input.get("section_b") or input.get("section_b_path")
    session_graph = context.get("session_graph")

    if not session_graph or not section_a or not section_b:
        return {"consistent": True, "issues": []}

    # 读取两个条款文本
    from app.review.tools.read_section import read_section

    result_a = await read_section({"section_path": section_a}, context)
    result_b = await read_section({"section_path": section_b}, context)

    text_a = result_a.get("text", "")
    text_b = result_b.get("text", "")

    if not text_a or not text_b:
        return {"consistent": True, "issues": ["未能读取到条款内容"]}

    # 简单规则：检查是否同时出现明显矛盾的表述
    issues = []

    # 试用期与合同期限冲突示例
    if "试用期" in text_a and ("合同期限" in text_b or "期限" in text_b):
        import re
        # 简单提取试用期月数
        m_a = re.search(r"试用期.*?(\d+)\s*个月", text_a)
        m_b = re.search(r"合同期限.*?(\d+)\s*年", text_b)
        if m_a and m_b:
            probation_months = int(m_a.group(1))
            term_years = int(m_b.group(1))
            # 法定：1年<=2个月，3年<=6个月（简化规则）
            max_months = 2 if term_years < 3 else 6
            if probation_months > max_months:
                issues.append(
                    f"试用期为 {probation_months} 个月，但合同期限为 {term_years} 年，"
                    f"法定试用期上限为 {max_months} 个月。"
                )

    # 社保放弃与其他条款冲突
    if ("放弃社保" in text_a or "不缴纳社保" in text_a) and "工资" in text_b:
        issues.append("条款A存在放弃社保的约定，与依法缴纳社保的义务相冲突。")

    return {
        "consistent": len(issues) == 0,
        "issues": issues,
        "section_a_text": text_a,
        "section_b_text": text_b,
    }
