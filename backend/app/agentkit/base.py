import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import get_settings
from app.llm import get_llm_client


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: dict[str, Any] | None = None,
        max_turns: int = 5,
        use_function_calling: bool = False,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools or {}
        self.max_turns = max_turns
        # 是否启用 function calling 多轮模式
        self.use_function_calling = use_function_calling
        self.logs: list[dict[str, Any]] = []
        # 默认使用全局 LLM 客户端
        self.llm_client: Any = get_llm_client()

    def set_llm_client(self, client: Any) -> None:
        """允许外部注入自定义 LLM 客户端。"""
        self.llm_client = client

    @abstractmethod
    async def run(
        self,
        session_graph: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        pass

    async def _react_loop(
        self,
        session_graph: Any,
        context: dict[str, Any],
        task_prompt: str,
    ) -> dict[str, Any]:
        """
        多轮 ReAct 循环。

        根据 self.use_function_calling 选择两种模式：
        - 若启用：使用 OpenAI function calling / tool calling 机制；
        - 若未启用：使用 Prompt 驱动的 ReAct JSON 格式（兼容现有 Agent）。

        每轮 LLM 可能输出工具调用或最终结论：
        - 如果输出工具调用，则执行工具，把结果加入上下文，继续下一轮；
        - 如果输出最终结论，循环结束。

        最大轮次由 self.max_turns 控制，防止无限循环。
        """
        # 本轮总线句柄：_call_tool 权限钩子经它发 denied/pending 事件（离线场景为 None）
        get_bus = getattr(session_graph, "get_bus", None)
        self._react_bus = get_bus() if callable(get_bus) else None
        # 本轮工具上下文：工具函数的 context 参数经它拿到会话图谱等运行时数据
        self._tool_context = {"session_graph": session_graph, "context": context}

        if self.use_function_calling and self.tools:
            return await self._function_calling_loop(task_prompt)
        return await self._prompt_based_loop(task_prompt)

    async def _function_calling_loop(
        self,
        task_prompt: str,
    ) -> dict[str, Any]:
        """基于 function calling 的多轮 ReAct 循环。"""
        tool_schemas = self._build_tool_schemas()
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task_prompt},
        ]

        final_output: Any = None

        for turn in range(1, self.max_turns + 1):
            try:
                result = await self.llm_client.chat_completion_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=0.3,
                    max_tokens=2048,
                )
            except Exception as e:
                self.logs.append({
                    "turn": turn,
                    "mode": "function_calling",
                    "error": f"调用 LLM 失败: {e}",
                })
                return {
                    "output": {
                        "risk_type": "未得出结论",
                        "level": "low",
                        "confidence": 0.3,
                        "reason": f"{self.name} function calling 调用失败: {e}",
                    },
                    "logs": self.logs,
                }

            content = result.get("content", "")
            tool_calls = result.get("tool_calls", [])

            # 没有工具调用，说明 LLM 已经给出结论
            if not tool_calls:
                parsed = self._parse_json_output(content)
                self.logs.append({
                    "turn": turn,
                    "mode": "function_calling",
                    "action": "final_answer",
                    "content": content,
                })
                final_output = parsed if isinstance(parsed, dict) else content
                break

            # 有工具调用，执行工具并构造 tool 消息
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": content or "",
            }
            tool_call_messages = []
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_input = tc.get("arguments", {})
                observation = await self._call_tool(tool_name, tool_input)

                self.logs.append({
                    "turn": turn,
                    "mode": "function_calling",
                    "action": tool_name,
                    "action_input": tool_input,
                    "observation": observation,
                })

                tool_call_id = f"{self.name}_{turn}_{tool_name}"
                tool_call_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": self._format_observation(observation),
                })

                # 让 assistant_message 也包含 tool_calls 标记
                assistant_message.setdefault("tool_calls", []).append(
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_input, ensure_ascii=False),
                        },
                    }
                )

            messages.append(assistant_message)
            messages.extend(tool_call_messages)

        if final_output is None:
            final_output = {
                "risk_type": "未得出结论",
                "level": "low",
                "confidence": 0.3,
                "reason": "达到最大 ReAct 轮次仍未得出结论",
            }

        return {"output": final_output, "logs": self.logs}

    async def _prompt_based_loop(
        self,
        task_prompt: str,
    ) -> dict[str, Any]:
        """基于 Prompt 的 ReAct 循环（兼容模式）。"""
        react_format_instruction = (
            "\n\n你可以使用以下工具：\n"
            + ("\n".join(f"- {name}" for name in self.tools) or "（无可用工具）")
            + "\n\n请按以下 JSON 格式输出（不要加 markdown 代码块）：\n"
            "{\n"
            '  "thought": "当前思考",\n'
            '  "action": "工具名称 或 final_answer",\n'
            '  "action_input": {"参数名": "参数值"},\n'
            '  "final_answer": {"risk_type": "...", "level": "...", ...}\n'
            "}\n"
            "如果你已经得出结论，请把 action 设为 \"final_answer\"，并把结论放在 final_answer 中。"
        )

        messages = [
            {"role": "system", "content": self.system_prompt + react_format_instruction},
            {"role": "user", "content": task_prompt},
        ]

        final_output: Any = None

        for turn in range(1, self.max_turns + 1):
            try:
                raw_output = await self.llm_client.chat_completion(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=2048,
                )
            except Exception as e:
                self.logs.append({
                    "turn": turn,
                    "mode": "prompt_based",
                    "error": f"调用 LLM 失败: {e}",
                })
                return {
                    "output": {
                        "risk_type": "未得出结论",
                        "level": "low",
                        "confidence": 0.3,
                        "reason": f"{self.name} 调用 LLM 失败: {e}",
                    },
                    "logs": self.logs,
                }

            parsed = self._parse_react_output(raw_output)
            thought = parsed.get("thought", "")
            action = parsed.get("action", "")
            action_input = parsed.get("action_input", {})
            final_answer = parsed.get("final_answer")

            # 情况一：LLM 直接给出结论（final_answer 存在）
            if final_answer is not None:
                self.logs.append({
                    "turn": turn,
                    "mode": "prompt_based",
                    "thought": thought or "直接给出结论",
                    "action": "final_answer",
                    "action_input": {},
                    "observation": {"final_answer": final_answer},
                })
                final_output = final_answer
                break

            # 情况二：action 为空、final_answer 或 finish，结束循环
            if not action or action in ("final_answer", "finish", "done"):
                # 兼容旧 Agent：把整个 parsed 作为输出
                self.logs.append({
                    "turn": turn,
                    "mode": "prompt_based",
                    "thought": thought or "输出结论",
                    "action": "final_answer",
                    "action_input": {},
                    "observation": {"raw_output": raw_output, "parsed": parsed},
                })
                final_output = parsed
                break

            # 情况三：调用工具，继续下一轮
            observation = await self._call_tool(action, action_input)
            self.logs.append({
                "turn": turn,
                "mode": "prompt_based",
                "thought": thought or f"调用工具 {action}",
                "action": action,
                "action_input": action_input,
                "observation": observation,
            })

            observation_text = self._format_observation(observation)
            messages.append({"role": "assistant", "content": raw_output})
            messages.append({
                "role": "user",
                "content": f"工具调用结果：\n{observation_text}\n\n请继续思考并输出下一步。",
            })

        if final_output is None:
            final_output = {
                "risk_type": "未得出结论",
                "level": "low",
                "confidence": 0.3,
                "reason": "达到最大 ReAct 轮次仍未得出结论",
            }

        return {"output": final_output, "logs": self.logs}

    def _build_tool_schemas(self) -> list[dict[str, Any]]:
        """根据 self.tools 构建 OpenAI function calling 格式的工具 schema。"""
        schemas = []
        for name, tool in self.tools.items():
            description = getattr(tool, "__doc__", None) or f"调用工具 {name}"
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description.strip(),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "查询关键词或参数",
                                },
                                "top_k": {
                                    "type": "integer",
                                    "description": "返回结果数量",
                                },
                            },
                        },
                    },
                }
            )
        return schemas

    def _parse_react_output(self, text: str) -> dict[str, Any]:
        """
        解析 LLM 的 ReAct 输出。

        优先尝试解析 JSON；如果解析失败，或者解析后的字典缺少必要字段，
        则把整个输出作为 final_answer 兼容返回。
        """
        parsed = self._parse_json_output(text)

        # 如果解析结果是字典且包含 thought/action/final_answer 等字段，直接返回
        if isinstance(parsed, dict) and any(
            k in parsed for k in ("thought", "action", "final_answer")
        ):
            return parsed

        # 否则兼容旧模式：把整个 parsed 当作 final_answer
        return {"final_answer": parsed}

    def _parse_json_output(self, text: str) -> Any:
        """
        尝试从 LLM 输出中解析 JSON。

        模型可能直接返回 JSON，也可能用 markdown 代码块包裹（```json ... ```）。
        解析失败时返回原始文本。
        """
        import re

        text = text.strip()

        # 先尝试直接 json.loads
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 再尝试提取 ```json ... ``` 代码块
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 都失败则把原始文本返回
        return text

    async def _call_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        tool = self.tools.get(tool_name)
        if tool is None:
            return {
                "error": True,
                "message": f"工具 {tool_name} 不存在",
            }

        # 统一工具签名：字符串入参转 {"query": ...}（审批登记与执行共用归一化结果）
        if isinstance(tool_input, str):
            tool_input = {"query": tool_input}
        if not isinstance(tool_input, dict):
            tool_input = {}

        # 权限三态钩子（协议 plugin_registry.md §2）：
        # deny 直接拒绝；approve 在 HITL_ENABLED 时真挂起等审批，否则等同放行仅记审计事件
        from app.agentkit.events import EventType, emit
        from app.agentkit.tool_registry import resolve_permission

        bus = getattr(self, "_react_bus", None)
        permission = resolve_permission(tool_name)
        if permission == "deny":
            if bus is not None:
                await emit(
                    bus,
                    EventType.TOOL_PERMISSION_DENIED,
                    {"agent_name": self.name, "tool": tool_name},
                )
            return {
                "error": True,
                "message": f"工具 {tool_name} 被权限策略拒绝",
            }
        if permission == "approve":
            if bus is not None:
                await emit(
                    bus,
                    EventType.TOOL_PERMISSION_PENDING,
                    {"agent_name": self.name, "tool": tool_name},
                )
            if get_settings().HITL_ENABLED:
                blocked = await self._wait_human_approval(tool_name, tool_input, bus)
                if blocked is not None:
                    return blocked

        # context 带运行时数据（session_graph 等）；未经 _react_loop 时回落空字典
        tool_context = getattr(self, "_tool_context", None) or {}

        try:
            if asyncio.iscoroutinefunction(tool):
                result = await tool(tool_input, tool_context)
            else:
                result = tool(tool_input, tool_context)
            return {"result": result}
        except Exception as e:
            return {
                "error": True,
                "message": str(e),
            }

    async def _wait_human_approval(
        self, tool_name: str, tool_input: dict[str, Any], bus: Any
    ) -> dict[str, Any] | None:
        """HITL 挂起：登记待审 → 等人裁决。放行返回 None，否则返回错误观察。"""
        from app.agentkit import approval
        from app.agentkit.events import EventType, emit

        try:
            approval_id = approval.create_request(tool_name, self.name, tool_input)
        except Exception:  # noqa: BLE001 —— Redis 不可用 = 拒绝，不静默放行
            status, approval_id = "unavailable", ""
        else:
            status = await approval.wait_for_decision(approval_id)

        if status == "approved":
            if bus is not None:
                await emit(
                    bus,
                    EventType.TOOL_PERMISSION_APPROVED,
                    {"approval_id": approval_id, "tool": tool_name, "agent_name": self.name},
                )
            return None

        reason = {"denied": "审批被拒绝", "timeout": "审批超时未裁决", "unavailable": "审批服务不可用"}.get(
            status, f"审批状态 {status}"
        )
        if bus is not None:
            await emit(
                bus,
                EventType.TOOL_PERMISSION_REJECTED,
                {"approval_id": approval_id, "tool": tool_name, "agent_name": self.name, "reason": reason},
            )
        return {"error": True, "message": f"工具 {tool_name} {reason}"}

    def _format_observation(self, observation: dict[str, Any]) -> str:
        if observation.get("error"):
            return f"调用工具失败：{observation.get('message', '')}"
        return json.dumps(observation.get("result", {}), ensure_ascii=False, indent=2)

    async def publish_progress(
        self,
        bus: Any,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if bus is not None:
            await bus.publish(
                event_type,
                {"agent_name": self.name, **payload},
            )
