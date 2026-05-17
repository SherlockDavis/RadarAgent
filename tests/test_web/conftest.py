from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from radaragent.config import Settings
from radaragent.config.loader import LLMConfig
from radaragent.storage.db import Database
from radaragent.users import SessionStore
from radaragent.web import WebContext, create_app


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [float(len(text) % 7), 1.0, 0.0]


class FakeLLM:
    async def answer(self, question: str, context: list[object]) -> str:
        return f"answer to: {question} ({len(context)} sources)"

    async def generate_digest(self, today: list[object], history: list[object]) -> str:
        return f"digest of {len(today)} article(s)"


class FakeStore:
    """Minimal RAGStore stand-in: no vectors, empty corpus."""

    def get_metadata(self, article_id: str) -> dict[str, object] | None:
        return None

    def nearest_content(self, vector: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        return []


@pytest.fixture
def settings() -> Settings:
    return Settings(llm=LLMConfig(api_key="test-key"))


@pytest.fixture
def web_ctx(db: Database, settings) -> WebContext:
    rescheduled: list[int] = []
    ctx = WebContext(
        settings=settings,
        db=db,
        store=FakeStore(),  # type: ignore[arg-type]
        llm=FakeLLM(),  # type: ignore[arg-type]
        embedder=FakeEmbedder(),  # type: ignore[arg-type]
        sessions=SessionStore(),
        reschedule=rescheduled.append,
    )
    ctx.rescheduled = rescheduled  # type: ignore[attr-defined]
    return ctx


@pytest.fixture
def client(web_ctx: WebContext) -> Iterator[TestClient]:
    with TestClient(create_app(web_ctx)) as c:
        yield c
