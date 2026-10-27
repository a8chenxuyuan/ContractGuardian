"""
工具：web_search
作用：使用 Tavily 联网搜索法规、司法解释、典型案例等法律内容。

输入示例：
{
    "query": "中华人民共和国公司法 第八十六条 股权转让 原文",
    "max_results": 5,
    "search_depth": "advanced",
    "include_raw_content": true
}

输出示例：
{
    "results": [
        {
            "title": "...",
            "url": "...",
            "content": "...",
            "raw_content": "...",
            "score": 0.95
        }
    ],
    "count": 1,
    "query": "..."
}
"""

from __future__ import annotations

from typing import Any

import httpx

from app.agentkit.tool_registry import register_tool
from app.core.config import get_settings

TAVILY_API_URL = "https://api.tavily.com/search"


# 联网外呼有外部副作用，声明 APPROVE：HITL 审批实现前等同放行并记 pending 事件
@register_tool("web_search", permission="approve")
async def web_search(input: dict, context: dict) -> dict[str, Any]:
    """
    使用 Tavily 执行联网搜索。

    优先使用 httpx 直接请求 Tavily REST API，避免对 tavily-python 包的强依赖。
    当 TAVILY_API_KEY 未配置时，返回空结果并给出明确提示。
    """
    settings = get_settings()
    api_key = settings.TAVILY_API_KEY

    query = input.get("query", "").strip()
    max_results = input.get("max_results", settings.TAVILY_MAX_RESULTS)
    search_depth = input.get("search_depth", settings.TAVILY_SEARCH_DEPTH)
    include_raw_content = input.get("include_raw_content", True)

    if not api_key or api_key.startswith("tvly-") and len(api_key) < 20:
        return {
            "results": [],
            "count": 0,
            "query": query,
            "error": "TAVILY_API_KEY 未配置或无效，请在 .env 中设置正确的 API Key（https://tavily.com）。",
        }

    if not query:
        return {"results": [], "count": 0, "query": query}

    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": bool(include_raw_content),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TAVILY_API_URL, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        return {
            "results": [],
            "count": 0,
            "query": query,
            "error": f"Tavily API 请求失败: HTTP {e.response.status_code} - {e.response.text}",
        }
    except Exception as e:
        return {
            "results": [],
            "count": 0,
            "query": query,
            "error": f"Tavily 搜索异常: {e}",
        }

    raw_results = data.get("results", []) or []
    results = []
    for item in raw_results:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "raw_content": item.get("raw_content", ""),
                "score": item.get("score", 0.0),
            }
        )

    return {
        "results": results,
        "count": len(results),
        "query": query,
    }
