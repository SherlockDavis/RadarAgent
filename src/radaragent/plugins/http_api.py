from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp

from radaragent.plugins.base import SourcePlugin
from radaragent.storage import RawArticle

logger = logging.getLogger(__name__)


class HTTPAPIPlugin(SourcePlugin):
    """Generic JSON-over-HTTP source plugin, fully YAML-driven.

    Many APIs follow the same shape: one HTTP request → JSON response →
    extract a list at some path → map source fields to RawArticle fields.
    Configure that mapping here instead of writing a new Python class.

    Config schema::

        method: GET                          # GET | POST
        url: https://example.com/api
        headers: {User-Agent: "RadarAgent"}  # optional
        params: {limit: 30}                  # optional query params
        json: {...}                          # optional POST body
        json_path: "data.items"              # dot-path to article list (omit
                                             # for top-level list)
        field_mapping:                       # source -> RawArticle
          title: title
          url: link
          content: summary
          timestamp: published_at            # ISO string or unix int
          language: lang                     # optional
        default_language: en                 # used when language field missing
        timeout: 30
        schedule: "0 */2 * * *"
    """

    def __init__(self, plugin_id: str, config: dict[str, Any]) -> None:
        super().__init__(plugin_id, config)
        self.method: str = str(config.get("method", "GET")).upper()
        self.url: str = config["url"]
        self.headers: dict[str, str] = dict(config.get("headers", {}))
        self.params: dict[str, Any] = dict(config.get("params", {}))
        self.json_body: Any = config.get("json")
        self.json_path: str = config.get("json_path", "")
        self.field_mapping: dict[str, str] = dict(config.get("field_mapping", {}))
        self.default_language: str = config.get("default_language", "en")
        self.timeout: int = int(config.get("timeout", 30))
        self.schedule: str = config.get("schedule", "0 */2 * * *")

        for required in ("title", "url"):
            if required not in self.field_mapping:
                raise ValueError(f"HTTPAPIPlugin {plugin_id!r} requires 'field_mapping.{required}'")

    def get_schedule(self) -> str:
        return self.schedule

    async def fetch(self) -> list[RawArticle]:
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with (
            aiohttp.ClientSession(timeout=timeout, headers=self.headers) as session,
            session.request(
                self.method,
                self.url,
                params=self.params or None,
                json=self.json_body,
            ) as response,
        ):
            response.raise_for_status()
            payload = await response.json()

        items = _walk_path(payload, self.json_path)
        if not isinstance(items, list):
            raise RuntimeError(
                f"HTTPAPIPlugin {self.plugin_id!r}: json_path {self.json_path!r} "
                f"did not resolve to a list"
            )

        articles: list[RawArticle] = []
        for item in items:
            try:
                articles.append(self._map_item(item))
            except Exception:
                logger.warning(
                    "HTTPAPIPlugin %s: skipping malformed item: %r", self.plugin_id, item
                )
        return articles

    def _map_item(self, item: dict[str, Any]) -> RawArticle:
        get = self.field_mapping.get
        title = _read_field(item, get("title", "title"))
        url = _read_field(item, get("url", "url"))
        content = _read_field(item, get("content", "")) or ""
        language_field = get("language")
        language = _read_field(item, language_field) if language_field else self.default_language
        timestamp_field = get("timestamp")
        timestamp = (
            _coerce_timestamp(_read_field(item, timestamp_field))
            if timestamp_field
            else datetime.now(tz=UTC)
        )
        return RawArticle(
            title=str(title or "").strip(),
            url=str(url or "").strip(),
            content=str(content).strip(),
            source=self.plugin_id,
            language=str(language or self.default_language),
            timestamp=timestamp,
            metadata={"raw": item},
        )


def _walk_path(payload: Any, path: str) -> Any:
    if not path:
        return payload
    current = payload
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            return None
    return current


def _read_field(item: dict[str, Any], path: str | None) -> Any:
    if not path:
        return None
    return _walk_path(item, path)


def _coerce_timestamp(value: Any) -> datetime:
    if value is None:
        return datetime.now(tz=UTC)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(tz=UTC)
    return datetime.now(tz=UTC)
