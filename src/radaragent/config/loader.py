from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


class PluginConfig(BaseModel):
    id: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    provider: str = "openai"
    filter_model: str = "gpt-4o-mini"
    digest_model: str = "gpt-4o"
    api_key: str
    base_url: str | None = None


class EmbeddingConfig(BaseModel):
    provider: str = "openai"
    model: str = "text-embedding-3-small"


class StorageConfig(BaseModel):
    type: str = "chroma"
    chroma: dict[str, Any] = Field(default_factory=dict)
    qdrant: dict[str, Any] = Field(default_factory=dict)


class NotifierConfig(BaseModel):
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class OutputConfig(BaseModel):
    digest_schedule: str = "0 8 * * *"
    notifiers: list[NotifierConfig] = Field(default_factory=list)


class Settings(BaseModel):
    llm: LLMConfig
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    plugins: list[PluginConfig] = Field(default_factory=list)
    output: OutputConfig = Field(default_factory=OutputConfig)


class InterestsConfig(BaseModel):
    profile: str
    keywords_boost: list[str] = Field(default_factory=list)
    keywords_ignore: list[str] = Field(default_factory=list)
    output_language: str = "zh"
    min_relevance_score: float = 6.0
    max_articles_per_digest: int = 15


def load_settings(path: str | Path) -> Settings:
    return Settings.model_validate(_read_yaml_with_env(path))


def load_interests(path: str | Path) -> InterestsConfig:
    return InterestsConfig.model_validate(_read_yaml_with_env(path))


def _read_yaml_with_env(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    expanded = _ENV_PATTERN.sub(_replace_env_var, text)
    data = yaml.safe_load(expanded) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def _replace_env_var(match: re.Match[str]) -> str:
    var_name = match.group(1)
    value = os.environ.get(var_name)
    if value is None:
        raise KeyError(f"Environment variable {var_name!r} is referenced in config but not set")
    return value
