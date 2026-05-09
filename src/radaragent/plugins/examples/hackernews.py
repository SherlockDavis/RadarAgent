"""Hacker News example plugin.

Uses the official HN Firebase API to fetch story metadata directly,
giving access to fields the hnrss.org RSS feed does not expose
(comment count, score, author). Also demonstrates a multi-step API:
one request lists the top story IDs, then we fan out to fetch each item.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp

from radaragent.plugins.base import SourcePlugin
from radaragent.storage import RawArticle

logger = logging.getLogger(__name__)

_BASE_URL = "https://hacker-news.firebaseio.com/v0"
_VALID_FEEDS = {"top", "new", "best"}


class HackerNewsPlugin(SourcePlugin):
    """Fetches the top / new / best stories from Hacker News.

    Config schema::

        feed: top                # top | new | best (default: top)
        limit: 30                # number of stories to fetch (default: 30)
        concurrency: 10          # parallel item requests (default: 10)
        timeout: 30
        schedule: "*/30 * * * *"
    """

    def __init__(self, plugin_id: str, config: dict[str, Any]) -> None:
        super().__init__(plugin_id, config)
        self.feed: str = config.get("feed", "top")
        if self.feed not in _VALID_FEEDS:
            raise ValueError(
                f"HackerNewsPlugin {plugin_id!r}: feed must be one of {sorted(_VALID_FEEDS)}, "
                f"got {self.feed!r}"
            )
        self.limit: int = int(config.get("limit", 30))
        self.concurrency: int = int(config.get("concurrency", 10))
        self.timeout: int = int(config.get("timeout", 30))
        self.schedule: str = config.get("schedule", "*/30 * * * *")

    def get_schedule(self) -> str:
        return self.schedule

    async def fetch(self) -> list[RawArticle]:
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            ids = await self._fetch_ids(session)
            ids = ids[: self.limit]
            semaphore = asyncio.Semaphore(self.concurrency)

            async def fetch_one(item_id: int) -> RawArticle | None:
                async with semaphore:
                    try:
                        return await self._fetch_item(session, item_id)
                    except Exception:
                        logger.warning("HN: failed to fetch item %d", item_id, exc_info=True)
                        return None

            results = await asyncio.gather(*(fetch_one(i) for i in ids))
        return [a for a in results if a is not None]

    async def _fetch_ids(self, session: aiohttp.ClientSession) -> list[int]:
        url = f"{_BASE_URL}/{self.feed}stories.json"
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
        if not isinstance(data, list):
            raise RuntimeError(f"HN: expected list of IDs, got {type(data).__name__}")
        return [int(i) for i in data]

    async def _fetch_item(self, session: aiohttp.ClientSession, item_id: int) -> RawArticle | None:
        url = f"{_BASE_URL}/item/{item_id}.json"
        async with session.get(url) as response:
            response.raise_for_status()
            item = await response.json()
        if not item or item.get("type") != "story" or item.get("dead") or item.get("deleted"):
            return None

        title = str(item.get("title", "")).strip()
        story_url = item.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
        text = str(item.get("text", "")).strip()
        return RawArticle(
            title=title,
            url=story_url,
            content=text or title,
            source=self.plugin_id,
            language="en",
            timestamp=datetime.fromtimestamp(int(item.get("time", 0)), tz=UTC),
            metadata={
                "id": item_id,
                "score": item.get("score"),
                "comments": item.get("descendants"),
                "author": item.get("by"),
                "hn_url": f"https://news.ycombinator.com/item?id={item_id}",
            },
        )
