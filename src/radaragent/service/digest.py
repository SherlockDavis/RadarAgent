from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from radaragent.storage import ProcessedArticle, RawArticle
from radaragent.subscriptions.crud import (
    get_subscription,
    record_digest,
    todays_scored_articles,
)

if TYPE_CHECKING:
    from radaragent.providers.embedding import EmbeddingProvider
    from radaragent.providers.llm.base import LLMProvider
    from radaragent.storage import RAGStore
    from radaragent.storage.db import Database


@dataclass
class Digest:
    subscription_id: int
    date: str
    content: str
    article_ids: list[str]


def _meta_to_processed(meta: dict[str, object], score: float, summary: str) -> ProcessedArticle:
    ts_raw = str(meta.get("timestamp") or datetime.now(tz=UTC).isoformat())
    try:
        ts = datetime.fromisoformat(ts_raw)
    except ValueError:
        ts = datetime.now(tz=UTC)
    return ProcessedArticle(
        raw=RawArticle(
            title=str(meta.get("title", "")),
            url=str(meta.get("url", "")),
            content="",
            source=str(meta.get("source", "")),
            language=str(meta.get("language", "en")),
            timestamp=ts,
        ),
        relevance_score=score,
        summary=summary,
        tags=[],
        key_insight="",
    )


async def generate_digest(
    db: Database,
    store: RAGStore,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    subscription_id: int,
    date: str,
    history_context_size: int = 5,
) -> Digest:
    sub = get_subscription(db, subscription_id)
    if sub is None:
        raise ValueError(f"subscription {subscription_id} not found")

    rows = todays_scored_articles(db, subscription_id, date)
    today_articles: list[ProcessedArticle] = []
    article_ids: list[str] = []
    for r in rows:
        meta = store.get_metadata(r["article_id"])
        if meta is None:
            continue
        today_articles.append(_meta_to_processed(meta, r["relevance_score"], r["summary"]))
        article_ids.append(r["article_id"])

    context: list[ProcessedArticle] = []
    if today_articles:
        qvec = await embedder.embed(sub.interest_profile)
        for aid, _ in store.nearest_content(qvec, top_k=history_context_size):
            if aid in article_ids:
                continue
            meta = store.get_metadata(aid)
            if meta:
                context.append(
                    _meta_to_processed(
                        meta,
                        float(meta.get("relevance_score", 0.0)),
                        str(meta.get("summary", "")),
                    )
                )

    content = await llm.generate_digest(today_articles, context)
    record_digest(db, subscription_id, date, content, article_ids)
    return Digest(
        subscription_id=subscription_id,
        date=date,
        content=content,
        article_ids=article_ids,
    )
