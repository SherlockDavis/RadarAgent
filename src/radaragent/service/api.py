from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from radaragent.service.digest import Digest, generate_digest
from radaragent.service.query import Answer, run_query
from radaragent.subscriptions.crud import scored_articles_for_user

if TYPE_CHECKING:
    from radaragent.providers.embedding import EmbeddingProvider
    from radaragent.providers.llm.base import LLMProvider
    from radaragent.storage import RAGStore
    from radaragent.storage.db import Database


@dataclass
class SearchFilters:
    keywords: list[str] = field(default_factory=list)
    min_score: float = 0.0
    source: str | None = None


@dataclass
class SearchResult:
    article_id: str
    title: str
    url: str
    source: str
    relevance_score: float
    summary: str
    tags: list[str]
    key_insight: str | None


class ServiceAPI:
    """Facade over RAG + processor + persistence. Sole entry point for
    consumers (Phase 3 CLI, Phase 4 web)."""

    def __init__(
        self,
        db: Database,
        store: RAGStore,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        history_context_size: int = 5,
    ) -> None:
        self._db = db
        self._store = store
        self._llm = llm
        self._embedder = embedder
        self._history_context_size = history_context_size

    def generate_digest(self, subscription_id: int, date: str) -> Digest:
        return asyncio.run(
            generate_digest(
                self._db,
                self._store,
                self._llm,
                self._embedder,
                subscription_id,
                date,
                self._history_context_size,
            )
        )

    async def query(self, user_id: int, question: str) -> Answer:
        return await run_query(self._db, self._store, self._llm, self._embedder, user_id, question)

    def search(self, user_id: int, filters: SearchFilters) -> list[SearchResult]:
        """Filter the user's scored articles. Pure DB + RAG metadata, no LLM,
        so it is safe to call synchronously from the web event loop."""
        keywords = [k.lower() for k in filters.keywords if k.strip()]
        source = (filters.source or "").lower().strip()
        results: list[SearchResult] = []
        for row in scored_articles_for_user(self._db, user_id):
            score = float(row["relevance_score"])
            if score < filters.min_score:
                continue
            meta = self._store.get_metadata(row["article_id"]) or {}
            title = str(meta.get("title", ""))
            art_source = str(meta.get("source", ""))
            if source and source not in art_source.lower():
                continue
            summary = row["summary"] or ""
            if keywords:
                haystack = f"{title} {summary}".lower()
                if not any(kw in haystack for kw in keywords):
                    continue
            results.append(
                SearchResult(
                    article_id=row["article_id"],
                    title=title,
                    url=str(meta.get("url", "")),
                    source=art_source,
                    relevance_score=score,
                    summary=summary,
                    tags=json.loads(row["tags_json"]) if row["tags_json"] else [],
                    key_insight=row["key_insight"],
                )
            )
        return results
