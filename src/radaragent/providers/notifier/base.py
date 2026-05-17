from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Notifier(ABC):
    """Delivery channel contract. Implementations never raise on send
    failure — they log and return False so one bad channel cannot abort a
    digest job."""

    @abstractmethod
    async def send(self, content: str, channel_config: dict[str, Any]) -> bool:
        """Deliver ``content`` per ``channel_config``; return success."""
