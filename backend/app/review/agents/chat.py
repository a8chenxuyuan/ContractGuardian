from typing import Any

from app.agentkit.base import BaseAgent
from app.review.prompts.chat import (
    CHAT_SYSTEM_PROMPT,
    CHAT_TASK_PROMPT_TEMPLATE,
)


class ChatAgent(BaseAgent):
    """
    合同问答 Agent。

    职责：基于合同审查结果图，回答用户关于合同风险、法律依据、修改建议的追问。
    特点：
      1. 支持多轮对话，可接收历史聊天记录；
      2. 优先引用 SessionGraph 中的风险信息；
      3. 对非合同相关问题明确拒绝回答；
      4. 输出结构化结果，包含回答和引用的风险编号。
    """

    def __init__(self, tools: dict[str, Any] | None = None):
        super().__init__(
            name="ChatAgent",
            system_prompt=CHAT_SYSTEM_PROMPT,
            tools=tools,
            max_turns=5,
        )

    async def run(self, session_graph: Any, context: dict[str, Any]) -> dict[str, Any]:
        """基于 SessionGraph 和多轮对话历史回答用户追问。"""
        question = context.get("question", "")
        if not question:
            return {
                "output": {
                    "answer": "请问您想了解这份合同的哪些方面？",
                    "referenced_risks": [],
                },
                "logs": self.logs,
            }

        # 导出 SessionGraph 为文本上下文
        session_node = session_graph.find_nodes(node_type="Session")
        node_id = session_node[0]["id"] if session_node else None
        graph_text = ""
        if node_id:
            # depth=2 能覆盖到风险节点和关联的法条/条款
            graph_text = session_graph.export_for_llm(node_id, depth=2)

        # 读取历史对话记录
        chat_history = context.get("chat_history", [])
        history_text = self._format_history(chat_history)

        # 构造任务提示词（经装配层唯一入口，带分层预算与装配事件）
        bus = session_graph.get_bus() if hasattr(session_graph, "get_bus") else None
        task_prompt = self._build_prompt(
            graph_text, history_text, question, bus=bus, user_id=context.get("user_id")
        )
        result = await self._react_loop(session_graph, context, task_prompt)

        # 解析输出：可能是字符串，也可能是 {answer, referenced_risks}
        output = result.get("output", {})
        if isinstance(output, str):
            output = {"answer": output, "referenced_risks": []}
        elif not isinstance(output, dict):
            output = {"answer": str(output), "referenced_risks": []}

        self.logs.extend(result.get("logs", []))
        return {"output": output, "logs": self.logs}

    def _format_history(self, chat_history: list[dict[str, str]]) -> str:
        """把历史对话格式化为文本。"""
        if not chat_history:
            return "（无历史对话）"

        lines = []
        for msg in chat_history[-6:]:  # 只取最近 6 轮，避免 token 过长
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"用户：{content}")
            else:
                lines.append(f"助手：{content}")
        return "\n".join(lines)

    def _build_prompt(
        self,
        graph_text: str,
        history_text: str,
        question: str,
        bus: Any = None,
        user_id: int | str | None = None,
    ) -> str:
        """构造给 LLM 的任务提示词。

        全部内容层经 ContextManager.assemble() 装配（协议 context_assembly.md）：
        分层预算裁剪 + context_assembled 事件审计；提供 user_id 时注入记忆层。
        """
        from app.agentkit.context import ContextManager, Layer, Priority
        from app.agentkit.memory import render_memory
        from app.agentkit.skills import match_skills, render_skills

        # 技能按需加载：命中触发词才注入对应 SKILL.md 正文（技能层，M2-1）
        matched = match_skills(question)
        skills_ctx = render_skills(matched)
        if matched and bus is not None:
            import asyncio

            from app.agentkit.events import EventType, emit

            try:
                asyncio.ensure_future(
                    emit(bus, EventType.SKILLS_MATCHED, {
                        "question": question[:200],
                        "matched": [s.id for s, _ in matched],
                    })
                )
            except RuntimeError:
                pass  # 无事件循环（同步调用）：跳过审计事件

        # 跨会话记忆层（M2-3）：dismiss 风险与显式偏好随问答注入
        memory_ctx = render_memory(user_id) if user_id is not None else ""
        assembled = ContextManager().assemble(
            layers=[
                Layer("tool", graph_text, Priority.NORMAL),
                Layer("skills", skills_ctx, Priority.HIGH),
                Layer("memory", memory_ctx, Priority.HIGH),
                Layer("history", history_text, Priority.LOW),
            ],
            bus=bus,
        )
        history_out = assembled.parts.get("history", "")
        if assembled.parts.get("skills"):
            history_out += f"\n\n[适用技能]\n{assembled.parts['skills']}"
        if assembled.parts.get("memory"):
            history_out += f"\n\n[该用户历史偏好]\n{assembled.parts['memory']}"
        return CHAT_TASK_PROMPT_TEMPLATE.format(
            graph_text=assembled.parts.get("tool", ""),
            history_text=history_out,
            question=question,
        )
