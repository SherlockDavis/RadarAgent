"""SEC EDGAR example plugin.

Demonstrates a JSON API that *requires* a User-Agent header (SEC will
reject requests without one and rate-limit aggressively otherwise) — a
case the generic HTTPAPIPlugin can also cover, but here we showcase
a richer per-source data shape (companies + filings).
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


class SECEdgarPlugin(SourcePlugin):
    """Fetches the latest SEC filings for a list of company CIKs.

    Config schema::

        ciks: ["0000320193", "0001318605"]    # padded 10-digit CIKs
        user_agent: "RadarAgent your@email.com"  # SEC requires this
        max_per_company: 10                   # default 10
        timeout: 30
        schedule: "0 */4 * * *"

    Reference: https://www.sec.gov/edgar/sec-api-documentation
    """

    def __init__(self, plugin_id: str, config: dict[str, Any]) -> None:
        super().__init__(plugin_id, config)
        self.ciks: list[str] = [_pad_cik(c) for c in config.get("ciks", [])]
        if not self.ciks:
            raise ValueError(f"SECEdgarPlugin {plugin_id!r} requires at least one CIK")
        self.user_agent: str = config.get("user_agent", "")
        if not self.user_agent:
            raise ValueError(
                f"SECEdgarPlugin {plugin_id!r} requires a 'user_agent' "
                "(SEC rejects requests without one)"
            )
        self.max_per_company: int = int(config.get("max_per_company", 10))
        self.timeout: int = int(config.get("timeout", 30))
        self.schedule: str = config.get("schedule", "0 */4 * * *")

    def get_schedule(self) -> str:
        return self.schedule

    async def fetch(self) -> list[RawArticle]:
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            results = await asyncio.gather(
                *(self._fetch_company(session, cik) for cik in self.ciks),
                return_exceptions=True,
            )
        articles: list[RawArticle] = []
        for cik, result in zip(self.ciks, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("SEC fetch failed for CIK %s: %s", cik, result)
                continue
            articles.extend(result)
        return articles

    async def _fetch_company(self, session: aiohttp.ClientSession, cik: str) -> list[RawArticle]:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()

        company = data.get("name", f"CIK {cik}")
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        primary_documents = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])

        articles: list[RawArticle] = []
        for i in range(min(self.max_per_company, len(forms))):
            accession_no_dashes = accession_numbers[i].replace("-", "")
            doc = primary_documents[i] if i < len(primary_documents) else ""
            doc_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dashes}/{doc}"
            )
            articles.append(
                RawArticle(
                    title=f"{company} - {forms[i]}",
                    url=doc_url,
                    content=descriptions[i] if i < len(descriptions) else forms[i],
                    source=self.plugin_id,
                    language="en",
                    timestamp=_parse_filing_date(filing_dates[i]),
                    metadata={
                        "cik": cik,
                        "company": company,
                        "form": forms[i],
                        "accession_number": accession_numbers[i],
                    },
                )
            )
        return articles


def _pad_cik(cik: str | int) -> str:
    return str(cik).zfill(10)


def _parse_filing_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return datetime.now(tz=UTC)
