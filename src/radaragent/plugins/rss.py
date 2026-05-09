from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import feedparser

from radaragent.plugins.base import SourcePlugin
from radaragent.storage import RawArticle

logger = logging.getLogger(__name__)


class RSSPlugin(SourcePlugin):
    """Generic RSS / Atom feed reader.

    Config schema::

        urls: list[str]                # one or more feed URLs
        schedule: str = "*/30 * * * *" # cron expression
        default_language: str = "en"   # fallback when feed entries omit it
    """

    def __init__(self, plugin_id: str, config: dict[str, Any]) -> None:
        super().__init__(plugin_id, config)
        self.urls: list[str] = list(config.get("urls", []))
        self.schedule: str = config.get("schedule", "*/30 * * * *")
        self.default_language: str = config.get("default_language", "en")
        if not self.urls:
            raise ValueError(f"RSSPlugin {plugin_id!r} requires at least one URL")

    def get_schedule(self) -> str:
        return self.schedule

    async def fetch(self) -> list[RawArticle]:
        results = await asyncio.gather(
            *(self._fetch_one(url) for url in self.urls),
            return_exceptions=True,
        )
        articles: list[RawArticle] = []
        for url, result in zip(self.urls, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("RSS fetch failed for %s: %s", url, result)
                continue
            articles.extend(result)
        return articles

    async def _fetch_one(self, url: str) -> list[RawArticle]:
        # feedparser is synchronous; offload to a thread to avoid blocking the loop.
        parsed = await asyncio.to_thread(feedparser.parse, url)
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(f"failed to parse feed {url}: {parsed.bozo_exception}")

        feed_lang = parsed.feed.get("language", self.default_language)
        articles: list[RawArticle] = []
        for entry in parsed.entries:
            articles.append(
                RawArticle(
                    title=entry.get("title", "").strip(),
                    url=entry.get("link", url),
                    content=_extract_content(entry),
                    source=self.plugin_id,
                    language=entry.get("language", feed_lang),
                    timestamp=_extract_timestamp(entry),
                    metadata={"feed_url": url, "id": entry.get("id", entry.get("link"))},
                )
            )
        return articles


def _extract_content(entry: Any) -> str:
    if "content" in entry and entry.content:
        return str(entry.content[0].get("value", "")).strip()
    return str(entry.get("summary", "")).strip()


def _extract_timestamp(entry: Any) -> datetime:
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time is None:
        return datetime.now(tz=UTC)
    return datetime(*parsed_time[:6], tzinfo=UTC)
