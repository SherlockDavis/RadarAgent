from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from radaragent.providers.llm.anthropic import AnthropicLLMProvider
from radaragent.storage import ProcessedArticle, RawArticle


def _article() -> RawArticle:
    return RawArticle(
        title="Quantum breakthrough",
        url="http://x/q",
        content="A long article about qubits.",
        source="lab-news",
        language="en",
        timestamp=datetime.now(tz=UTC),
    )


def _processed(title: str, score: float) -> ProcessedArticle:
    return ProcessedArticle(
        raw=RawArticle(
            title=title,
            url=f"http://x/{title}",
            content="",
            source="s",
            language="en",
            timestamp=datetime.now(tz=UTC),
        ),
        relevance_score=score,
        summary=f"summary of {title}",
        tags=[],
        key_insight=f"insight {title}",
    )


def _resp(text: str) -> SimpleNamespace:
    # Anthropic Messages responses expose .content as a list of blocks;
    # a text block has a .text attribute.
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


@pytest.fixture
def provider() -> AnthropicLLMProvider:
    p = AnthropicLLMProvider(api_key="test-key")
    p._client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    return p


async def test_score_and_summarize_parses_json(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp(
        '{"relevance_score": 8.5, "summary": "好的", '
        '"tags": ["quantum", "physics"], "key_insight": "重要"}'
    )
    result = await provider.score_and_summarize(_article(), "量子计算", "zh")

    assert result.relevance_score == 8.5
    assert result.summary == "好的"
    assert result.tags == ["quantum", "physics"]
    assert result.key_insight == "重要"
    assert result.is_duplicate is False
    assert result.raw.title == "Quantum breakthrough"


async def test_score_uses_filter_model_and_cached_system_prompt(
    provider: AnthropicLLMProvider,
) -> None:
    provider._client.messages.create.return_value = _resp('{"relevance_score": 1}')
    await provider.score_and_summarize(_article(), "p", "en")

    kwargs = provider._client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
    assert kwargs["max_tokens"] == 1024
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "JSON object" in kwargs["system"][0]["text"]


async def test_score_tolerates_non_json(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp("sorry, I cannot")
    result = await provider.score_and_summarize(_article(), "p", "en")
    assert result.relevance_score == 0.0
    assert result.summary == ""


async def test_generate_digest(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp("# Digest\n- point")
    out = await provider.generate_digest([_processed("A", 9.0)], [_processed("Old", 5.0)])
    assert out == "# Digest\n- point"
    kwargs = provider._client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 2048
    assert "Today's articles" in kwargs["messages"][0]["content"]


async def test_answer(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp("Per the context, yes.")
    out = await provider.answer("Is X true?", [_processed("Doc", 7.0)])
    assert out == "Per the context, yes."
    kwargs = provider._client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 1024
    assert "Is X true?" in kwargs["messages"][0]["content"]
    assert "context" in kwargs["system"].lower()


async def test_answer_no_context(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp("Not enough info.")
    out = await provider.answer("Q?", [])
    assert out == "Not enough info."
    kwargs = provider._client.messages.create.call_args.kwargs
    assert "(no context)" in kwargs["messages"][0]["content"]
