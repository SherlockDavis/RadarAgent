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


def _seed_scored(db, store, *, url, title, score, summary):
    u = db.connection.execute("SELECT id FROM users LIMIT 1").fetchone()
    sub = create_subscription(
        db,
        SubscriptionCreate(
            user_id=u["id"],
            name=f"s-{title}",
            interest_profile="p",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    aid = _seed_article(store, url, title)
    record_score(db, aid, sub.id, score, summary, ["tag1"], "insight")
    return u["id"], aid


def test_search_returns_scored_articles(db, store):
    register(db, "a@b.com", "hunter2pass")
    uid, aid = _seed_scored(
        db, store, url="http://x/a", title="Alpha", score=8.0, summary="about ml"
    )
    api = ServiceAPI(db=db, store=store, llm=FakeLLM(), embedder=FakeEmbedder())

    res = api.search(uid, SearchFilters())
    assert len(res) == 1
    r = res[0]
    assert r.article_id == aid
    assert r.title == "Alpha"
    assert r.source == "fake"
    assert r.relevance_score == 8.0
    assert r.summary == "about ml"
    assert r.tags == ["tag1"]
    assert r.key_insight == "insight"


def test_search_min_score_filter(db, store):
    register(db, "a@b.com", "hunter2pass")
    uid, _ = _seed_scored(db, store, url="http://x/a", title="Low", score=3.0, summary="s")
    api = ServiceAPI(db=db, store=store, llm=FakeLLM(), embedder=FakeEmbedder())
    assert api.search(uid, SearchFilters(min_score=5.0)) == []
    assert len(api.search(uid, SearchFilters(min_score=2.0))) == 1


def test_search_keyword_and_source_filter(db, store):
    register(db, "a@b.com", "hunter2pass")
    uid, _ = _seed_scored(
        db, store, url="http://x/a", title="Quantum news", score=9.0, summary="qubits"
    )
    api = ServiceAPI(db=db, store=store, llm=FakeLLM(), embedder=FakeEmbedder())

    assert len(api.search(uid, SearchFilters(keywords=["quantum"]))) == 1
    assert api.search(uid, SearchFilters(keywords=["bioscience"])) == []
    assert len(api.search(uid, SearchFilters(source="fake"))) == 1
    assert api.search(uid, SearchFilters(source="nytimes")) == []
