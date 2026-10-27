from typing import Any

from app.agentkit.base import BaseAgent


class LegalBasisAgent(BaseAgent):
    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="LegalBasisAgent",
            system_prompt="为合同风险发现关联相关法律依据。",
            tools=tools,
            max_turns=5,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """为已有 Risk 节点补充法律依据。"""
        search_knowledge = self.tools.get("search_knowledge")
        risk_nodes = session_graph.find_nodes(node_type="Risk")

        updated_count = 0
        for risk in risk_nodes:
            props = risk.get("properties", {})
            # 已经有 law_refs 的不重复查询
            if props.get("law_refs"):
                continue

            risk_type = props.get("risk_type", "")
            reason = props.get("reason", "")

            # 根据风险类型选择更精准的法条查询关键词
            query = self._build_law_query(risk_type, reason)

            law_refs = []
            if search_knowledge and query:
                try:
                    result = await search_knowledge(
                        {"query": query, "limit": 3},
                        context,
                    )
                    for article in result.get("results", []):
                        # article_number 已包含"第X条"格式，直接拼接法律名称
                        law_refs.append(
                            f"{article['law_name']}{article['article_number']}"
                        )
                except Exception:
                    law_refs = []

            if law_refs:
                session_graph.update_node(
                    risk["id"],
                    {"law_refs": law_refs},
                )
                updated_count += 1

        return {
            "output": {"updated_count": updated_count},
            "findings": [],
            "logs": self.logs,
        }

    def _build_law_query(self, risk_type: str, reason: str) -> str:
        """根据风险类型选择更可能命中法条的关键词。"""
        risk_type = risk_type or ""
        reason = reason or ""
        combined = risk_type + reason

        if "试用期" in combined:
            return "试用期"
        if "社保" in combined or "社会保险" in combined:
            return "社会保险"
        if "违约金" in combined:
            return "违约金"
        if "服务期" in combined or "培训" in combined:
            return "服务期"
        if "解除" in combined:
            return "解除"
        if "经济补偿" in combined:
            return "经济补偿"
        if "劳动报酬" in combined or "工资" in combined:
            return "劳动报酬"
        if "工作时间" in combined or "休息休假" in combined:
            return "工作时间"
        if "工作内容" in combined or "工作地点" in combined:
            return "劳动合同应当具备的条款"

        # 默认用风险类型本身查询
        return risk_type[:20]
