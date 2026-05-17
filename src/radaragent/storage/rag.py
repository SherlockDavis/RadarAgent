from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from radaragent.storage.models import ProcessedArticle

if TYPE_CHECKING:
    from chromadb.api import ClientAPI
    from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)

_CONTENT_COLLECTION = "articles_content"
_SUMMARY_COLLECTION = "articles_summary"


class RAGStore:
    """Chroma-backed vector store with parallel content + summary collections.

    Two collections per article share the same id (sha1 of url):

    * ``articles_content`` — vector is embedding of the original-language body.
      Used for dedup and same-language semantic retrieval.
    * ``articles_summary`` — vector is embedding of the target-language summary.
      Used for user-facing queries in the output language (e.g., a Chinese
      question against English source articles).

    Collections are created with ``hnsw:space=cosine`` so distance values
    from ``query()`` are in ``[0, 2]`` and ``similarity = 1 - distance``.
    """

    def __init__(self, persist_directory: str | Path) -> None:
        import chromadb

        path = Path(persist_directory)
        path.mkdir(parents=True, exist_ok=True)
        self._client: ClientAPI = chromadb.PersistentClient(path=str(path))
        self._content: Collection = self._client.get_or_create_collection(
            name=_CONTENT_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._summary: Collection = self._client.get_or_create_collection(
            name=_SUMMARY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "RAGStore ready at %s (content=%d, summary=%d)",
            path,
            self._content.count(),
            self._summary.count(),
        )

    @staticmethod
    def article_id(url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()

    def has_url(self, url: str) -> bool:
        existing = self._content.get(ids=[self.article_id(url)])
        return bool(existing.get("ids"))

    def nearest_content(self, vector: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        """Return up to ``top_k`` (article_id, cosine_similarity) pairs from the
        content collection, ordered by similarity descending.
        """
        count = self._content.count()
        if count == 0:
            return []
        result = self._content.query(
            query_embeddings=[vector],  # type: ignore[arg-type]
            n_results=min(top_k, count),
            include=["distances"],
        )
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0] or []  # type: ignore[index]
        pairs: list[tuple[str, float]] = []
        for aid, dist in zip(ids, distances, strict=True):
            pairs.append((aid, 1.0 - float(dist)))
        return pairs

    def add(
        self,
        processed: ProcessedArticle,
        content_vector: list[float],
        summary_vector: list[float],
    ) -> str:
        aid = self.article_id(processed.raw.url)
        metadata: dict[str, Any] = {
            "url": processed.raw.url,
            "title": processed.raw.title,
            "source": processed.raw.source,
            "language": processed.raw.language,
            "timestamp": processed.raw.timestamp.isoformat(),
            "relevance_score": float(processed.relevance_score),
            "tags": ",".join(processed.tags),
            "is_duplicate": bool(processed.is_duplicate),
        }
        self._content.upsert(
            ids=[aid],
            embeddings=[content_vector],  # type: ignore[arg-type]
            documents=[processed.raw.content[:5000]],
            metadatas=[metadata],
        )
        self._summary.upsert(
            ids=[aid],
            embeddings=[summary_vector],  # type: ignore[arg-type]
            documents=[processed.summary],
            metadatas=[metadata],
        )
        return aid

    def get_metadata(self, article_id: str) -> dict[str, Any] | None:
        """Return the summary collection's metadata for an article, with the
        stored summary document folded in under ``summary``."""
        got = self._summary.get(ids=[article_id], include=["metadatas", "documents"])
        metas = got.get("metadatas") or []
        if not metas:
            return None
        meta = dict(metas[0])
        docs = got.get("documents") or []
        if docs:
            meta["summary"] = docs[0]
        return meta

    def stats(self) -> dict[str, int]:
        return {
            "content": self._content.count(),
            "summary": self._summary.count(),
        }
