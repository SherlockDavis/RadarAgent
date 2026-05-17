from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RawArticle:
    title: str
    url: str
    content: str
    source: str
    language: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessedArticle:
    raw: RawArticle
    relevance_score: float
    summary: str
    tags: list[str]
    key_insight: str
    is_duplicate: bool = False
