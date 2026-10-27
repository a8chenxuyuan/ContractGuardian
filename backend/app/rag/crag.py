"""
文件：app/rag/crag.py
作用：CRAG（Corrective RAG）—— 检索质量自纠错。

设计动机（为什么）：
- 旧链路「向量检索 → 结果不够 → 直接降级关键词/联网」缺少质量判断：
  查询写得烂（口语化、术语对不上）时，检索结果是垃圾，LLM 拿着垃圾硬答；
- CRAG 在中间加一道闸门：先给检索结果打分（复用 reranker/余弦的 0-1 分数），
  不达标就用 LLM 把原问题改写成多个变体重新检索，还不行才降级——
  把「没找到」和「问法不对」区分开。

降级策略：最多 1 轮改写重检索（防延迟爆炸），最终结果始终返回，
degraded 标志告诉调用方「依据不足」。
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from app.core.config import get_settings

# 单批改写数量：3 个视角（口语化/术语化/法条原文风格）足够覆盖常见错配
_REWRITE_COUNT = 3


def max_score(results: list[dict[str, Any]]) -> float:
    """取检索结果最高分（0-1）。空结果返回 0。"""
    if not results:
        return 0.0
    return max(float(r.get("score", 0.0)) for r in results)


async def rewrite_queries(
    query: str,
    client: Any,
    model: str,
    count: int = _REWRITE_COUNT,
) -> list[str]:
    """用 LLM 把原问题改写为 count 个检索变体。

    视角：① 术语化（换成法条原文用词）② 口语化（同义表达）③ 拆解（去掉修饰只留核心）。
    失败返回空列表，由调用方降级——CRAG 是增益项，不能因改写失败中断。
    """
    prompt = (
        "你是法律检索查询改写助手。把下面的检索问题改写成 "
        f"{count} 个不同问法，用于法条库向量检索：\n"
        "1. 术语化：用中国法律条文的规范用词表达；\n"
        "2. 口语化：换一种日常说法；\n"
        "3. 核心：去掉修饰语，只留法律关键词。\n"
        '只输出 JSON：{"queries": ["改写1", "改写2", "改写3"]}\n\n'
        f"原问题：{query}"
    )
    try:
        content = await client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.3,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        start, end = content.find("{"), content.rfind("}")
        data = json.loads(content[start : end + 1])
        queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()]
        return queries[:count]
    except Exception:
        return []


async def corrective_search(
    search_fn: Callable[[str], Awaitable[list[dict[str, Any]]]],
    query: str,
    llm_client: Any | None = None,
    model: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """带纠错的检索主入口。

    search_fn: async (query_text) -> list[hit]，hit 需含 0-1 的 score 字段。
    返回 (结果列表, degraded)：degraded=True 表示两轮检索后仍未达到阈值，
    调用方应在报告中标注「依据不足」。

    闭环：检索 → 分数达标？→ 是：返回
                        → 否：LLM 改写 ×3 → 逐一检索 → 合并去重取最优 → 返回
    """
    settings = get_settings()
    threshold = settings.CRAG_SCORE_THRESHOLD

    results = await search_fn(query)
    if max_score(results) >= threshold:
        return results, False

    # 第一轮不达标 → 改写重检索（最多 1 轮，防延迟爆炸）
    if not settings.CRAG_ENABLED or llm_client is None:
        return results, True

    variants = await rewrite_queries(query, llm_client, model or settings.LLM_MODEL)
    if not variants:
        return results, True

    merged: dict[str, dict[str, Any]] = {}
    for r in results:  # 保留第一轮结果参与合并
        key = _dedup_key(r)
        if key:
            merged[key] = r
    for vq in variants:
        try:
            more = await search_fn(vq)
        except Exception:
            continue
        for r in more:
            key = _dedup_key(r)
            if key and key not in merged:
                merged[key] = r

    combined = sorted(merged.values(), key=lambda r: r.get("score", 0.0), reverse=True)
    return combined[: len(results) or 5], max_score(combined) >= threshold


def _dedup_key(hit: dict[str, Any]) -> str:
    """去重键：优先 law+article（知识库），否则 parent_id（合同条款）。"""
    law = hit.get("law_name")
    if law:
        return f"{law}|{hit.get('article_number', '')}"
    return str(hit.get("parent_id") or "")
