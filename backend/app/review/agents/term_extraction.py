import re
from typing import Any

from app.agentkit.base import BaseAgent


class TermExtractionAgent(BaseAgent):
    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="TermExtractionAgent",
            system_prompt="从劳动合同中提取甲乙双方名称、合同期限、工作岗位等关键商务条款。",
            tools=tools,
            max_turns=5,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """提取合同主体信息并写入 SessionGraph。"""
        chunks = context.get("chunks", [])
        contract_text = "\n".join(c.get("text", "") for c in chunks)

        party_a = self._extract_party(contract_text, "甲方")
        party_b = self._extract_party(contract_text, "乙方")
        contract_term = self._extract_contract_term(contract_text)
        job_position = self._extract_job_position(contract_text)

        # 写入 Party 节点
        if party_a:
            session_graph.add_node(
                node_type="Party",
                properties={
                    "party_type": "甲方",
                    "name": party_a,
                    "role": "用人单位",
                },
            )
        if party_b:
            session_graph.add_node(
                node_type="Party",
                properties={
                    "party_type": "乙方",
                    "name": party_b,
                    "role": "劳动者",
                },
            )

        output = {
            "party_a": party_a,
            "party_b": party_b,
            "contract_term": contract_term,
            "job_position": job_position,
        }

        return {"output": output, "findings": [], "logs": self.logs}

    def _extract_party(self, text: str, label: str) -> str | None:
        """简单提取甲方/乙方名称。"""
        pattern = rf"{label}[:：]\s*([^\n（(]{2,50})"
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
        return None

    def _extract_contract_term(self, text: str) -> str | None:
        """提取合同期限。"""
        match = re.search(r"合同期限[：:]\s*([^\n。]{2,30})", text)
        if match:
            return match.group(1).strip()
        return None

    def _extract_job_position(self, text: str) -> str | None:
        """提取工作岗位。"""
        match = re.search(r"(工作岗位|职位|职务)[：:]\s*([^\n。]{2,30})", text)
        if match:
            return match.group(2).strip()
        return None
