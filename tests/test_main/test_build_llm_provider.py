from __future__ import annotations

import pytest

from radaragent.config.loader import LLMConfig, Settings
from radaragent.main import _build_llm_provider
from radaragent.providers.llm.anthropic import AnthropicLLMProvider
from radaragent.providers.llm.openai import OpenAILLMProvider


def _settings(provider: str) -> Settings:
    return Settings(
        llm=LLMConfig(
            provider=provider,
            filter_model="m1",
            digest_model="m2",
            api_key="k",
        )
    )


def test_build_openai_provider() -> None:
    assert isinstance(_build_llm_provider(_settings("openai")), OpenAILLMProvider)


def test_build_anthropic_provider() -> None:
    p = _build_llm_provider(_settings("anthropic"))
    assert isinstance(p, AnthropicLLMProvider)
    assert p.filter_model == "m1"
    assert p.digest_model == "m2"


def test_build_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match=r"unsupported llm\.provider"):
        _build_llm_provider(_settings("grok"))
