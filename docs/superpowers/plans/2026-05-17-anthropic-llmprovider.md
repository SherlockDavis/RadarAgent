# Anthropic LLMProvider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Claude-backed `AnthropicLLMProvider` as a drop-in alternative to the existing OpenAI/DeepSeek provider, selectable via `llm.provider: anthropic`.

**Architecture:** New `AnthropicLLMProvider(LLMProvider)` mirrors `OpenAILLMProvider`'s three methods using the `anthropic` AsyncAnthropic SDK. Anthropic has no `response_format=json_object`, so JSON scoring relies on the existing strict-JSON system prompt + the same tolerant parser. The static scoring system prompt is sent with `cache_control` (Anthropic prompt caching) since it repeats verbatim on every article. The daemon factory `_build_llm_provider` gains an `anthropic` branch; nothing else in the pipeline changes (it only depends on the `LLMProvider` ABC).

**Tech Stack:** Python 3.11+, `anthropic>=0.25` (already an optional extra), pytest + `unittest.mock` (no network/key in tests), existing `RawArticle`/`ProcessedArticle` models.

---

## File Structure

- `src/radaragent/providers/llm/anthropic.py` — **new**. `AnthropicLLMProvider` + private `_parse_json_payload` (intentionally duplicated 8-line helper rather than refactoring the untested working OpenAI provider — lower risk, follows the existing per-module pattern).
- `src/radaragent/providers/llm/__init__.py` — **modify**. Export `AnthropicLLMProvider`.
- `src/radaragent/main.py:38-46` — **modify**. Add `anthropic` branch to `_build_llm_provider`.
- `config/settings.yaml` — **modify**. Add a commented Anthropic example block.
- `.env.example` — **modify**. Uncomment/clarify `ANTHROPIC_API_KEY`.
- `CHANGELOG.md` — **modify**. Record under `## [Unreleased]`.
- `tests/test_providers/test_anthropic.py` — **new**. Unit tests with a mocked AsyncAnthropic client.

The provider is one focused file with one responsibility (translate the `LLMProvider` contract to Anthropic Messages API calls). It changes together with its test; the factory edit is the only integration point.

---

## Pre-requisite: install the anthropic extra into the dev venv

- [ ] **Step 1: Install anthropic into the existing venv**

The local `.venv` was created with `.[dev]` only; CI installs `.[dev,anthropic,...]`. The tests import `anthropic`, so install it locally:

Run: `cd /Users/hupochuan/Desktop/RadarAgent && .venv/bin/python -m pip install -q -e ".[dev,anthropic]"`
Expected: exits 0; `.venv/bin/python -c "import anthropic; print(anthropic.__version__)"` prints a version `>= 0.25`.

- [ ] **Step 2: Branch off develop**

Run:
```bash
cd /Users/hupochuan/Desktop/RadarAgent
git checkout develop && git pull --ff-only origin develop
git checkout -b feature/anthropic-llmprovider
```
Expected: on branch `feature/anthropic-llmprovider`, working tree clean.

---

## Task 1: `AnthropicLLMProvider.score_and_summarize` (+ prompt caching)

**Files:**
- Create: `src/radaragent/providers/llm/anthropic.py`
- Test: `tests/test_providers/test_anthropic.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_providers/test_anthropic.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from radaragent.providers.llm.anthropic import AnthropicLLMProvider
from radaragent.storage import RawArticle


def _article() -> RawArticle:
    return RawArticle(
        title="Quantum breakthrough",
        url="http://x/q",
        content="A long article about qubits.",
        source="lab-news",
        language="en",
        timestamp=datetime.now(tz=UTC),
    )


def _resp(text: str) -> SimpleNamespace:
    # Anthropic Messages responses expose .content as a list of blocks;
    # a text block has a .text attribute.
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


@pytest.fixture
def provider() -> AnthropicLLMProvider:
    p = AnthropicLLMProvider(api_key="test-key")
    p._client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    return p


async def test_score_and_summarize_parses_json(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp(
        '{"relevance_score": 8.5, "summary": "好的", '
        '"tags": ["quantum", "physics"], "key_insight": "重要"}'
    )
    result = await provider.score_and_summarize(_article(), "量子计算", "zh")

    assert result.relevance_score == 8.5
    assert result.summary == "好的"
    assert result.tags == ["quantum", "physics"]
    assert result.key_insight == "重要"
    assert result.is_duplicate is False
    assert result.raw.title == "Quantum breakthrough"


async def test_score_uses_filter_model_and_cached_system_prompt(
    provider: AnthropicLLMProvider,
) -> None:
    provider._client.messages.create.return_value = _resp('{"relevance_score": 1}')
    await provider.score_and_summarize(_article(), "p", "en")

    kwargs = provider._client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
    assert kwargs["max_tokens"] == 1024
    # System prompt is a cache-controlled block (Anthropic prompt caching).
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "JSON object" in kwargs["system"][0]["text"]


async def test_score_tolerates_non_json(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp("sorry, I cannot")
    result = await provider.score_and_summarize(_article(), "p", "en")
    assert result.relevance_score == 0.0
    assert result.summary == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_providers/test_anthropic.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.providers.llm.anthropic'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/radaragent/providers/llm/anthropic.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_providers/test_anthropic.py -q`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/radaragent/providers/llm/anthropic.py tests/test_providers/test_anthropic.py
git commit -m "feat(provider): AnthropicLLMProvider.score_and_summarize + prompt caching

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `generate_digest`

**Files:**
- Modify: `src/radaragent/providers/llm/anthropic.py`
- Test: `tests/test_providers/test_anthropic.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_providers/test_anthropic.py`:

```python
from radaragent.storage import ProcessedArticle


def _processed(title: str, score: float) -> ProcessedArticle:
    return ProcessedArticle(
        raw=RawArticle(
            title=title,
            url=f"http://x/{title}",
            content="",
            source="s",
            language="en",
            timestamp=datetime.now(tz=UTC),
        ),
        relevance_score=score,
        summary=f"summary of {title}",
        tags=[],
        key_insight=f"insight {title}",
    )


async def test_generate_digest(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp("# Digest\n- point")
    out = await provider.generate_digest(
        [_processed("A", 9.0)], [_processed("Old", 5.0)]
    )
    assert out == "# Digest\n- point"
    kwargs = provider._client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 2048
    assert "Today's articles" in kwargs["messages"][0]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_providers/test_anthropic.py::test_generate_digest -q`
Expected: FAIL — `AttributeError: 'AnthropicLLMProvider' object has no attribute 'generate_digest'` (abstract method not implemented → actually `TypeError` at construction if missing; either way the suite is red).

- [ ] **Step 3: Write minimal implementation**

In `src/radaragent/providers/llm/anthropic.py`, add this method to the class (after `score_and_summarize`):

```python
    async def generate_digest(
        self,
        articles: list[ProcessedArticle],
        context: list[ProcessedArticle],
    ) -> str:
        bullets = "\n".join(
            f"- [{a.relevance_score:.1f}] {a.raw.title} — {a.key_insight} ({a.raw.url})"
            for a in articles
        )
        context_bullets = (
            "\n".join(f"- {c.raw.title} — {c.summary}" for c in context) or "(none)"
        )
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_providers/test_anthropic.py -q`
Expected: PASS — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/radaragent/providers/llm/anthropic.py tests/test_providers/test_anthropic.py
git commit -m "feat(provider): AnthropicLLMProvider.generate_digest

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `answer`

**Files:**
- Modify: `src/radaragent/providers/llm/anthropic.py`
- Test: `tests/test_providers/test_anthropic.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_providers/test_anthropic.py`:

```python
async def test_answer(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp("Per the context, yes.")
    out = await provider.answer("Is X true?", [_processed("Doc", 7.0)])
    assert out == "Per the context, yes."
    kwargs = provider._client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 1024
    assert "Is X true?" in kwargs["messages"][0]["content"]
    assert "context" in kwargs["system"].lower()


async def test_answer_no_context(provider: AnthropicLLMProvider) -> None:
    provider._client.messages.create.return_value = _resp("Not enough info.")
    out = await provider.answer("Q?", [])
    assert out == "Not enough info."
    kwargs = provider._client.messages.create.call_args.kwargs
    assert "(no context)" in kwargs["messages"][0]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_providers/test_anthropic.py -q`
Expected: FAIL — `TypeError: Can't instantiate abstract class AnthropicLLMProvider with abstract method answer` (the fixture construction fails because `answer` is still abstract).

- [ ] **Step 3: Write minimal implementation**

In `src/radaragent/providers/llm/anthropic.py`, add this method to the class (after `generate_digest`):

```python
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
            messages=[
                {"role": "user", "content": f"Context:\n{joined}\n\nQuestion: {question}"}
            ],
        )
        return _text(response).strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_providers/test_anthropic.py -q`
Expected: PASS — 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/radaragent/providers/llm/anthropic.py tests/test_providers/test_anthropic.py
git commit -m "feat(provider): AnthropicLLMProvider.answer

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Wire into the daemon factory + exports

**Files:**
- Modify: `src/radaragent/providers/llm/__init__.py`
- Modify: `src/radaragent/main.py:38-46`
- Test: `tests/test_main/test_build_llm_provider.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_main/test_build_llm_provider.py`:

```python
from __future__ import annotations

import pytest

from radaragent.config.loader import LLMConfig, Settings
from radaragent.main import _build_llm_provider
from radaragent.providers.llm.anthropic import AnthropicLLMProvider
from radaragent.providers.llm.openai import OpenAILLMProvider


def _settings(provider: str) -> Settings:
    return Settings(
        llm=LLMConfig(
            provider=provider,
            filter_model="m1",
            digest_model="m2",
            api_key="k",
        )
    )


def test_build_openai_provider() -> None:
    assert isinstance(_build_llm_provider(_settings("openai")), OpenAILLMProvider)


def test_build_anthropic_provider() -> None:
    p = _build_llm_provider(_settings("anthropic"))
    assert isinstance(p, AnthropicLLMProvider)
    assert p.filter_model == "m1"
    assert p.digest_model == "m2"


def test_build_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unsupported llm.provider"):
        _build_llm_provider(_settings("grok"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_main/test_build_llm_provider.py -q`
Expected: FAIL — `test_build_anthropic_provider` raises `ValueError: unsupported llm.provider='anthropic'`.

- [ ] **Step 3: Write minimal implementation**

Edit `src/radaragent/providers/llm/__init__.py` to:

```python
from radaragent.providers.llm.anthropic import AnthropicLLMProvider
from radaragent.providers.llm.base import LLMProvider
from radaragent.providers.llm.openai import OpenAILLMProvider

__all__ = ["AnthropicLLMProvider", "LLMProvider", "OpenAILLMProvider"]
```

In `src/radaragent/main.py`, add the import alongside the existing LLM imports (near `from radaragent.providers.llm.openai import OpenAILLMProvider`):

```python
from radaragent.providers.llm.anthropic import AnthropicLLMProvider
```

Then replace the body of `_build_llm_provider` (currently `src/radaragent/main.py:38-46`) with:

```python
def _build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm.provider == "openai":
        return OpenAILLMProvider(
            api_key=settings.llm.api_key,
            filter_model=settings.llm.filter_model,
            digest_model=settings.llm.digest_model,
            base_url=settings.llm.base_url,
        )
    if settings.llm.provider == "anthropic":
        return AnthropicLLMProvider(
            api_key=settings.llm.api_key,
            filter_model=settings.llm.filter_model,
            digest_model=settings.llm.digest_model,
            base_url=settings.llm.base_url,
        )
    raise ValueError(f"unsupported llm.provider={settings.llm.provider!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_main/test_build_llm_provider.py -q`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/radaragent/providers/llm/__init__.py src/radaragent/main.py tests/test_main/test_build_llm_provider.py
git commit -m "feat(provider): select AnthropicLLMProvider via llm.provider=anthropic

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Config example, env, CHANGELOG

**Files:**
- Modify: `config/settings.yaml`
- Modify: `.env.example`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add a commented Anthropic block to `config/settings.yaml`**

Immediately after the `llm:` block (the lines ending with `base_url: https://api.deepseek.com`), insert:

```yaml
  # 切换到 Anthropic Claude：把上面 llm 整段替换为下面这段
  # provider: anthropic
  # filter_model: claude-haiku-4-5-20251001   # 便宜，过滤评分
  # digest_model: claude-sonnet-4-6           # 简报/问答，质量更高
  # api_key: ${ANTHROPIC_API_KEY}
  # （Anthropic 不需要 base_url；评分系统 prompt 已启用 prompt caching）
```

- [ ] **Step 2: Clarify `ANTHROPIC_API_KEY` in `.env.example`**

Replace the line `# ANTHROPIC_API_KEY=` with:

```bash
# Anthropic Claude (set llm.provider: anthropic in settings.yaml to use)
# ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Step 3: Record in CHANGELOG**

Under `## [Unreleased]` in `CHANGELOG.md`, add (create an `### Added` subsection if none exists under Unreleased):

```markdown
### Added
- `AnthropicLLMProvider` — Claude-backed `LLMProvider` alternative
  (`llm.provider: anthropic`), with Anthropic prompt caching on the
  static scoring system prompt. DeepSeek remains the OpenAI-compatible
  default; this adds a genuinely different vendor for redundancy.
```

- [ ] **Step 4: Commit**

```bash
git add config/settings.yaml .env.example CHANGELOG.md
git commit -m "docs(config): document Anthropic provider option

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Full verification gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — all prior tests plus the new ones (baseline was 63; +9 new = 72 passed). Zero failures.

- [ ] **Step 2: Lint**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check src tests`
Expected: `All checks passed!` and `N files already formatted`. If format flags a file, run `.venv/bin/ruff format src tests` and re-stage/amend the relevant commit.

- [ ] **Step 3: Type-check**

Run: `.venv/bin/mypy src`
Expected: `Success: no issues found`. Contingency: if mypy reports `import-untyped`/`import-not-found` for `anthropic`, add `"anthropic.*"` to the `module = [...]` list under `[[tool.mypy.overrides]]` in `pyproject.toml` (with `ignore_missing_imports = true`), commit as `chore(ci): mypy override for anthropic`, and re-run. (`anthropic>=0.25` ships `py.typed`, so this is expected to be unnecessary.)

- [ ] **Step 4: Push and open PR**

```bash
git push -u origin feature/anthropic-llmprovider
```
Then open a PR `feature/anthropic-llmprovider` → `develop` (Conventional Commits title: `feat(provider): Anthropic LLMProvider`). No `gh` on this machine — the human opens it via the compare URL and merges after CI is green.

---

## Self-Review

**1. Spec coverage:** Spec = "Anthropic LLMProvider 备选" (CLAUDE.md Phase 5). Covered: provider class implementing all three `LLMProvider` abstract methods (Tasks 1-3), selectable via config (Task 4), documented (Task 5), verified (Task 6). Prompt caching added per the claude-api guidance for Anthropic apps. No other Phase 5 subsystem is in scope (intentional — separate plans).

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to". Every code step shows full code; every run step shows the exact command and expected output. JSON-parse fallback and empty-content paths are concretely implemented and tested.

**3. Type consistency:** `_text()` and `_parse_json_payload()` are defined in Task 1 and reused (not redefined) in Tasks 2-3. Method signatures (`score_and_summarize`/`generate_digest`/`answer`) match the `LLMProvider` ABC exactly (verified against `src/radaragent/providers/llm/base.py`). Constructor kwargs (`api_key`, `filter_model`, `digest_model`, `base_url`) match what `_build_llm_provider` passes in Task 4. Model-id constants (`claude-haiku-4-5-20251001`, `claude-sonnet-4-6`) are consistent between the implementation and the assertions in Tasks 1-3.
