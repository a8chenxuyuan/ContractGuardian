from typing import Any

from app.agentkit.base import BaseAgent


class HumanReviewAgent(BaseAgent):
    """
    人工复核分流 Agent。

    职责：在 Triage 阶段之前，扫描所有 Risk 节点，判断哪些需要人工专家复核，
          并给出复核原因和优先级。
    """

    # 涉及重大利益的敏感关键词
    HIGH_STAKES_KEYWORDS = [
        "违约金", "赔偿金", "解除", "终止", "竞业限制",
        "保密", "知识产权", "工伤", "社保", "加班费",
    ]

    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="HumanReviewAgent",
            system_prompt="标记需要人工复核的审查项，并给出复核原因和优先级。",
            tools=tools,
            max_turns=5,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """
        根据多维度规则判断哪些风险需要人工复核。

        复核维度：
        1. 高风险项（level == high）
        2. 置信度较低（confidence < 0.7）
        3. 跨条款组合风险
        4. 权利义务平衡性争议
        5. 缺少法律依据或法条验证未通过
        6. 涉及重大利益（违约金、解除、工伤、社保等）
        7. 多个 Agent 对同一类风险都有发现（可能存在叠加或冲突）
        8. 行业合规问题和审查盲区
        """
        risk_nodes = session_graph.find_nodes(node_type="Risk")

        # 统计同类风险被多少个 Agent 触发
        risk_type_counter: dict[str, int] = {}
        for risk in risk_nodes:
            risk_type = risk.get("properties", {}).get("risk_type", "")
            risk_type_counter[risk_type] = risk_type_counter.get(risk_type, 0) + 1

        items = []
        for risk in risk_nodes:
            props = risk.get("properties", {})
            level = props.get("level", "low")
            confidence = props.get("confidence", 0.0)
            is_cross_clause = props.get("is_cross_clause", False)
            is_balance_issue = props.get("is_balance_issue", False)
            is_industry_compliance_issue = props.get(
                "is_industry_compliance_issue", False
            )
            is_blind_spot = props.get("is_blind_spot", False)
            law_refs = props.get("law_refs", [])
            verified = props.get("verified", None)
            risk_type = props.get("risk_type", "")
            reason = props.get("reason", "")
            clause_text = props.get("clause_text", "")

            # 判断是否需要人工复核
            needs_review = False
            review_reasons = []
            suggested_action = "请人工专家确认"

            if level == "high":
                needs_review = True
                review_reasons.append("高风险项")
                suggested_action = "建议优先复核，确认是否必须修改"

            if confidence < 0.7:
                needs_review = True
                review_reasons.append("置信度较低")
                suggested_action = "建议复核原始条款，补充判断依据"

            if is_cross_clause:
                needs_review = True
                review_reasons.append("跨条款组合风险")
                suggested_action = "建议结合多个条款整体判断"

            if is_balance_issue:
                needs_review = True
                review_reasons.append("权利义务平衡性争议")
                suggested_action = "建议评估违约责任是否对等"

            if not law_refs:
                needs_review = True
                review_reasons.append("缺少法律依据")
                suggested_action = "建议补充相关法律法规"
            elif verified is False:
                needs_review = True
                review_reasons.append("法条验证未通过")
                suggested_action = "建议核实法律依据的准确性"

            # 多个 Agent 都发现同类风险，说明情况较复杂
            if risk_type_counter.get(risk_type, 0) > 1:
                needs_review = True
                review_reasons.append("多个 Agent 交叉发现")
                suggested_action = "建议对比不同 Agent 的结论，确认是否存在重复或冲突"

            # 涉及重大利益
            text_for_check = f"{risk_type}{reason}{clause_text}"
            if any(kw in text_for_check for kw in self.HIGH_STAKES_KEYWORDS):
                needs_review = True
                review_reasons.append("涉及重大利益")
                if suggested_action == "请人工专家确认":
                    suggested_action = "建议重点复核经济责任和法律后果"

            # 行业合规和盲区问题
            if is_industry_compliance_issue:
                needs_review = True
                review_reasons.append("行业特殊合规问题")
                suggested_action = "建议由行业专家判断"

            if is_blind_spot:
                needs_review = True
                review_reasons.append("审查盲区")
                suggested_action = "建议确认是否需要补充约定"

            if needs_review:
                items.append(
                    {
                        "risk_id": risk["id"],
                        "risk_type": risk_type,
                        "level": level,
                        "confidence": confidence,
                        "reason": reason,
                        "clause_text": clause_text,
                        "review_reason": "、".join(review_reasons),
                        "suggested_action": suggested_action,
                    }
                )

        # 按优先级排序：high > medium > low，同等级置信度低的优先
        level_rank = {"high": 3, "medium": 2, "low": 1}
        items.sort(
            key=lambda x: (
                -level_rank.get(x["level"], 0),
                x["confidence"],
            )
        )

        return {"output": {"items": items}, "items": items, "logs": self.logs}
