"""Semantic embeddings for KB chunks using multilingual MiniLM (via fastembed/ONNX)."""
import asyncio
import logging
from typing import List
from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

_model = None
_lock = asyncio.Lock()

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIM = 384


async def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        async with _lock:
            if _model is None:
                logger.info(f"Loading embedding model {MODEL_NAME}")
                _model = await asyncio.to_thread(TextEmbedding, MODEL_NAME)
                logger.info("Embedding model loaded")
    return _model


async def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    m = await _get_model()
    embs = await asyncio.to_thread(lambda: [e.tolist() for e in m.embed(texts)])
    return embs


async def embed_query(q: str) -> List[float]:
    m = await _get_model()
    embs = await asyncio.to_thread(lambda: [e.tolist() for e in m.query_embed([q])])
    return embs[0]


def cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
