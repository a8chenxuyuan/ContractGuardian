from typing import Any

from app.agentkit.base import BaseAgent
from app.review.prompts.balance import (
    BALANCE_SYSTEM_PROMPT,
    BALANCE_TASK_PROMPT_TEMPLATE,
)


class BalanceAgent(BaseAgent):
    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="BalanceAgent",
            system_prompt=BALANCE_SYSTEM_PROMPT,
            tools=tools,
            max_turns=5,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """分析合同权利义务平衡性。"""
        chunks = context.get("chunks", [])
        contract_type = context.get("contract_type", "通用")
        discovered_laws = context.get("discovered_laws", [])
        contract_text = "\n".join(c.get("text", "") for c in chunks)

        if not contract_text:
            return {"output": {}, "findings": [], "logs": self.logs}

        law_context = self._format_law_context(discovered_laws)

        task_prompt = BALANCE_TASK_PROMPT_TEMPLATE.format(
            contract_type=contract_type,
            law_context=law_context,
            contract_text=contract_text[:3000],
        )

        result = await self._react_loop(session_graph, context, task_prompt)
        output = result.get("output", {})

        imbalances = output if isinstance(output, list) else output.get("imbalances", [])
        if not isinstance(imbalances, list):
            imbalances = []

        findings = []
        for item in imbalances:
            if not isinstance(item, dict):
                continue
            level = item.get("level", "medium")
            if level not in ("high", "medium"):
                continue
            session_graph.add_node(
                node_type="Risk",
                properties={
                    "risk_type": item.get("risk_type", "权利义务不对等"),
                    "level": level,
                    "confidence": item.get("confidence", 0.7),
                    "reason": item.get("reason", ""),
                    "suggestion": {
                        "original_text": item.get("clause_text", ""),
                        "revised_text": item.get("suggestion", ""),
                        "rationale": item.get("reason", ""),
                    },
                    "clause_text": item.get("clause_text", ""),
                    "is_balance_issue": True,
                },
            )
            findings.append(item)

        self.logs.extend(result.get("logs", []))
        return {"output": output, "findings": findings, "logs": self.logs}

    def _format_law_context(self, discovered_laws: list[dict[str, Any]]) -> str:
        """将动态发现的法律依据格式化为上下文文本。"""
        if not discovered_laws:
            return "（本次尚未检索到具体法律依据，请基于一般法律原则进行判断）"

        lines = []
        for law in discovered_laws[:5]:
            name = law.get("law_name", "")
            number = law.get("article_number", "")
            text = law.get("article_text", "")[:300]
            review_points = law.get("review_points", [])
            lines.append(f"【{name} {number}】")
            if text:
                lines.append(f"原文：{text}")
            if review_points:
                lines.append("审查要点：" + "；".join(review_points))
            lines.append("")
        return "\n".join(lines)
