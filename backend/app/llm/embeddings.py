"""
文件：app/llm/embeddings.py
作用：封装文本向量模型，提供统一的 embedding 编码接口。

两条编码路径：
1. EmbeddingClient：sentence-transformers 加载 BGE-M3，仅稠密向量——
   供 red_flag_detector 等既有模块使用，行为不变；
2. DualEmbeddingClient：FlagEmbedding.BGEM3FlagModel 加载同一模型，
   一次前向同时输出 dense + sparse（词法权重）双路向量——供 M1 检索底座使用，
   与 Qdrant named vectors（dense + sparse）配合做混合检索。

模型在首次调用时延迟加载，避免启动时阻塞。

配置来源（环境变量 / .env）：
- EMBEDDING_MODEL: 模型名称或本地路径，默认 "BAAI/bge-m3"
- EMBEDDING_DEVICE: 运行设备，默认 "cpu"
- EMBEDDING_MAX_LENGTH: 双路编码最大 token 数，默认 1024（子块 ≤450 字足够）
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings

# 国内 Hugging Face 镜像，避免首次下载模型时连接超时
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 项目本地模型目录（scripts/download_models.py 预下载产物）
LOCAL_MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models" / "bge-m3"


def _resolve_model_path(model_name: str) -> str:
    """优先使用项目本地模型目录，避免运行时联网下载。"""
    if model_name in ("BAAI/bge-m3", "bge-m3") and LOCAL_MODELS_DIR.exists():
        marker = LOCAL_MODELS_DIR / "modules.json"
        if marker.exists():
            return str(LOCAL_MODELS_DIR)
    return model_name


class EmbeddingClient:
    """文本向量编码客户端。

    使用 sentence-transformers 加载模型，支持单条和批量编码。
    模型延迟加载，首次调用时初始化；后续复用同一实例。
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        normalize_embeddings: bool = True,
    ):
        settings = get_settings()
        self.model_name = model_name or getattr(settings, "EMBEDDING_MODEL", "BAAI/bge-m3")
        self.device = device or getattr(settings, "EMBEDDING_DEVICE", "cpu")
        self.normalize_embeddings = normalize_embeddings
        self._model: Any | None = None

    def _load_model(self) -> Any:
        """延迟加载 sentence-transformers 模型。"""
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("sentence-transformers 未安装，无法使用向量检索") from exc

        self._model = SentenceTransformer(_resolve_model_path(self.model_name), device=self.device)
        return self._model

    def encode(self, text: str) -> list[float]:
        """将单条文本编码为向量。"""
        if not text or not text.strip():
            return []
        model = self._load_model()
        vector = model.encode(
            text,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
        )
        return vector.astype(np.float32).tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """批量编码文本列表。"""
        if not texts:
            return []
        model = self._load_model()
        vectors = model.encode(
            texts,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [v.astype(np.float32).tolist() for v in vectors]

    def dimension(self) -> int:
        """返回模型输出向量的维度。"""
        # 优先从模型配置读取；若未加载则返回 BGE-M3 默认值
        if self._model is not None:
            return self._model.get_sentence_embedding_dimension()
        return 1024


# 全局默认客户端实例（单例）
_default_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    """获取全局默认 EmbeddingClient 实例。"""
    global _default_client
    if _default_client is None:
        _default_client = EmbeddingClient()
    return _default_client


async def get_embedding(text: str) -> list[float]:
    """异步友好的单文本编码辅助函数。

    sentence-transformers 的 encode 是 CPU 密集型同步调用，
    这里使用 run_in_executor 避免阻塞事件循环。
    """
    import asyncio

    loop = asyncio.get_event_loop()
    client = get_embedding_client()
    return await loop.run_in_executor(None, client.encode, text)


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """异步友好的批量编码辅助函数。"""
    import asyncio

    if not texts:
        return []

    loop = asyncio.get_event_loop()
    client = get_embedding_client()
    return await loop.run_in_executor(None, client.encode_batch, texts)


class DualEmbeddingClient:
    """BGE-M3 双路编码客户端（dense + sparse）。

    用 FlagEmbedding.BGEM3FlagModel 而非 sentence-transformers：
    后者只能取 dense，sparse（词法权重）需要前向时同时输出，
    BGEM3FlagModel 一次 encode 同时返回两路，模型权重同一份（约 2.3GB 内存）。
    """

    def __init__(self, model_name: str | None = None, device: str | None = None):
        settings = get_settings()
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.device = device or settings.EMBEDDING_DEVICE
        self.max_length = settings.EMBEDDING_MAX_LENGTH
        self._model: Any | None = None

    def available(self) -> bool:
        """FlagEmbedding 是否可导入（不触发模型加载）。"""
        try:
            import FlagEmbedding  # noqa: F401

            return True
        except ImportError:
            return False

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        from FlagEmbedding import BGEM3FlagModel

        path = _resolve_model_path(self.model_name)
        self._model = BGEM3FlagModel(path, use_fp16=False, device=self.device)
        return self._model

    def encode_sync(self, texts: list[str]) -> list[dict[str, Any]]:
        """同步编码：返回 [{dense: [1024], sparse: {indices, values}}]。"""
        model = self._load_model()
        output = model.encode(
            texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
            max_length=self.max_length,
        )
        dense_list = output.get("dense_vecs")
        sparse_list = output.get("lexical_weights", [])

        results: list[dict[str, Any]] = []
        for i in range(len(texts)):
            dense = (
                np.asarray(dense_list[i], dtype=np.float32).tolist()
                if dense_list is not None
                else []
            )
            sparse_raw = sparse_list[i] if i < len(sparse_list) else {}
            # BGE-M3 返回 {token_id_str: weight}；Qdrant 需要 indices/values 数组
            indices = [int(k) for k in sparse_raw.keys()]
            values = [float(v) for v in sparse_raw.values()]
            results.append(
                {"dense": dense, "sparse": {"indices": indices, "values": values}}
            )
        return results

    async def encode(self, texts: list[str]) -> list[dict[str, Any]]:
        """异步版本：模型加载与推理放线程池，避免阻塞事件循环。"""
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.encode_sync, texts)


_dual_client: DualEmbeddingClient | None = None


def get_dual_embedding_client() -> DualEmbeddingClient:
    """获取全局 DualEmbeddingClient（单例，延迟加载模型）。"""
    global _dual_client
    if _dual_client is None:
        _dual_client = DualEmbeddingClient()
    return _dual_client


async def get_dual_embeddings(texts: list[str]) -> list[dict[str, Any]]:
    """双路批量编码辅助函数。FlagEmbedding 不可用时 dense 置空（调用方降级）。"""
    client = get_dual_embedding_client()
    if not client.available():
        return [{"dense": [], "sparse": None} for _ in texts]
    return await client.encode(texts)
