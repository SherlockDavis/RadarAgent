from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from radaragent.providers.llm.base import LLMProvider
from radaragent.storage import ProcessedArticle, RawArticle

logger = logging.getLogger(__name__)

_SCORE_SYSTEM_PROMPT = """You are an information triage assistant for a personalized intelligence radar.

Given a user's interest profile and a single article, you must produce a strict JSON object with these fields:

{
  "relevance_score": number,   // 0-10, how well the article matches the profile
  "summary": string,           // 2-3 sentences, written in the requested output language
  "tags": string[],            // 3-7 short, lowercase, kebab-case topical tags
  "key_insight": string        // one-sentence takeaway in the output language
}

Hard rules:
- Output ONLY the JSON object, no markdown fences, no commentary.
- The summary and key_insight MUST be in the requested output language.
- Tags use the original-language vocabulary the article is about.
- If the article is empty or unintelligible, return relevance_score: 0 with a brief explanation in summary.
"""


class OpenAILLMProvider(LLMProvider):
    """OpenAI-backed LLMProvider.

    Uses two models — a cheap one for filter/score, a stronger one for digest
    generation — both selectable through ``filter_model`` and ``digest_model``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        filter_model: str = "gpt-4o-mini",
        digest_model: str = "gpt-4o",
        base_url: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.filter_model = filter_model
        self.digest_model = digest_model

    async def score_and_summarize(
        self,
        article: RawArticle,
        profile: str,
        output_language: str,
    ) -> ProcessedArticle:
        user_prompt = (
            f"User interest profile:\n{profile.strip()}\n\n"
            f"Output language: {output_language}\n\n"
            f"Article:\n"
            f"  title: {article.title}\n"
            f"  source: {article.source}\n"
            f"  url: {article.url}\n"
            f"  language: {article.language}\n"
            f"  content: {article.content[:4000]}\n"
        )
        response = await self._client.chat.completions.create(
            model=self.filter_model,
            messages=[
                {"role": "system", "content": _SCORE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        payload = _parse_json_payload(response.choices[0].message.content)
        return ProcessedArticle(
            raw=article,
            relevance_score=float(payload.get("relevance_score", 0.0)),
            summary=str(payload.get("summary", "")).strip(),
            tags=[str(t).strip() for t in payload.get("tags", []) if str(t).strip()],
            key_insight=str(payload.get("key_insight", "")).strip(),
            is_duplicate=False,
        )

    async def generate_digest(
        self,
        articles: list[ProcessedArticle],
        context: list[ProcessedArticle],
    ) -> str:
        # Phase 1: minimal digest. Phase 3 will replace this with a richer template.
        bullets = "\n".join(
            f"- [{a.relevance_score:.1f}] {a.raw.title} — {a.key_insight} ({a.raw.url})"
            for a in articles
        )
        context_bullets = "\n".join(f"- {c.raw.title} — {c.summary}" for c in context) or "(none)"
        user_prompt = (
            "Compose a concise daily intelligence digest from today's articles, "
            "drawing connections to the historical context where relevant. "
            "Output as Markdown with a short headline and grouped bullet points.\n\n"
            f"Today's articles:\n{bullets}\n\nHistorical context:\n{context_bullets}\n"
        )
        response = await self._client.chat.completions.create(
            model=self.digest_model,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.5,
        )
        return (response.choices[0].message.content or "").strip()

    async def answer(self, question: str, context: list[ProcessedArticle]) -> str:
        joined = (
            "\n\n".join(f"- {c.summary or c.raw.title} ({c.raw.url})" for c in context)
            or "(no context)"
        )
        response = await self._client.chat.completions.create(
            model=self.digest_model,
            messages=[
                {
                    "role": "system",
                    "content": "Answer the user's question using only the provided "
                    "context. Cite article titles. If the context is insufficient, "
                    "say so.",
                },
                {
                    "role": "user",
                    "content": f"Context:\n{joined}\n\nQuestion: {question}",
                },
            ],
            temperature=0.3,
        )
        return (response.choices[0].message.content or "").strip()


def _parse_json_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return dict(json.loads(raw))
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned non-JSON payload, falling back to empty: %s", exc)
        return {}
