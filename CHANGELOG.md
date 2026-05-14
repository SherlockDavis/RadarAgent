# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Sherlock/RadarAgent/compare/HEAD
