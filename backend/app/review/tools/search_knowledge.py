"""
工具：search_knowledge
作用：查询法律知识库，返回相关法律条文。

检索策略：
1. 优先使用 Qdrant 向量语义检索，命中语义相关但关键词不同的法条；
2. 当 Qdrant 不可用、模型未加载或向量化失败时，自动回退到 SQLite/PostgreSQL 关键词 LIKE 检索；
3. 当本地检索结果不足（数量少或质量低），且开启 enable_web_search 时，
   调用 Tavily 联网搜索并提取原文，经去重后缓存到 PostgreSQL + Qdrant，然后再次本地检索返回结果。

输入示例：
{
    "query": "试用期",
    "category": "劳动合同法",
    "limit": 5,
    "enable_web_search": true
}

输出示例：
{
    "results": [
        {
            "law_name": "《中华人民共和国劳动合同法》",
            "article_number": "第十九条",
            "article_text": "..."
        }
    ],
    "count": 1,
    "source": "vector|keyword|web_cache"
}
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from app.agentkit.tool_registry import register_tool
from app.core.config import get_settings
from app.rag.knowledge_cache import cache_articles_from_web_search
from app.rag.vector_store import VectorStoreError, get_vector_store


def _is_local_results_sufficient(results: list[dict[str, Any]], limit: int) -> bool:
    """判断本地检索结果是否足够。"""
    if not results:
        return False
    # 如果结果数量达到 limit 的 60% 且第一条有合理分数，视为足够
    if len(results) >= max(1, limit * 0.6):
        top_score = results[0].get("score", 0.0)
        if top_score >= 0.55:
            return True
    # 否则只要结果数量达到 limit 也视为足够
    return len(results) >= limit


@register_tool("search_knowledge")
async def search_knowledge(input: dict, context: dict) -> dict[str, Any]:
    """查询法律知识库。优先语义检索，失败回退关键词检索；本地不足时联网搜索并缓存。"""
    query = input.get("query", "")
    category = input.get("category")
    limit = input.get("limit", 5)
    enable_web_search = input.get("enable_web_search", True)

    if not query:
        return {"results": [], "count": 0}

    # ---------- 1. 优先尝试向量语义检索 ----------
    try:
        store = get_vector_store()
        vector_results = await store.search_knowledge_async(
            query=query,
            category=category,
            top_k=limit,
            score_threshold=0.0,
        )
        if _is_local_results_sufficient(vector_results, limit):
            return {
                "results": vector_results,
                "count": len(vector_results),
                "source": "vector",
            }
    except VectorStoreError:
        # Qdrant 未启动或配置错误，继续回退关键词检索
        vector_results = []
    except Exception:
        # 模型加载失败、编码异常等，同样回退
        vector_results = []

    # ---------- 2. 回退：SQLite / PostgreSQL 关键词 LIKE 检索 ----------
    keyword_results = await _keyword_search_knowledge(query, category, limit)
    keyword_list = keyword_results.get("results", [])
    if _is_local_results_sufficient(keyword_list, limit):
        return {
            "results": keyword_list,
            "count": len(keyword_list),
            "source": "keyword",
        }

    # ---------- 3. 本地不足：联网搜索并缓存原文 ----------
    if enable_web_search:
        try:
            cached = await cache_articles_from_web_search(
                query=query,
                category=category,
                limit=max(1, limit - len(keyword_list)),
            )
            # 如果成功缓存了新法条，再次本地检索返回最新结果
            if cached and any(item.get("cached") for item in cached):
                # 优先重新做向量检索
                try:
                    store = get_vector_store()
                    vector_results = await store.search_knowledge_async(
                        query=query,
                        category=category,
                        top_k=limit,
                        score_threshold=0.0,
                    )
                    if vector_results:
                        return {
                            "results": vector_results,
                            "count": len(vector_results),
                            "source": "web_cache+vector",
                            "cached_count": len(cached),
                        }
                except Exception as exc:
                    # 联网缓存向量写入失败：缓存非关键路径，留痕后走关键词回退
                    print(f"[warn] web_cache 向量写入失败: {exc}", flush=True)

                # 向量失败则回退关键词
                keyword_results = await _keyword_search_knowledge(query, category, limit)
                if keyword_results.get("results"):
                    return {
                        "results": keyword_results["results"],
                        "count": keyword_results["count"],
                        "source": "web_cache+keyword",
                        "cached_count": len(cached),
                    }
        except Exception:
            # 联网缓存失败不应阻塞返回已有本地结果
            pass

    # ---------- 4. 返回本地已有结果（哪怕不足） ----------
    combined = vector_results or keyword_list
    return {
        "results": combined,
        "count": len(combined),
        "source": "local_fallback",
    }


async def _keyword_search_knowledge(
    query: str, category: str | None, limit: int
) -> dict[str, Any]:
    """基于 SQL 关键词匹配查询法律知识库。"""
    settings = get_settings()
    engine = create_engine(settings.SYNC_DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        from app.models.knowledge import KnowledgeArticle

        terms = [t.strip() for t in query.split() if t.strip()]
        filters = []
        for term in terms:
            filters.append(
                or_(
                    KnowledgeArticle.law_name.contains(term),
                    KnowledgeArticle.article_number.contains(term),
                    KnowledgeArticle.article_text.contains(term),
                    KnowledgeArticle.article_title.contains(term),
                )
            )

        q = db.query(KnowledgeArticle)
        if filters:
            q = q.filter(or_(*filters))
        if category:
            q = q.filter(KnowledgeArticle.category == category)

        articles = q.order_by(KnowledgeArticle.id).limit(limit).all()

        results = [
            {
                "law_name": a.law_name,
                "article_number": a.article_number,
                "article_title": a.article_title,
                "article_text": a.article_text,
                "category": a.category,
            }
            for a in articles
        ]
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"results": [], "count": 0, "error": str(e)}
    finally:
        db.close()
        engine.dispose()
