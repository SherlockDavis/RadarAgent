from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radaragent.processor.llm_filter import build_sink
from radaragent.storage import DedupChecker, ProcessedArticle, RawArticle
from radaragent.subscriptions.crud import create_subscription, todays_scored_articles
from radaragent.subscriptions.models import Channel, SubscriptionCreate, SubscriptionFilter
from radaragent.users.auth import register


class FakeLLM:
    def __init__(self, score: float = 8.0) -> None:
        self.calls = 0
        self._score = score

    async def score_and_summarize(self, article, profile, output_language):
        self.calls += 1
        return ProcessedArticle(
            raw=article,
            relevance_score=self._score,
            summary=f"sum::{article.title}",
            tags=["t"],
            key_insight="insight",
        )

    async def generate_digest(self, articles, context):
        return "digest"


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 3

    async def embed(self, text: str):
        return [float(len(text) % 7), 1.0, 2.0]

    async def embed_batch(self, texts):
        return [[float(len(t) % 7), 1.0, 2.0] for t in texts]


class FakePlugin:
    plugin_id = "fake"


def _raw(title: str, url: str) -> RawArticle:
    return RawArticle(
        title=title,
        url=url,
        content=f"body of {title}",
        source="fake",
        language="en",
        timestamp=datetime.now(tz=UTC),
    )


@pytest.fixture
def store(tmp_path):
    from radaragent.storage import RAGStore

    return RAGStore(persist_directory=tmp_path / "chroma")


async def test_sink_scores_per_enabled_subscription(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    s1 = create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s1",
            interest_profile="p1",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    llm = FakeLLM(score=8.0)
    sink = build_sink(llm, FakeEmbedder(), store, DedupChecker(store), db)
    await sink(FakePlugin(), [_raw("A", "http://x/a"), _raw("B", "http://x/b")])

    rows = todays_scored_articles(db, s1.id)
    assert len(rows) == 2
    assert llm.calls == 2


async def test_sink_low_score_not_persisted(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s1",
            interest_profile="p1",
            filter=SubscriptionFilter(min_score=9.0),
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    llm = FakeLLM(score=5.0)
    sink = build_sink(llm, FakeEmbedder(), store, DedupChecker(store), db)
    await sink(FakePlugin(), [_raw("A", "http://x/a")])
    rows = db.connection.execute("SELECT COUNT(*) FROM article_scores").fetchone()[0]
    assert rows == 0


async def test_sink_skips_already_scored_pair(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s1",
            interest_profile="p1",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    llm = FakeLLM()
    sink = build_sink(llm, FakeEmbedder(), store, DedupChecker(store), db)
    art = _raw("A", "http://x/a")
    await sink(FakePlugin(), [art])
    await sink(FakePlugin(), [art])  # second pass: URL dedup + score-pair dedup
    assert llm.calls == 1
