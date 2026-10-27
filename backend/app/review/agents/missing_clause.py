from typing import Any

from app.agentkit.base import BaseAgent
from app.review.prompts.missing_clause import (
    MISSING_CLAUSE_SYSTEM_PROMPT,
    MISSING_CLAUSE_TASK_PROMPT_TEMPLATE,
)


class MissingClauseAgent(BaseAgent):
    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="MissingClauseAgent",
            system_prompt=MISSING_CLAUSE_SYSTEM_PROMPT,
            tools=tools,
            max_turns=5,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """检查合同缺失条款，写入 SessionGraph。"""
        chunks = context.get("chunks", [])
        contract_type = context.get("contract_type", "通用")
        discovered_laws = context.get("discovered_laws", [])
        contract_text = "\n".join(c.get("text", "") for c in chunks)

        if not contract_text:
            return {"output": {}, "findings": [], "logs": self.logs}

        law_context = self._format_law_context(discovered_laws)

        task_prompt = MISSING_CLAUSE_TASK_PROMPT_TEMPLATE.format(
            contract_type=contract_type,
            law_context=law_context,
            contract_text=contract_text[:3000],
        )

        result = await self._react_loop(session_graph, context, task_prompt)
        output = result.get("output", {})

        # 支持多种返回格式：数组、包含 missing_clauses 的字典
        missing_items = output if isinstance(output, list) else output.get("missing_clauses", [])
        if not isinstance(missing_items, list):
            missing_items = []

        findings = []
        valid_levels = {"high", "medium", "low"}
        # 用于识别 LLM 误报的'实际上未缺失'项
        not_missing_indicators = [
            "不构成缺失", "已明确", "已约定", "已规定", "合同已", "不属于缺失",
            "无需报告", "不构风险", "已具备", "已包含", "无需补充",
        ]

        for item in missing_items:
            if not isinstance(item, dict):
                continue
            level = item.get("level", "medium")
            if level not in valid_levels:
                level = "medium"
            # 只保留中高风险，避免轻微缺失造成误报
            if level not in ("high", "medium"):
                continue

            reason = item.get("reason", "")
            missing_item = item.get("missing_item", "")

            # 过滤无效/空项：LLM 有时会输出空对象或仅有占位符
            missing_item = missing_item.strip()
            reason = reason.strip()
            if not missing_item or not reason:
                continue
            if len(missing_item) < 2 or len(reason) < 5:
                continue

            combined_text = f"{missing_item} {reason}"

            # 过滤掉 LLM 误判的'实际上未缺失'项
            if any(indicator in combined_text for indicator in not_missing_indicators):
                continue

            # 过滤掉常见的正常简化约定误报
            trivial_missing_patterns = [
                "质量标准", "知识产权归属", "押金退还", "保密措施", "保密范围",
                "争议解决", "管辖法院", "转租", "维修义务",
            ]
            # 只有当缺失确实导致权利义务严重失衡时才保留；普通简化约定过滤
            if any(p in combined_text for p in trivial_missing_patterns):
                # 必须有明确的失衡或违法说明才保留
                imbalance_indicators = [
                    "严重", "明显失衡", "违反法律", "强制", "可执行性严重降低",
                    "权益严重受损", "显失公平", "任意", "一方可以",
                ]
                if not any(ind in combined_text for ind in imbalance_indicators):
                    continue

            session_graph.add_node(
                node_type="Risk",
                properties={
                    "risk_type": f"缺失关键条款：{missing_item}",
                    "level": level,
                    "confidence": item.get("confidence", 0.7),
                    "reason": reason,
                    "suggestion": {
                        "original_text": "",
                        "revised_text": item.get("suggestion", ""),
                        "rationale": reason,
                    },
                    "clause_text": "",
                    "is_missing_clause": True,
                },
            )
            findings.append(item)

        self.logs.extend(result.get("logs", []))
        return {"output": output, "findings": findings, "logs": self.logs}

    def _format_law_context(self, discovered_laws: list[dict[str, Any]]) -> str:
        """将动态发现的法律依据格式化为上下文文本。"""
        if not discovered_laws:
            return "（本次尚未检索到具体法律依据，请基于一般法律原则和合同类型常识进行判断）"

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
