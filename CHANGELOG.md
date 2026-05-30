# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `AnthropicLLMProvider` — Claude-backed `LLMProvider` alternative
  (`llm.provider: anthropic`), with Anthropic prompt caching on the
  static scoring system prompt. DeepSeek remains the OpenAI-compatible
  default; this adds a genuinely different vendor for redundancy.

## [0.1.0] - 2026-05-17

First public release: Phases 1–4 — plugin-based ingestion, RAG, the
user/subscription model + ServiceAPI, and the FastAPI web app with
Docker/Caddy deployment.

### Added
- Initial project scaffolding: CLAUDE.md, design spec, repository configuration files
- MIT License
- Conventional Commits + branch strategy + PR template
- pre-commit configuration (ruff / mypy / commitlint)
- GitHub Actions CI workflow scaffold
- Local SSH commit signing configuration
- Phase 1 MVP source layout: `src/radaragent/` package
- Data models: `RawArticle`, `ProcessedArticle`
- `SourcePlugin` base class + plugin registry
- `RSSPlugin` (generic RSS / Atom reader)
- `LLMProvider` base + `OpenAILLMProvider` (score, digest, embed)
- `PluginScheduler` (APScheduler-backed, cron triggers, error isolation)
- Config loader with `${VAR}` env-var expansion (pydantic-validated)
- Default `config/settings.yaml` + `config/interests.yaml` + `.env.example`
- CLI entry: `radaragent` with `--once` smoke mode

### Changed
- Default LLM provider switched to DeepSeek (OpenAI-compatible API,
  cheaper). `settings.yaml` now references `${DEEPSEEK_API_KEY}` and
  sets `base_url: https://api.deepseek.com`.

### Fixed
- Mojibake on Windows when printing LLM-generated non-ASCII summaries.
  `main.py` now reconfigures `sys.stdout` / `sys.stderr` to UTF-8 and
  switches the Windows console code page to 65001 at startup so
  cp936/GBK consoles display Chinese correctly. (PyCharm's pseudo-
  terminal still requires `PYTHONIOENCODING=utf-8` in Run config.)

### Phase 2a — Multi-source data extension

- `HTTPAPIPlugin` (generic JSON-over-HTTP plugin, fully YAML-driven —
  configure URL / headers / params / json_path / field_mapping)
- Example plugins under `src/radaragent/plugins/examples/`:
  - `HackerNewsPlugin` — official HN Firebase API, multi-step fetch,
    exposes score / comments / author
  - `ArxivPlugin` — arXiv Atom API by category (cs.LG, cs.CL, ...)
  - `SECEdgarPlugin` — SEC EDGAR submissions JSON, requires
    `User-Agent` header and CIK list
- Plugin registry expanded to include all four new types
- `config/settings.yaml` enriched with commented templates showing how
  to enable each plugin type

### Phase 2b — Persistent RAG + deduplication

- `EmbeddingProvider` interface separated from `LLMProvider`. Two
  implementations: `LocalEmbeddingProvider` (sentence-transformers,
  default model `BAAI/bge-m3`, auto-detects CUDA/MPS/CPU) and
  `OpenAIEmbeddingProvider` (kept for users who already have an
  OpenAI key). DeepSeek users default to local since DeepSeek has no
  embedding endpoint.
- `RAGStore` — Chroma-backed vector store with two parallel collections
  (`articles_content` + `articles_summary`), cosine distance metric.
  Each article gets a sha1(url) id shared across collections.
- `DedupChecker` — two-layer duplicate detection: cheap URL exact match
  first, then cosine similarity over the content vector (default
  threshold `0.92`). Duplicates are still stored with `is_duplicate=True`
  for provenance but excluded from digests.
- `main.py` sink chain rewritten: URL dedup → score (with LLM) → batch
  embed → vector dedup → store → print. URL dedup runs first so the
  expensive LLM call is skipped on re-fetched articles.
- New dependency: `chromadb>=0.5`. Optional `local-embed` extra adds
  `sentence-transformers` + `torch` (heavy: ~4-5GB combined with CUDA
  wheel and the bge-m3 model download).
- `embedding.dedup_threshold` exposed in `settings.yaml` so users can
  tune dedup aggressiveness without code changes.

### Phase 3 — User-ization + backend services

- `Database` — SQLite wrapper with schema for `users` / `subscriptions` /
  `article_scores` / `digests`. Foreign keys on, idempotent `init_schema`.
- `User` model + bcrypt auth: `register` (first user becomes admin,
  ≥8-char password, unique email) / `authenticate`. In-memory
  `SessionStore` (token TTL, persistence seam for a future SQLite store).
- `Subscription` pydantic models with cron-expression and `min_score`
  range validation; `Channel` and `SubscriptionFilter`. Full DAO:
  create / get / list-enabled / enable-toggle / score upsert /
  digest upsert / per-user scored-article-id lookup.
- Per-subscription scoring sink (`radaragent.processor.build_sink`):
  articles are embedded + dedup-stored once globally, then scored once
  per enabled subscription with that subscription's interest profile;
  the `article_scores` primary key prevents re-scoring a known pair.
- `ServiceAPI` facade: `generate_digest` (today's scored articles +
  RAG history context, idempotent per `(subscription, date)`) and
  `query` (RAG Q&A scoped to the user's own scored articles).
  `search` is a Phase 4 placeholder. Added `LLMProvider.answer` and
  `RAGStore.get_metadata`.
- `Notifier` ABC + `EmailNotifier` (aiosmtplib); failures are logged
  and return `False` so one bad channel cannot abort a digest job.
- Scheduler gains per-subscription cron digest jobs alongside plugin
  fetch jobs; `register_digest_jobs` / `reschedule`.
- CLI restructured into subcommands: `run` (24/7 daemon, the primary
  path), `digest`, `query`, `useradd`. First daemon start with an empty
  `users` table interactively bootstraps the admin account.

### Changed (Phase 3)

- Config: removed `InterestsConfig` / `load_interests`; added
  `SMTPConfig`, `AuthConfig`, `DigestConfig`, and
  `storage.sqlite_path`. `settings.yaml` no longer carries interests.
- Scoring logic moved out of `main.py` into `radaragent.processor`.
- New dependencies: `bcrypt>=4.1`, `aiosmtplib>=3.0`.

### Removed (Phase 3)

- `config/interests.yaml` — interests are now per-subscription in the
  database, edited via the Web UI (Phase 4) or `useradd` bootstrap.

### Phase 4 — Web application + deployment

- FastAPI web app served **in-process** by `radaragent run` (same
  asyncio loop as the scheduler) when `web.enabled`. `WebContext`
  shares the daemon's DB connection, RAG store, providers and
  in-memory `SessionStore`; a reschedule closure re-syncs digest jobs
  on subscription edits without restarting.
- Six pages + JSON endpoint: `/login` `/register` `/logout` auth
  (httponly session cookie, `cookie_secure`/ttl from config), `/`
  Dashboard (subscriptions + recent digests), `/subscriptions/new`
  + create/toggle/delete (ownership-checked, live reschedule),
  `/digest/{sub}/{date}` detail with on-demand generation, `/ask`
  + `POST /api/query` RAG Q&A, `/search` filtered retrieval.
  Jinja2 templates + a dark CSS shell; `/healthz` liveness probe.
- `ServiceAPI.search` implemented (was the Phase 3 placeholder):
  filters the user's scored articles by `min_score` / source /
  keywords over `article_scores` + RAG metadata, pure-sync so it is
  safe in the web loop. Adds `SearchResult`,
  `crud.scored_articles_for_user`, `users.get_user`,
  `crud.list_subscriptions_for_user` / `delete_subscription` /
  `get_digest` / `recent_digests_for_user`.
- `WebConfig` (enabled / host / port / cookie_secure /
  session_cookie); `settings.yaml` gains a `web:` section.
- Deployment: `Dockerfile` (slim, non-root, healthcheck, torch
  excluded), `docker-compose.yaml` (app + Caddy auto-HTTPS),
  `Caddyfile`, `.dockerignore`, `docs/deploy.md` VPS walkthrough.
  `ensure_admin_user` no longer blocks without a TTY so detached
  `docker compose up -d` works (first `/register` becomes admin).

### Changed (Phase 4)

- New dependencies: `fastapi>=0.110`, `uvicorn>=0.29`,
  `jinja2>=3.1`, `python-multipart>=0.0.9`.
- commitlint scope-enum gains `web` and `deploy`.

[Unreleased]: https://github.com/SherlockDavis/RadarAgent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SherlockDavis/RadarAgent/releases/tag/v0.1.0
