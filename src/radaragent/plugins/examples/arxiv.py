"""arXiv example plugin.

Demonstrates how to wrap a domain-specific Atom API behind a YAML config
that the user can think about in domain terms (categories, max results)
rather than URLs and field paths.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import feedparser

from radaragent.plugins.base import SourcePlugin
from radaragent.storage import RawArticle

logger = logging.getLogger(__name__)

_BASE_URL = "http://export.arxiv.org/api/query"


class ArxivPlugin(SourcePlugin):
    """Fetches recent arXiv submissions for a list of categories.

    Config schema::

        categories: [cs.LG, cs.CL]
        max_results: 30                   # default 30
        sort_by: submittedDate            # submittedDate | lastUpdatedDate | relevance
        sort_order: descending            # ascending | descending
        schedule: "0 */6 * * *"
    """

    def __init__(self, plugin_id: str, config: dict[str, Any]) -> None:
        super().__init__(plugin_id, config)
        self.categories: list[str] = list(config.get("categories", []))
        if not self.categories:
            raise ValueError(f"ArxivPlugin {plugin_id!r} requires at least one category")
        self.max_results: int = int(config.get("max_results", 30))
        self.sort_by: str = config.get("sort_by", "submittedDate")
        self.sort_order: str = config.get("sort_order", "descending")
        self.schedule: str = config.get("schedule", "0 */6 * * *")

    def get_schedule(self) -> str:
        return self.schedule

    def _build_url(self) -> str:
        cats = "+OR+".join(f"cat:{c}" for c in self.categories)
        return (
            f"{_BASE_URL}?search_query={cats}"
            f"&max_results={self.max_results}"
            f"&sortBy={self.sort_by}"
            f"&sortOrder={self.sort_order}"
        )

    async def fetch(self) -> list[RawArticle]:
        url = self._build_url()
        parsed = await asyncio.to_thread(feedparser.parse, url)
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(f"failed to parse arXiv feed: {parsed.bozo_exception}")

        articles: list[RawArticle] = []
        for entry in parsed.entries:
            articles.append(
                RawArticle(
                    title=str(entry.get("title", "")).strip(),
                    url=str(entry.get("link", "")).strip(),
                    content=str(entry.get("summary", "")).strip(),
                    source=self.plugin_id,
                    language="en",
                    timestamp=_extract_timestamp(entry),
                    metadata={
                        "authors": [a.get("name") for a in entry.get("authors", [])],
                        "categories": [t.get("term") for t in entry.get("tags", [])],
                        "arxiv_id": entry.get("id"),
                    },
                )
            )
        return articles


def _extract_timestamp(entry: Any) -> datetime:
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time is None:
        return datetime.now(tz=UTC)
    return datetime(*parsed_time[:6], tzinfo=UTC)
