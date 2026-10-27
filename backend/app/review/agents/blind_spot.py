from typing import Any

from app.agentkit.base import BaseAgent
from app.review.prompts.blind_spot import (
    BLIND_SPOT_SYSTEM_PROMPT,
    BLIND_SPOT_TASK_PROMPT_TEMPLATE,
)


class BlindSpotAgent(BaseAgent):
    """
    盲区扫描 Agent。

    职责：在其他 Agent 审查完成后，检查是否存在被忽略的风险、未审查到的条款
          或组合风险，作为系统审查的补充。
    实现方式：
      1. 读取 SessionGraph 中已有 Risk 和 Clause；
      2. 使用 LLM 分析哪些条款被忽略、哪些风险类型未被覆盖；
      3. 用规则兜底，确保常见盲区（如保密、竞业限制、培训、解除）被覆盖。
    """

    # 常见盲区关键词兜底规则：关键词出现但相关义务未明确约定
    BLIND_SPOT_RULES = [
        ("保密", "保密义务", "合同中提到保密，但未明确保密范围、期限和违约责任"),
        ("竞业限制", "竞业限制补偿", "合同涉及竞业限制，但未约定竞业限制补偿金"),
        ("培训", "服务期与违约金", "合同涉及培训，但未明确服务期和违约金计算方式"),
        ("解除", "解除条件", "合同涉及解除，但未明确解除条件、通知期限和经济补偿"),
        ("加班", "加班费", "合同提及加班，但未约定加班费计算标准"),
        ("调岗", "调岗条件", "合同涉及调岗，但未明确调岗条件和程序"),
    ]

    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="BlindSpotAgent",
            system_prompt=BLIND_SPOT_SYSTEM_PROMPT,
            tools=tools,
            max_turns=5,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """扫描审查盲区，LLM 驱动 + 规则兜底。"""
        chunks = context.get("chunks", [])
        contract_text = "\n".join(c.get("text", "") for c in chunks)

        if not contract_text:
            return {"output": {}, "findings": [], "logs": self.logs}

        # 读取已有的 Risk 节点，避免重复
        risk_nodes = session_graph.find_nodes(node_type="Risk")
        existing_risks = []
        for risk in risk_nodes:
            props = risk.get("properties", {})
            existing_risks.append(
                f"- {props.get('risk_type', '')}: {props.get('reason', '')}"
            )
        existing_risks_text = "\n".join(existing_risks[:30]) or "（暂无）"

        # 读取所有 Clause 节点
        clause_nodes = session_graph.find_nodes(node_type="Clause")
        clauses_text = "\n".join(
            c.get("properties", {}).get("text", "") for c in clause_nodes[:30]
        )

        task_prompt = BLIND_SPOT_TASK_PROMPT_TEMPLATE.format(
            clauses_text=clauses_text[:2000],
            existing_risks_text=existing_risks_text,
        )

        result = await self._react_loop(session_graph, context, task_prompt)
        output = result.get("output", {})
        findings = output if isinstance(output, list) else output.get("blind_spots", [])

        created_risks = []
        for item in findings:
            if not isinstance(item, dict):
                continue
            level = item.get("level", "low")
            if level not in {"high", "medium", "low"}:
                level = "low"

            session_graph.add_node(
                node_type="Risk",
                properties={
                    "risk_type": f"审查盲区：{item.get('risk_type', '未分类')}",
                    "level": level,
                    "confidence": item.get("confidence", 0.6),
                    "reason": item.get("reason", ""),
                    "suggestion": {
                        "original_text": item.get("clause_text", ""),
                        "revised_text": item.get("suggestion", ""),
                        "rationale": item.get("reason", ""),
                    },
                    "clause_text": item.get("clause_text", ""),
                    "is_blind_spot": True,
                },
            )
            created_risks.append(item)

        # 规则兜底：常见盲区扫描
        for keyword, topic, issue in self.BLIND_SPOT_RULES:
            if keyword in contract_text and topic not in contract_text:
                # 避免与已有风险重复：检查是否已经存在相同 keyword 的风险
                already_exists = any(
                    keyword in r.get("properties", {}).get("risk_type", "")
                    or keyword in r.get("properties", {}).get("reason", "")
                    for r in risk_nodes
                )
                if already_exists:
                    continue

                session_graph.add_node(
                    node_type="Risk",
                    properties={
                        "risk_type": f"审查盲区：{topic}未明确",
                        "level": "low",
                        "confidence": 0.65,
                        "reason": issue,
                        "suggestion": {
                            "original_text": "",
                            "revised_text": f"建议补充{topic}相关条款",
                            "rationale": issue,
                        },
                        "clause_text": "",
                        "is_blind_spot": True,
                    },
                )
                created_risks.append({"risk_type": f"{topic}未明确", "reason": issue})

        self.logs.extend(result.get("logs", []))
        return {"output": output, "findings": created_risks, "logs": self.logs}
