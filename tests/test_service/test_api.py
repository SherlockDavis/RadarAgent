from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radaragent.service.api import SearchFilters, ServiceAPI
from radaragent.storage import RAGStore, RawArticle
from radaragent.subscriptions.crud import create_subscription, record_score
from radaragent.subscriptions.models import Channel, SubscriptionCreate
from radaragent.users.auth import register


class FakeLLM:
    async def score_and_summarize(self, article, profile, output_language):  # unused
        raise NotImplementedError

    async def generate_digest(self, articles, context):
        return f"DIGEST n={len(articles)} ctx={len(context)}"

    async def answer(self, question, context):
        return f"ANSWER to {question!r} using {len(context)} docs"


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 3

    async def embed(self, text: str):
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def store(tmp_path):
    return RAGStore(persist_directory=tmp_path / "chroma")


def _seed_article(store: RAGStore, url: str, title: str) -> str:
    from radaragent.storage import ProcessedArticle

    raw = RawArticle(
        title=title,
        url=url,
        content=f"content {title}",
        source="fake",
        language="en",
        timestamp=datetime.now(tz=UTC),
    )
    p = ProcessedArticle(
        raw=raw, relevance_score=0.0, summary=f"sum {title}", tags=[], key_insight=""
    )
    store.add(p, [1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    return store.article_id(url)


def test_generate_digest_writes_and_is_idempotent(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    sub = create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s",
            interest_profile="p",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    aid = _seed_article(store, "http://x/a", "A")
    record_score(db, aid, sub.id, 8.0, "sum A", ["t"], "insight")

    api = ServiceAPI(db=db, store=store, llm=FakeLLM(), embedder=FakeEmbedder())
    today = datetime.now(tz=UTC).date().isoformat()
    d1 = api.generate_digest(sub.id, today)
    assert "DIGEST n=1" in d1.content
    d2 = api.generate_digest(sub.id, today)  # rerun overwrites
    rows = db.connection.execute(
        "SELECT COUNT(*) FROM digests WHERE subscription_id=?", (sub.id,)
    ).fetchone()[0]
    assert rows == 1
    assert d2.date == today


async def test_query_scoped_to_user_articles(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    sub = create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s",
            interest_profile="p",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    aid = _seed_article(store, "http://x/a", "A")
    record_score(db, aid, sub.id, 8.0, "sum A", [], None)
    _seed_article(store, "http://x/other", "Other")  # not scored for this user

    api = ServiceAPI(db=db, store=store, llm=FakeLLM(), embedder=FakeEmbedder())
    ans = await api.query(u.id, "what is new?")
    assert "ANSWER" in ans.text
    assert ans.sources == [aid]


def test_search_is_placeholder(db, store):
    api = ServiceAPI(db=db, store=store, llm=FakeLLM(), embedder=FakeEmbedder())
    with pytest.raises(NotImplementedError):
        api.search(1, SearchFilters())
