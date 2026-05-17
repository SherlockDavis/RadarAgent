from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Vector embedding contract.

    Separated from ``LLMProvider`` because not every LLM vendor offers
    embeddings (DeepSeek doesn't; bge-m3 is local). Keeping the two
    concerns independent lets users mix-and-match.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector dimensionality."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embed a single string."""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many strings at once. Heavily preferred over looping ``embed``
        because most backends pay a fixed per-call overhead that batching amortizes.
        """
