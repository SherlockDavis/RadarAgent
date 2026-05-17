from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

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


class AnthropicLLMProvider(LLMProvider):
    """Claude-backed LLMProvider, drop-in alternative to OpenAILLMProvider.

    Anthropic has no JSON response-format flag, so scoring leans on the strict
    system prompt + tolerant parsing. That system prompt is identical on every
    scoring call, so it is sent as a ``cache_control`` block (prompt caching).
    """

    def __init__(
        self,
        *,
        api_key: str,
        filter_model: str = "claude-haiku-4-5-20251001",
        digest_model: str = "claude-sonnet-4-6",
        base_url: str | None = None,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url)
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
        response = await self._client.messages.create(
            model=self.filter_model,
            max_tokens=1024,
            temperature=0.2,
            system=[
                {
                    "type": "text",
                    "text": _SCORE_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
        payload = _parse_json_payload(_text(response))
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
        response = await self._client.messages.create(
            model=self.digest_model,
            max_tokens=2048,
            temperature=0.5,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return _text(response).strip()

    async def answer(self, question: str, context: list[ProcessedArticle]) -> str:
        joined = (
            "\n\n".join(f"- {c.summary or c.raw.title} ({c.raw.url})" for c in context)
            or "(no context)"
        )
        response = await self._client.messages.create(
            model=self.digest_model,
            max_tokens=1024,
            temperature=0.3,
            system="Answer the user's question using only the provided context. "
            "Cite article titles. If the context is insufficient, say so.",
            messages=[{"role": "user", "content": f"Context:\n{joined}\n\nQuestion: {question}"}],
        )
        return _text(response).strip()


def _text(response: Any) -> str:
    blocks = getattr(response, "content", None) or []
    if not blocks:
        return ""
    return str(getattr(blocks[0], "text", "") or "")


def _parse_json_payload(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return dict(json.loads(raw))
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned non-JSON payload, falling back to empty: %s", exc)
        return {}
