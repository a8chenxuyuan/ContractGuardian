"""LLM 层：大模型客户端与向量编码。旧路径 app/llm.py / app/embeddings.py 的兼容垫片。"""

from app.llm.client import LLMClient, get_llm_client
from app.llm.embeddings import (
    DualEmbeddingClient,
    EmbeddingClient,
    get_dual_embedding_client,
    get_dual_embeddings,
    get_embedding,
    get_embedding_client,
    get_embeddings,
)

__all__ = [
    "DualEmbeddingClient",
    "EmbeddingClient",
    "LLMClient",
    "get_dual_embedding_client",
    "get_dual_embeddings",
    "get_embedding",
    "get_embedding_client",
    "get_embeddings",
    "get_llm_client",
]
