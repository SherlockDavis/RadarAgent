from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from radaragent.storage import RawArticle


class SourcePlugin(ABC):
    """Base class for all data source plugins.

    Subclasses implement how to fetch articles from a specific source
    (RSS, REST API, etc.) and how often to schedule fetches.
    """

    def __init__(self, plugin_id: str, config: dict[str, Any]) -> None:
        self.plugin_id = plugin_id
        self.config = config

    @abstractmethod
    async def fetch(self) -> list[RawArticle]:
        """Fetch articles from this source."""

    @abstractmethod
    def get_schedule(self) -> str:
        """Return a cron expression defining fetch frequency."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.plugin_id!r}>"
