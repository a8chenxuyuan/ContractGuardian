"""
文件：app/rag/reranker.py
作用：交叉编码器重排（BGE-reranker-v2-m3）。

设计动机（为什么）：
- 双向量召回（dense+sparse + RRF）解决"召回率"，但排序仍由 embedding 相似度决定；
- cross-encoder 把 query 和候选文本拼在一起过模型，能逐 token 交互打分，
  精度显著高于 bi-encoder——代价是不能离线预计算，只能对少量候选在线打分；
- 因此只对去重后的 Top20 父块（用其子块文本打分）重排，取 Top5 返回。

不可用时（FlagEmbedding 缺失/模型未下载）rerank() 返回 None，调用方按召回顺序直通。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.core.config import get_settings

LOCAL_RERANKER_DIR = (
    Path(__file__).resolve().parent.parent.parent / "models" / "bge-reranker-v2-m3"
)


def _resolve_reranker_path(model_name: str) -> str:
    """优先使用项目本地模型目录，避免运行时联网下载。"""
    if "bge-reranker-v2-m3" in model_name and LOCAL_RERANKER_DIR.exists():
        marker = LOCAL_RERANKER_DIR / "config.json"
        if marker.exists():
            return str(LOCAL_RERANKER_DIR)
    return model_name


class RerankerClient:
    """交叉编码器重排客户端。"""

    def __init__(self, model_name: str | None = None, device: str | None = None):
        settings = get_settings()
        self.model_name = model_name or getattr(
            settings, "RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"
        )
        self.device = device or getattr(settings, "RERANKER_DEVICE", "cpu")
        self._model: Any | None = None

    def available(self) -> bool:
        """FlagEmbedding 是否可用（不触发模型加载）。"""
        try:
            import FlagEmbedding  # noqa: F401
            return True
        except ImportError:
            return False

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        from FlagEmbedding import FlagReranker

        path = _resolve_reranker_path(self.model_name)
        self._model = FlagReranker(path, use_fp16=(self.device != "cpu"))
        return self._model

    def _score_sync(self, pairs: list[list[str]]) -> list[float]:
        model = self._load_model()
        scores = model.compute_score(pairs, normalize=True, batch_size=8)
        # 单条时 FlagReranker 可能直接返回 float 而非 list
        if isinstance(scores, (int, float)):
            return [float(scores)]
        return [float(s) for s in scores]

    def rerank_sync(
        self, query: str, texts: list[str], top_k: int | None = None
    ) -> list[tuple[int, float]] | None:
        """对 (query, text) 打分并按分数降序。

        返回 [(原列表下标, 分数)]，分数已归一化到 0-1（compute_score normalize=True）。
        模型不可用返回 None，调用方按原顺序直通。
        """
        if not texts:
            return []
        if not self.available():
            return None
        try:
            scores = self._score_sync([[query, t] for t in texts])
        except Exception:
            # 模型加载失败/内存不足等：重排是增益项，失败不应中断检索
            return None

        ranked = sorted(
            ((i, s) for i, s in enumerate(scores)), key=lambda x: x[1], reverse=True
        )
        if top_k is not None:
            ranked = ranked[:top_k]
        return ranked

    async def rerank(
        self, query: str, texts: list[str], top_k: int | None = None
    ) -> list[tuple[int, float]] | None:
        """异步版本：CPU 推理放线程池，避免阻塞事件循环。"""
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.rerank_sync, query, texts, top_k)


# 全局单例
_reranker: RerankerClient | None = None


def get_reranker() -> RerankerClient:
    global _reranker
    if _reranker is None:
        _reranker = RerankerClient()
    return _reranker
