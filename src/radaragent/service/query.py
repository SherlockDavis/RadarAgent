from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from radaragent.storage import ProcessedArticle, RawArticle
from radaragent.subscriptions.crud import scored_article_ids_for_user

if TYPE_CHECKING:
    from radaragent.providers.embedding import EmbeddingProvider
    from radaragent.providers.llm.base import LLMProvider
    from radaragent.storage import RAGStore
    from radaragent.storage.db import Database


@dataclass
class Answer:
    text: str
    sources: list[str]


def _meta_to_processed(meta: dict[str, object]) -> ProcessedArticle:
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
        relevance_score=float(meta.get("relevance_score", 0.0)),  # type: ignore[arg-type]
        summary=str(meta.get("summary", "")),
        tags=[],
        key_insight="",
    )


async def run_query(
    db: Database,
    store: RAGStore,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    user_id: int,
    question: str,
    top_k: int = 8,
) -> Answer:
    allowed = scored_article_ids_for_user(db, user_id)
    if not allowed:
        return Answer(text="你还没有任何已评分的文章可供检索。", sources=[])
    qvec = await embedder.embed(question)
    neighbors = store.nearest_content(qvec, top_k=top_k)
    picked = [aid for aid, _ in neighbors if aid in allowed]
    context: list[ProcessedArticle] = []
    for aid in picked:
        meta = store.get_metadata(aid)
        if meta is not None:
            context.append(_meta_to_processed(meta))
    text = await llm.answer(question, context)
    return Answer(text=text, sources=picked)
