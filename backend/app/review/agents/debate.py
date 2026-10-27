from typing import Any

from app.agentkit.base import BaseAgent
from app.review.prompts.debate import DEBATE_SYSTEM_PROMPT


class DebateAgent(BaseAgent):
    def __init__(
        self,
        tools: dict[str, Any] | None = None,
        use_function_calling: bool = False,
    ):
        super().__init__(
            name="DebateAgent",
            system_prompt=DEBATE_SYSTEM_PROMPT,
            tools=tools,
            max_turns=5,
            use_function_calling=use_function_calling,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """对 high 风险进行正反辩论，并返回结构化结论。"""
        risk_nodes = session_graph.find_nodes(node_type="Risk")
        high_risks = [
            r for r in risk_nodes
            if r.get("properties", {}).get("level") == "high"
        ]

        if not high_risks:
            return {"output": {"debate_results": []}, "findings": [], "logs": self.logs}

        risk_texts = []
        for risk in high_risks[:5]:  # 最多辩论 5 个
            props = risk.get("properties", {})
            risk_texts.append(
                f"风险类型：{props.get('risk_type', '')}\n"
                f"条款原文：{props.get('clause_text', '')}\n"
                f"原因：{props.get('reason', '')}\n"
            )

        task_prompt = (
            "请对以下高风险项逐一进行正反辩论，并给出保留/降级/撤销的结论：\n\n"
            + "\n---\n".join(risk_texts)
        )
        result = await self._react_loop(session_graph, context, task_prompt)
        output = result.get("output", {})

        # 标准化辩论结论为结构化列表
        debate_results = self._normalize_debate_output(output)

        # 把辩论结论写回对应 Risk 节点，供 Triage 阶段应用
        self._apply_debate_results_to_graph(session_graph, high_risks[:5], debate_results)

        self.logs.extend(result.get("logs", []))
        return {"output": {"debate_results": debate_results}, "findings": [], "logs": self.logs}

    def _normalize_debate_output(self, output: Any) -> list[dict[str, Any]]:
        """把 LLM 输出统一解析成 [{risk_type, conclusion, reason}] 格式。"""
        if isinstance(output, list):
            return [
                {
                    "risk_type": str(item.get("risk_type", "")),
                    "conclusion": str(item.get("conclusion", "保留")),
                    "reason": str(item.get("reason", "")),
                }
                for item in output
                if isinstance(item, dict)
            ]
        if isinstance(output, dict):
            # 兼容 {risk_type, conclusion, reason} 单条或 {results: [...]} 的格式
            if "results" in output and isinstance(output["results"], list):
                return self._normalize_debate_output(output["results"])
            if "risk_type" in output:
                return [
                    {
                        "risk_type": str(output.get("risk_type", "")),
                        "conclusion": str(output.get("conclusion", "保留")),
                        "reason": str(output.get("reason", "")),
                    }
                ]
        return []

    def _apply_debate_results_to_graph(
        self,
        session_graph: Any,
        debated_risks: list[dict[str, Any]],
        debate_results: list[dict[str, Any]],
    ) -> None:
        """把辩论结论写入对应 Risk 节点的 debate_conclusion 属性。"""
        for risk, result in zip(debated_risks, debate_results):
            risk_id = risk.get("id")
            if risk_id is None:
                continue
            conclusion = result.get("conclusion", "保留")
            if conclusion not in {"保留", "降级", "撤销"}:
                conclusion = "保留"
            session_graph.update_node(
                node_id=risk_id,
                properties={
                    "debate_conclusion": conclusion,
                    "debate_reason": result.get("reason", ""),
                },
            )
