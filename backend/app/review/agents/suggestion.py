from typing import Any

from app.agentkit.base import BaseAgent
from app.review.prompts.suggestion import SUGGESTION_SYSTEM_PROMPT


class SuggestionAgent(BaseAgent):
    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="SuggestionAgent",
            system_prompt=SUGGESTION_SYSTEM_PROMPT,
            tools=tools,
            max_turns=5,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """为已有 Risk 节点生成修改建议。"""
        risk_nodes = session_graph.find_nodes(node_type="Risk")
        if not risk_nodes:
            return {"output": {}, "findings": [], "logs": self.logs}

        # 把现有风险汇总成文本，一次性让 LLM 生成建议
        risk_texts = []
        for risk in risk_nodes:
            props = risk.get("properties", {})
            risk_texts.append(
                f"风险类型：{props.get('risk_type', '')}\n"
                f"风险等级：{props.get('level', '')}\n"
                f"条款原文：{props.get('clause_text', '')}\n"
                f"原因：{props.get('reason', '')}\n"
            )

        task_prompt = (
            "请为以下合同风险逐条给出修改建议：\n\n"
            + "\n---\n".join(risk_texts[:10])
        )
        result = await self._react_loop(session_graph, context, task_prompt)
        output = result.get("output", {})

        suggestions = output if isinstance(output, list) else output.get("suggestions", [])

        # 按 risk_type 建立建议索引
        suggestion_map = {
            s.get("risk_type", "").strip(): s
            for s in suggestions
            if isinstance(s, dict)
        }

        updated_count = 0
        for risk in risk_nodes:
            props = risk.get("properties", {})
            risk_type = props.get("risk_type", "").strip()
            suggestion = suggestion_map.get(risk_type)

            if suggestion and not props.get("suggestion"):
                session_graph.update_node(
                    risk["id"],
                    {
                        "suggestion": {
                            "original_text": suggestion.get("original_text", props.get("clause_text", "")),
                            "revised_text": suggestion.get("revised_text", ""),
                            "rationale": suggestion.get("rationale", ""),
                        }
                    },
                )
                updated_count += 1

        self.logs.extend(result.get("logs", []))
        return {
            "output": {"updated_count": updated_count},
            "findings": suggestions,
            "logs": self.logs,
        }
