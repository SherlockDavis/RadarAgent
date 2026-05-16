from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from radaragent.service.digest import Digest, generate_digest
from radaragent.service.query import Answer, run_query

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

    def search(self, user_id: int, filters: SearchFilters) -> list[Any]:
        raise NotImplementedError("search lands with the Phase 4 web layer")
