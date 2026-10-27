"""
工具：search_document
作用：在合同文本中搜索与查询语义相关的条款。

检索策略：
1. 优先使用 Qdrant 向量语义检索，命中语义相关但关键词不同的条款；
2. 当 Qdrant 不可用时，自动回退到本地关键词匹配。

输入示例：
{
    "query": "试用期"
}

输出示例：
{
    "results": [
        {"section_path": "1.1", "text": "本合同试用期为六个月...", "score": 0.92}
    ],
    "count": 1
}
"""

from typing import Any

from app.agentkit.tool_registry import register_tool
from app.rag.vector_store import VectorStoreError, get_vector_store


@register_tool("search_document")
async def search_document(input: dict, context: dict) -> dict[str, Any]:
    """在合同 chunks 中做语义/关键词搜索。"""
    query = input.get("query", "")
    session_graph = context.get("session_graph")
    chunks = context.get("chunks", [])
    contract_id = context.get("contract_id")
    top_k = input.get("limit", 5)

    if not query:
        return {"results": [], "count": 0}

    # ---------- 1. 优先尝试向量语义检索 ----------
    # 只有在提供了 contract_id 时才走 Qdrant 语义检索：
    # contract_clauses collection 按 contract_id 过滤，没有 contract_id 时语义检索意义有限；
    # 同时也能避免在测试或轻量场景中加载 BGE-M3 模型。
    if contract_id is not None:
        try:
            store = get_vector_store()
            vector_results = await store.search_clauses_async(
                query=query,
                contract_id=contract_id,
                top_k=top_k,
                score_threshold=0.0,
            )
            if vector_results:
                return {"results": vector_results, "count": len(vector_results)}
        except VectorStoreError:
            # Qdrant 未启动或配置错误，继续回退关键词检索
            pass
        except Exception:
            # 模型加载失败等，同样回退
            pass

    # ---------- 2. 回退：本地关键词匹配 ----------
    return _keyword_search_document(query, session_graph, chunks)


def _keyword_search_document(
    query: str,
    session_graph: Any | None,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """基于关键词匹配在合同 chunks 中搜索。"""
    if session_graph:
        clauses = session_graph.find_nodes(node_type="Clause")
    else:
        clauses = [
            {
                "properties": {
                    "text": c.get("text", ""),
                    "section_path": c.get("section_path", ""),
                }
            }
            for c in chunks
        ]

    query_terms = [q.strip() for q in query.split() if q.strip()]
    results = []

    for clause in clauses:
        props = clause.get("properties", {})
        text = props.get("text", "")
        if not text:
            continue

        if all(term in text for term in query_terms):
            results.append(
                {
                    "section_path": props.get("section_path", ""),
                    "text": text,
                    "score": 1.0,
                }
            )

    return {"results": results, "count": len(results)}
