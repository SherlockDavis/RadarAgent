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
    provider: str = "local"  # local | openai
    model: str = "BAAI/bge-m3"
    device: str | None = None  # cuda | mps | cpu | None (auto-detect)
    dedup_threshold: float = 0.92
    api_key: str | None = None  # only used when provider=openai
    base_url: str | None = None


class StorageConfig(BaseModel):
    type: str = "chroma"
    sqlite_path: str = "./data/radaragent.db"
    chroma: dict[str, Any] = Field(default_factory=dict)
    qdrant: dict[str, Any] = Field(default_factory=dict)


class NotifierConfig(BaseModel):
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class OutputConfig(BaseModel):
    digest_schedule: str = "0 8 * * *"
    notifiers: list[NotifierConfig] = Field(default_factory=list)


class SMTPConfig(BaseModel):
    host: str
    port: int = 587
    username: str
    password: str
    use_tls: bool = True
    from_addr: str


class AuthConfig(BaseModel):
    session_ttl_days: int = 30


class DigestConfig(BaseModel):
    history_context_size: int = 5


class Settings(BaseModel):
    llm: LLMConfig
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    plugins: list[PluginConfig] = Field(default_factory=list)
    output: OutputConfig = Field(default_factory=OutputConfig)
    smtp: SMTPConfig | None = None
    auth: AuthConfig = Field(default_factory=AuthConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)


def load_settings(path: str | Path) -> Settings:
    return Settings.model_validate(_read_yaml_with_env(path))


def _read_yaml_with_env(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return _expand_env_vars(data)


def _expand_env_vars(value: Any) -> Any:
    """Recursively replace ${VAR} in string leaves with the env var value.

    Operating on parsed YAML (rather than the raw file text) means commented-
    out templates do not trigger lookups for env vars that don't exist.
    """
    if isinstance(value, str):
        return _ENV_PATTERN.sub(_replace_env_var, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


def _replace_env_var(match: re.Match[str]) -> str:
    var_name = match.group(1)
    value = os.environ.get(var_name)
    if value is None:
        raise KeyError(f"Environment variable {var_name!r} is referenced in config but not set")
    return value
