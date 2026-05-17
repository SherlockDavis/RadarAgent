from __future__ import annotations

import logging

from openai import AsyncOpenAI

from radaragent.providers.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embeddings API (also compatible with Azure / any OpenAI-shape provider).

    Note: DeepSeek does NOT expose an embedding endpoint, so even if your
    LLM provider is DeepSeek you'd need a separate ``OPENAI_API_KEY`` to use
    this. For an offline / single-key setup use ``LocalEmbeddingProvider``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self._dimension = _DIMENSIONS.get(model, 1536)

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        result = await self.embed_batch([text])
        return result[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(model=self.model, input=texts)
        return [list(item.embedding) for item in response.data]
