"""
文件：app/llm/client.py
作用：封装大模型调用客户端，提供统一的异步 chat_completion 接口。

当前实现使用 OpenAI 兼容接口，可对接：
- 阿里云百炼（Bailian）
- 通义千问（DashScope）兼容模式
- 智谱、DeepSeek、SiliconFlow 等兼容 OpenAI 协议的服务

配置来源：app/core/config.py 中的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
"""

from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings


class LLMClient:
    """
    LLM 调用客户端。

    通过 AsyncOpenAI 与模型服务通信，所有网络请求都是异步非阻塞的。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        """
        初始化 LLM 客户端。

        参数：
            api_key: 模型服务 API 密钥。默认从配置读取 LLM_API_KEY。
            base_url: 模型服务请求地址。默认从配置读取 LLM_BASE_URL。
            model: 模型名称。默认从配置读取 LLM_MODEL。
            timeout: 单次请求超时（秒）。默认读 LLM_TIMEOUT；视觉 OCR 等长任务可传更大值。
        """
        settings = get_settings()
        self.api_key = api_key or settings.LLM_API_KEY or ""
        self.base_url = base_url or settings.LLM_BASE_URL or None
        self.model = model or settings.LLM_MODEL or "qwen-max"

        # 创建 OpenAI 兼容客户端
        # 不填 base_url 时默认走 OpenAI 官方接口
        # timeout 防止模型服务无响应时审查任务被无限挂起（SDK 默认 600s 过长）
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout or settings.LLM_TIMEOUT,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> str:
        """
        调用大模型进行对话补全。

        参数：
            messages: 消息列表，格式为 [{"role": "system"/"user"/"assistant", "content": "..."}]
            model: 本次请求使用的模型名，默认使用初始化时配置的模型
            temperature: 采样温度，越低越稳定
            max_tokens: 最大返回 token 数
            kwargs: 其他透传给 OpenAI SDK 的参数

        返回：
            模型生成的文本字符串
        """
        result = await self.chat_completion_with_tools(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return result.get("content", "")

    async def chat_completion_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        调用大模型，支持 function calling / tool calling。

        参数：
            messages: 消息列表
            tools: 工具 schema 列表，OpenAI 格式
            model: 模型名
            temperature: 采样温度
            max_tokens: 最大返回 token 数
            kwargs: 其他透传参数

        返回：
            {"content": str, "tool_calls": [{"name": str, "arguments": dict}, ...]}
        """
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY 未配置，请在 .env 中设置")

        request_params: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,  # type: ignore[arg-type]
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(
            **request_params,
            **kwargs,
        )

        # 提取模型回复
        content = ""
        tool_calls: list[dict[str, Any]] = []

        if response.choices and len(response.choices) > 0:
            message = response.choices[0].message
            content = message.content or ""

            # 解析 tool_calls
            raw_tool_calls = getattr(message, "tool_calls", None)
            if raw_tool_calls:
                for tc in raw_tool_calls:
                    try:
                        import json

                        arguments = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        arguments = tc.function.arguments or {}
                    tool_calls.append(
                        {
                            "name": tc.function.name,
                            "arguments": arguments,
                        }
                    )
        else:
            content = getattr(response, "text", "") or ""

        # token 用量埋点：归因到当前审查 trace（未绑定则静默跳过）
        usage_obj = getattr(response, "usage", None)
        if usage_obj is not None:
            from app.llm.usage import record_usage

            record_usage(
                {
                    "model": request_params["model"],
                    "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
                }
            )

        return {"content": content, "tool_calls": tool_calls}

    async def close(self) -> None:
        """关闭客户端，释放网络连接。"""
        await self._client.close()


# 全局默认客户端实例，方便各模块直接导入使用
_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """获取全局默认 LLMClient 实例（单例）。"""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
