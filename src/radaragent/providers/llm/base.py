from __future__ import annotations

from abc import ABC, abstractmethod

from radaragent.storage import ProcessedArticle, RawArticle


class LLMProvider(ABC):
    """Unified LLM interface so the rest of the system is provider-agnostic.

    Concrete providers (OpenAI, Anthropic, local model, ...) implement
    scoring + digest generation. Embeddings are handled separately by
    ``EmbeddingProvider`` because not every LLM vendor exposes embeddings
    (DeepSeek doesn't) and users frequently want a local embedding model
    paired with a cloud chat model.
    """

    @abstractmethod
    async def score_and_summarize(
        self,
        article: RawArticle,
        profile: str,
        output_language: str,
    ) -> ProcessedArticle:
        """Score relevance, translate, and summarize in one call.

        Returns a ProcessedArticle whose ``relevance_score`` is in [0, 10].
        """

    @abstractmethod
    async def generate_digest(
        self,
        articles: list[ProcessedArticle],
        context: list[ProcessedArticle],
    ) -> str:
        """Generate a digest from today's articles + historical RAG context."""
