from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from radaragent.providers.embedding.base import EmbeddingProvider

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class LocalEmbeddingProvider(EmbeddingProvider):
    """sentence-transformers backed embedding provider.

    Default model is ``BAAI/bge-m3`` — a 1024-dim multilingual model that
    handles Chinese and English well in the same vector space. First call
    downloads ~2.3GB from HuggingFace. Set ``HF_ENDPOINT=https://hf-mirror.com``
    in environments where huggingface.co is unreachable.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self._model: SentenceTransformer | None = None
        self._device = device
        self._dimension: int | None = None
        self._load_lock = asyncio.Lock()

    def _ensure_loaded_sync(self) -> SentenceTransformer:
        if self._model is not None:
            return self._model
        # Imports deferred so the rest of the app doesn't pay the torch import
        # cost (and ~1.5GB of CUDA libs) when a different provider is used.
        import torch
        from sentence_transformers import SentenceTransformer

        device = self._device or _pick_device(torch)
        logger.info(
            "Loading embedding model %s on %s (first call may be slow)", self.model_name, device
        )
        self._model = SentenceTransformer(self.model_name, device=device)
        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise RuntimeError(f"model {self.model_name!r} did not report an embedding dimension")
        self._dimension = int(dim)
        logger.info("Loaded %s (dim=%d, device=%s)", self.model_name, self._dimension, device)
        return self._model

    async def _ensure_loaded(self) -> SentenceTransformer:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                await asyncio.to_thread(self._ensure_loaded_sync)
        assert self._model is not None
        return self._model

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._ensure_loaded_sync()
        assert self._dimension is not None
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        result = await self.embed_batch([text])
        return result[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await self._ensure_loaded()
        embeddings = await asyncio.to_thread(_encode, model, texts)
        return [list(v) for v in embeddings]


def _encode(model: Any, texts: list[str]) -> list[list[float]]:
    """Inference wrapper.

    ``normalize_embeddings=True`` makes the output unit-length, so cosine
    similarity reduces to a plain dot product. Chroma's cosine space already
    handles this internally, but normalizing here keeps vectors directly
    comparable outside Chroma too.
    """
    result = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return result.tolist()  # type: ignore[no-any-return]


def _pick_device(torch_module: Any) -> str:
    if torch_module.cuda.is_available():
        return "cuda"
    mps_backend = getattr(torch_module.backends, "mps", None)
    if mps_backend is not None and mps_backend.is_available():
        return "mps"
    return "cpu"
