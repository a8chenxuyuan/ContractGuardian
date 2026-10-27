from typing import Any

from app.agentkit.base import BaseAgent
from app.review.prompts.industry_compliance import (
    INDUSTRY_COMPLIANCE_SYSTEM_PROMPT,
    INDUSTRY_COMPLIANCE_TASK_PROMPT_TEMPLATE,
)


class IndustryComplianceAgent(BaseAgent):
    """
    行业合规检查 Agent。

    职责：根据合同类型和行业特点，检查是否存在行业特殊合规风险。
    实现方式：
      1. 优先使用 LLM 做行业化语义审查，识别行业特殊风险；
      2. 使用硬规则兜底，确保常见违法表述不会被漏检。
    """

    # 行业名称与对应检查重点的映射
    INDUSTRY_FOCUS = {
        "互联网": ["竞业限制范围", "知识产权归属", "加班与工时", "数据保密"],
        "金融": ["反洗钱义务", "适当性义务", "信息披露", "风险提示"],
        "医药": ["临床试验合规", "药品推广合规", "不良反应报告"],
        "建筑": ["安全生产", "工程款支付", "农民工工资", "资质要求"],
        "教育培训": ["预收费监管", "教师资格", "退费条款", "虚假宣传"],
        "餐饮": ["食品安全", "健康证", "用工时长", "工资支付"],
        "制造业": ["安全生产", "职业病防护", "工伤赔偿", "环保合规"],
    }

    # 通用违法表述兜底规则
    FORBIDDEN_TERMS = [
        ("自愿放弃社保", "规避社会保险缴纳义务"),
        ("工伤概不负责", "免除工伤赔偿责任"),
        ("无条件加班", "违反工时规定"),
        ("生死自负", "免除人身损害赔偿责任"),
    ]

    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="IndustryComplianceAgent",
            system_prompt=INDUSTRY_COMPLIANCE_SYSTEM_PROMPT,
            tools=tools,
            max_turns=5,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """执行行业合规检查，LLM 驱动 + 规则兜底。"""
        chunks = context.get("chunks", [])
        contract_type = context.get("contract_type", "通用")
        industry = context.get("industry", "通用")
        contract_text = "\n".join(c.get("text", "") for c in chunks)

        if not contract_text:
            return {"output": {}, "findings": [], "logs": self.logs}

        # 构建行业化审查提示词
        focus_points = self.INDUSTRY_FOCUS.get(industry, ["一般合规要求"])
        focus_text = "、".join(focus_points)

        task_prompt = INDUSTRY_COMPLIANCE_TASK_PROMPT_TEMPLATE.format(
            contract_type=contract_type,
            industry=industry,
            focus_text=focus_text,
            contract_text=contract_text[:3000],
        )

        result = await self._react_loop(session_graph, context, task_prompt)
        output = result.get("output", {})
        findings = output if isinstance(output, list) else output.get("issues", [])

        created_risks = []
        for item in findings:
            if not isinstance(item, dict):
                continue
            level = item.get("level", "medium")
            if level not in {"high", "medium", "low"}:
                level = "medium"

            session_graph.add_node(
                node_type="Risk",
                properties={
                    "risk_type": f"行业合规问题：{item.get('risk_type', '未分类')}",
                    "level": level,
                    "confidence": item.get("confidence", 0.7),
                    "reason": item.get("reason", ""),
                    "suggestion": {
                        "original_text": item.get("clause_text", ""),
                        "revised_text": item.get("suggestion", ""),
                        "rationale": item.get("reason", ""),
                    },
                    "clause_text": item.get("clause_text", ""),
                    "is_industry_compliance_issue": True,
                    "industry": industry,
                },
            )
            created_risks.append(item)

        # 规则兜底：通用违法表述
        for term, reason in self.FORBIDDEN_TERMS:
            if term in contract_text:
                session_graph.add_node(
                    node_type="Risk",
                    properties={
                        "risk_type": "行业合规问题：包含违法表述",
                        "level": "high",
                        "confidence": 0.9,
                        "reason": f"合同中包含违法表述：{reason}",
                        "suggestion": {
                            "original_text": term,
                            "revised_text": "删除该违法表述",
                            "rationale": "违反法律强制性规定",
                        },
                        "clause_text": term,
                        "is_industry_compliance_issue": True,
                        "industry": industry,
                    },
                )
                created_risks.append({"risk_type": "包含违法表述", "reason": reason})

        self.logs.extend(result.get("logs", []))
        return {"output": output, "findings": created_risks, "logs": self.logs}
