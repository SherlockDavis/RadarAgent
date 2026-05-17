from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from radaragent.config import Settings
    from radaragent.providers.embedding import EmbeddingProvider
    from radaragent.providers.llm.base import LLMProvider
    from radaragent.storage import RAGStore
    from radaragent.storage.db import Database
    from radaragent.users import SessionStore


@dataclass
class WebContext:
    """Shared, process-wide handles the web layer borrows from the daemon.

    The web app runs in the same event loop as the scheduler, so it reuses the
    daemon's single SQLite connection, RAG store, providers and in-memory
    session store rather than constructing its own. ``reschedule`` is a closure
    over the live scheduler so subscription edits re-sync digest jobs without
    the routes reaching into scheduler internals.
    """

    settings: Settings
    db: Database
    store: RAGStore
    llm: LLMProvider
    embedder: EmbeddingProvider
    sessions: SessionStore
    reschedule: Callable[[int], None]
