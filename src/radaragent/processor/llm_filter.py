from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from radaragent.storage import ProcessedArticle, RawArticle
from radaragent.subscriptions.crud import (
    has_score,
    list_enabled_subscriptions,
    record_score,
)
from radaragent.subscriptions.models import Subscription
from radaragent.users.auth import _row_to_user

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from radaragent.providers.embedding import EmbeddingProvider
    from radaragent.providers.llm.base import LLMProvider
    from radaragent.storage import DedupChecker, RAGStore
    from radaragent.storage.db import Database

logger = logging.getLogger(__name__)


def build_sink(
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    store: RAGStore,
    dedup: DedupChecker,
    db: Database,
) -> Callable[[object, list[RawArticle]], Awaitable[None]]:
    """Fetch sink: store new article vectors once (global), then score each
    new article against every enabled subscription's profile.

    Scoring is the cartesian product article x subscription, deduplicated by
    the ``article_scores`` primary key so a re-fetched article is never
    re-scored for a subscription it already has a row for.
    """
    semaphore = asyncio.Semaphore(4)

    async def _score(sub: Subscription, art: RawArticle, out_lang: str) -> None:
        aid = store.article_id(art.url)
        if has_score(db, aid, sub.id):
            return
        async with semaphore:
            try:
                proc = await llm.score_and_summarize(art, sub.interest_profile, out_lang)
            except Exception:
                logger.exception("scoring failed: %s", art.url)
                return
        if proc.relevance_score >= sub.filter.min_score:
            record_score(
                db,
                aid,
                sub.id,
                proc.relevance_score,
                proc.summary,
                proc.tags,
                proc.key_insight,
            )

    async def sink(plugin: object, articles: list[RawArticle]) -> None:
        if not articles:
            return

        fresh = [a for a in articles if not store.has_url(a.url)]
        if fresh:
            content_vecs = await embedder.embed_batch([a.content[:4000] or a.title for a in fresh])
            for art, cv in zip(fresh, content_vecs, strict=True):
                result = dedup.check(art.url, cv)
                processed = ProcessedArticle(
                    raw=art,
                    relevance_score=0.0,
                    summary="",
                    tags=[],
                    key_insight="",
                    is_duplicate=result.is_duplicate,
                )
                store.add(processed, cv, cv)

        subscriptions = list_enabled_subscriptions(db)
        if not subscriptions:
            logger.info("no enabled subscriptions; %d article(s) stored only", len(fresh))
            return

        for sub in subscriptions:
            urow = db.connection.execute(
                "SELECT * FROM users WHERE id = ?", (sub.user_id,)
            ).fetchone()
            out_lang = _row_to_user(urow).output_language if urow else "zh"
            await asyncio.gather(*(_score(sub, a, out_lang) for a in articles))

    return sink
