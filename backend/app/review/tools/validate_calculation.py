"""
工具：validate_calculation
作用：验证合同中的数字计算是否合理（如违约金、赔偿金等）。

输入示例：
{
    "clause_text": "违约金为月工资的 5 倍，即 50000 元。",
    "monthly_salary": 10000
}

输出示例：
{
    "valid": true,
    "errors": []
}
"""

import re
from typing import Any

from app.agentkit.tool_registry import register_tool


@register_tool("validate_calculation")
async def validate_calculation(input: dict, context: dict) -> dict[str, Any]:
    """验证合同中的简单计算。"""
    clause_text = input.get("clause_text", "")
    monthly_salary = input.get("monthly_salary")
    errors = []

    if not clause_text:
        return {"valid": True, "errors": []}

    # 提取文本中的数字
    numbers = [float(n.replace(",", "")) for n in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", clause_text)]

    # 如果有月工资，检查违约金倍数是否合理
    if monthly_salary and numbers:
        # 简单规则：违约金不应超过月工资的 12 倍（法定常见上限）
        max_reasonable = monthly_salary * 12
        for num in numbers:
            if num > max_reasonable:
                errors.append(
                    f"金额 {num} 元超过月工资 {monthly_salary} 元的 12 倍（{max_reasonable} 元），可能过高。"
                )

    # 检查试用期月数是否匹配合同期限（如果文本中包含）
    probation_match = re.search(r"试用期.*?(\d+)\s*个月", clause_text)
    term_match = re.search(r"合同期限.*?(\d+)\s*年", clause_text)
    if probation_match and term_match:
        probation_months = int(probation_match.group(1))
        term_years = int(term_match.group(1))
        max_months = 2 if term_years < 3 else 6
        if probation_months > max_months:
            errors.append(
                f"试用期 {probation_months} 个月超过 {term_years} 年期合同的法定上限 {max_months} 个月。"
            )

    return {"valid": len(errors) == 0, "errors": errors}
