from __future__ import annotations

import logging
from dataclasses import dataclass

from radaragent.storage.rag import RAGStore

logger = logging.getLogger(__name__)


@dataclass
class DedupResult:
    is_duplicate: bool
    matched_id: str | None
    reason: str  # "url" | "semantic" | "none"
    similarity: float = 0.0


class DedupChecker:
    """Two-layer duplicate detection.

    1. **URL exact match** — cheapest, catches the common case of refetching
       the same feed. No vector work needed.
    2. **Cosine similarity** — embed-based near-duplicate detection. A new
       article whose content vector has cosine similarity ≥ ``threshold``
       with any existing article is flagged as a semantic duplicate. The
       default ``0.92`` is conservative: republished press releases and
       mirrored news pieces cluster well above 0.92 even across paraphrasing,
       while genuinely different stories on the same topic sit below.

    Duplicates are still written to storage (with ``is_duplicate=True``);
    the digest layer is responsible for filtering them out at display time.
    Keeping duplicates around preserves provenance — useful for "this story
    was first reported by X, then re-covered by Y" analyses later.
    """

    def __init__(self, store: RAGStore, threshold: float = 0.92, top_k: int = 5) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError(f"threshold must be in (0, 1], got {threshold}")
        self._store = store
        self.threshold = threshold
        self.top_k = top_k

    def check(self, url: str, content_vector: list[float]) -> DedupResult:
        if self._store.has_url(url):
            aid = self._store.article_id(url)
            return DedupResult(is_duplicate=True, matched_id=aid, reason="url", similarity=1.0)

        neighbors = self._store.nearest_content(content_vector, top_k=self.top_k)
        if neighbors:
            best_id, best_sim = neighbors[0]
            if best_sim >= self.threshold:
                return DedupResult(
                    is_duplicate=True,
                    matched_id=best_id,
                    reason="semantic",
                    similarity=best_sim,
                )

        return DedupResult(is_duplicate=False, matched_id=None, reason="none")
