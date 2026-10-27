from itertools import combinations
from typing import Any

from app.agentkit.base import BaseAgent


class CrossReferenceAgent(BaseAgent):
    def __init__(
        self,
        tools: dict[str, Any] | None = None,
        use_function_calling: bool = False,
    ):
        super().__init__(
            name="CrossReferenceAgent",
            system_prompt="检查合同条款之间引用的一致性和冲突。必要时调用 read_section 读取条款原文，调用 check_cross_reference 检查条款一致性。",
            tools=tools,
            max_turns=5,
            use_function_calling=use_function_calling,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """两两检查 Clause 之间是否存在冲突。"""
        check_tool = self.tools.get("check_cross_reference")
        if not check_tool:
            return {"output": {}, "findings": [], "logs": self.logs}

        clauses = session_graph.find_nodes(node_type="Clause")
        # 只取有 section_path 的 clause，避免过多组合
        section_paths = [
            c["properties"].get("section_path", c["id"])
            for c in clauses
            if c["properties"].get("section_path")
        ]

        findings = []
        # 限制组合数量，避免爆炸
        for a, b in combinations(section_paths[:10], 2):
            try:
                result = await check_tool(
                    {"section_a": a, "section_b": b},
                    context,
                )
                if not result.get("consistent", True):
                    for issue in result.get("issues", []):
                        session_graph.add_node(
                            node_type="Risk",
                            properties={
                                "risk_type": "条款间引用冲突",
                                "level": "high",
                                "confidence": 0.8,
                                "reason": issue,
                                "clause_text": f"{a} 与 {b}",
                                "is_cross_reference_issue": True,
                            },
                        )
                        findings.append(issue)
            except Exception:
                continue

        return {"output": {"checked_pairs": len(list(combinations(section_paths[:10], 2)))}, "findings": findings, "logs": self.logs}
