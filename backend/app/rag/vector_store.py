"""
文件：app/rag/vector_store.py
作用：Qdrant 向量检索底座（M1 升级版）。

核心变化（相对 v1）：
- 父子两级索引：子块（200-400 字，含 LLM 定位句）做向量检索，命中后返回父块全文给 LLM；
- 双路召回：dense（语义）+ sparse（BGE-M3 词法权重），Qdrant 服务端 RRF(k=60) 融合；
- 交叉编码器重排：Top20 父块 → BGE-reranker-v2-m3 → Top5；
- collection 使用 named vectors（dense 1024 维 COSINE + sparse），
  新 collection 带 _v2 后缀，与旧数据隔离，可用 scripts/rebuild_index.py 重建。

降级链路（每一步都保证不中断）：
- FlagEmbedding 未安装 → 无 sparse 路，dense-only 检索；
- reranker 不可用 → 按 dense 相似度排序直通；
- 定位句 LLM 失败 → 机械拼接「标题+章节路径」。

分数语义：始终返回 0-1 的可比分数（重排开启时为 reranker 归一化分，
否则为 dense COSINE），search_knowledge 工具的 0.55 充分性阈值在两种模式下均成立。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import uuid
from typing import Any

import numpy as np

from app.core.config import get_settings

# v2 collection：named vectors 结构与 v1 不兼容，隔离命名
KNOWLEDGE_COLLECTION = "knowledge_articles_v2"
CONTRACT_COLLECTION = "contract_clauses_v2"
OLD_COLLECTIONS = ("knowledge_articles", "contract_clauses")  # v1 遗留，可手动删除

_DENSE_VECTOR = "dense"
_SPARSE_VECTOR = "sparse"


class VectorStoreError(Exception):
    """向量存储操作异常。"""


def _run_coro_sync(coro: Any) -> Any:
    """在任意上下文安全地同步执行协程。

    踩坑：asyncio.run 在已有事件循环内会抛 RuntimeError。
    sync 入口可能被脚本调用（无 loop），也可能被 async 代码残留调用（有 loop），
    统一丢到独立线程开新 loop 执行。
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


class VectorStore:
    """Qdrant 客户端封装：collection 管理、双路 upsert、混合检索。"""

    def __init__(self, url: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.url = url or settings.QDRANT_URL
        self.api_key = api_key or getattr(settings, "QDRANT_API_KEY", None)
        self._client: Any | None = None

    # ---------- 基础设施 ----------

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise VectorStoreError("qdrant-client 未安装") from exc

        # timeout=30：默认 5s 在 Qdrant flush/大批量写入期间会瞬时超时（踩坑记录）
        self._client = QdrantClient(url=self.url, api_key=self.api_key, timeout=30)
        return self._client

    def _get_collections(self) -> set[str]:
        client = self._get_client()
        try:
            collections = client.get_collections().collections
        except Exception as exc:
            raise VectorStoreError(f"无法连接 Qdrant: {exc}") from exc
        return {c.name for c in collections}

    def _ensure_collection(self, name: str) -> None:
        """确保 v2 collection 存在（named vectors: dense + sparse）。"""
        from qdrant_client.http.models import (
            Distance,
            SparseIndexParams,
            SparseVectorParams,
            VectorParams,
        )

        client = self._get_client()
        names = self._get_collections()
        if name in names:
            return

        sparse_params = (
            SparseVectorParams(index=SparseIndexParams(on_disk=False))
            if get_settings().RETRIEVAL_SPARSE_ENABLED
            else None
        )
        try:
            client.create_collection(
                collection_name=name,
                vectors_config={
                    _DENSE_VECTOR: VectorParams(size=1024, distance=Distance.COSINE),
                },
                sparse_vectors_config=(
                    {_SPARSE_VECTOR: sparse_params} if sparse_params else None
                ),
            )
        except Exception as exc:
            raise VectorStoreError(f"创建 Qdrant collection {name} 失败: {exc}") from exc

    @staticmethod
    def _sparse_enabled() -> bool:
        settings = get_settings()
        if not settings.RETRIEVAL_SPARSE_ENABLED:
            return False
        from app.llm.embeddings import get_dual_embedding_client

        return get_dual_embedding_client().available()

    # ---------- upsert：知识库 ----------

    async def upsert_knowledge_async(
        self,
        articles: list[dict[str, Any]],
        batch_size: int = 32,
        enhance: bool = True,
    ) -> int:
        """法律知识条目入库（父子切块 + 定位句 + 双路向量）。"""
        from qdrant_client.http.models import PointStruct

        from app.llm.embeddings import get_dual_embeddings
        from app.rag.chunker import build_knowledge_children

        if not articles:
            return 0

        self._ensure_collection(KNOWLEDGE_COLLECTION)
        client = self._get_client()

        # 1) 逐条切块，并把法条字段直接挂到子块上（避免后续反查 articles）
        all_children: list[dict[str, Any]] = []
        for article in articles:
            article_id = article.get("id")
            if article_id is None:
                continue
            children = build_knowledge_children(article.get("article_text", ""))
            if not children:
                continue
            for child in children:
                child["parent_id"] = f"ka-{article_id}"
                child["article_id"] = article_id
                child["law_name"] = article.get("law_name", "")
                child["article_number"] = article.get("article_number", "")
                child["article_title"] = article.get("article_title", "")
                child["category"] = article.get("category", "")
                child["article_text"] = article.get("article_text", "")
                all_children.append(child)

        if not all_children:
            return 0

        # 2) 定位句：LLM 增强或机械拼接
        locators = [""] * len(all_children)
        if enhance:
            try:
                from app.rag.context_enhancer import enhance_locators

                locators = await enhance_locators(None, all_children)
            except Exception:
                locators = [""] * len(all_children)
        if not enhance or any(loc == "" for loc in locators):
            for i, child in enumerate(all_children):
                if not locators[i]:
                    # 法条场景机械句用「法名+条号+标题」，比通用的"本文档"更有检索锚点
                    loc = " ".join(
                        p
                        for p in (
                            child.get("law_name", ""),
                            child.get("article_number", ""),
                            child.get("article_title", ""),
                        )
                        if p
                    )
                    locators[i] = f"【{loc}】" if loc else ""

        # 3) 编码（CPU 密集，放线程池）+ 分批 upsert
        total = 0
        for i in range(0, len(all_children), batch_size):
            batch = all_children[i : i + batch_size]
            batch_locators = locators[i : i + batch_size]
            texts = [
                f"{loc} {c['text']}".strip()
                for loc, c in zip(batch_locators, batch)
            ]
            vectors = await get_dual_embeddings(texts)

            points: list[PointStruct] = []
            for j, child in enumerate(batch):
                vec = vectors[j]
                point_vector: dict[str, Any] = {_DENSE_VECTOR: vec.get("dense", [])}
                if vec.get("sparse"):
                    point_vector[_SPARSE_VECTOR] = _make_sparse_vector(vec["sparse"])

                points.append(
                    PointStruct(
                        id=str(
                            uuid.uuid5(
                                uuid.NAMESPACE_DNS,
                                f"cgv2-ka-{child['article_id']}-{child['index']}",
                            )
                        ),
                        vector=point_vector,
                        payload={
                            "parent_id": child["parent_id"],
                            "article_id": child["article_id"],
                            "law_name": child.get("law_name", ""),
                            "article_number": child.get("article_number", ""),
                            "article_title": child.get("article_title", ""),
                            "category": child.get("category", ""),
                            "parent_text": child.get("article_text", ""),
                            "child_text": child["text"],
                            "locator": batch_locators[j],
                            "child_index": child["index"],
                        },
                    )
                )

            try:
                client.upsert(collection_name=KNOWLEDGE_COLLECTION, points=points)
            except Exception as exc:
                raise VectorStoreError(
                    f"写入 Qdrant collection {KNOWLEDGE_COLLECTION} 失败: {exc}"
                ) from exc
            total += len(points)

        return total

    def upsert_knowledge(
        self,
        articles: list[dict[str, Any]],
        batch_size: int = 32,
        enhance: bool = True,
    ) -> int:
        """同步入口（脚本场景）；async 上下文请直接 await upsert_knowledge_async。"""
        return _run_coro_sync(
            self.upsert_knowledge_async(articles, batch_size=batch_size, enhance=enhance)
        )

    # ---------- upsert：合同条款 ----------

    async def upsert_clauses_async(
        self,
        contract_id: int,
        clauses: list[dict[str, Any]],
        doc_title: str | None = None,
        enhance: bool = True,
        batch_size: int = 32,
    ) -> int:
        """合同条款入库。clauses 为 parser 产出的条款列表（section_path/text/page...）。

        幂等：先按 contract_id 清空旧向量再写。
        """
        from qdrant_client.http.models import PointStruct

        from app.llm.embeddings import get_dual_embeddings
        from app.rag.chunker import build_parents_and_children

        if not clauses:
            return 0

        self._ensure_collection(CONTRACT_COLLECTION)

        parents, children = build_parents_and_children(clauses)
        if not children:
            return 0

        # 定位句
        locators = [""] * len(children)
        if enhance:
            try:
                from app.rag.context_enhancer import enhance_locators

                locators = await enhance_locators(doc_title, children)
            except Exception:
                locators = [""] * len(children)
        if not enhance or any(loc == "" for loc in locators):
            for i, child in enumerate(children):
                if not locators[i]:
                    locators[i] = (
                        f"【本文档：{doc_title or '合同文档'} · "
                        f"{child.get('section_path', '')}】".replace("  ", " ")
                    )

        parent_map = {p["parent_id"]: p for p in parents}
        client = self._get_client()

        # 幂等：清掉该合同的旧向量
        try:
            self.delete_contract_clauses(contract_id)
        except VectorStoreError:
            pass

        total = 0
        for i in range(0, len(children), batch_size):
            batch = children[i : i + batch_size]
            batch_locators = locators[i : i + batch_size]
            texts = [
                f"{loc} {c['text']}".strip()
                for loc, c in zip(batch_locators, batch)
            ]
            vectors = await get_dual_embeddings(texts)

            points: list[PointStruct] = []
            for j, child in enumerate(batch):
                vec = vectors[j]
                point_vector: dict[str, Any] = {_DENSE_VECTOR: vec.get("dense", [])}
                if vec.get("sparse"):
                    point_vector[_SPARSE_VECTOR] = _make_sparse_vector(vec["sparse"])

                parent = parent_map.get(child["parent_id"], {})
                points.append(
                    PointStruct(
                        id=str(
                            uuid.uuid5(
                                uuid.NAMESPACE_DNS,
                                f"cgv2-cc-{contract_id}-{child['parent_id']}-{child['index']}",
                            )
                        ),
                        vector=point_vector,
                        payload={
                            "contract_id": contract_id,
                            "parent_id": child["parent_id"],
                            "section_path": child.get("section_path", ""),
                            "title": child.get("title", ""),
                            "page": parent.get("page", 1),
                            "parent_text": parent.get("text", child["text"]),
                            "child_text": child["text"],
                            "locator": batch_locators[j],
                            "child_index": child["index"],
                        },
                    )
                )

            try:
                client.upsert(collection_name=CONTRACT_COLLECTION, points=points)
            except Exception as exc:
                raise VectorStoreError(
                    f"写入 Qdrant collection {CONTRACT_COLLECTION} 失败: {exc}"
                ) from exc
            total += len(points)

        return total

    def upsert_clauses(
        self,
        contract_id: int,
        clauses: list[dict[str, Any]],
        doc_title: str | None = None,
        enhance: bool = True,
        batch_size: int = 32,
    ) -> int:
        """同步入口（脚本场景）；async 上下文请直接 await upsert_clauses_async。"""
        return _run_coro_sync(
            self.upsert_clauses_async(
                contract_id,
                clauses,
                doc_title=doc_title,
                enhance=enhance,
                batch_size=batch_size,
            )
        )

    def delete_contract_clauses(self, contract_id: int) -> None:
        """删除某个合同的所有条款向量。"""
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        client = self._get_client()
        if CONTRACT_COLLECTION not in self._get_collections():
            return

        client.delete(
            collection_name=CONTRACT_COLLECTION,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="contract_id", match=MatchValue(value=contract_id)
                    )
                ]
            ),
        )

    # ---------- 检索 ----------

    def _hybrid_search_core(
        self,
        collection: str,
        query: str,
        query_filter: Any | None,
        top_k: int,
        rerank: bool | None = None,
    ) -> list[dict[str, Any]]:
        """双路召回 + RRF 融合 + 父块去重 + 可选重排。"""
        from qdrant_client.http.models import FusionQuery, Prefetch, SparseVector

        settings = get_settings()
        self._ensure_collection(collection)
        client = self._get_client()

        from app.llm.embeddings import get_dual_embedding_client

        dual = get_dual_embedding_client()
        # core 在线程池中同步执行，用 encode_sync（async 版本只供 upsert 链路）
        q = dual.encode_sync([query])[0]
        if not q.get("dense"):
            return []

        prefetch: list[Prefetch] = [
            Prefetch(
                query=q["dense"],
                using=_DENSE_VECTOR,
                limit=settings.RETRIEVAL_PREFETCH_LIMIT,
                filter=query_filter,
            )
        ]
        use_sparse = self._sparse_enabled() and q.get("sparse")
        if use_sparse:
            prefetch.append(
                Prefetch(
                    query=SparseVector(
                        indices=q["sparse"]["indices"], values=q["sparse"]["values"]
                    ),
                    using=_SPARSE_VECTOR,
                    limit=settings.RETRIEVAL_PREFETCH_LIMIT,
                    filter=query_filter,
                )
            )

        response = client.query_points(
            collection_name=collection,
            prefetch=prefetch,
            query=FusionQuery(fusion="rrf"),
            limit=settings.RETRIEVAL_CANDIDATE_LIMIT,
            with_payload=True,
            with_vectors=[_DENSE_VECTOR],
        )

        # 父块去重：同一父块的多个子块只保留 RRF 名次最高的一个
        seen: dict[str, Any] = {}
        for point in response.points:
            pid = (point.payload or {}).get("parent_id")
            if pid is None:
                pid = str(point.id)
            if pid not in seen:
                seen[pid] = point
        candidates = list(seen.values())

        query_dense = np.asarray(q["dense"], dtype=np.float32)
        do_rerank = settings.RETRIEVAL_RERANK_ENABLED if rerank is None else rerank

        if do_rerank and candidates:
            from app.rag.reranker import get_reranker

            reranker = get_reranker()
            ranked = reranker.rerank_sync(
                query, [p.payload.get("child_text", "") for p in candidates]
            )
            if ranked is not None:
                return _apply_negative_penalty(
                    [
                        self._format_hit(candidates[idx], score=score, reranked=True)
                        for idx, score in ranked[:top_k]
                    ]
                )[:top_k]

        # 重排关闭或不可用：dense 余弦相似度排序（向量均已归一化，点积即余弦）
        scored: list[tuple[Any, float]] = []
        for p in candidates:
            vec = p.vector or {}
            dense = vec.get(_DENSE_VECTOR) if isinstance(vec, dict) else None
            score = (
                float(np.dot(query_dense, np.asarray(dense, dtype=np.float32)))
                if dense
                else 0.0
            )
            scored.append((p, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return _apply_negative_penalty(
            [self._format_hit(p, score=s, reranked=False) for p, s in scored[:top_k]]
        )[:top_k]

    @staticmethod
    def _format_hit(point: Any, score: float, reranked: bool) -> dict[str, Any]:
        """统一输出结构。article_text/text 一律返回父块全文，供 LLM 生成使用。"""
        payload = point.payload or {}
        hit = {
            "parent_id": payload.get("parent_id", ""),
            "score": round(float(score), 4),
            "locator": payload.get("locator", ""),
            "child_text": payload.get("child_text", ""),
        }
        if "law_name" in payload:
            hit.update(
                {
                    "law_name": payload.get("law_name", ""),
                    "article_number": payload.get("article_number", ""),
                    "article_title": payload.get("article_title", ""),
                    "article_text": payload.get(
                        "parent_text", payload.get("child_text", "")
                    ),
                    "category": payload.get("category", ""),
                }
            )
        else:
            hit.update(
                {
                    "section_path": payload.get("section_path", ""),
                    "text": payload.get("parent_text", payload.get("child_text", "")),
                    "page": payload.get("page"),
                }
            )
        return hit

    def search_knowledge(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 5,
        score_threshold: float = 0.0,
        rerank: bool | None = None,
    ) -> list[dict[str, Any]]:
        """语义搜索法律知识库（同步入口）。"""
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        query_filter = None
        if category:
            query_filter = Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            )
        results = self._hybrid_search_core(
            KNOWLEDGE_COLLECTION, query, query_filter, top_k, rerank=rerank
        )
        if score_threshold > 0:
            results = [r for r in results if r["score"] >= score_threshold]
        return results

    async def search_knowledge_async(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 5,
        score_threshold: float = 0.0,
        rerank: bool | None = None,
    ) -> list[dict[str, Any]]:
        """异步入口：CPU 密集的检索核心放线程池，避免阻塞事件循环。"""
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        query_filter = None
        if category:
            query_filter = Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            )
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: self._hybrid_search_core(
                KNOWLEDGE_COLLECTION, query, query_filter, top_k, rerank=rerank
            ),
        )
        if score_threshold > 0:
            results = [r for r in results if r["score"] >= score_threshold]
        return results

    def search_clauses(
        self,
        query: str,
        contract_id: int | None = None,
        top_k: int = 5,
        score_threshold: float = 0.0,
        rerank: bool | None = None,
    ) -> list[dict[str, Any]]:
        """语义搜索合同条款（同步入口）。"""
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        query_filter = None
        if contract_id is not None:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="contract_id", match=MatchValue(value=contract_id)
                    )
                ]
            )
        results = self._hybrid_search_core(
            CONTRACT_COLLECTION, query, query_filter, top_k, rerank=rerank
        )
        if score_threshold > 0:
            results = [r for r in results if r["score"] >= score_threshold]
        return results

    async def search_clauses_async(
        self,
        query: str,
        contract_id: int | None = None,
        top_k: int = 5,
        score_threshold: float = 0.0,
        rerank: bool | None = None,
    ) -> list[dict[str, Any]]:
        """异步入口。"""
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        query_filter = None
        if contract_id is not None:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="contract_id", match=MatchValue(value=contract_id)
                    )
                ]
            )
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: self._hybrid_search_core(
                CONTRACT_COLLECTION, query, query_filter, top_k, rerank=rerank
            ),
        )
        if score_threshold > 0:
            results = [r for r in results if r["score"] >= score_threshold]
        return results


def _apply_negative_penalty(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检索负样本降权（M5 闭环）：被用户纠错过的法条得分减半，沉到结果尾部。

    反例库读取失败时静默跳过——闭环是增益项，不能因反馈文件损坏中断检索。
    """
    try:
        from app.review.learning import get_counter_example_store

        negatives = get_counter_example_store().get_negative_law_keys()
    except Exception:
        return hits
    if not negatives:
        return hits
    for hit in hits:
        key = f"{hit.get('law_name', '')}|{hit.get('article_number', '')}"
        if key in negatives:
            hit["score"] = round(hit["score"] * 0.5, 4)
            hit["penalized"] = True
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits


def _make_sparse_vector(sparse: dict[str, list[Any]]) -> Any:
    from qdrant_client.http.models import SparseVector

    return SparseVector(
        indices=[int(i) for i in sparse.get("indices", [])],
        values=[float(v) for v in sparse.get("values", [])],
    )


# 全局默认 VectorStore 实例（单例）
_default_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """获取全局默认 VectorStore 实例。"""
    global _default_store
    if _default_store is None:
        _default_store = VectorStore()
    return _default_store
